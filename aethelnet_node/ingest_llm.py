import os
import json
import logging
import urllib.request
import urllib.error
import hashlib
import datetime
from typing import Dict, Any, List, Optional
import torch

from .ontology import registry
from . import database
from .state import text_to_embedding

logger = logging.getLogger("Aethelnet.IngestLLM")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:latest")

def compute_claim_hash(app_id: str, source_doc_id: str, src: str, tgt: str, rtype: str) -> str:
    """
    Computes an idempotent, deterministic content-addressed hash for a claim edge.
    Guarantees that re-ingesting or updating the same document modifies the edge in place
    rather than generating orphaned duplicate edges.
    """
    doc_anchor = source_doc_id.strip() if source_doc_id else "stream"
    raw_key = f"{app_id}:{doc_anchor}:{src.strip().lower()}:{tgt.strip().lower()}:{rtype.strip().lower()}"
    return f"claim_{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:16]}"

def infer_entity_type(name: str, schema, default_type: str = "concept") -> str:
    """
    Infers an ontology entity type from an entity's name, titles, and lexical context.
    Matches against schema.entities if available.
    """
    nl = name.lower()
    allowed_types = set(schema.entities.keys()) if schema and hasattr(schema, "entities") and schema.entities else set()
    
    # Priority Heuristic Classification
    classified = None
    if any(k in nl for k in ["tp53", "brca1", "brca2", "pten", "egfr", "kras", "braf", "gene", "locus"]):
        for cand in ["gene"]:
            if cand in allowed_types:
                classified = cand
                break

    elif any(k in nl for k in ["p.", "c.", "variant", "missense", "nonsense", "frameshift", "snv", "i251t", "y465h", "y138c", "r1699q", "r175h", "r273h", "r248w"]):
        for cand in ["protein_variant", "variant"]:
            if cand in allowed_types:
                classified = cand
                break

    elif any(k in nl for k in ["domain", "dbd", "brct", "phosphatase", "zinc finger", "kinase"]):
        for cand in ["structural_domain", "domain"]:
            if cand in allowed_types:
                classified = cand
                break

    elif any(k in nl for k in ["syndrome", "cancer", "carcinoma", "hboc", "fraumeni", "cowden", "phenotype", "disease"]):
        for cand in ["phenotype", "disease"]:
            if cand in allowed_types:
                classified = cand
                break

    elif any(k in nl for k in ["bank", "corp", "fund", " ag", " gmbh", " llc", " ltd", " inc", "holding", "trust", "museum", "foundation", "ministry", "court", "sec", "bpi", "ey", "kpmg", "citadel"]):
        for cand in ["institution", "organization", "corporation", "company"]:
            if cand in allowed_types:
                classified = cand
                break
        if not classified:
            classified = "organization" if "organization" in allowed_types else "institution"

    elif any(k in nl for k in ["dr.", "dr ", "prof", "mr.", "frau", "herr", "hauptmann", "king", "sultan", "officer", "whistleblower", "director", "minister", "trader", "ceo", "cfo", "auditor", "witness", "glauning", "njoya", "putlitz"]):
        for cand in ["person", "actor", "individual", "subjekt"]:
            if cand in allowed_types:
                classified = cand
                break
        if not classified:
            classified = "person"

    elif any(k in nl for k in ["thron", "maske", "schwert", "statue", "bronze", "painting", "ledger", "certificate", "escrow", "shares", "wire", "token", "asset", "transfer", "beadwork"]):
        for cand in ["artifact", "asset", "object", "item"]:
            if cand in allowed_types:
                classified = cand
                break
        if not classified:
            classified = "artifact"

    elif any(k in nl for k in ["filing", "report", "statement", "affidavit", "dossier", "log", "contract", "email", "dispatch", "bulletin", "notice"]):
        for cand in ["document", "evidence", "source_doc"]:
            if cand in allowed_types:
                classified = cand
                break
        if not classified:
            classified = "document"

    elif any(k in nl for k in ["berlin", "bamum", "foumban", "manila", "singapore", "munich", "zurich", "cayman", "bvi", "london", "cameroon", "germany", "philippines"]):
        for cand in ["location", "place", "jurisdiction"]:
            if cand in allowed_types:
                classified = cand
                break
        if not classified:
            classified = "location"

    if classified and (not allowed_types or classified in allowed_types):
        return classified

    # Fallback to schema's first defined entity type or provided default
    if allowed_types:
        return list(allowed_types)[0]
    return default_type

