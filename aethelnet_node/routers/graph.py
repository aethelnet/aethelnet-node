import asyncio
import base64
import json
import logging
import math
import os
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
import httpx
import torch
import numpy as np

from aethelnet_node.database import (
    save_node, delete_node, save_edge, delete_edge,
    get_node_text, get_db_connection
)
from aethelnet_node.state import (
    graph_instance, node_metrics, text_to_embedding,
    calculate_centrality, broadcast_resonance,
    REALITY_ANCHORS, DEFAULT_CONFIDENCE, KNOWLEDGE_CONFIDENCE,
    active_websockets
)
from aethelnet_node.security import auth_headers

logger = logging.getLogger("Aethelnet.Node.Graph")

router = APIRouter()

ingest_zone = os.path.expanduser("~/.aethelnet/ingest_zone")
os.makedirs(ingest_zone, exist_ok=True)

class NodeCreate(BaseModel):
    id: str
    text_content: Optional[str] = ""
    content: Optional[str] = None
    connections: Optional[List[str]] = []
    source_tag: Optional[str] = "internal"
    is_quarantined: Optional[bool] = False
    node_type: Optional[str] = "standard"
    parent_id: Optional[str] = None
    meta_data: Optional[str] = None

    class Config:
        extra = "allow"

class NodeUpdate(BaseModel):
    id: str
    text_content: str
    source_tag: Optional[str] = None
    is_quarantined: Optional[bool] = None

class EdgeCreate(BaseModel):
    source: Optional[str] = None
    target: Optional[str] = None
    source_id: Optional[str] = None
    target_id: Optional[str] = None
    weight: Optional[float] = 1.0
    label: Optional[str] = None
    edge_type: Optional[str] = "hebbian"
    tags: Optional[List[str]] = []
    is_manual: Optional[bool] = False

    class Config:
        extra = "allow"

class EdgeUpdate(BaseModel):
    weight: float

class NodeStimulateRequest(BaseModel):
    intensity: Optional[float] = 0.5

class UniversalIngest(BaseModel):
    bot_name: str
    observation: str
    confidence: Optional[float] = DEFAULT_CONFIDENCE
    context_tags: Optional[List[str]] = []
    media_b64: Optional[str] = None
    media_type: Optional[str] = None

class FileIngestRequest(BaseModel):
    file_path: str

@router.post("/ingest/file")
async def ingest_file(payload: FileIngestRequest, background_tasks: BackgroundTasks):
    if not os.path.exists(payload.file_path):
        raise HTTPException(status_code=400, detail="File path does not exist.")
        
    ext = os.path.splitext(payload.file_path)[1].lower()
    from aethelnet_node.sensors import SensorArray
    sensors = SensorArray()
    
    chunks = []
    if ext == ".pdf":
        chunks = sensors.parse_pdf(payload.file_path)
    elif ext in [".png", ".jpg", ".jpeg"]:
        chunks = sensors.perceive_image(payload.file_path)
    elif ext in [".txt", ".md"]:
        try:
            with open(payload.file_path, "r", encoding="utf-8") as f:
                text = f.read()
            chunks = [{"type": "text", "content": text, "metadata": payload.file_path}]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Read failed: {e}")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {ext}")
        
    doc_id = os.path.basename(payload.file_path)
    doc_emb = text_to_embedding(doc_id)
    graph_instance.add_node(doc_id, doc_emb)
    save_node(
        doc_id, doc_emb, 0.0, 0.9, 0.0, False, False, 
        text_content=f"Document uploaded: {payload.file_path}", source_tag="file_ingest"
    )
    
    for idx, chunk in enumerate(chunks):
        chunk_id = f"Chunk_{doc_id}_{idx}"
        chunk_emb = text_to_embedding(chunk["content"])
        graph_instance.add_node(chunk_id, chunk_emb)
        save_node(
            chunk_id, chunk_emb, 0.0, KNOWLEDGE_CONFIDENCE, 0.0, False, False, 
            text_content=chunk["content"], source_tag=f"sensor_{chunk['type']}"
        )
        graph_instance.nx_graph.add_edge(doc_id, chunk_id, weight=1.0)
        save_edge(doc_id, chunk_id, 1.0)
        
    return {"status": "success", "doc_id": doc_id, "chunks_ingested": len(chunks)}

