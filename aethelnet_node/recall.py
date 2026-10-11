"""
Associative recall for stuck agents (first end-to-end milestone, aethelnet-core/docs/VISION.md #5).

Pipeline, chosen by aethelnet-core/research/recall_benchmark:
1. Hybrid retrieval over node texts: BM25 (code-aware tokens) + MiniLM cosine, fused by reciprocal rank.
   Without sentence-transformers the node only has hash embeddings, so recall falls back to BM25.
2. Spreading activation: Personalized PageRank from the top hits over "used together" edges
   (coaccess.py), teleport 0.5. It surfaces nodes that agents needed alongside the hits even when
   they share no words with the query.
3. Working-memory dossier: the claims attached to each result (relation, evidence, contested flag,
   author), so an agent sees what is known and what is disputed.

Stored meaning stays anchored: the benchmark showed that smoothing stored embeddings does not help,
so activation is spread at query time and the node texts and embeddings are left untouched.
"""

import hashlib
import math
import re
import threading
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

import numpy as np

RRF_K = 60
SEED_TOP = 10
TELEPORT = 0.5
PPR_ITERATIONS = 40
MAX_TEXT_CHARS = 4000
SNIPPET_CHARS = 280

STOP = set("""a an and are as at be by for from has have if in into is it its of on or that the this to was were
will with not no self def return import const let var function class true false none null new else""".split())


def tokenize(text: str) -> List[str]:
    """Lower-case word pieces; splits camelCase and snake_case so code identifiers match prose."""
    out = []
    for word in re.findall(r"[A-Za-z0-9]+", text or ""):
        for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", word):
            p = part.lower()
            if len(p) > 1 and p not in STOP:
                out.append(p)
    return out


class _Index:
    def __init__(self):
        self.version = None
        self.ids: List[str] = []
        self.labels: List[str] = []
        self.texts: List[str] = []
        self.lengths = np.zeros(0)
        self.postings: Dict[str, List[tuple]] = {}
        self.dense: Optional[np.ndarray] = None
        self.dense_cache: Dict[str, np.ndarray] = {}


_index = _Index()
_index_lock = threading.Lock()


def _embedding_model():
    from aethelnet_node.state import get_embedding_model
    return get_embedding_model()


_ACTIVE = "COALESCE(is_archived, 0) = 0 AND COALESCE(is_quarantined, 0) = 0"


