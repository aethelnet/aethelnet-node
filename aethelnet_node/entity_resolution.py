import re
import difflib
import logging
from typing import Dict, Any, List, Optional, Tuple, Set
from collections import defaultdict

from .database import get_db_connection, sync_conflicts_for_app

logger = logging.getLogger("Aethelnet.EntityResolution")

# Titles, honorifics, nobility particles and corporate legal forms
HONORIFICS_REGEX = re.compile(
    r'\b(hauptmann|oberst|leutnant|major|general|feldwebel|gouverneur|vize-gouverneur|'
    r'könig|koenig|fon|prinz|graf|baron|herzog|dr|dr\.|prof|prof\.|professor|sir|lord|'
    r'von|zu|vom|den|der|des|de|van|du)\b',
    re.IGNORECASE
)

CORPORATE_REGEX = re.compile(
    r'\b(ltd|ltd\.|limited|llc|corp|corp\.|corporation|inc|inc\.|incorporated|'
    r'gmbh|ag|co|co\.|kg|kgaa|holdings|group|holding|sa|bv|nv|plc)\b',
    re.IGNORECASE
)

INVENTORY_PREFIX_REGEX = re.compile(
    r'^(inv\s*[\.\-]?\s*nr\s*[\.\-]?|inventarnummer|kat\s*[\.\-]?\s*nr\s*[\.\-]?|nr\s*[\.\-]?)\s*',
    re.IGNORECASE
)

def normalize_label(label: str) -> Tuple[str, str]:
    """
    Normalizes an entity label:
    1. Returns cleaned display name (stripped of honorifics/corporate forms).
    2. Returns canonical slug (alphanumeric only, lowercase, for indexing).
    """
    if not label:
        return "", ""

    raw = str(label).strip()

    # Strip inventory prefixes (e.g. "Inv.-Nr. III C 1234" -> "III C 1234")
    raw = INVENTORY_PREFIX_REGEX.sub('', raw)

    # Clean honorifics / corporate forms for display
    cleaned = HONORIFICS_REGEX.sub('', raw)
    cleaned = CORPORATE_REGEX.sub('', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' ,.-_')

    if not cleaned:
        cleaned = raw

    # Canonical alphanumeric slug for matching
    slug = re.sub(r'[^a-z0-9]', '', cleaned.lower())
    if not slug:
        slug = re.sub(r'[^a-z0-9]', '', raw.lower())

    return cleaned, slug

def are_types_compatible(type1: Optional[str], type2: Optional[str]) -> bool:
    """Checks whether two node entity types can be safely merged."""
    if not type1 or not type2:
        return True
    t1 = type1.lower()
    t2 = type2.lower()
    if t1 == t2:
        return True
    
    # Equivalent groupings
    person_types = {"person", "actor", "individual", "witness", "official"}
    org_types = {"organization", "company", "institution", "shell_company", "bank"}
    artifact_types = {"artifact", "object", "asset", "property"}

    if t1 in person_types and t2 in person_types:
        return True
    if t1 in org_types and t2 in org_types:
        return True
    if t1 in artifact_types and t2 in artifact_types:
        return True

    # Generic types can match specific ones
    if t1 in {"standard", "entity", "generic"} or t2 in {"standard", "entity", "generic"}:
        return True

    return False

