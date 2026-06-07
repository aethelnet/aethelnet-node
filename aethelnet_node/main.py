import asyncio
import logging
import math
import os
import socket
import time
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import torch

from aethelnet.liquid_graph import LiquidGraph
from aethelnet_node.database import (
    init_db, save_node, delete_node, save_edge, delete_edge,
    load_graph_state, save_persona, load_personas, get_node_text
)

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Aethelnet.Node")

app = FastAPI(title="Aethelnet Node", version="1.0.0")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HIDDEN_DIM = 768
init_db()

# Global GNN and metrics state
graph_instance = LiquidGraph(hidden_dim=HIDDEN_DIM, resonance_threshold=0.6, decay_rate=0.05)
node_metrics: Dict[str, Dict[str, Any]] = {}

# Reality Anchors
REALITY_ANCHORS = {
    "Gravity Constant (g)": {"value": 9.81, "desc": "Earth gravitational acceleration in m/s^2", "dim": "L/T^2"},
    "Pi Ratio (π)": {"value": 3.14159265, "desc": "Circle circumference to diameter ratio", "dim": "Dimensionless"},
    "Speed of Light (c)": {"value": 299792458.0, "desc": "Cosmic speed limit in m/s", "dim": "L/T"},
    "Planck Constant (h)": {"value": 6.62607e-34, "desc": "Quantum of electromagnetic action in J*s", "dim": "M*L^2/T"}
}

# --- P2P Network Settings ---
KNOWN_PEERS = ["172.20.10.10:8000", "141.147.20.191:8000"]

class NodeCreate(BaseModel):
    id: str
    text_content: str
    connections: Optional[List[str]] = []
    source_tag: Optional[str] = "internal"
    is_quarantined: Optional[bool] = False

class PeerSyncPayload(BaseModel):
    peer_id: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]

class UniversalIngest(BaseModel):
    bot_name: str
    observation: str
    confidence: Optional[float] = 0.8
    context_tags: Optional[List[str]] = []

def text_to_embedding(text: str, dim: int = HIDDEN_DIM) -> torch.Tensor:
    torch.manual_seed(hash(text) % (2**32 - 1))
    raw_emb = torch.randn(dim)
    return raw_emb / (raw_emb.norm() + 1e-8)

def load_all_from_db():
    global node_metrics
    nodes, edges, metrics = load_graph_state(dim=HIDDEN_DIM)
    
    if not nodes:
        logger.info("[Aethelnet] Database empty. Seeding default reality anchors...")
        for anchor_name, info in REALITY_ANCHORS.items():
            anchor_text = f"{anchor_name}: {info['desc']} value={info['value']}"
            emb = text_to_embedding(anchor_text)
            graph_instance.add_node(anchor_name, emb)
            save_node(anchor_name, emb, 0.0, 0.95, 0.0, True, False, text_content=anchor_text)
            
        nodes, edges, metrics = load_graph_state(dim=HIDDEN_DIM)
        
    graph_instance.nodes.clear()
    graph_instance.nx_graph.clear()
    
    for nid, emb in nodes.items():
        graph_instance.add_node(nid, emb)
        
    for u, v, weight in edges:
        if u in graph_instance.nodes and v in graph_instance.nodes:
            graph_instance.nx_graph.add_edge(u, v, weight=weight)
            
    personas, active_status = load_personas()
    graph_instance.personas = personas
    graph_instance.active_personas = active_status
            
    node_metrics = metrics
    logger.info(f"[Aethelnet] Loaded {len(nodes)} nodes, {len(edges)} bridges, and {len(personas)} personas.")

# --- API ENDPOINTS ---

class FileIngestRequest(BaseModel):
    file_path: str