def extract_year(text: str) -> str:
    import re
    match = re.search(r'\b(1[89]\d\d|20\d\d)\b', text)
    return match.group(1) if match else ""

def fast_heuristic_extract(text: str, schema) -> Dict[str, Any]:
    """
    High-speed, zero-GPU rule-based triple extractor (<10ms).
    Handles:
    - Pipe-delimited: 'Entity | relation | Target | Evidence Quote'
    - Arrow-delimited: 'Entity -> relation -> Target'
    - CSV/TSV: 'Entity, relation, Target, Quote'
    - Markdown lists: '- Entity -> relation -> Target'
    - JSON snippets
    """
    import re
    import csv
    import io

    nodes = {}
    edges = []
    
    allowed_relations = {r.lower(): r for r in schema.relations.keys()} if schema and hasattr(schema, "relations") else {}
    allowed_entities = list(schema.entities.keys()) if schema and hasattr(schema, "entities") and schema.entities else ["concept"]
    default_entity = allowed_entities[0] if allowed_entities else "concept"

    lines = text.strip().split("\n")
    for line in lines:
        line_clean = line.strip()
        if not line_clean or line_clean.startswith("#") or line_clean.startswith("//"):
            continue

        # Strip leading bullet points
        line_clean = re.sub(r'^[-*+•\d.]+\s*', '', line_clean)

        parts = []
        if "|" in line_clean:
            parts = [p.strip() for p in line_clean.split("|")]
        elif re.search(r'->|-->|=>', line_clean):
            parts = [p.strip() for p in re.split(r'->|-->|=>', line_clean)]
        elif "\t" in line_clean and len(line_clean.split("\t")) >= 3:
            parts = [p.strip() for p in line_clean.split("\t")]
        elif "," in line_clean and len(line_clean.split(",")) >= 3:
            try:
                reader = csv.reader(io.StringIO(line_clean))
                row = next(reader)
                parts = [p.strip() for p in row if p.strip()]
            except Exception:
                parts = [p.strip() for p in line_clean.split(",")]

        if len(parts) >= 3:
            src_raw = parts[0].strip()
            rel_raw = parts[1].strip()
            tgt_raw = parts[2].strip()
            quote = parts[3].strip() if len(parts) > 3 else line_clean

            if not src_raw or not rel_raw or not tgt_raw:
                continue

            src_slug = src_raw.lower().replace(" ", "_").replace("-", "_")
            tgt_slug = tgt_raw.lower().replace(" ", "_").replace("-", "_")
            rel_norm = rel_raw.lower().replace(" ", "_").replace("-", "_")

            # Map to nearest schema relation if available
            final_rel = allowed_relations.get(rel_norm, rel_norm)
            if final_rel not in allowed_relations and allowed_relations:
                # Check for prefix or substring match
                matched = None
                for k, v in allowed_relations.items():
                    if k in rel_norm or rel_norm in k:
                        matched = v
                        break
                final_rel = matched or list(allowed_relations.values())[0]

            src_type = infer_entity_type(src_raw, schema, default_entity)
            tgt_type = infer_entity_type(tgt_raw, schema, default_entity)

            nodes[src_slug] = {"id": src_slug, "label": src_raw, "entity_type": src_type}
            nodes[tgt_slug] = {"id": tgt_slug, "label": tgt_raw, "entity_type": tgt_type}

            edges.append({
                "source": src_slug,
                "target": tgt_slug,
                "relation_type": final_rel,
                "timestamp": extract_year(quote),
                "evidence_quote": quote
            })

    return {"nodes": list(nodes.values()), "edges": edges, "mode": "heuristic"}