@router.post("/universal_ingest")
async def universal_ingest(payload: UniversalIngest, background_tasks: BackgroundTasks):
    uplink_url = os.environ.get("AETHELNET_UPLINK_URL")
    if uplink_url and os.environ.get("IS_CLOUD_NODE") != "1":
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.post(
                    f"{uplink_url.rstrip('/')}/api/lgnn/universal_ingest",
                    json=payload.dict(),
                    headers=auth_headers(os.environ.get("AETHELNET_UPLINK_TOKEN", ""))
                )
        except Exception:
            pass

    logger.info(f"[Universal Ingest] Observation received from {payload.bot_name}: {payload.observation}")
    
    if payload.bot_name == "Ouroboros_Coach":
        for ws in list(active_websockets):
            try:
                background_tasks.add_task(ws.send_json, {"type": "consensus", "text": payload.observation})
            except Exception:
                pass
                
    # For automated bots and continuous sensors, update a fixed slot per bot to prevent unbounded accumulation
    if payload.bot_name in ("cosmic_telemetry", "Ouroboros_Coach", "entropy_daemon", "stimulus", "web_spider"):
        node_id = f"Obs_{payload.bot_name}"
    else:
        node_id = f"Obs_{payload.bot_name}_{int(time.time())}"
    
    if payload.media_b64:
        try:
            import uuid
            ext = ".png"
            if payload.media_type and "jpeg" in payload.media_type: ext = ".jpg"
            elif payload.media_type and "gif" in payload.media_type: ext = ".gif"
            
            filename = f"upload_{uuid.uuid4().hex[:8]}{ext}"
            filepath = os.path.join(ingest_zone, filename)
            
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(payload.media_b64))
                
            payload.observation += f" [Media Attached: /media/{filename}]"
            node_metrics[node_id] = {"media_path": filepath}
            logger.info(f"[Universal Ingest] Saved media to {filepath}")
        except Exception as e:
            logger.error(f"[Universal Ingest] Failed to save media: {e}")

    graph_instance.add_node(node_id, emb)
    confidence = payload.confidence if payload.confidence is not None else DEFAULT_CONFIDENCE
    save_node(
        node_id, emb, 0.0, confidence, 0.0, False, False, 
        text_content=payload.observation, source_tag=payload.bot_name
    )
    
    minted_amount = 0.0
    try:
        from aethelnet_node.reward_system import economy
        minted_amount = economy.mint_reward(
            peer_identifier=payload.bot_name,
            truth_id=node_id,
            resonance_score=confidence,
            graph_instance=graph_instance
        )
    except Exception as e:
        logger.debug(f"[Economy] Mint reward: {e}")
    
    asyncio.create_task(broadcast_resonance(node_id, float(emb.mean()), payload.observation))
    return {"status": "ingested", "node_id": node_id, "reward_minted": minted_amount}

@router.post("/node")
async def create_node_route(payload: NodeCreate):
    text = payload.text_content or payload.content or ""
    emb = text_to_embedding(text)
    graph_instance.add_node(payload.id, emb, connections=payload.connections or [])
    
    meta_dict = {}
    if payload.meta_data and payload.meta_data.strip():
        try:
            parsed = json.loads(payload.meta_data)
            if isinstance(parsed, dict):
                meta_dict = parsed
        except Exception:
            pass

    # Determine effective parent_id
    effective_parent = "root"
    if payload.parent_id and payload.parent_id != "root":
        effective_parent = payload.parent_id
    elif "parent_id" in meta_dict and meta_dict["parent_id"]:
        effective_parent = meta_dict["parent_id"]
    elif " // " in payload.id:
        effective_parent = payload.id.split(" // ")[0].strip()

    meta_dict["parent_id"] = effective_parent
    meta = json.dumps(meta_dict)
    safe_id = graph_instance._safe_id(payload.id)

    save_node(
        payload.id, emb, 0.0, DEFAULT_CONFIDENCE, 0.0, False, False, 
        text_content=text, source_tag=payload.source_tag or "internal",
        is_quarantined=payload.is_quarantined or False, node_type=payload.node_type or "standard",
        meta_data=meta
    )
    metric_entry = {
        "confidence": DEFAULT_CONFIDENCE,
        "plateau_factor": 0.0,
        "is_grounded": False,
        "help_chain": False,
        "source_tag": payload.source_tag or "internal",
        "is_quarantined": payload.is_quarantined or False,
        "parent_id": effective_parent,
        "node_type": payload.node_type or "standard",
        "meta_data": meta,
        "text_content": text
    }
    node_metrics[payload.id] = metric_entry
    node_metrics[safe_id] = metric_entry
    return {"status": "created", "id": payload.id, "parent_id": effective_parent}

