import uuid
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, File, UploadFile, Form, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..ontology import registry, AppOntology, EntityType, RelationType, ConflictRule
from .. import database

router = APIRouter(prefix="/api/ontology", tags=["Ontology & Multigraph"])

class MultigraphEdgeCreate(BaseModel):
    edge_id: Optional[str] = None
    app_id: str = "general"
    source: str
    target: str
    relation_type: str
    weight: float = 1.0
    timestamp: str = ""
    evidence_quote: str = ""
    source_doc_id: str = ""

@router.get("/apps")
def list_apps():
    """Returns a list of all registered workspace apps/ontologies."""
    return {
        "status": "success",
        "apps": registry.list_schemas()
    }

@router.get("/apps/{app_id}")
def get_app_schema(app_id: str):
    """Returns the full schema specification for a specific workspace app."""
    schema = registry.get_schema(app_id)
    if not schema:
        raise HTTPException(status_code=404, detail=f"Ontology for app '{app_id}' not found.")
    return {
        "status": "success",
        "ontology": schema.model_dump()
    }

def parse_flexible_ontology(payload: Dict[str, Any]) -> AppOntology:
    """
    Parses a flexible dictionary into a strictly typed AppOntology instance.
    Supports simple list-of-strings for entities and relations, or explicit dicts.
    """
    app_id = str(payload.get("app_id", "")).strip().lower().replace(" ", "_")
    if not app_id:
        raise ValueError("Field 'app_id' is required.")
    name = str(payload.get("name", "")).strip() or app_id.replace("_", " ").title()
    domain = str(payload.get("domain", "forensics")).strip() or "forensics"
    description = str(payload.get("description", "")).strip()
    icon = str(payload.get("icon", "shield-search")).strip()
    version = str(payload.get("version", "1.0.0")).strip()
    default_view = str(payload.get("default_view", "graph")).strip()

    # Entities
    entities_dict: Dict[str, EntityType] = {}
    raw_entities = payload.get("entities", [])
    if isinstance(raw_entities, list):
        for item in raw_entities:
            if isinstance(item, str):
                tid = item.strip().lower().replace(" ", "_")
                if tid:
                    entities_dict[tid] = EntityType(type_id=tid, name=item.strip().capitalize())
            elif isinstance(item, dict):
                tid = (item.get("type_id") or item.get("name", "")).strip().lower().replace(" ", "_")
                if tid:
                    entities_dict[tid] = EntityType(
                        type_id=tid,
                        name=item.get("name", tid.capitalize()),
                        description=item.get("description", ""),
                        color=item.get("color", "#FFFFFF"),
                        icon=item.get("icon", "circle")
                    )
    elif isinstance(raw_entities, dict):
        for k, v in raw_entities.items():
            if isinstance(v, dict):
                entities_dict[k] = EntityType.model_validate(v)
            elif isinstance(v, EntityType):
                entities_dict[k] = v

    # Relations
    relations_dict: Dict[str, RelationType] = {}
    raw_relations = payload.get("relations", [])
    if isinstance(raw_relations, list):
        for item in raw_relations:
            if isinstance(item, str):
                tid = item.strip().lower().replace(" ", "_")
                if tid:
                    relations_dict[tid] = RelationType(type_id=tid, name=item.strip().capitalize())
            elif isinstance(item, dict):
                tid = (item.get("type_id") or item.get("name", "")).strip().lower().replace(" ", "_")
                if tid:
                    relations_dict[tid] = RelationType(
                        type_id=tid,
                        name=item.get("name", tid.capitalize()),
                        description=item.get("description", ""),
                        color=item.get("color", "#FFFFFF"),
                        is_directional=item.get("is_directional", True),
                        is_conflict_candidate=item.get("is_conflict_candidate", False)
                    )
    elif isinstance(raw_relations, dict):
        for k, v in raw_relations.items():
            if isinstance(v, dict):
                relations_dict[k] = RelationType.model_validate(v)
            elif isinstance(v, RelationType):
                relations_dict[k] = v

    # Conflict rules
    conflict_rules: List[ConflictRule] = []
    raw_rules = payload.get("conflict_rules", [])
    for idx, r in enumerate(raw_rules):
        if isinstance(r, dict):
            rule_id = r.get("rule_id") or f"rule_{idx+1}"
            r_name = r.get("name") or rule_id.replace("_", " ").title()
            conflicting = r.get("conflicting_relations", [])
            if not conflicting and "rel_a" in r and "rel_b" in r:
                conflicting = [r["rel_a"], r["rel_b"]]
            conflict_rules.append(ConflictRule(
                rule_id=rule_id,
                name=r_name,
                conflicting_relations=conflicting,
                severity=r.get("severity", "critical"),
                description=r.get("description", "")
            ))
        elif isinstance(r, ConflictRule):
            conflict_rules.append(r)

    return AppOntology(
        app_id=app_id,
        name=name,
        version=version,
        domain=domain,
        description=description,
        icon=icon,
        entities=entities_dict,
        relations=relations_dict,
        conflict_rules=conflict_rules,
        default_view=default_view
    )