def find_merge_candidates(app_id: str, min_confidence: float = 0.88, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Scans a workspace multigraph and identifies high-probability duplicate entities
    without altering any database records.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, label, entity_type, text_content, node_type
        FROM lgnn_nodes 
        WHERE app_id = ? AND (is_archived = 0 OR is_archived IS NULL)
    """, (app_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []

    nodes = [dict(r) for r in rows]
    for n in nodes:
        lbl = n.get("label") or n.get("id") or ""
        cleaned, slug = normalize_label(lbl)
        n["_cleaned"] = cleaned
        n["_slug"] = slug
        n["_tokens"] = [t for t in re.split(r'[\s\-_]+', cleaned.lower()) if len(t) > 1]

    candidates: List[Dict[str, Any]] = []
    seen_pairs: Set[Tuple[str, str]] = set()

    # 1. Exact Slug Match (Different labels mapping to the exact same normalized slug)
    slug_map = defaultdict(list)
    for n in nodes:
        if n["_slug"]:
            slug_map[n["_slug"]].append(n)

    for slug, group in slug_map.items():
        if len(group) > 1:
            # Pick canonical primary: preferentially the one with longer/more detailed label
            sorted_group = sorted(group, key=lambda x: (len(x.get("text_content") or ""), len(x.get("label") or "")), reverse=True)
            primary = sorted_group[0]
            for dup in sorted_group[1:]:
                if dup["id"] == primary["id"]:
                    continue
                pair_key = tuple(sorted([primary["id"], dup["id"]]))
                if pair_key in seen_pairs:
                    continue
                if not are_types_compatible(primary.get("entity_type"), dup.get("entity_type")):
                    continue

                seen_pairs.add(pair_key)
                candidates.append({
                    "primary_id": primary["id"],
                    "primary_label": primary.get("label") or primary["id"],
                    "primary_type": primary.get("entity_type", "standard"),
                    "duplicate_id": dup["id"],
                    "duplicate_label": dup.get("label") or dup["id"],
                    "duplicate_type": dup.get("entity_type", "standard"),
                    "confidence": 1.0,
                    "match_type": "canonical_slug_exact",
                    "reason": f"Identical normalized slug '{slug}' after honorific/punctuation normalization."
                })

    # 2. Unique Surname Containment (e.g. "Puttkamer" -> "Jesko von Puttkamer")
    # Build frequency of single-token surnames
    all_surnames = defaultdict(list)
    for n in nodes:
        if n["_tokens"]:
            surname = n["_tokens"][-1]
            if len(surname) > 3:
                all_surnames[surname].append(n)

    for n in nodes:
        # Check if node is just a single token / surname
        if len(n["_tokens"]) == 1:
            single = n["_tokens"][0]
            matches = all_surnames.get(single, [])
            # Only consider if there is exactly ONE multi-token full name candidate with this surname
            full_candidates = [m for m in matches if len(m["_tokens"]) > 1 and m["id"] != n["id"]]
            if len(full_candidates) == 1:
                primary = full_candidates[0]
                pair_key = tuple(sorted([primary["id"], n["id"]]))
                if pair_key not in seen_pairs and are_types_compatible(primary.get("entity_type"), n.get("entity_type")):
                    seen_pairs.add(pair_key)
                    candidates.append({
                        "primary_id": primary["id"],
                        "primary_label": primary.get("label") or primary["id"],
                        "primary_type": primary.get("entity_type", "standard"),
                        "duplicate_id": n["id"],
                        "duplicate_label": n.get("label") or n["id"],
                        "duplicate_type": n.get("entity_type", "standard"),
                        "confidence": 0.94,
                        "match_type": "unique_surname_alias",
                        "reason": f"Single surname '{single}' uniquely resolves to '{primary.get('label')}'."
                    })

    # 3. High Fuzzy Sequence Similarity (Typo detection, e.g. >= 0.92)
    # Check within clusters having similar first 3 letters to avoid O(N^2) over thousands of nodes
    prefix_clusters = defaultdict(list)
    for n in nodes:
        if len(n["_slug"]) >= 3:
            prefix = n["_slug"][:3]
            prefix_clusters[prefix].append(n)

    for prefix, cluster in prefix_clusters.items():
        if len(cluster) < 2 or len(cluster) > 80:
            continue
        for i in range(len(cluster)):
            n1 = cluster[i]
            for j in range(i + 1, len(cluster)):
                n2 = cluster[j]
                pair_key = tuple(sorted([n1["id"], n2["id"]]))
                if pair_key in seen_pairs:
                    continue
                if not are_types_compatible(n1.get("entity_type"), n2.get("entity_type")):
                    continue

                # CRITICAL GUARDRAIL: Do not fuzzy-match artifacts/catalog numbers where digit differences denote distinct objects
                is_artifact = (n1.get("entity_type") in {"artifact", "object"} or n2.get("entity_type") in {"artifact", "object"})
                digits1 = re.findall(r'\d+', n1["_slug"])
                digits2 = re.findall(r'\d+', n2["_slug"])
                if is_artifact or (digits1 != digits2):
                    continue

                ratio = difflib.SequenceMatcher(None, n1["_slug"], n2["_slug"]).ratio()
                if ratio >= min_confidence:
                    seen_pairs.add(pair_key)
                    # Pick primary as the longer/richer label
                    if len(n1.get("label") or n1["id"]) >= len(n2.get("label") or n2["id"]):
                        pri, dup = n1, n2
                    else:
                        pri, dup = n2, n1

                    candidates.append({
                        "primary_id": pri["id"],
                        "primary_label": pri.get("label") or pri["id"],
                        "primary_type": pri.get("entity_type", "standard"),
                        "duplicate_id": dup["id"],
                        "duplicate_label": dup.get("label") or dup["id"],
                        "duplicate_type": dup.get("entity_type", "standard"),
                        "confidence": round(ratio, 3),
                        "match_type": "fuzzy_typo_match",
                        "reason": f"High fuzzy similarity ({int(ratio * 100)}%) between '{pri.get('label')}' and '{dup.get('label')}'."
                    })

    # Sort candidates by confidence descending
    candidates.sort(key=lambda c: (c["confidence"], len(c["primary_label"])), reverse=True)
    return candidates[:limit]

def resolve_clusters(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Given pairwise candidates, constructs equivalence components and resolves
    each component into 1 canonical primary and N duplicates.
    Eliminates redundant/chained pairwise operations and circular references.
    """
    if not candidates:
        return []

    adj = defaultdict(set)
    meta = {}
    for c in candidates:
        pri = c["primary_id"]
        dup = c["duplicate_id"]
        adj[pri].add(dup)
        adj[dup].add(pri)
        if pri not in meta:
            meta[pri] = {"label": c.get("primary_label", pri), "type": c.get("primary_type", "standard"), "conf": c.get("confidence", 1.0)}
        if dup not in meta:
            meta[dup] = {"label": c.get("duplicate_label", dup), "type": c.get("duplicate_type", "standard"), "conf": c.get("confidence", 1.0)}

    visited = set()
    resolved_pairs = []

    for node in sorted(adj.keys()):
        if node not in visited:
            comp = []
            queue = [node]
            visited.add(node)
            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            if len(comp) < 2:
                continue

            # Pick canonical primary:
            # 1. Prefer standard inventory prefix if artifact (Inv.-Nr. > Inv. Nr. > raw number)
            # 2. Prefer full names with more informative content words (Hans Dominik > Major Dominik)
            # 3. Penalize trailing punctuation (Stab > Stab:, Pavel > Pavel,)
            # 4. Prefer richer/longer label
            def canonical_score(item_id: str) -> Tuple[int, int, int, int, int]:
                lbl = meta.get(item_id, {}).get("label", item_id)
                raw = lbl.strip().rstrip(' ,.:;')
                prefix_score = 3 if (raw.startswith("Inv.-Nr.") or raw.startswith("III C")) else (1 if "Inv" in raw else 0)
                cleaned = HONORIFICS_REGEX.sub('', raw).strip(' ,.-_')
                cleaned_words = len([w for w in cleaned.split() if len(w) > 1])
                no_trailing_punct = 1 if lbl == raw else 0
                return (prefix_score, cleaned_words, no_trailing_punct, len(cleaned), len(raw))

            comp.sort(key=canonical_score, reverse=True)
            canonical_pri = comp[0]

            for dup_id in comp[1:]:
                matching_confs = [
                    c["confidence"] for c in candidates 
                    if (c["primary_id"] in {canonical_pri, dup_id} and c["duplicate_id"] in {canonical_pri, dup_id})
                ]
                conf = max(matching_confs) if matching_confs else 0.94
                resolved_pairs.append({
                    "primary_id": canonical_pri,
                    "primary_label": meta.get(canonical_pri, {}).get("label", canonical_pri),
                    "duplicate_id": dup_id,
                    "duplicate_label": meta.get(dup_id, {}).get("label", dup_id),
                    "confidence": conf
                })

    return resolved_pairs


def execute_merge(app_id: str, primary_id: str, duplicate_id: str, dry_run: bool = True) -> Dict[str, Any]:
    """
    Reroutes all inbound and outbound edges from duplicate_id to primary_id,
    and removes duplicate_id. If dry_run=True, no mutations are committed.
    """
    if primary_id == duplicate_id:
        return {"status": "noop", "message": "Primary and duplicate IDs are identical."}

    conn = get_db_connection()
    cursor = conn.cursor()

    # Inbound edges (target = duplicate_id)
    cursor.execute("""
        SELECT COUNT(*) FROM lgnn_multigraph_edges 
        WHERE app_id = ? AND target = ?
    """, (app_id, duplicate_id))
    inbound_count = cursor.fetchone()[0]

    # Outbound edges (source = duplicate_id)
    cursor.execute("""
        SELECT COUNT(*) FROM lgnn_multigraph_edges 
        WHERE app_id = ? AND source = ?
    """, (app_id, duplicate_id))
    outbound_count = cursor.fetchone()[0]

    total_edges_affected = inbound_count + outbound_count

    if dry_run:
        conn.close()
        return {
            "status": "dry_run",
            "app_id": app_id,
            "primary_id": primary_id,
            "duplicate_id": duplicate_id,
            "edges_to_reroute": total_edges_affected,
            "inbound_edges": inbound_count,
            "outbound_edges": outbound_count,
            "action": f"Would reroute {total_edges_affected} edges from '{duplicate_id}' to '{primary_id}' and delete '{duplicate_id}'."
        }

    # Execute mutations
    # 1. Reroute outbound
    cursor.execute("""
        UPDATE lgnn_multigraph_edges 
        SET source = ? 
        WHERE app_id = ? AND source = ?
    """, (primary_id, app_id, duplicate_id))

    # 2. Reroute inbound
    cursor.execute("""
        UPDATE lgnn_multigraph_edges 
        SET target = ? 
        WHERE app_id = ? AND target = ?
    """, (primary_id, app_id, duplicate_id))

    # 3. Clean up self-loops if source == target
    cursor.execute("""
        DELETE FROM lgnn_multigraph_edges 
        WHERE app_id = ? AND source = target
    """, (app_id,))

    # 4. Remove duplicate node
    cursor.execute("""
        DELETE FROM lgnn_nodes 
        WHERE app_id = ? AND id = ?
    """, (app_id, duplicate_id))

    conn.commit()
    conn.close()

    # 5. Re-synchronize conflict rules
    conflicts = sync_conflicts_for_app(app_id)

    return {
        "status": "executed",
        "app_id": app_id,
        "primary_id": primary_id,
        "duplicate_id": duplicate_id,
        "edges_rerouted": total_edges_affected,
        "active_conflicts_remaining": len(conflicts)
    }


def execute_batch_merge(
    app_id: str,
    merges: Optional[List[Dict[str, str]]] = None,
    min_confidence: float = 0.90,
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    Executes an atomic batch merge across a workspace multigraph:
    - Clusters transitive duplicate candidates into disjoint components.
    - Resolves all edges from duplicate nodes to canonical primary nodes in an atomic transaction.
    - Prunes duplicate node records.
    - Synchronizes conflicts and triggers edge weight recalculation.
    """
    if merges:
        raw_candidates = [
            {"primary_id": m["primary_id"], "duplicate_id": m["duplicate_id"], "confidence": 1.0}
            for m in merges if m.get("primary_id") and m.get("duplicate_id") and m["primary_id"] != m["duplicate_id"]
        ]
        resolved_tasks = resolve_clusters(raw_candidates)
    else:
        candidates = find_merge_candidates(app_id=app_id, min_confidence=min_confidence, limit=500)
        resolved_tasks = resolve_clusters(candidates)

    if not resolved_tasks:
        return {
            "status": "noop",
            "app_id": app_id,
            "dry_run": dry_run,
            "merges_planned": 0,
            "edges_affected": 0,
            "tasks": []
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    total_edges = 0
    task_reports = []

    for task in resolved_tasks:
        pri = task["primary_id"]
        dup = task["duplicate_id"]

        cursor.execute("SELECT COUNT(*) FROM lgnn_multigraph_edges WHERE app_id = ? AND target = ?", (app_id, dup))
        in_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM lgnn_multigraph_edges WHERE app_id = ? AND source = ?", (app_id, dup))
        out_count = cursor.fetchone()[0]
        edges_affected = in_count + out_count
        total_edges += edges_affected

        task_reports.append({
            "primary_id": pri,
            "primary_label": task.get("primary_label", pri),
            "duplicate_id": dup,
            "duplicate_label": task.get("duplicate_label", dup),
            "confidence": task.get("confidence", 1.0),
            "edges_to_reroute": edges_affected,
            "inbound_edges": in_count,
            "outbound_edges": out_count
        })

    if dry_run:
        conn.close()
        return {
            "status": "dry_run",
            "app_id": app_id,
            "dry_run": True,
            "merges_planned": len(task_reports),
            "total_edges_affected": total_edges,
            "tasks": task_reports
        }

    # ATOMIC EXECUTION TRANSACTION
    try:
        for task in task_reports:
            pri = task["primary_id"]
            dup = task["duplicate_id"]

            cursor.execute("""
                UPDATE lgnn_multigraph_edges 
                SET source = ? 
                WHERE app_id = ? AND source = ?
            """, (pri, app_id, dup))

            cursor.execute("""
                UPDATE lgnn_multigraph_edges 
                SET target = ? 
                WHERE app_id = ? AND target = ?
            """, (pri, app_id, dup))

            cursor.execute("""
                DELETE FROM lgnn_multigraph_edges 
                WHERE app_id = ? AND source = target
            """, (app_id,))

            cursor.execute("""
                DELETE FROM lgnn_nodes 
                WHERE app_id = ? AND id = ?
            """, (app_id, dup))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Atomic batch merge transaction failed: {e}")
        raise e

    conn.close()

    # Re-synchronize conflicts and edge weights
    conflicts = sync_conflicts_for_app(app_id)
    weights_summary = {}
    try:
        from .weights import recalculate_case_weights
        weights_summary = recalculate_case_weights(app_id)
    except Exception as we:
        logger.warning(f"Could not auto-recalculate weights after batch merge: {we}")

    return {
        "status": "executed",
        "app_id": app_id,
        "dry_run": False,
        "nodes_pruned": len(task_reports),
        "total_edges_rerouted": total_edges,
        "active_conflicts_remaining": len(conflicts),
        "weights_summary": weights_summary,
        "tasks": task_reports
    }