@app.post("/api/ingest/file")
async def ingest_file(payload: FileIngestRequest, background_tasks: BackgroundTasks):
    if not os.path.exists(payload.file_path):
        raise HTTPException(status_code=400, detail="File path does not exist.")
        
    ext = os.path.splitext(payload.file_path)[1].lower()
    from aethelnet_node.sensors import SensorArray
    from aethelnet_node.scouter import scout_arxiv_optimizations
    
    sensors = SensorArray()
    if ext == ".pdf":
        chunks = sensors.parse_pdf(payload.file_path)
    elif ext in [".obj", ".stl"]:
        chunks = sensors.perceive_spatial_geometry(payload.file_path)
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format.")
        
    if not chunks or (len(chunks) == 1 and chunks[0].get("type") == "error"):
        raise HTTPException(status_code=500, detail=chunks[0].get("content", "Failed to parse file."))
        
    doc_id = os.path.basename(payload.file_path)
    doc_emb = text_to_embedding(doc_id)
    graph_instance.add_node(doc_id, doc_emb)
    save_node(
        doc_id, doc_emb, 0.0, 0.9, 0.0, False, False, 
        text_content=f"Document perceived. Path: {payload.file_path}", 
        source_tag="sensor_document"
    )
    
    keywords_found = []
    for idx, chunk in enumerate(chunks):
        chunk_id = f"Chunk_{doc_id}_{idx}"
        chunk_emb = text_to_embedding(chunk["content"])
        
        graph_instance.add_node(chunk_id, chunk_emb)
        save_node(
            chunk_id, chunk_emb, 0.0, 0.85, 0.0, False, False, 
            text_content=chunk["content"], source_tag=f"sensor_{chunk['type']}"
        )
        graph_instance.nx_graph.add_edge(doc_id, chunk_id, weight=1.0)
        save_edge(doc_id, chunk_id, 1.0)
        
        if chunk["type"] == "text":
            found_kws = sensors.extract_keywords(chunk["content"])
            keywords_found.extend(found_kws)
            
    unique_kws = list(set(keywords_found))
    logger.info(f"[Sensors] Found keywords for scouting: {unique_kws}")
    
    def run_scouter_bg():
        for kw in unique_kws:
            try:
                papers = scout_arxiv_optimizations(query=kw, hidden_dim=HIDDEN_DIM)
                for paper in papers:
                    p_id = paper["title"]
                    p_emb = text_to_embedding(p_id)
                    graph_instance.add_node(p_id, p_emb)
                    save_node(
                        p_id, p_emb, 0.0, 0.9, 0.0, False, False, 
                        text_content=paper["summary"], source_tag="arxiv_scouter"
                    )
                    graph_instance.nx_graph.add_edge(doc_id, p_id, weight=0.8)
                    save_edge(doc_id, p_id, 0.8)
                    logger.info(f"[Scouter] Discovered and linked paper: {p_id}")
            except Exception as e:
                logger.error(f"[Scouter] Background search failed for {kw}: {e}")
                
    background_tasks.add_task(run_scouter_bg)
    
    return {
        "status": "ingested",
        "document_node": doc_id,
        "chunks_count": len(chunks),
        "keywords_detected": unique_kws
    }

@app.get("/")
def health():
    return {"status": "operational", "node": socket.gethostname(), "peers_configured": len(KNOWN_PEERS)}

@app.get("/p2p/ping")
async def ping_peer():
    hostname = socket.gethostname()
    return {"status": "alive", "peer_id": f"lgnn_node_{hostname}", "version": "1.0.0"}

@app.get("/p2p/expertise")
async def extract_expertise():
    sorted_nodes = sorted(node_metrics.items(), key=lambda x: x[1].get("confidence", 0.0), reverse=True)
    expert_nodes = []
    for nid, metrics in sorted_nodes:
        if metrics.get("is_grounded", False):
            continue
        expert_nodes.append({
            "id": nid,
            "confidence": metrics.get("confidence", 0.0),
            "plateau_factor": metrics.get("plateau_factor", 0.0)
        })
        if len(expert_nodes) >= 10:
            break
    return {"domain": "general_expertise", "nodes": expert_nodes}

@app.post("/p2p/sync")
async def receive_peer_sync(payload: PeerSyncPayload):
    logger.info(f"[P2P] Receiving topological sync from peer {payload.peer_id}...")
    assimilated_count = 0
    for node_data in payload.nodes:
        if node_data["id"] in REALITY_ANCHORS:
            continue
            
        emb = text_to_embedding(node_data["id"])
        graph_instance.add_node(node_data["id"], emb)
        save_node(
            node_data["id"], emb, 0.0, node_data.get("confidence", 0.8), 0.0, 
            False, False, text_content=f"Imported from {payload.peer_id}", 
            source_tag=f"p2p_{payload.peer_id}"
        )
        assimilated_count += 1
        
    logger.info(f"[P2P] Successfully assimilated {assimilated_count} concepts.")
    return {"status": "assimilated", "count": assimilated_count}

@app.post("/api/lgnn/universal_ingest")
async def universal_ingest(payload: UniversalIngest):
    logger.info(f"[Universal Ingest] Observation received: {payload.observation}")
    emb = text_to_embedding(payload.observation)
    node_id = f"Obs_{payload.bot_name}_{int(time.time())}"
    graph_instance.add_node(node_id, emb)
    save_node(
        node_id, emb, 0.0, payload.confidence, 0.0, False, False, 
        text_content=payload.observation, source_tag=payload.bot_name
    )
    return {"status": "ingested", "node_id": node_id}

@app.post("/api/lgnn/node")
async def create_node_route(payload: NodeCreate):
    emb = text_to_embedding(payload.text_content)
    graph_instance.add_node(payload.id, emb, connections=payload.connections)
    save_node(
        payload.id, emb, 0.0, 0.8, 0.0, False, False, 
        text_content=payload.text_content, source_tag=payload.source_tag,
        is_quarantined=payload.is_quarantined
    )
    return {"status": "created", "id": payload.id}

