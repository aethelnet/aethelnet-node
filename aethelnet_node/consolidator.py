"""
Memory Immune System & Offline Gemma 4 Consolidator (Ideas #4, #5, #8, #9).

Combines continuous-time LiquidGraph epistemic physics (Tier 1 axioms stay anchored,
Kuramoto LTC gates down-weight conflicting neighbor noise) with a strictly additive
offline LLM auditor (default: local `gemma4:12b-it-qat` via Ollama):
  - NEVER overwrites or deletes original node `text_content`.
  - Contradictions -> additive `contradicts` edge with `is_contested=1` so `recall()`
    surfaces `[CONTESTED]` on both concepts immediately.
  - Long notes (> 900 chars) -> additive `meta_data["distilled_summary"]` (<= 500 chars)
    so tiny models (4B) can parse full facts in one shot while full text stays intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from aethelnet_node.agents import current_agent
from aethelnet_node.database import (
    deserialize_tensor,
    get_db_connection,
    init_db,
    log_agent_write,
    save_multigraph_edge,
)
from aethelnet_node.recall import tokenize
from aethelnet_node.state import (
    HIDDEN_DIM,
    REALITY_ANCHORS,
    graph_instance,
    infer_epistemic_tier,
)

logger = logging.getLogger("Aethelnet.Consolidator")

DEFAULT_CONSOLIDATOR_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:12b-it-qat")
DEFAULT_OLLAMA_CHAT_URL = os.getenv("OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")
LONG_NOTE_THRESHOLD = 900


def sync_epistemic_physics(compute_time: float = 0.5) -> Dict[str, Any]:
    """Sync active DB nodes into LiquidGraph with Idea #4 tiers and run 1 Kuramoto LTC step."""
    init_db()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, embedding, node_type, is_grounded, confidence
        FROM lgnn_nodes
        WHERE COALESCE(is_archived, 0) = 0 AND COALESCE(is_quarantined, 0) = 0
        """
    )
    rows = cur.fetchall()
    cur.execute("SELECT source, target, weight FROM lgnn_edges")
    edge_rows = cur.fetchall()
    conn.close()

    tier_counts: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    tier_map: Dict[str, int] = {}

    for r in rows:
        nid = r["id"]
        tier = infer_epistemic_tier(
            node_type=r["node_type"],
            is_grounded=bool(r["is_grounded"]),
            confidence=r["confidence"],
        )
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        tier_map[nid] = tier
        if not graph_instance.nx_graph.has_node(nid):
            emb = deserialize_tensor(r["embedding"], dim=HIDDEN_DIM) if r["embedding"] else None
            if emb is not None:
                graph_instance.add_node(nid, emb, tier=tier)
        else:
            graph_instance.set_node_physics(nid, tier=tier)

    for er in edge_rows:
        u, v, w = er["source"], er["target"], float(er["weight"] or 1.0)
        if graph_instance.nx_graph.has_node(u) and graph_instance.nx_graph.has_node(v):
            graph_instance.nx_graph.add_edge(u, v, weight=w)

    report = graph_instance.evolve_topology(compute_time=compute_time) if graph_instance.nodes else {}
    high_strain_alerts: List[Dict[str, Any]] = []
    taus_by_tier: Dict[int, List[float]] = {1: [], 2: [], 3: [], 4: []}

    for nid, tier in tier_map.items():
        strain = graph_instance.get_node_strain(nid)
        tau = graph_instance.get_effective_tau(nid)
        if tau is not None:
            taus_by_tier.setdefault(tier, []).append(tau)
        if tier in (1, 2) and strain > 0.15:
            high_strain_alerts.append({"node_id": nid, "tier": tier, "strain": round(strain, 4)})

    mean_tau_by_tier = {
        str(t): round(sum(vals) / len(vals), 4)
        for t, vals in taus_by_tier.items()
        if vals
    }

    return {
        "active_nodes": len(rows),
        "liquid_mode": graph_instance.liquid_mode,
        "tier_counts": {str(k): v for k, v in tier_counts.items()},
        "mean_effective_tau": report.get("mean_effective_tau"),
        "mean_tau_by_tier": mean_tau_by_tier,
        "high_strain_alerts": high_strain_alerts,
    }


def _load_auditable_nodes() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, label, text_content, node_type, is_grounded, confidence, created_by, meta_data
        FROM lgnn_nodes
        WHERE COALESCE(is_archived, 0) = 0 AND COALESCE(is_quarantined, 0) = 0
        """
    )
    nodes = []
    for r in cur.fetchall():
        nid = r["id"]
        if nid in REALITY_ANCHORS:
            continue
        nodes.append(
            {
                "id": nid,
                "label": r["label"] or nid,
                "text_content": r["text_content"] or "",
                "node_type": r["node_type"] or "standard",
                "is_grounded": bool(r["is_grounded"]),
                "confidence": float(r["confidence"] or 0.5),
                "created_by": r["created_by"] or "system",
                "meta_data": r["meta_data"] or "{}",
                "tokens": set(tokenize(f"{nid} {r['label'] or ''} {r['text_content'] or ''}")),
            }
        )
    conn.close()
    return nodes