@router.post("/node/update")
async def update_node_route(payload: NodeUpdate):
    safe_id = graph_instance._safe_id(payload.id)
    target_nid = None
    if safe_id in graph_instance.nodes:
        target_nid = safe_id
    elif payload.id in graph_instance.nodes:
        target_nid = payload.id
        
    if target_nid is None:
        raise HTTPException(status_code=404, detail="Node not found")
        
    emb = text_to_embedding(payload.text_content)
    with torch.no_grad():
        graph_instance.nodes[target_nid].copy_(emb)
        
    for key in (payload.id, safe_id, target_nid):
        if key in node_metrics:
            node_metrics[key]["text_content"] = payload.text_content
            node_metrics[key]["vector"] = emb.numpy()
            if payload.source_tag is not None:
                node_metrics[key]["source_tag"] = payload.source_tag
            if payload.is_quarantined is not None:
                node_metrics[key]["is_quarantined"] = payload.is_quarantined
            
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE lgnn_nodes SET text_content = ?, embedding = ?, source_tag = coalesce(?, source_tag), is_quarantined = coalesce(?, is_quarantined) WHERE id = ? OR id = ?",
        (payload.text_content, emb.numpy().tobytes(), payload.source_tag, 1 if payload.is_quarantined else 0, safe_id, payload.id)
    )
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Node {payload.id} updated"}

@router.post("/edge")
async def create_edge_route(payload: EdgeCreate):
    source = payload.source or payload.source_id
    target = payload.target or payload.target_id
    if not source or not target:
        raise HTTPException(status_code=400, detail="Both source and target must be provided")

    s_safe = graph_instance._safe_id(source)
    t_safe = graph_instance._safe_id(target)
    s_orig = graph_instance._original_id(source)
    t_orig = graph_instance._original_id(target)
    weight = float(payload.weight) if payload.weight is not None else 1.0
    label = payload.label or "synapse"

    graph_instance.nx_graph.add_edge(s_orig, t_orig, weight=weight, label=label)
    if s_safe != s_orig or t_safe != t_orig:
        graph_instance.nx_graph.add_edge(s_safe, t_safe, weight=weight, label=label)
    save_edge(s_orig, t_orig, weight, label)
    return {"status": "success", "source": s_orig, "target": t_orig, "weight": weight, "label": label}

@router.put("/edge/{source}/{target}")
async def update_edge_route(source: str, target: str, payload: EdgeUpdate):
    s_safe = graph_instance._safe_id(source)
    t_safe = graph_instance._safe_id(target)
    
    if graph_instance.nx_graph.has_edge(s_safe, t_safe):
        graph_instance.nx_graph[s_safe][t_safe]['weight'] = payload.weight
        save_edge(s_safe, t_safe, payload.weight)
        return {"status": "success"}
        
    # If both nodes exist in the graph, allow creating the edge (standard PUT upsert)
    if s_safe in graph_instance.nodes and t_safe in graph_instance.nodes:
        graph_instance.nx_graph.add_edge(s_safe, t_safe, weight=payload.weight)
        save_edge(s_safe, t_safe, payload.weight)
        return {"status": "success"}
        
    raise HTTPException(status_code=404, detail="One or both nodes not found")

@router.delete("/edge/{source}/{target}")
async def delete_edge_route(source: str, target: str):
    s_safe = graph_instance._safe_id(source)
    t_safe = graph_instance._safe_id(target)
    
    if graph_instance.nx_graph.has_edge(s_safe, t_safe):
        graph_instance.nx_graph.remove_edge(s_safe, t_safe)
        delete_edge(s_safe, t_safe)
        return {"status": "success"}
        
    raise HTTPException(status_code=404, detail="Edge not found")