@app.get("/api/lgnn/graph")
async def get_graph():
    nodes_data = []
    links_data = []
    
    for nid in list(graph_instance.nodes.keys()):
        state_tensor = graph_instance.nodes[nid]
        mean_activation = float(state_tensor.mean().detach().cpu())
        metrics = node_metrics.setdefault(nid, {
            "confidence": 0.8, "plateau_factor": 0.0, 
            "is_grounded": nid in REALITY_ANCHORS, 
            "help_chain": False, "source_tag": "internal", "is_quarantined": False
        })
        nodes_data.append({
            "id": nid,
            "label": nid,
            "mean_activation": mean_activation,
            "confidence": metrics["confidence"],
            "is_grounded": metrics["is_grounded"],
            "source_tag": metrics["source_tag"]
        })
        
    for u, v, data in graph_instance.nx_graph.edges(data=True):
        links_data.append({
            "source": u,
            "target": v,
            "weight": data.get("weight", 1.0)
        })
        
    return {"nodes": nodes_data, "links": links_data}

# --- P2P BACKGROUND LOOPS ---

async def hunt_for_peers():
    import httpx
    logger.info("[P2P] Peer Hunter active...")
    while True:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer in KNOWN_PEERS:
                if peer == f"{socket.gethostbyname(socket.gethostname())}:8000" or peer.startswith("127.0.0.1"):
                    continue
                peer_url = f"http://{peer}/p2p/expertise"
                try:
                    response = await client.get(peer_url)
                    if response.status_code == 200:
                        data = response.json()
                        expert_nodes = data.get("nodes", [])
                        logger.info(f"[P2P] Discovered {len(expert_nodes)} high-confidence concepts from {peer}.")
                        
                        persona_name = f"Expertise_{peer.replace(':', '_')}"
                        persona_node_ids = []
                        
                        for node in expert_nodes:
                            nid = node["id"]
                            emb = text_to_embedding(nid)
                            graph_instance.add_node(nid, emb)
                            save_node(
                                nid, emb, 0.0, node.get("confidence", 0.8), 0.0,
                                False, False, text_content=f"Harvested from peer {peer}",
                                source_tag=f"p2p_gossip_{peer}"
                            )
                            persona_node_ids.append(nid)
                            
                        if persona_node_ids:
                            graph_instance.define_persona(persona_name, persona_node_ids)
                            save_persona(persona_name, persona_node_ids, active=True)
                            graph_instance.set_persona_active(persona_name, True)
                            
                except Exception:
                    pass
        await asyncio.sleep(60)

async def gossip_truth_to_peers():
    import httpx
    await asyncio.sleep(30)
    while True:
        sorted_nodes = sorted(node_metrics.items(), key=lambda x: x[1].get("confidence", 0.0), reverse=True)
        grain_of_truth_id = None
        for nid, metrics in sorted_nodes:
            if not metrics.get("is_grounded", False):
                grain_of_truth_id = nid
                break
                
        if grain_of_truth_id:
            truth_text = get_node_text(grain_of_truth_id)
            hostname = socket.gethostname()
            payload = {
                "bot_name": f"lgnn_gossip_{hostname}",
                "observation": f"[{grain_of_truth_id}] {truth_text}",
                "confidence": node_metrics[grain_of_truth_id].get("confidence", 0.8),
                "context_tags": ["p2p_gossip"]
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                for peer in KNOWN_PEERS:
                    peer_url = f"http://{peer}/api/lgnn/universal_ingest"
                    try:
                        await client.post(peer_url, json=payload)
                    except Exception:
                        pass
        await asyncio.sleep(60)

# --- STARTUP EVENT ---
@app.on_event("startup")
async def startup_event():
    load_all_from_db()
    # Start the continuous ODE evolution loop in background
    async def continuous_ode_loop():
        while True:
            try:
                graph_instance.evolve_topology(compute_time=1.0)
                # Persist evolved node parameters
                for nid in list(graph_instance.nodes.keys()):
                    state_tensor = graph_instance.nodes[nid]
                    metrics = node_metrics.get(nid, {})
                    save_node(
                        nid, state_tensor, float(state_tensor.mean().detach().cpu()), 
                        metrics.get("confidence", 0.8), metrics.get("plateau_factor", 0.0), 
                        metrics.get("is_grounded", False), metrics.get("help_chain", False),
                        text_content=get_node_text(nid), source_tag=metrics.get("source_tag", "internal")
                    )
            except Exception as e:
                logger.error(f"[ODE] Evolution step failed: {e}")
            await asyncio.sleep(10)
            
    asyncio.create_task(continuous_ode_loop())
    asyncio.create_task(hunt_for_peers())
    asyncio.create_task(gossip_truth_to_peers())
    logger.info("[Aethelnet Node] Startup actions completed.")