def extract_triples_with_local_llm(text: str, app_id: str, mode: str = "heuristic") -> Dict[str, Any]:
    """
    Extracts structured entities and multigraph edges from text.
    - If mode in ('heuristic', 'fast'), uses fast_heuristic_extract (<10ms).
    - If mode == 'auto', checks if structured delimiters exist; if so, uses fast_heuristic_extract.
    - If mode == 'llm', calls local Ollama with fallback.
    """
    schema = registry.get_schema(app_id) or registry.get_schema("blank_investigation") or registry.get_schema("universal_forensic")
    if not schema:
        raise ValueError(f"Unknown app_id '{app_id}' and default ontology missing.")

    stripped = text.strip()
    if not stripped:
        return {"nodes": [], "edges": []}

    # 1. Fast Path: Raw JSON
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict) and ("nodes" in parsed or "edges" in parsed):
                return parsed
        except Exception:
            pass

    # 2. Heuristic Mode Dispatch
    if mode in ("heuristic", "fast"):
        return fast_heuristic_extract(stripped, schema)

    has_structured_lines = any(
        ("|" in line or "->" in line or "-->" in line or "\t" in line or ("," in line and len(line.split(",")) >= 3))
        for line in stripped.split("\n") if line.strip() and not line.strip().startswith("#")
    )

    if mode == "auto" and has_structured_lines:
        return fast_heuristic_extract(stripped, schema)

    # 3. Local LLM Extraction via Ollama
    entities_desc = "\n".join([
        f"- {etype.type_id}: {etype.name} ({etype.description})"
        for etype in schema.entities.values()
    ])
    relations_desc = "\n".join([
        f"- {rtype.type_id}: {rtype.name} (from {rtype.allowed_source_types or 'any'} -> {rtype.allowed_target_types or 'any'})"
        for rtype in schema.relations.values()
    ])

    prompt = f"""You are the Aethelnet Sovereign Intelligence Extraction Engine.
Extract entities and relationships from the provided text according to the following strict ontology for '{schema.name}'.

ALLOWED ENTITY TYPES:
{entities_desc}

ALLOWED RELATION TYPES:
{relations_desc}

TEXT TO ANALYZE:
\"\"\"{text[:4000]}\"\"\"

Respond with ONLY valid JSON containing two lists: 'nodes' and 'edges'.
Format:
{{
  "nodes": [
    {{
      "id": "unique_lowercase_slug",
      "label": "Human Readable Name",
      "entity_type": "one_of_the_allowed_entity_types",
      "properties": {{"notes": "extracted detail"}}
    }}
  ],
  "edges": [
    {{
      "source": "source_node_id",
      "target": "target_node_id",
      "relation_type": "one_of_the_allowed_relation_types",
      "timestamp": "e.g. 1905 or 2026",
      "evidence_quote": "exact quote from text verifying this link"
    }}
  ]
}}
"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 1024,
            "num_thread": 4
        }
    }

    try:
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            raw_response = res_data.get("response", "{}")
            extracted = json.loads(raw_response)
            return extracted
    except Exception as e:
        logger.warning(f"Local LLM extraction failed or timed out: {e}. Executing fast heuristic fallback.")
        return fast_heuristic_extract(text, schema)

def detect_action_events(
    initial_conflicts: List[Dict[str, Any]],
    new_conflicts: List[Dict[str, Any]],
    app_id: str
) -> List[Dict[str, Any]]:
    """
    Analyzes topological dissonance transitions before and after an evidentiary ingestion.
    Emits ActionEvents when new contradictions emerge, deadlocks occur, or verdicts shift.
    """
    events = []

    def extract_ents(c):
        ents = c.get("entities")
        if not ents:
            src = c.get("source")
            tgt = c.get("target")
            ents = [src, tgt] if src and tgt else []
        return [str(x) for x in ents if x]

    def extract_delta(c):
        if "weight_delta" in c:
            return float(c["weight_delta"])
        wa = c.get("weight_a")
        wb = c.get("weight_b")
        if wa is not None and wb is not None:
            return abs(float(wa) - float(wb))
        return 0.0

    def conflict_key(c):
        ents = tuple(sorted(extract_ents(c)))
        rule = c.get("rule_id") or c.get("rule_name") or "conflict"
        return f"{rule}:{ents}"

    init_map = {conflict_key(c): c for c in initial_conflicts}
    new_map = {conflict_key(c): c for c in new_conflicts}

    # 1. New contradictions triggered by incoming evidence
    for k, c in new_map.items():
        delta = extract_delta(c)
        ents = extract_ents(c)
        rule_name = c.get("rule_name", "Contradiction")
        verdict = c.get("verdict", "Contested")

        if k not in init_map:
            is_deadlock = delta < 0.04
            events.append({
                "event_type": "DEADLOCK_TRIGGERED" if is_deadlock else "NEW_CONTRADICTION_DETECTED",
                "severity": "CRITICAL" if is_deadlock else "WARNING",
                "rule_name": rule_name,
                "entities": ents,
                "delta": delta,
                "verdict": verdict,
                "message": f"Contradiction '{rule_name}' between {ents}: {verdict} (Δ={delta:.2f})",
                "action_required": "AUDIT_PRIMARY_ARCHIVE" if is_deadlock else "MONITOR_DISCOVERY"
            })
        else:
            old_c = init_map[k]
            old_delta = extract_delta(old_c)
            
            # Check if an existing deadlock was decisively resolved
            if old_delta < 0.04 and delta >= 0.15:
                events.append({
                    "event_type": "DEADLOCK_RESOLVED_DECISIVE",
                    "severity": "SUCCESS",
                    "rule_name": rule_name,
                    "entities": ents,
                    "old_delta": old_delta,
                    "new_delta": delta,
                    "verdict": verdict,
                    "message": f"Deadlock between {ents} decisively resolved by incoming evidence (Δ={delta:.2f}): {verdict}",
                    "action_required": "ARCHIVE_CASE_VERDICT"
                })
            elif abs(delta - old_delta) >= 0.08:
                events.append({
                    "event_type": "CONTRADICTION_VERDICT_SHIFTED",
                    "severity": "INFO",
                    "rule_name": rule_name,
                    "entities": ents,
                    "old_delta": old_delta,
                    "new_delta": delta,
                    "verdict": verdict,
                    "message": f"Evidence delta shifted from {old_delta:.2f} to {delta:.2f} ({verdict})",
                    "action_required": "REVIEW_DELTA_CHANGE"
                })

    # 2. Contradictions eliminated
    for k, c in init_map.items():
        if k not in new_map:
            ents = extract_ents(c)
            events.append({
                "event_type": "CONTRADICTION_ELIMINATED",
                "severity": "INFO",
                "rule_name": c.get("rule_name", "Contradiction"),
                "entities": ents,
                "message": f"Contradiction between {ents} was completely eliminated.",
                "action_required": "NONE"
            })

    return events

def ingest_and_commit_to_graph(
    text: str,
    app_id: str,
    source_doc_id: str = "",
    auto_dedup: bool = False,
    mode: str = "heuristic"
) -> Dict[str, Any]:
    """
    Idempotent Reactive Ingestion Pipeline Hook:
    1. Records pre-ingest contradiction state.
    2. Extracts structured entities and relations (Fast Heuristic or Local LLM).
    3. Persists nodes and edges with deterministic SHA256 claim IDs (prevents duplicates).
    4. Evaluates initial epistemic authority weights directly from citations.
    5. Optionally runs Disjoint-Set transitive deduplication if auto_dedup=True.
    6. Recalculates whole-case multi-source corroboration weights.
    7. Evaluates contradiction shifts and emits structured ActionEvents.
    """
    # 1. Snapshot pre-existing conflicts
    try:
        from .ontology import registry as ont_reg
        initial_edges = database.get_multigraph_edges(app_id=app_id)
        initial_conflicts = ont_reg.detect_conflicts(app_id, initial_edges)
    except Exception:
        initial_conflicts = []

    # 2. Extract structured triples
    extracted = extract_triples_with_local_llm(text, app_id, mode=mode)
    nodes = extracted.get("nodes", [])
    edges = extracted.get("edges", [])

    created_nodes = 0
    created_edges = 0
    updated_edges = 0

    # Index existing edges for this app
    existing_edge_ids = {e.get("edge_id") for e in database.get_multigraph_edges(app_id=app_id)}

    committed_node_ids = []
    # 3. Commit Nodes
    for n in nodes:
        nid = str(n.get("id", "")).strip().lower().replace(" ", "_")
        if not nid:
            continue
        if nid not in committed_node_ids:
            committed_node_ids.append(nid)
        label = n.get("label", nid)
        etype = n.get("entity_type", "concept")
        props = n.get("properties", {})
        emb = text_to_embedding(f"{label} {json.dumps(props)}")

        database.save_node(
            node_id=nid,
            embedding=emb,
            mean_activation=0.0,
            confidence=0.9,
            plateau_factor=0.0,
            is_grounded=True,
            help_chain=False,
            text_content=label,
            node_type=etype,
            meta_data=json.dumps({"app_id": app_id, "label": label, **props}),
            app_id=app_id,
            entity_type=etype,
            label=label
        )
        created_nodes += 1

    # 4. Commit Edges with Deterministic Claim Hashes
    doc_ref = source_doc_id.strip() if source_doc_id else "direct_input"

    for e in edges:
        src = str(e.get("source", "")).strip().lower().replace(" ", "_")
        tgt = str(e.get("target", "")).strip().lower().replace(" ", "_")
        rtype = str(e.get("relation_type", "")).strip().lower().replace(" ", "_")
        if not src or not tgt or not rtype:
            continue

        # Deterministic Idempotent Claim ID
        edge_id = compute_claim_hash(app_id, doc_ref, src, tgt, rtype)

        # Compute initial epistemic edge weight based on source tier & verbatim quote
        try:
            from .weights import compute_edge_weight
            initial_weight, _ = compute_edge_weight(
                source_doc=doc_ref,
                evidence_quote=e.get("evidence_quote", ""),
                corroboration_count=1
            )
        except Exception:
            initial_weight = 0.55

        if edge_id in existing_edge_ids:
            updated_edges += 1
        else:
            created_edges += 1
            existing_edge_ids.add(edge_id)

        database.save_multigraph_edge(
            edge_id=edge_id,
            app_id=app_id,
            source=src,
            target=tgt,
            relation_type=rtype,
            weight=initial_weight,
            timestamp=e.get("timestamp", ""),
            evidence_quote=e.get("evidence_quote", ""),
            source_doc_id=doc_ref
        )

    # 5. Optional Transitive Deduplication Hook
    dedup_summary = None
    if auto_dedup:
        try:
            from .entity_resolution import execute_batch_merge
            dedup_summary = execute_batch_merge(app_id=app_id, min_confidence=0.92, dry_run=False)
            logger.info(f"[Ingest Pipeline] Auto-dedup executed: {dedup_summary.get('clusters_merged', 0)} clusters merged.")
        except Exception as err:
            logger.warning(f"[Ingest Pipeline] Auto-dedup warning: {err}")

    # 6. Recalculate whole-case multi-source weights
    try:
        from .weights import recalculate_case_weights
        weights_summary = recalculate_case_weights(app_id)
    except Exception as err:
        logger.warning(f"[Ingest Pipeline] Weight recalculation warning: {err}")
        weights_summary = {}

    # 7. Evaluate post-ingest conflict state & emit ActionEvents
    new_conflicts = database.sync_conflicts_for_app(app_id)
    action_events = detect_action_events(initial_conflicts, new_conflicts, app_id)

    if action_events:
        for ev in action_events:
            logger.info(f"[ACTION EVENT: {ev['event_type']}] [{ev['severity']}] {ev['message']}")

    return {
        "status": "success",
        "app_id": app_id,
        "source_doc_id": doc_ref,
        "nodes_ingested": created_nodes,
        "edges_ingested": created_edges,
        "edges_updated": updated_edges,
        "active_conflicts": len(new_conflicts),
        "conflicts": new_conflicts,
        "action_events": action_events,
        "weights_summary": weights_summary,
        "dedup_summary": dedup_summary,
        "new_node_ids": committed_node_ids
    }