@router.delete("/node/{node_id}")
async def delete_node_route(node_id: str):
    safe_id = graph_instance._safe_id(node_id)
    if safe_id in graph_instance.nodes:
        del graph_instance.nodes[safe_id]
    if graph_instance.nx_graph.has_node(safe_id):
        graph_instance.nx_graph.remove_node(safe_id)
    if node_id in node_metrics:
        del node_metrics[node_id]
    if safe_id in node_metrics:
        del node_metrics[safe_id]
    delete_node(safe_id)
    return {"status": "success", "message": f"Node {node_id} deleted"}

@router.post("/node/{node_id}/stimulate")
async def stimulate_node_route(node_id: str, payload: Optional[NodeStimulateRequest] = None):
    safe_id = graph_instance._safe_id(node_id)
    if safe_id not in graph_instance.nodes:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found in neural lattice")
        
    intensity = 0.5
    if payload and payload.intensity is not None:
        intensity = max(0.05, min(float(payload.intensity), 2.0))
        
    # Excite target node latent tensor
    with torch.no_grad():
        graph_instance.nodes[safe_id] += float(intensity) * 0.25
        graph_instance.nodes[safe_id] = torch.clamp(graph_instance.nodes[safe_id], -5.0, 5.0)
        
    target_mean = float(graph_instance.nodes[safe_id].mean().detach().cpu())
    if not math.isfinite(target_mean):
        target_mean = 1.0
        
    metrics = node_metrics.setdefault(safe_id, {
        "confidence": DEFAULT_CONFIDENCE, "plateau_factor": 0.0,
        "is_grounded": safe_id in REALITY_ANCHORS,
        "help_chain": False, "source_tag": "internal", "is_quarantined": False,
        "parent_id": "root"
    })
    new_conf = min(1.0, float(metrics.get("confidence", DEFAULT_CONFIDENCE)) + 0.05)
    metrics["confidence"] = new_conf
    metrics["mean_activation"] = target_mean
    
    save_node(
        safe_id, graph_instance.nodes[safe_id],
        target_mean, new_conf,
        float(metrics.get("plateau_factor", 0.0)),
        bool(metrics.get("is_grounded", False)),
        bool(metrics.get("help_chain", False)),
        text_content=metrics.get("text_content", ""),
        source_tag=metrics.get("source_tag", "internal"),
        is_quarantined=bool(metrics.get("is_quarantined", False)),
        node_type=metrics.get("node_type", "standard"),
        meta_data=metrics.get("meta_data", "{}")
    )
    
    # Diffuse excitation across synaptic edges to direct neighbors
    neighbors_excited = 0
    search_ids = [nid for nid in [node_id, safe_id] if graph_instance.nx_graph.has_node(nid)]
    visited_neighbors = set()
    for sid in search_ids:
        for neighbor in list(graph_instance.nx_graph.neighbors(sid)):
            if neighbor in visited_neighbors:
                continue
            visited_neighbors.add(neighbor)
            n_safe = graph_instance._safe_id(neighbor) if neighbor not in graph_instance.nodes else neighbor
            if n_safe in graph_instance.nodes:
                edge_data = graph_instance.nx_graph.get_edge_data(sid, neighbor) or {}
                weight = float(edge_data.get("weight", 1.0))
                synaptic_boost = float(intensity) * 0.12 * math.tanh(abs(weight))
                with torch.no_grad():
                    graph_instance.nodes[n_safe] += synaptic_boost
                    graph_instance.nodes[n_safe] = torch.clamp(graph_instance.nodes[n_safe], -5.0, 5.0)
                n_mean = float(graph_instance.nodes[n_safe].mean().detach().cpu())
                if not math.isfinite(n_mean):
                    n_mean = 1.0
                n_metrics = node_metrics.setdefault(n_safe, {
                    "confidence": DEFAULT_CONFIDENCE, "plateau_factor": 0.0,
                    "is_grounded": neighbor in REALITY_ANCHORS or n_safe in REALITY_ANCHORS,
                    "help_chain": False, "source_tag": "internal", "is_quarantined": False,
                    "parent_id": "root"
                })
                n_metrics["mean_activation"] = n_mean
                save_node(
                    n_safe, graph_instance.nodes[n_safe],
                    n_mean, float(n_metrics.get("confidence", DEFAULT_CONFIDENCE)),
                    float(n_metrics.get("plateau_factor", 0.0)),
                    bool(n_metrics.get("is_grounded", False)),
                    bool(n_metrics.get("help_chain", False)),
                    text_content=n_metrics.get("text_content", ""),
                    source_tag=n_metrics.get("source_tag", "internal"),
                    is_quarantined=bool(n_metrics.get("is_quarantined", False)),
                    node_type=n_metrics.get("node_type", "standard"),
                    meta_data=n_metrics.get("meta_data", "{}")
                )
                neighbors_excited += 1
                
    asyncio.create_task(broadcast_resonance(safe_id, target_mean, f"Targeted stimulus pulse ({intensity:.2f}) on {node_id}"))
    
    return {
        "status": "stimulated",
        "id": node_id,
        "mean_activation": target_mean,
        "confidence": new_conf,
        "neighbors_excited": neighbors_excited
    }