@router.post("/apps")
def register_app_schema(payload: Dict[str, Any]):
    """
    Registers a new runtime workspace ontology or updates an existing one.
    Accepts both full AppOntology JSON and simplified flexible forms.
    """
    try:
        schema_obj = parse_flexible_ontology(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid schema: {e}")

    success = registry.register_schema(schema_obj)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to persist ontology schema.")
    
    # Resync conflicts if case already has edges
    try:
        database.sync_conflicts_for_app(schema_obj.app_id)
    except Exception as e:
        pass

    return {
        "status": "success",
        "message": f"Registered ontology '{schema_obj.app_id}'",
        "ontology": schema_obj.model_dump()
    }

@router.delete("/apps/{app_id}")
def delete_app_schema(app_id: str):
    """Deletes a custom workspace ontology schema and clears its graph."""
    if app_id in ["project_echo", "nexus_osint"]:
        raise HTTPException(status_code=400, detail=f"Cannot delete protected core workspace '{app_id}'.")
    success = registry.delete_schema(app_id)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to delete ontology schema for '{app_id}'.")
    
    # Also purge nodes and edges
    clear_case_multigraph(app_id)
    return {
        "status": "success",
        "message": f"Deleted ontology '{app_id}' and cleared its graph."
    }

@router.get("/multigraph/{app_id}")
def get_multigraph(app_id: str):
    """
    Returns the complete multigraph for a workspace app,
    including typed edges, conflicts, and topological metrics.
    """
    schema = registry.get_schema(app_id)
    if not schema and app_id != "general":
        raise HTTPException(status_code=404, detail=f"App '{app_id}' does not exist.")
    
    graph_data = database.get_app_multigraph(app_id)
    return {
        "status": "success",
        "app_id": app_id,
        "ontology_name": schema.name if schema else "General",
        **graph_data
    }

@router.post("/multigraph/edge")
def create_edge(edge: MultigraphEdgeCreate):
    """Creates or updates a typed edge in the multigraph."""
    edge_id = edge.edge_id or f"edge_{uuid.uuid4().hex[:12]}"
    database.save_multigraph_edge(
        edge_id=edge_id,
        app_id=edge.app_id,
        source=edge.source,
        target=edge.target,
        relation_type=edge.relation_type,
        weight=edge.weight,
        timestamp=edge.timestamp,
        evidence_quote=edge.evidence_quote,
        source_doc_id=edge.source_doc_id
    )
    # Trigger conflict re-sync for this app
    conflicts = database.sync_conflicts_for_app(edge.app_id)
    return {
        "status": "success",
        "edge_id": edge_id,
        "active_conflicts": len(conflicts)
    }

@router.delete("/multigraph/edge/{edge_id}")
def delete_edge(edge_id: str):
    """Deletes a typed edge from the multigraph."""
    database.delete_multigraph_edge(edge_id)
    return {
        "status": "success",
        "message": f"Edge '{edge_id}' deleted."
    }

@router.delete("/multigraph/{app_id}")
def clear_case_multigraph(app_id: str):
    """Purges all edges and nodes associated with this investigation for a clean blank slate."""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lgnn_multigraph_edges WHERE app_id = ?", (app_id,))
    cursor.execute("DELETE FROM lgnn_nodes WHERE app_id = ?", (app_id,))
    conn.commit()
    conn.close()
    return {
        "status": "success",
        "message": f"Cleared all nodes and edges for investigation '{app_id}'."
    }

@router.get("/multigraph/{app_id}/conflicts")
def get_conflicts(app_id: str):
    """Returns all contested dissonance pairs detected for this workspace."""
    conflicts = database.sync_conflicts_for_app(app_id)
    return {
        "status": "success",
        "app_id": app_id,
        "count": len(conflicts),
        "conflicts": conflicts
    }

class TextIngestRequest(BaseModel):
    text: str
    app_id: str
    source_doc_id: Optional[str] = ""
    auto_dedup: Optional[bool] = False
    mode: Optional[str] = "heuristic"

@router.post("/ingest/text")
def ingest_text(req: TextIngestRequest):
    """
    Zero-Shot Structured Ingestion & Reactive Pipeline Hook:
    Extracts entities and relationships according to the active AppOntology,
    computes deterministic idempotent claim IDs, evaluates epistemic weights,
    triggers optional auto-deduplication, and emits ActionEvents on dissonance shifts.
    """
    try:
        from ..ingest_llm import ingest_and_commit_to_graph
    except ImportError:
        from aethelnet_node.ingest_llm import ingest_and_commit_to_graph
        
    result = ingest_and_commit_to_graph(
        text=req.text,
        app_id=req.app_id,
        source_doc_id=req.source_doc_id or "",
        auto_dedup=req.auto_dedup or False,
        mode=req.mode or "heuristic"
    )
    return result

@router.post("/ingest/file")
async def ingest_file_api(
    file: UploadFile = File(...),
    app_id: str = Form("general"),
    source_doc_id: Optional[str] = Form(None),
    auto_dedup: Optional[bool] = Form(False),
    mode: Optional[str] = Form("heuristic")
):
    """
    Multi-Format Document Ingestion Hook:
    Accepts text, markdown, CSV, or JSON dossiers directly from the Sovereign Dropzone.
    """
    try:
        from ..ingest_llm import ingest_and_commit_to_graph
    except ImportError:
        from aethelnet_node.ingest_llm import ingest_and_commit_to_graph

    content_bytes = await file.read()
    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = content_bytes.decode("latin-1", errors="replace")

    doc_id = source_doc_id or file.filename or "uploaded_doc"
    result = await asyncio.to_thread(
        ingest_and_commit_to_graph,
        text=text,
        app_id=app_id,
        source_doc_id=doc_id,
        auto_dedup=bool(auto_dedup),
        mode=str(mode or "heuristic")
    )
    return result


class DaoProposalVerificationRequest(BaseModel):
    proposal_id: Optional[str] = ""
    title: str
    abstract: str
    ipfs_cid: Optional[str] = ""
    app_id: Optional[str] = "quantum_biology_dao"

@router.post("/dao/verify_proposal")
def verify_dao_proposal(req: DaoProposalVerificationRequest):
    """
    Epistemic Truth Verification for DAO Proposals:
    Ingests proposal claims into the verification graph, evaluates dissonance rules,
    and returns a deterministic epistemic validation receipt before
    treasury funds can be released on-chain.
    """
    import hashlib
    import time
    
    app_id = req.app_id or "quantum_biology_dao"
    
    try:
        from ..ingest_llm import ingest_and_commit_to_graph
    except ImportError:
        from aethelnet_node.ingest_llm import ingest_and_commit_to_graph
        
    full_text = f"PROPOSAL TITLE: {req.title}\nIPFS CID: {req.ipfs_cid or 'none'}\n\nABSTRACT & CLAIMS:\n{req.abstract}"
    ingest_res = ingest_and_commit_to_graph(
        text=full_text,
        app_id=app_id,
        source_doc_id=f"DAO_PROP_{req.proposal_id or req.ipfs_cid or 'draft'}"
    )
    
    conflicts = database.sync_conflicts_for_app(app_id)
    approved = len(conflicts) == 0
    
    receipt_payload = f"{req.proposal_id}:{req.ipfs_cid}:{approved}:{len(conflicts)}:{time.time()}".encode()
    receipt_hash = "0x" + hashlib.sha256(receipt_payload).hexdigest()
    
    return {
        "status": "success",
        "proposal_id": req.proposal_id,
        "ipfs_cid": req.ipfs_cid,
        "approved": approved,
        "active_conflicts": len(conflicts),
        "conflicts": conflicts,
        "extracted_nodes": ingest_res.get("nodes_ingested", 0),
        "extracted_edges": ingest_res.get("edges_ingested", 0),
        "validation_receipt": receipt_hash,
        "recommendation": "ELIGIBLE_FOR_TREASURY_FUNDING" if approved else "CONTESTED_CLAIMS_DETECTED_REJECT"
    }


# =====================================================================
# HEADLESS ENTITY RESOLUTION & DEDUPLICATION API
# =====================================================================

@router.get("/multigraph/{app_id}/dedup_candidates")
def get_dedup_candidates(app_id: str, min_confidence: float = 0.88, limit: int = 50):
    """
    Returns candidate duplicate entities identified via canonical slug matching,
    unique surname containment, and constrained fuzzy typo detection.
    """
    try:
        from ..entity_resolution import find_merge_candidates
    except ImportError:
        from aethelnet_node.entity_resolution import find_merge_candidates
        
    candidates = find_merge_candidates(app_id=app_id, min_confidence=min_confidence, limit=limit)
    return {
        "status": "success",
        "app_id": app_id,
        "count": len(candidates),
        "candidates": candidates
    }

class DedupExecuteRequest(BaseModel):
    merges: Optional[List[Dict[str, str]]] = None
    min_confidence: Optional[float] = 0.92
    dry_run: Optional[bool] = False

@router.post("/multigraph/{app_id}/dedup_execute")
@router.post("/multigraph/{app_id}/dedup_batch_execute")
def execute_dedup(app_id: str, req: DedupExecuteRequest):
    """
    Executes atomic node merging and edge rerouting:
    - Clusters transitive duplicate candidates into disjoint components.
    - Reroutes inbound and outbound edges from duplicate to canonical primary node.
    - Removes redundant duplicate node records.
    - Automatically re-evaluates conflict detection rules and recalculates epistemic weights.
    If dry_run=True, returns the proposed mutation plan without writing to database.
    """
    try:
        from ..entity_resolution import execute_batch_merge
    except ImportError:
        from aethelnet_node.entity_resolution import execute_batch_merge
        
    res = execute_batch_merge(
        app_id=app_id,
        merges=req.merges,
        min_confidence=req.min_confidence or 0.92,
        dry_run=req.dry_run if req.dry_run is not None else False
    )
    return res


# =====================================================================
# EPISTEMIC EDGE WEIGHTS & CREDIBILITY SCORING API
# =====================================================================

@router.post("/multigraph/{app_id}/weights_recalculate")
def recalculate_weights_api(app_id: str):
    """
    Recalculates institutional source authority and quote completeness
    for all edges in the case multigraph, re-evaluates competing claims,
    and updates mathematical dissonance resolution verdicts.
    """
    try:
        from ..weights import recalculate_case_weights
    except ImportError:
        from aethelnet_node.weights import recalculate_case_weights

    stats = recalculate_case_weights(app_id)
    conflicts = database.sync_conflicts_for_app(app_id)

    # Count decisive verdicts vs deadlocks
    decisive_count = sum(1 for c in conflicts if c.get("weight_delta", 0) >= 0.15)
    moderate_count = sum(1 for c in conflicts if 0.04 <= c.get("weight_delta", 0) < 0.15)
    deadlock_count = sum(1 for c in conflicts if c.get("weight_delta", 0) < 0.04)

    return {
        "status": "success",
        "app_id": app_id,
        "weights_summary": stats,
        "conflicts_evaluated": len(conflicts),
        "verdict_distribution": {
            "decisive_verdicts": decisive_count,
            "moderate_leads": moderate_count,
            "deadlocks": deadlock_count
        }
    }


# =====================================================================
# CRYPTOGRAPHIC STATE ROOT NOTARIZATION API (THE FORGE)
# =====================================================================

@router.get("/multigraph/{app_id}/state_root")
def get_state_root_api(app_id: str):
    """
    Computes an immutable, deterministic SHA-256 state root for the investigation multigraph.
    """
    return database.compute_case_state_root(app_id)


@router.post("/multigraph/{app_id}/notarize")
async def notarize_case_api(app_id: str, use_paymaster: bool = Query(True)):
    """
    Computes the canonical state root and commits it on-chain to TheForge smart contract
    via gasless Account Abstraction (ERC-4337).
    """
    import asyncio
    try:
        from ..forge_client import forge_client
    except ImportError:
        from aethelnet_node.forge_client import forge_client

    state_info = database.compute_case_state_root(app_id)
    state_root = state_info["state_root"]
    node_count = state_info["node_count"]
    edge_count = state_info["edge_count"]

    if not forge_client.is_connected():
        return {
            "status": "dry_run_offline",
            "message": "Web3 RPC not connected; state root computed locally but not broadcast.",
            "case_id": app_id,
            "state_root": state_root,
            "node_count": node_count,
            "edge_count": edge_count,
            "contract": forge_client.contract_address
        }

    try:
        receipt = await asyncio.to_thread(
            forge_client.commit_state_root,
            case_id=app_id,
            state_root=state_root,
            node_count=node_count,
            edge_count=edge_count,
            use_paymaster=use_paymaster
        )
        return {
            "status": "success",
            "case_id": app_id,
            "receipt": receipt,
            "contract": forge_client.contract_address
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "case_id": app_id,
            "state_root": state_root,
            "contract": forge_client.contract_address
        }


@router.get("/multigraph/{app_id}/notarization")
async def get_notarization_api(app_id: str):
    """
    Retrieves the on-chain notarization status and timestamp from TheForge contract.
    """
    import asyncio
    try:
        from ..forge_client import forge_client
    except ImportError:
        from aethelnet_node.forge_client import forge_client

    notarization = await asyncio.to_thread(forge_client.get_case_notarization, app_id)
    local_state = database.compute_case_state_root(app_id)

    is_verified = bool(
        notarization.get("is_notarized", False) and
        notarization.get("state_root", "").lower() == local_state["state_root"].lower()
    )

    return {
        "case_id": app_id,
        "on_chain": notarization,
        "local_state": local_state,
        "is_cryptographically_verified": is_verified,
        "contract": forge_client.contract_address
    }


@router.get("/multigraph/{app_id}/export_bundle")
def export_bundle_api(app_id: str, download: bool = Query(False)):
    """
    Exports a canonical, content-addressed Aethelnet Evidence Bundle (JSON).
    Contains bit-exact nodes, edges, active conflicts, deterministic Merkle state root,
    IPFS CIDv1, and Ethereum Sepolia notarization metadata.
    """
    import json
    try:
        from ..ipfs_bridge import build_canonical_bundle
    except ImportError:
        from aethelnet_node.ipfs_bridge import build_canonical_bundle

    bundle = build_canonical_bundle(app_id)
    if download:
        content = json.dumps(bundle, indent=2, ensure_ascii=False)
        filename = f"aethelnet_case_{app_id}_{bundle['manifest']['state_root'][:10]}.json"
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    return bundle


@router.get("/multigraph/{app_id}/dossier", response_class=HTMLResponse)
def get_case_dossier_api(app_id: str, format: str = Query("html")):
    """
    Renders a court-proof forensic evidence dossier report for an investigation case.
    Supports printable HTML/PDF view or canonical JSON.
    """
    try:
        from ..ipfs_bridge import build_canonical_bundle
        from ..dossier_generator import generate_html_dossier
    except ImportError:
        from aethelnet_node.ipfs_bridge import build_canonical_bundle
        from aethelnet_node.dossier_generator import generate_html_dossier

    bundle = build_canonical_bundle(app_id)
    if format.lower() == "json":
        import json
        return Response(
            content=json.dumps(bundle, indent=2, ensure_ascii=False),
            media_type="application/json"
        )

    html_content = generate_html_dossier(app_id, bundle)
    return HTMLResponse(content=html_content)