def _existing_contradiction_pairs() -> set:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT source, target FROM lgnn_multigraph_edges WHERE relation_type = 'contradicts' OR is_contested = 1"
    )
    seen = {tuple(sorted((r["source"], r["target"]))) for r in cur.fetchall()}
    conn.close()
    return seen


def select_audit_pairs(max_pairs: int = 8) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Select plausible candidate pairs sharing lexical overlap or existing graph/coaccess links."""
    nodes = _load_auditable_nodes()
    if len(nodes) < 2:
        return []

    already_contested = _existing_contradiction_pairs()
    linked_pairs: set = set()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT node_a, node_b FROM agent_coaccess_edges")
    for r in cur.fetchall():
        linked_pairs.add(tuple(sorted((r["node_a"], r["node_b"]))))
    cur.execute("SELECT source, target FROM lgnn_multigraph_edges")
    for r in cur.fetchall():
        linked_pairs.add(tuple(sorted((r["source"], r["target"]))))
    conn.close()

    scored: List[Tuple[float, Dict[str, Any], Dict[str, Any]]] = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            na, nb = nodes[i], nodes[j]
            pair_key = tuple(sorted((na["id"], nb["id"])))
            if pair_key in already_contested:
                continue
            overlap = len(na["tokens"] & nb["tokens"])
            is_linked = pair_key in linked_pairs
            if overlap < 2 and not is_linked:
                continue
            # Prefer strong lexical overlap (possible contradiction/duplicate) over weak links
            score = float(overlap) * 2.0 + (1.0 if is_linked else 0.0)
            scored.append((score, na, nb))

    scored.sort(key=lambda item: -item[0])
    return [(a, b) for _, a, b in scored[: max(0, int(max_pairs))]]


def _post_ollama_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    ollama_url: Optional[str] = None,
    json_mode: bool = False,
    num_predict: int = 256,
) -> Optional[str]:
    target_model = model or os.getenv("OLLAMA_MODEL", DEFAULT_CONSOLIDATOR_MODEL)
    url = ollama_url or os.getenv("OLLAMA_CHAT_URL", DEFAULT_OLLAMA_CHAT_URL)
    payload: Dict[str, Any] = {
        "model": target_model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_predict": num_predict},
    }
    if json_mode:
        payload["format"] = "json"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return str(data.get("message", {}).get("content", "")).strip()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as e:
        logger.debug(f"[Consolidator] Ollama call unavailable: {e}")
        return None


def _judge_pair_llm(
    node_a: Dict[str, Any],
    node_b: Dict[str, Any],
    model: Optional[str] = None,
    ollama_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask local LLM (e.g. gemma4:12b-it-qat) whether two notes contradict, duplicate, or complement."""
    prompt = (
        "Audit these two knowledge graph notes strictly for factual consistency.\n"
        "Respond ONLY with JSON matching: "
        '{"verdict": "consistent"|"contradiction"|"duplicate"|"bridge", "confidence": 0.0..1.0, "reason": "short sentence"}\n'
        "- contradiction: incompatible commands, ports, rules, metrics, or opposing claims on the same topic.\n"
        "- duplicate: essentially the same rule/fact stated twice.\n"
        "- bridge: compatible notes that meaningfully extend each other.\n"
        "- consistent: separate compatible facts with no conflict.\n\n"
        f"NOTE A [{node_a['id']}] (type={node_a['node_type']}, label={node_a['label']}):\n"
        f"{node_a['text_content'][:700]}\n\n"
        f"NOTE B [{node_b['id']}] (type={node_b['node_type']}, label={node_b['label']}):\n"
        f"{node_b['text_content'][:700]}\n"
    )
    raw = _post_ollama_chat(
        [{"role": "user", "content": prompt}],
        model=model,
        ollama_url=ollama_url,
        json_mode=True,
        num_predict=256,
    )
    if not raw:
        return {"verdict": "consistent", "confidence": 0.0, "reason": "llm_offline"}
    try:
        parsed = json.loads(raw)
        verdict = str(parsed.get("verdict", "consistent")).strip().lower()
        if verdict not in {"consistent", "contradiction", "duplicate", "bridge"}:
            verdict = "consistent"
        conf = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
        reason = str(parsed.get("reason", "")).strip()[:240]
        return {"verdict": verdict, "confidence": conf, "reason": reason}
    except (ValueError, TypeError):
        return {"verdict": "consistent", "confidence": 0.0, "reason": "invalid_json"}