@router.post("/node/{node_id}/decompose")
async def decompose_node_route(node_id: str):
    """
    Synthesizes and crystallizes 4 fractal sub-facets for a node,
    enabling rich multi-level exploration when diving into a subgraph.
    """
    safe_id = graph_instance._safe_id(node_id)
    node_text = get_node_text(node_id)
    if not node_text and safe_id in node_metrics:
        node_text = node_metrics[safe_id].get("text_content", "")
    if not node_text and node_id in REALITY_ANCHORS:
        node_text = REALITY_ANCHORS[node_id].get("desc", "")
    if not node_text:
        node_text = f"Latent concept node {node_id}"

    facet_templates = [
        ("Core Axiom", f"Foundational axiom and invariant constraints governing {node_id}. Substrate: {node_text[:120]}"),
        ("Continuous Dynamics", f"Differential state transformations and dynamic flow vector fields of {node_id}."),
        ("Synaptic Coupling", f"Resonance interfaces, Hebbian edge transitions, and coupling weights for {node_id}."),
        ("Empirical Manifestation", f"Observed operational outcomes and boundary telemetry for {node_id}.")
    ]

    created_children = []
    child_ids = []
    
    for suffix, desc in facet_templates:
        child_id = f"{node_id} // {suffix}"
        child_safe = graph_instance._safe_id(child_id)
        emb = text_to_embedding(desc)
        meta_str = json.dumps({"parent_id": node_id, "facet": suffix})
        
        graph_instance.add_node(child_id, emb)
        save_node(
            child_id, emb,
            0.2, 0.9, 0.0, False, False,
            text_content=desc,
            source_tag="sub_facet",
            node_type="concept",
            meta_data=meta_str
        )
        child_metric = {
            "confidence": 0.9,
            "plateau_factor": 0.0,
            "is_grounded": False,
            "help_chain": False,
            "source_tag": "sub_facet",
            "is_quarantined": False,
            "parent_id": node_id,
            "node_type": "concept",
            "meta_data": meta_str,
            "text_content": desc
        }
        node_metrics[child_safe] = child_metric
        node_metrics[child_id] = child_metric
        child_ids.append(child_id)
        created_children.append(child_id)

    # Interconnect the child facets in a semantic clique
    for i in range(len(child_ids)):
        for j in range(i + 1, len(child_ids)):
            u, v = child_ids[i], child_ids[j]
            graph_instance.nx_graph.add_edge(u, v, weight=0.85)
            save_edge(u, v, 0.85, "facet_coupling")

    logger.info(f"[Decompose] Synthesized {len(created_children)} sub-facets for '{node_id}'.")
    return {
        "status": "decomposed",
        "parent_id": node_id,
        "children": created_children
    }