def _corpus_version():
    """Cheap change detector: count, newest update, total text and id length of active nodes."""
    from aethelnet_node.database import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT COUNT(*) AS n, MAX(last_updated) AS newest,
               SUM(LENGTH(COALESCE(text_content, ''))) AS text_len, SUM(LENGTH(id)) AS id_len
        FROM lgnn_nodes WHERE {_ACTIVE}
    """)
    row = cur.fetchone()
    conn.close()
    return (row["n"], str(row["newest"]), row["text_len"], row["id_len"])


def _load_corpus():
    from aethelnet_node.database import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT id, label, text_content, last_updated FROM lgnn_nodes WHERE {_ACTIVE}")
    rows = [(r["id"], r["label"] or "", r["text_content"] or "", str(r["last_updated"])) for r in cur.fetchall()]
    conn.close()
    return rows


def _current_index() -> _Index:
    version = _corpus_version()
    with _index_lock:
        if _index.version == version:
            return _index
        rows = _load_corpus()
        _index.ids = [r[0] for r in rows]
        _index.labels = [r[1] for r in rows]
        _index.texts = [r[2] for r in rows]
        postings: Dict[str, List[tuple]] = defaultdict(list)
        lengths = []
        for i, (node_id, label, text, _) in enumerate(rows):
            tokens = tokenize(f"{node_id} {label} ") * 2 + tokenize(text[:MAX_TEXT_CHARS])
            lengths.append(len(tokens))
            for term, tf in Counter(tokens).items():
                postings[term].append((i, tf))
        _index.postings = dict(postings)
        _index.lengths = np.array(lengths, dtype=float)

        model = _embedding_model()
        if model is not None and rows:
            keys = [hashlib.sha1(f"{i}\0{t}".encode()).hexdigest() for i, _, t, _ in rows]
            missing = [(k, f"{node_id}: {text[:MAX_TEXT_CHARS]}") for k, (node_id, _, text, _) in zip(keys, rows)
                       if k not in _index.dense_cache]
            if missing:
                vecs = model.encode([m[1] for m in missing], batch_size=64, normalize_embeddings=True,
                                    show_progress_bar=False)
                for (k, _), v in zip(missing, vecs):
                    _index.dense_cache[k] = np.asarray(v, dtype=np.float32)
            _index.dense = np.stack([_index.dense_cache[k] for k in keys])
        else:
            _index.dense = None
        _index.version = version
        return _index


def _bm25(index: _Index, query_tokens: List[str], k1: float = 1.2, b: float = 0.75) -> np.ndarray:
    n = len(index.ids)
    scores = np.zeros(n)
    if n == 0:
        return scores
    avg = index.lengths.mean() or 1.0
    for term in set(query_tokens):
        plist = index.postings.get(term)
        if not plist:
            continue
        idf = math.log(1 + (n - len(plist) + 0.5) / (len(plist) + 0.5))
        for i, tf in plist:
            scores[i] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * index.lengths[i] / avg))
    return scores


def _rrf_contribution(scores: np.ndarray, only_positive: bool) -> np.ndarray:
    order = np.argsort(-scores, kind="stable")
    ranks = np.empty(len(scores), dtype=int)
    ranks[order] = np.arange(1, len(scores) + 1)
    contrib = 1.0 / (RRF_K + ranks)
    if only_positive:
        contrib[scores <= 0] = 0.0
    return contrib


def _ppr(seed_scores: np.ndarray, edges, id_to_idx: Dict[str, int]) -> np.ndarray:
    n = len(seed_scores)
    seed = np.zeros(n)
    top = [i for i in np.argsort(-seed_scores, kind="stable")[:SEED_TOP] if seed_scores[i] > 0]
    for rank, i in enumerate(top, start=1):
        seed[i] = 1.0 / rank
    if seed.sum() == 0:
        return seed_scores
    seed /= seed.sum()
    neighbours: Dict[int, List[tuple]] = defaultdict(list)
    for a, b, w in edges:
        ia, ib = id_to_idx[a], id_to_idx[b]
        neighbours[ia].append((ib, w))
        neighbours[ib].append((ia, w))
    degree = {i: sum(w for _, w in nb) for i, nb in neighbours.items()}
    r = seed.copy()
    for _ in range(PPR_ITERATIONS):
        spread = np.zeros(n)
        dangling = 0.0
        for i in np.nonzero(r)[0]:
            if i in neighbours:
                for j, w in neighbours[i]:
                    spread[j] += r[i] * w / degree[i]
            else:
                dangling += r[i]
        r = TELEPORT * seed + (1 - TELEPORT) * (spread + dangling * seed)
    # keep the hybrid order among nodes the walk never reaches
    return r + 1e-9 * seed_scores / (seed_scores.max() + 1e-12)


def _claims_for(node_ids: List[str], per_node: int = 3) -> Dict[str, List[Dict[str, Any]]]:
    if not node_ids:
        return {}
    from aethelnet_node.database import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    marks = ",".join("?" for _ in node_ids)
    cur.execute(f"""
        SELECT edge_id, app_id, source, target, relation_type, evidence_quote, source_doc_id,
               is_contested, created_by
        FROM lgnn_multigraph_edges WHERE source IN ({marks}) OR target IN ({marks})
    """, (*node_ids, *node_ids))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    claims: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: -int(r.get("is_contested") or 0)):  # disputed knowledge first
        for node_id in (row["source"], row["target"]):
            if node_id in node_ids and len(claims[node_id]) < per_node:
                claims[node_id].append({
                    "relation": row["relation_type"],
                    "source": row["source"],
                    "target": row["target"],
                    "evidence": (row.get("evidence_quote") or "")[:200],
                    "source_doc": row.get("source_doc_id") or "",
                    "contested": bool(row.get("is_contested")),
                    "by": row.get("created_by") or "",
                    "app_id": row.get("app_id") or "",
                })
    return dict(claims)


def recall(query: str, k: int = 8, use_popularity: bool = False, include_claims: bool = True) -> Dict[str, Any]:
    from aethelnet_node import coaccess

    k = max(1, min(int(k), 50))
    index = _current_index()
    n = len(index.ids)
    result: Dict[str, Any] = {"query": query, "results": [], "dense_enabled": index.dense is not None,
                              "corpus_size": n, "association_edges": 0}
    if n == 0 or not (query or "").strip():
        return result

    lexical = _bm25(index, tokenize(query))
    hybrid = _rrf_contribution(lexical, only_positive=True)
    dense_scores = None
    if index.dense is not None:
        q_vec = np.asarray(_embedding_model().encode(query, normalize_embeddings=True), dtype=np.float32)
        dense_scores = index.dense @ q_vec
        hybrid = hybrid + _rrf_contribution(dense_scores, only_positive=False)
    if use_popularity:
        counts = coaccess.touch_counts()
        popularity = np.array([counts.get(i, 0) for i in index.ids], dtype=float)
        hybrid = hybrid + _rrf_contribution(popularity, only_positive=True)

    if hybrid.max() <= 0:
        return result
    id_to_idx = {node_id: i for i, node_id in enumerate(index.ids)}
    edges = coaccess.edges_among(index.ids)
    result["association_edges"] = len(edges)
    final = _ppr(hybrid, edges, id_to_idx) if edges else hybrid

    hybrid_top = set(np.argsort(-hybrid, kind="stable")[:k].tolist())
    lexical_rank = {i: r for r, i in enumerate(np.argsort(-lexical, kind="stable"), start=1) if lexical[i] > 0}
    dense_rank = ({i: r for r, i in enumerate(np.argsort(-dense_scores, kind="stable"), start=1)}
                  if dense_scores is not None else {})
    picked = [i for i in np.argsort(-final, kind="stable")[:k] if final[i] > 0]
    claims = _claims_for([index.ids[i] for i in picked]) if include_claims else {}
    for rank, i in enumerate(picked, start=1):
        node_id = index.ids[i]
        result["results"].append({
            "rank": rank,
            "node_id": node_id,
            "label": index.labels[i],
            "snippet": re.sub(r"\s+", " ", index.texts[i])[:SNIPPET_CHARS],
            "score": float(final[i]),
            "lexical_rank": lexical_rank.get(i),
            "dense_rank": dense_rank.get(i),
            "via_association": i not in hybrid_top,
            "claims": claims.get(node_id, []),
        })
    return result


def format_recall(result: Dict[str, Any]) -> str:
    """Plain-text rendering for MCP clients."""
    if not result["results"]:
        if result["corpus_size"] == 0:
            return "The node has no searchable concepts yet."
        return f"No concepts matched '{result['query']}'."
    lines = [f"Associative recall for: {result['query']}"]
    for r in result["results"]:
        why = []
        if r["lexical_rank"]:
            why.append(f"keywords #{r['lexical_rank']}")
        if r["dense_rank"] and r["dense_rank"] <= 20:
            why.append(f"meaning #{r['dense_rank']}")
        if r["via_association"]:
            why.append("used together with the top hits")
        lines.append(f"{r['rank']}. [{r['node_id']}] {r['snippet']}" + (f"  ({', '.join(why)})" if why else ""))
        for c in r["claims"]:
            flag = " [CONTESTED]" if c["contested"] else ""
            evidence = f' "{c["evidence"]}"' if c["evidence"] else ""
            by = f" (by {c['by']})" if c["by"] else ""
            lines.append(f"     claim: {c['source']} -{c['relation']}-> {c['target']}{flag}{evidence}{by}")
    lines.append("If some of these helped, call lgnn_mark_useful with their node ids so the graph learns "
                 "which concepts belong together.")
    return "\n".join(lines)