def _distill_long_note_llm(
    node: Dict[str, Any],
    model: Optional[str] = None,
    ollama_url: Optional[str] = None,
) -> Optional[str]:
    """Generate a concise <= 500 char summary stored strictly in metadata (never mutating raw text)."""
    prompt = (
        "Summarize the following technical note in at most 420 characters, preserving exact commands, paths, numbers, and caveats:\n\n"
        f"[{node['id']}] {node['label']}:\n{node['text_content'][:3500]}"
    )
    out = _post_ollama_chat(
        [{"role": "user", "content": prompt}],
        model=model,
        ollama_url=ollama_url,
        json_mode=False,
        num_predict=180,
    )
    return out[:500].strip() if out else None


def run_consolidation(
    max_pairs: int = 8,
    use_llm: bool = True,
    dry_run: bool = False,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute one Memory Immune + Offline Consolidation cycle:
      1. Sync epistemic tiers & run 1 Kuramoto LTC evolution check.
      2. Audit candidate pairs for contradictions (`is_contested=1`), duplicates, or bridges.
      3. Distill long notes (> 900 chars) into `meta_data['distilled_summary']` (original text untouched).
    """
    init_db()
    physics_report = sync_epistemic_physics(compute_time=0.5)
    pairs = select_audit_pairs(max_pairs=max_pairs)

    contradictions: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []
    bridges: List[Dict[str, Any]] = []
    distilled: List[Dict[str, Any]] = []

    token = current_agent.set("consolidator")
    try:
        if use_llm:
            for na, nb in pairs:
                verdict = _judge_pair_llm(na, nb, model=model)
                vtype = verdict["verdict"]
                conf = verdict["confidence"]
                entry = {
                    "source": na["id"],
                    "target": nb["id"],
                    "verdict": vtype,
                    "confidence": conf,
                    "reason": verdict["reason"],
                }
                if vtype == "contradiction" and conf >= 0.70:
                    contradictions.append(entry)
                    if not dry_run:
                        a, b = sorted((na["id"], nb["id"]))
                        edge_id = "consolidator_contradiction_" + hashlib.sha256(f"{a}\0{b}".encode()).hexdigest()[:12]
                        save_multigraph_edge(
                            edge_id=edge_id,
                            source=a,
                            target=b,
                            relation_type="contradicts",
                            app_id="memory_immune",
                            weight=conf,
                            evidence_quote=verdict["reason"],
                            source_doc_id="consolidator_audit",
                            is_contested=1,
                            conflict_notes=verdict["reason"],
                        )
                elif vtype == "duplicate" and conf >= 0.80:
                    duplicates.append(entry)
                elif vtype == "bridge" and conf >= 0.85:
                    bridges.append(entry)

            # Long-note distillation strictly into meta_data JSON
            for node in _load_auditable_nodes():
                if len(node["text_content"]) <= LONG_NOTE_THRESHOLD:
                    continue
                try:
                    meta = json.loads(node["meta_data"] or "{}")
                    if not isinstance(meta, dict):
                        meta = {}
                except ValueError:
                    meta = {}
                if meta.get("distilled_summary"):
                    continue
                summary = _distill_long_note_llm(node, model=model)
                if summary:
                    distilled.append({"node_id": node["id"], "summary_chars": len(summary)})
                    if not dry_run:
                        meta["distilled_summary"] = summary
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute(
                            "UPDATE lgnn_nodes SET meta_data = ? WHERE id = ?",
                            (json.dumps(meta), node["id"]),
                        )
                        conn.commit()
                        conn.close()

        if not dry_run and (contradictions or distilled):
            log_agent_write("consolidator", "POST", "/api/lgnn/consolidate", 200)
    finally:
        current_agent.reset(token)

    return {
        "dry_run": bool(dry_run),
        "use_llm": bool(use_llm),
        "model": model or os.getenv("OLLAMA_MODEL", DEFAULT_CONSOLIDATOR_MODEL),
        "physics": physics_report,
        "pairs_audited": len(pairs),
        "contradictions_flagged": contradictions,
        "duplicates_flagged": duplicates,
        "bridges_suggested": bridges,
        "distilled_notes": distilled,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Aethelnet Memory Immune & Gemma 4 Consolidator")
    parser.add_argument("--max-pairs", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--model", type=str, default=None)
    args = parser.parse_args()
    out = run_consolidation(
        max_pairs=args.max_pairs,
        use_llm=not args.no_llm,
        dry_run=args.dry_run,
        model=args.model,
    )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