@router.get("/vitals")
async def get_vitals():
    from aethelnet_node.daemons import get_hebbian_metrics
    hebb = get_hebbian_metrics()
    
    node_count = len(graph_instance.nodes)
    edge_count = graph_instance.nx_graph.number_of_edges()
    mean_energy = 0.0
    if node_count > 0:
        energies = [float(t.mean().detach().cpu()) for t in graph_instance.nodes.values() if math.isfinite(float(t.mean().detach().cpu()))]
        if energies:
            mean_energy = sum(energies) / len(energies)
            
    return {
        "status": "healthy",
        "nodes": node_count,
        "edges": edge_count,
        "hebb_cycle": hebb["cycle"],
        "mean_tether_strain": hebb["mean_tether_strain"],
        "max_strain_node": hebb["max_strain_node"],
        "max_strain_val": hebb["max_strain_val"],
        "mean_topological_energy": mean_energy,
        "active_websockets": len(active_websockets),
        "timestamp": time.time()
    }

@router.get("/diary")
async def get_system_diary():
    """Returns recent cognitive observations and synthesis events for the UI diary."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, text_content, mean_activation, confidence, last_updated FROM lgnn_nodes ORDER BY last_updated DESC LIMIT 50"
        )
        rows = cursor.fetchall()
        diary = []
        for r in rows:
            diary.append({
                "id": r["id"],
                "message": r["text_content"] if r["text_content"] else f"Node {r['id']}",
                "energy": float(r["mean_activation"]) if r["mean_activation"] is not None else 0.0,
                "confidence": float(r["confidence"]) if r["confidence"] is not None else 0.8,
                "timestamp": str(r["last_updated"])
            })
        return {"status": "success", "diary": diary}
    except Exception as e:
        logger.warning(f"[Diary] Error fetching diary entries: {e}")
        return {"status": "success", "diary": []}
    finally:
        conn.close()

@router.get("/graph")
async def get_graph(parent_id: Optional[str] = "root"):
    nodes_data = []
    links_data = []
    
    target_pid = (parent_id or "root").strip().lower()
    
    centrality_scores = calculate_centrality(graph_instance.nx_graph)
    leader_node = max(centrality_scores, key=centrality_scores.get) if centrality_scores else None

    allowed_nodes = set()
    for nid in list(graph_instance.nodes.keys()):
        orig_id = graph_instance._original_id(nid)
        metrics = node_metrics.get(nid) or node_metrics.get(orig_id)
        if not metrics:
            metrics = {
                "confidence": DEFAULT_CONFIDENCE, "plateau_factor": 0.0, 
                "is_grounded": orig_id in REALITY_ANCHORS, 
                "help_chain": False, "source_tag": "internal", "is_quarantined": False,
                "parent_id": "root"
            }
            node_metrics[nid] = metrics
        
        node_pid = (metrics.get("parent_id") or "root").strip().lower()
        if node_pid == target_pid or (target_pid in ("root", "none", "") and node_pid in ("root", "none", "")):
            allowed_nodes.add(orig_id)
            state_tensor = graph_instance.nodes[nid]
            mean_activation = float(state_tensor.mean().detach().cpu())
            if not math.isfinite(mean_activation):
                mean_activation = 1.0 if mean_activation > 0 else -1.0
            
            nodes_data.append({
                "id": orig_id,
                "label": orig_id,
                "mean_activation": mean_activation,
                "confidence": metrics.get("confidence", 0.8),
                "is_grounded": metrics.get("is_grounded", False),
                "source_tag": metrics.get("source_tag", "internal"),
                "node_type": metrics.get("node_type", "standard"),
                "is_leader": (orig_id == leader_node),
                "centrality": centrality_scores.get(orig_id, 0.0),
                "tether_strain": metrics.get("tether_strain", 0.0),
                "text_content": metrics.get("text_content", ""),
                "parent_id": metrics.get("parent_id", "root"),
                "meta_data": metrics.get("meta_data", "{}")
            })
        
    seen_edges = set()
    for u, v, data in graph_instance.nx_graph.edges(data=True):
        u_orig = graph_instance._original_id(u)
        v_orig = graph_instance._original_id(v)
        if (u in allowed_nodes or u_orig in allowed_nodes) and (v in allowed_nodes or v_orig in allowed_nodes):
            edge_key = tuple(sorted([u_orig, v_orig]))
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                links_data.append({
                    "source": u_orig,
                    "target": v_orig,
                    "weight": data.get("weight", 1.0),
                    "label": data.get("label", "")
                })
        
    return {"nodes": nodes_data, "links": links_data}

@router.get("/node/{node_id}")
async def get_node_details(node_id: str, format: str = "AUTO"):
    text = get_node_text(node_id)
    safe_id = graph_instance._safe_id(node_id)
    metrics = node_metrics.get(safe_id, {})
    
    response_data = {
        "id": node_id,
        "text_content": text,
        "confidence": metrics.get("confidence", DEFAULT_CONFIDENCE),
        "source_tag": metrics.get("source_tag", "internal"),
        "is_grounded": metrics.get("is_grounded", False),
        "format": "TXT"
    }

    if format != "AUTO":
        try:
            from aethelnet_node.decoders.omni_decoder import UniversalOmniDecoder
            decoder = UniversalOmniDecoder()
            
            tensor = graph_instance.nodes.get(safe_id)
            if tensor is not None:
                vector = tensor.detach().cpu().numpy()
            else:
                vector = np.random.randn(768)
                
            nodes = [{"id": node_id, "vector": vector}]
            filepath = ""
            
            if safe_id in node_metrics and "media_path" in node_metrics[safe_id]:
                filepath = node_metrics[safe_id]["media_path"]
                response_data["format"] = "IMG"
            elif format == "IMG":
                filepath = decoder._render_image(vector, nodes)
                response_data["format"] = "IMG"
            elif format == "WAV":
                filepath = decoder._render_audio(vector)
                response_data["format"] = "WAV"
            elif format == "TXT":
                filepath = decoder._render_text(vector, nodes)
                response_data["format"] = "TXT"
            
            if filepath and os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    file_bytes = f.read()
                    b64_str = base64.b64encode(file_bytes).decode("utf-8")
                    response_data["media_b64"] = b64_str
                    
                if format == "TXT":
                    response_data["text_content"] = file_bytes.decode("utf-8")
        except Exception as e:
            logger.error(f"[OmniDecoder] Failed to decode format {format}: {e}")
            
    return response_data

# --- Synaptic Synthesis Endpoints ---

class SynthesizeRequest(BaseModel):
    node_a: str
    node_b: str
    resonance: Optional[float] = None

class CrystallizeRequest(BaseModel):
    synthesis_id: str

@router.get("/syntheses")
@router.get("/lgnn/syntheses")
async def get_all_syntheses(limit: int = 50):
    from aethelnet_node.database import get_syntheses
    return {"status": "success", "syntheses": get_syntheses(limit=limit)}

@router.get("/synthesis/{synthesis_id}")
@router.get("/lgnn/synthesis/{synthesis_id}")
async def get_single_synthesis(synthesis_id: str):
    from aethelnet_node.database import get_synthesis_by_id
    res = get_synthesis_by_id(synthesis_id)
    if not res:
        raise HTTPException(status_code=404, detail="Synthesis not found")
    return res

@router.get("/node_syntheses/{node_id}")
@router.get("/lgnn/node_syntheses/{node_id}")
async def get_syntheses_for_single_node(node_id: str):
    from aethelnet_node.database import get_syntheses_for_node
    return {"status": "success", "syntheses": get_syntheses_for_node(node_id)}

@router.post("/synthesis/crystallize")
@router.post("/lgnn/synthesis/crystallize")
async def crystallize_synthesis_endpoint(payload: CrystallizeRequest):
    from aethelnet_node.database import crystallize_synthesis
    ok = crystallize_synthesis(payload.synthesis_id)
    return {"status": "success" if ok else "not_found", "crystallized": ok}

@router.post("/synthesize_nodes")
@router.post("/lgnn/synthesize_nodes")
async def synthesize_nodes_manual(payload: SynthesizeRequest):
    from aethelnet_node.synthesis import synthesis_engine
    res = payload.resonance
    if res is None:
        res = graph_instance.get_resonance(payload.node_a, payload.node_b)
    result = await synthesis_engine.synthesize_pair(payload.node_a, payload.node_b, float(res))
    if not result:
        raise HTTPException(status_code=500, detail="Synthesis failed")
    return result
