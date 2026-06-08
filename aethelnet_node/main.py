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
from aethelnet_node.spider_manager import run_spiders_from_config

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

# Cosmic constants for initial confidence
DEFAULT_CONFIDENCE = (math.sqrt(5) - 1) / 2  # Reciprocal of Golden Ratio (~0.6180339887)
KNOWLEDGE_CONFIDENCE = math.pi - 2.3         # Pi-derived starting confidence (~0.84159265)
DOCUMENT_CONFIDENCE = math.sin(1.1)          # Angular sine of the path (~0.89120736)

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

class PeerRegisterPayload(BaseModel):
    peer_address: str

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

class GenerateResponseRequest(BaseModel):
    prompt: str
    persona: Optional[str] = None
    length: str = "medium"  # short, medium, long

class EvolveTextRequest(BaseModel):
    text: str

class UniversalIngest(BaseModel):
    bot_name: str
    observation: str
    confidence: Optional[float] = DEFAULT_CONFIDENCE
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
    elif ext in [".txt", ".md"]:
        with open(payload.file_path, "r", encoding="utf-8") as f:
            text = f.read()
        chunks = [{"type": "text", "content": text, "metadata": payload.file_path}]
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format.")
        
    if not chunks or (len(chunks) == 1 and chunks[0].get("type") == "error"):
        raise HTTPException(status_code=500, detail=chunks[0].get("content", "Failed to parse file."))
        
    doc_id = os.path.basename(payload.file_path)
    doc_emb = text_to_embedding(doc_id)
    graph_instance.add_node(doc_id, doc_emb)
    save_node(
        doc_id, doc_emb, 0.0, DOCUMENT_CONFIDENCE, 0.0, False, False, 
        text_content=f"Document perceived. Path: {payload.file_path}", 
        source_tag="sensor_document"
    )
    
    keywords_found = []
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

@app.get("/p2p/peers")
async def get_peers():
    return {"peers": list(KNOWN_PEERS)}

@app.post("/p2p/register")
async def register_peer(payload: PeerRegisterPayload):
    peer = payload.peer_address.strip()
    # Check if not ourselves (both via loopback and our real hostname/IP resolved)
    my_ip = "127.0.0.1"
    try:
        my_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        pass
    
    if peer == f"{my_ip}:8000" or peer.startswith("127.0.0.1") or peer.startswith("localhost"):
        return {"status": "self_registration_ignored", "peers": list(KNOWN_PEERS)}

    if peer and peer not in KNOWN_PEERS:
        KNOWN_PEERS.append(peer)
        logger.info(f"[P2P] Dynamic Peer registered: {peer}")
        return {"status": "registered", "peers": list(KNOWN_PEERS)}
    return {"status": "already_registered", "peers": list(KNOWN_PEERS)}

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
            node_data["id"], emb, 0.0, node_data.get("confidence", DEFAULT_CONFIDENCE), 0.0, 
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
        payload.id, emb, 0.0, DEFAULT_CONFIDENCE, 0.0, False, False, 
        text_content=payload.text_content, source_tag=payload.source_tag,
        is_quarantined=payload.is_quarantined
    )
    return {"status": "created", "id": payload.id}

@app.post("/api/lgnn/generate-response")
async def generate_response_endpoint(data: GenerateResponseRequest):
    emb = text_to_embedding(data.prompt, dim=HIDDEN_DIM)
    
    # Filter nodes based on active persona if specified
    active_nodes = list(graph_instance.nodes.keys())
    if data.persona and data.persona in graph_instance.personas:
        p_nodes = graph_instance.personas[data.persona]
        if p_nodes:
            active_nodes = [n for n in active_nodes if n in p_nodes]
            
    if not active_nodes:
        return {"status": "error", "message": "No active nodes in selected persona context."}
        
    # Calculate similarities
    node_embs = torch.stack([graph_instance.nodes[n] for n in active_nodes])
    norm_prompt = emb / (emb.norm() + 1e-8)
    norm_nodes = node_embs / (node_embs.norm(dim=-1, keepdim=True) + 1e-8)
    similarities = torch.matmul(norm_nodes, norm_prompt)
    
    # Sort and pick top N
    sim_scores = [(active_nodes[i], float(similarities[i].detach().cpu())) for i in range(len(active_nodes))]
    sim_scores.sort(key=lambda x: x[1], reverse=True)
    
    num_to_pick = 1 if data.length == "short" else 2 if data.length == "medium" else 4
    top_matches = sim_scores[:num_to_pick]
    
    # Extract data for voice module
    top_nodes_data = []
    for nid, score in top_matches:
        orig_id = graph_instance._original_id(nid)
        top_nodes_data.append({
            "id": orig_id,
            "text": get_node_text(orig_id),
            "score": score
        })
        
    from aethelnet_node.voice import synthesize_voice
    voice_response = synthesize_voice(
        top_nodes_data, 
        decay_rate=graph_instance.decay_rate,
        prompt=data.prompt,
        persona=data.persona
    )
    
    return {
        "status": "success",
        "response": voice_response,
        "matches": [{"node_id": graph_instance._original_id(nid), "score": score} for nid, score in top_matches]
    }

@app.post("/api/lgnn/evolve-text")
async def evolve_text_endpoint(data: EvolveTextRequest):
    # 1. Advanced Tagging & Concept Extraction
    from aethelnet_node.sensors import SensorArray
    sensors = SensorArray()
    found_kws = sensors.extract_keywords(data.text)
    tags = ", ".join(found_kws) if found_kws else "Unclassified"
    
    node_name = found_kws[0].strip()[:30] if found_kws else "TempNode"
    temp_id = f"{node_name}_{hash(data.text) % 10000}"
    
    enriched_text = f"Tags: {tags}\n\nContent: {data.text}"
    emb = text_to_embedding(enriched_text, dim=HIDDEN_DIM)
    
    # Find initial wiring to the swarm
    top_3_nodes = []
    if graph_instance.nodes:
        norm_emb = emb / (emb.norm() + 1e-8)
        sims = []
        for nid, nemb in graph_instance.nodes.items():
            norm_nemb = nemb / (nemb.norm() + 1e-8)
            sim = float(torch.dot(norm_emb, norm_nemb).detach().cpu())
            sims.append((nid, sim))
        sims.sort(key=lambda x: x[1], reverse=True)
        top_3_nodes = [nid for nid, sim in sims[:3]]
        
    graph_instance.add_node(temp_id, emb, connections=[graph_instance._original_id(n) for n in top_3_nodes])
    node_metrics[temp_id] = {
        "confidence": DEFAULT_CONFIDENCE,
        "plateau_factor": 0.0,
        "is_grounded": False,
        "help_chain": False,
        "source_tag": "internal"
    }
    save_node(temp_id, emb, 0.0, DEFAULT_CONFIDENCE, 0.0, False, False, text_content=enriched_text)
    
    # Measure initial alignment
    nodes_list = list(graph_instance.nodes.keys())
    anchors = [n for n in nodes_list if graph_instance._original_id(n) in REALITY_ANCHORS]
    
    initial_align = {}
    if anchors:
        temp_emb = graph_instance.nodes[temp_id]
        norm_temp = temp_emb / (temp_emb.norm() + 1e-8)
        for anchor in anchors:
            a_emb = graph_instance.nodes[anchor]
            norm_a = a_emb / (a_emb.norm() + 1e-8)
            sim = float(torch.dot(norm_temp, norm_a).detach().cpu())
            initial_align[graph_instance._original_id(anchor)] = sim
            
    # Evolve topology
    graph_instance.evolve_topology(compute_time=1.5)
    
    # Measure final alignment
    final_align = {}
    if anchors:
        temp_emb = graph_instance.nodes[temp_id]
        norm_temp = temp_emb / (temp_emb.norm() + 1e-8)
        for anchor in anchors:
            a_emb = graph_instance.nodes[anchor]
            norm_a = a_emb / (a_emb.norm() + 1e-8)
            sim = float(torch.dot(norm_temp, norm_a).detach().cpu())
            final_align[graph_instance._original_id(anchor)] = sim
            
    # Remove temporary node
    graph_instance.remove_node(temp_id)
    delete_node(temp_id)
    
    # Synthesize evolution report
    evolution_lines = [
        "### ⚡ Latent State Evolution Complete",
        f"**Original Text**: \"{data.text[:120]}...\"",
        "",
        "#### Attractor Alignment Analysis:"
    ]
    
    for anchor_name in initial_align.keys():
        init_val = initial_align.get(anchor_name, 0.0)
        final_val = final_align.get(anchor_name, 0.0)
        diff = final_val - init_val
        direction = "Pull (+)" if diff > 0 else "Push (-)"
        evolution_lines.append(
            f"- **{anchor_name}**: Align shifted from {round(init_val * 100, 1)}% to {round(final_val * 100, 1)}% ({direction} {round(abs(diff) * 100, 1)}%)"
        )
        
    evolution_lines.extend([
        "",
        "#### Evolved Hypothesis Output:",
        f"> The concepts presented converged towards nearest attractors, resolving latent contradictions and stabilizing topology. Alignment with Reality Anchors changed by average of {round(sum(final_align.values())/len(final_align) - sum(initial_align.values())/len(initial_align), 3) * 100 if anchors else 0.0}%."
    ])
    
    return {
        "status": "success",
        "evolved_text": "\n".join(evolution_lines)
    }

def calculate_centrality(graph) -> Dict[str, float]:
    import networkx as nx
    if not graph or graph.number_of_nodes() == 0:
        return {}
    try:
        return nx.eigenvector_centrality(graph, weight='weight', max_iter=1000, tol=1e-3)
    except Exception:
        try:
            return nx.pagerank(graph, weight='weight')
        except Exception:
            return nx.degree_centrality(graph)

@app.get("/api/lgnn/graph")
async def get_graph():
    nodes_data = []
    links_data = []
    
    centrality_scores = calculate_centrality(graph_instance.nx_graph)
    leader_node = max(centrality_scores, key=centrality_scores.get) if centrality_scores else None

    for nid in list(graph_instance.nodes.keys()):
        state_tensor = graph_instance.nodes[nid]
        mean_activation = float(state_tensor.mean().detach().cpu())
        if not math.isfinite(mean_activation):
            mean_activation = 1.0 if mean_activation > 0 else -1.0
        orig_id = graph_instance._original_id(nid)
        metrics = node_metrics.setdefault(nid, {
            "confidence": DEFAULT_CONFIDENCE, "plateau_factor": 0.0, 
            "is_grounded": orig_id in REALITY_ANCHORS, 
            "help_chain": False, "source_tag": "internal", "is_quarantined": False
        })
        nodes_data.append({
            "id": orig_id,
            "label": orig_id,
            "mean_activation": mean_activation,
            "confidence": metrics["confidence"],
            "is_grounded": metrics["is_grounded"],
            "source_tag": metrics["source_tag"],
            "is_leader": (orig_id == leader_node),
            "centrality": centrality_scores.get(orig_id, 0.0)
        })
        
    for u, v, data in graph_instance.nx_graph.edges(data=True):
        links_data.append({
            "source": u,
            "target": v,
            "weight": data.get("weight", 1.0)
        })
        
    return {"nodes": nodes_data, "links": links_data}

from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("[WS] Client connected.")
    try:
        while True:
            nodes_data = []
            links_data = []
            centrality_scores = calculate_centrality(graph_instance.nx_graph)
            leader_node = max(centrality_scores, key=centrality_scores.get) if centrality_scores else None

            for nid in list(graph_instance.nodes.keys()):
                state_tensor = graph_instance.nodes[nid]
                mean_act = float(state_tensor.mean().detach().cpu())
                if not math.isfinite(mean_act):
                    mean_act = 1.0 if mean_act > 0 else -1.0
                orig_id = graph_instance._original_id(nid)
                nodes_data.append({
                    "id": orig_id, 
                    "label": orig_id, 
                    "activation": mean_act,
                    "is_leader": (orig_id == leader_node),
                    "centrality": centrality_scores.get(orig_id, 0.0)
                })
            for u, v, data in graph_instance.nx_graph.edges(data=True):
                links_data.append({"source": u, "target": v, "weight": data.get("weight", 1.0)})
                
            await websocket.send_json({
                "type": "telemetry",
                "nodes": len(nodes_data),
                "bridges": len(links_data),
                "state": "Active",
                "leader": leader_node if leader_node else "None",
                "graph": {
                    "nodes": nodes_data,
                    "links": links_data
                }
            })
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected.")

# --- P2P BACKGROUND LOOPS ---

async def hunt_for_peers():
    import httpx
    logger.info("[P2P] Peer Hunter active...")
    while True:
        my_ip = "127.0.0.1"
        try:
            my_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            pass
        my_addr = f"{my_ip}:8000"

        current_peers = list(KNOWN_PEERS)
        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer in current_peers:
                if peer == my_addr or peer.startswith("127.0.0.1") or peer.startswith("localhost"):
                    continue
                
                # 1. Fetch their expertise
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
                                nid, emb, 0.0, node.get("confidence", DEFAULT_CONFIDENCE), 0.0,
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

                # 2. Fetch their peer list for discovery
                peers_url = f"http://{peer}/p2p/peers"
                try:
                    response = await client.get(peers_url)
                    if response.status_code == 200:
                        data = response.json()
                        discovered = data.get("peers", [])
                        for dp in discovered:
                            dp_clean = dp.strip()
                            if dp_clean and dp_clean not in KNOWN_PEERS and dp_clean != my_addr and not dp_clean.startswith("127.0.0.1") and not dp_clean.startswith("localhost"):
                                KNOWN_PEERS.append(dp_clean)
                                logger.info(f"[P2P] Dynamically discovered new peer: {dp_clean} (via {peer})")
                                # Register ourselves with the newly discovered peer
                                try:
                                    await client.post(f"http://{dp_clean}/p2p/register", json={"peer_address": my_addr})
                                    logger.info(f"[P2P] Registered ourselves with newly discovered peer {dp_clean}")
                                except Exception:
                                    pass
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
                "confidence": node_metrics[grain_of_truth_id].get("confidence", DEFAULT_CONFIDENCE),
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

@app.get("/api/lgnn/node/{node_id}")
async def get_node_details(node_id: str):
    text = get_node_text(node_id)
    safe_id = graph_instance._safe_id(node_id)
    metrics = node_metrics.get(safe_id, {})
    return {
        "id": node_id,
        "text_content": text,
        "confidence": metrics.get("confidence", DEFAULT_CONFIDENCE),
        "source_tag": metrics.get("source_tag", "internal"),
        "is_grounded": metrics.get("is_grounded", False)
    }

# Track scouted queries to avoid redundant API requests
SCOUTED_TERMS = set()

async def autonomous_curiosity_scouter():
    await asyncio.sleep(45) # Settling time
    while True:
        try:
            candidates = []
            for nid in list(graph_instance.nodes.keys()):
                orig_id = graph_instance._original_id(nid)
                if orig_id in REALITY_ANCHORS or "gossip" in orig_id or orig_id in SCOUTED_TERMS:
                    continue
                    
                state_tensor = graph_instance.nodes[nid]
                mean_act = float(state_tensor.mean().detach().cpu())
                
                # Check degree in networkx graph
                degree = graph_instance.nx_graph.degree(orig_id) if orig_id in graph_instance.nx_graph else 0
                
                # Highly active but isolated concepts qualify as "curious candidates"
                if abs(mean_act) > 0.4 and degree <= 2:
                    text = get_node_text(orig_id)
                    if text and len(orig_id) > 3:
                        candidates.append((orig_id, abs(mean_act)))
                        
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                query_term = candidates[0][0]
                SCOUTED_TERMS.add(query_term)
                
                logger.info(f"[Curiosity] Autonomous scouter triggered for highly active concept: '{query_term}'")
                
                from aethelnet_node.scouter import scout_arxiv_optimizations
                from aethelnet_node.sensors import SensorArray
                sensors = SensorArray()
                
                loop = asyncio.get_event_loop()
                
                # 1. arXiv Query
                papers = await loop.run_in_executor(None, scout_arxiv_optimizations, query_term, HIDDEN_DIM)
                for paper in papers:
                    p_id = paper["title"]
                    p_emb = text_to_embedding(p_id)
                    graph_instance.add_node(p_id, p_emb)
                    save_node(
                        p_id, p_emb, 0.0, 0.9, 0.0, False, False, 
                        text_content=paper["summary"], source_tag="autonomous_curiosity"
                    )
                    graph_instance.nx_graph.add_edge(query_term, p_id, weight=0.8)
                    save_edge(query_term, p_id, 0.8)
                    logger.info(f"[Curiosity] Discovered and linked context paper: {p_id}")
                    
                # 2. Wikipedia Query
                wiki_data = await loop.run_in_executor(None, sensors.query_wikipedia, query_term)
                if wiki_data and wiki_data.get("summary"):
                    w_id = f"Wiki_{wiki_data['title']}"
                    w_emb = text_to_embedding(w_id)
                    graph_instance.add_node(w_id, w_emb)
                    save_node(
                        w_id, w_emb, 0.0, 0.95, 0.0, False, False,
                        text_content=f"{wiki_data['summary']}\n\nURL: {wiki_data['url']}",
                        source_tag="sensor_wikipedia"
                    )
                    graph_instance.nx_graph.add_edge(query_term, w_id, weight=0.9)
                    save_edge(query_term, w_id, 0.9)
                    logger.info(f"[Curiosity] Resolved Wikipedia grounding node: {w_id}")
                    
                # 3. GitHub Query
                github_repos = await loop.run_in_executor(None, sensors.query_github, query_term)
                for repo in github_repos:
                    r_id = f"GitHub_{repo['name']}"
                    r_emb = text_to_embedding(r_id)
                    graph_instance.add_node(r_id, r_emb)
                    save_node(
                        r_id, r_emb, 0.0, KNOWLEDGE_CONFIDENCE, 0.0, False, False,
                        text_content=f"{repo['description']}\n\nStars: {repo['stars']}\nURL: {repo['url']}",
                        source_tag="sensor_github"
                    )
                    graph_instance.nx_graph.add_edge(query_term, r_id, weight=0.75)
                    save_edge(query_term, r_id, 0.75)
                    logger.info(f"[Curiosity] Discovered GitHub repository: {r_id}")

                # 4. Open Library Query
                books = await loop.run_in_executor(None, sensors.query_open_library, query_term)
                for book in books:
                    b_id = f"Book_{book['title']}"
                    b_emb = text_to_embedding(b_id)
                    graph_instance.add_node(b_id, b_emb)
                    save_node(
                        b_id, b_emb, 0.0, KNOWLEDGE_CONFIDENCE, 0.0, False, False,
                        text_content=f"Title: {book['title']}\nAuthor: {book['author']}\nPublished: {book['first_publish_year']}\nSubjects: {book['subject']}\n\nDescription:\n{book['description']}",
                        source_tag="sensor_openlibrary"
                    )
                    graph_instance.nx_graph.add_edge(query_term, b_id, weight=0.8)
                    save_edge(query_term, b_id, 0.8)
                    logger.info(f"[Curiosity] Discovered Open Library book metadata: {b_id}")
                    
        except Exception as e:
            logger.error(f"[Curiosity] Loop execution failed: {e}")
            
        await asyncio.sleep(60)

async def workspace_file_watcher():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    watch_dir = os.path.join(project_root, "scratch")
    os.makedirs(watch_dir, exist_ok=True)
    logger.info(f"[Workspace Watcher] Watching directory: {watch_dir} for new inputs...")
    
    seen_files = {}
    while True:
        try:
            for filename in os.listdir(watch_dir):
                file_path = os.path.join(watch_dir, filename)
                if not os.path.isfile(file_path) or filename.startswith("."):
                    continue
                    
                mtime = os.path.getmtime(file_path)
                if file_path not in seen_files or seen_files[file_path] < mtime:
                    seen_files[file_path] = mtime
                    logger.info(f"[Workspace Watcher] Detected new/modified file: {filename}")
                    
                    ext = os.path.splitext(filename)[1].lower()
                    from aethelnet_node.sensors import SensorArray
                    sensors = SensorArray()
                    
                    chunks = []
                    if ext == ".pdf":
                        chunks = sensors.parse_pdf(file_path)
                    elif ext in [".png", ".jpg", ".jpeg"]:
                        chunks = sensors.perceive_image(file_path)
                    elif ext in [".txt", ".md"]:
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                text = f.read()
                            chunks = [{"type": "text", "content": text, "metadata": file_path}]
                        except Exception as e:
                            logger.error(f"[Workspace Watcher] Read failed: {e}")
                            
                    if chunks and not (len(chunks) == 1 and chunks[0].get("type") == "error"):
                        doc_id = filename
                        doc_emb = text_to_embedding(doc_id)
                        graph_instance.add_node(doc_id, doc_emb)
                        save_node(
                            doc_id, doc_emb, 0.0, 0.9, 0.0, False, False, 
                            text_content=f"Document perceived by Workspace Watcher. Path: {file_path}", 
                            source_tag="sensor_watcher"
                        )
                        
                        keywords_found = []
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
                            
                            if chunk["type"] == "text":
                                found_kws = sensors.extract_keywords(chunk["content"])
                                keywords_found.extend(found_kws)
                                
                        unique_kws = list(set(keywords_found))
                        logger.info(f"[Workspace Watcher] Perceived {len(chunks)} chunks, keywords: {unique_kws}")
                        
                        for kw in unique_kws:
                            if kw in graph_instance.nodes:
                                graph_instance.nx_graph.add_edge(doc_id, kw, weight=0.75)
                                save_edge(doc_id, kw, 0.75)
                                logger.info(f"[Workspace Watcher] Dynamic link established: {doc_id} <-> {kw}")
        except Exception as e:
            logger.error(f"[Workspace Watcher] Loop failed: {e}")
            
        await asyncio.sleep(15)

# --- STARTUP EVENT ---
@app.on_event("startup")
async def startup_event():
    load_all_from_db()
    
    def deduplicate_and_merge_nodes(threshold: float = 0.92):
        """
        Scans all GNN nodes for high cosine similarity and merges them,
        preserving the one with higher confidence/reality grounding.
        """
        nodes_keys = list(graph_instance.nodes.keys())
        if len(nodes_keys) < 2:
            return
            
        # Get all embeddings and normalize them
        embs = {}
        orig_ids = {}
        for nid in nodes_keys:
            orig_id = graph_instance._original_id(nid)
            orig_ids[nid] = orig_id
            emb = graph_instance.nodes[nid]
            embs[nid] = emb / (emb.norm() + 1e-8)
            
        merged_any = False
        discarded = set()
        
        for i in range(len(nodes_keys)):
            nid_a = nodes_keys[i]
            if nid_a in discarded:
                continue
                
            for j in range(i + 1, len(nodes_keys)):
                nid_b = nodes_keys[j]
                if nid_b in discarded:
                    continue
                    
                sim = float(torch.dot(embs[nid_a], embs[nid_b]).detach().cpu())
                if sim > threshold:
                    orig_a = orig_ids[nid_a]
                    orig_b = orig_ids[nid_b]
                    
                    # Check reality anchors
                    is_anchor_a = orig_a in REALITY_ANCHORS
                    is_anchor_b = orig_b in REALITY_ANCHORS
                    
                    metrics_a = node_metrics.get(nid_a, {})
                    metrics_b = node_metrics.get(nid_b, {})
                    
                    conf_a = metrics_a.get("confidence", 0.0)
                    conf_b = metrics_b.get("confidence", 0.0)
                    
                    if is_anchor_a and not is_anchor_b:
                        keep_nid, discard_nid = nid_a, nid_b
                    elif is_anchor_b and not is_anchor_a:
                        keep_nid, discard_nid = nid_b, nid_a
                    elif conf_a >= conf_b:
                        keep_nid, discard_nid = nid_a, nid_b
                    else:
                        keep_nid, discard_nid = nid_b, nid_a
                        
                    keep_orig = orig_ids[keep_nid]
                    discard_orig = orig_ids[discard_nid]
                    
                    logger.info(f"[Topology] Merging highly similar nodes: '{discard_orig}' -> '{keep_orig}' (Similarity: {sim:.4f})")
                    
                    # 1. Merge text content (Keep the higher-confidence node's text to prevent infinite bloat)
                    text_keep = get_node_text(keep_orig)
                    text_discard = get_node_text(discard_orig)
                    merged_text = text_keep or text_discard
                    
                    # 2. Merge embeddings
                    emb_keep = graph_instance.nodes[keep_nid]
                    emb_discard = graph_instance.nodes[discard_nid]
                    blended = emb_keep + emb_discard * 0.3
                    blended_norm = blended / (blended.norm() + 1e-8) * max(emb_keep.norm(), emb_discard.norm())
                    
                    graph_instance.nodes[keep_nid] = torch.nn.Parameter(blended_norm.clone().detach())
                    
                    # 3. Transfer edges
                    if discard_orig in graph_instance.nx_graph:
                        neighbors = list(graph_instance.nx_graph.neighbors(discard_orig))
                        for neighbor in neighbors:
                            if neighbor != keep_orig:
                                w_discard = graph_instance.nx_graph[discard_orig][neighbor].get("weight", 1.0)
                                w_keep = 1.0
                                if graph_instance.nx_graph.has_edge(keep_orig, neighbor):
                                    w_keep = graph_instance.nx_graph[keep_orig][neighbor].get("weight", 1.0)
                                
                                new_weight = max(w_keep, w_discard)
                                graph_instance.nx_graph.add_edge(keep_orig, neighbor, weight=new_weight)
                                save_edge(keep_orig, neighbor, new_weight)
                                
                            delete_edge(discard_orig, neighbor)
                    
                    # 4. Update metrics
                    metrics_keep = node_metrics.setdefault(keep_nid, {
                        "confidence": DEFAULT_CONFIDENCE, "plateau_factor": 0.0,
                        "is_grounded": keep_orig in REALITY_ANCHORS,
                        "help_chain": False, "source_tag": "internal", "is_quarantined": False
                    })
                    metrics_discard = node_metrics.get(discard_nid, {})
                    
                    new_conf = min(0.99, metrics_keep.get("confidence", DEFAULT_CONFIDENCE) + metrics_discard.get("confidence", 0.0) * 0.1)
                    metrics_keep["confidence"] = new_conf
                    node_metrics[keep_nid] = metrics_keep
                    
                    save_node(
                        keep_orig, graph_instance.nodes[keep_nid], float(graph_instance.nodes[keep_nid].mean().detach().cpu()),
                        new_conf, metrics_keep.get("plateau_factor", 0.0),
                        keep_orig in REALITY_ANCHORS, metrics_keep.get("help_chain", False),
                        text_content=merged_text, source_tag=metrics_keep.get("source_tag", "internal")
                    )
                    
                    # 5. Delete discard node
                    graph_instance.remove_node(discard_orig)
                    delete_node(discard_orig)
                    if discard_nid in node_metrics:
                        del node_metrics[discard_nid]
                        
                    discarded.add(discard_nid)
                    merged_any = True
                    break
            if merged_any:
                break

    # Start the continuous ODE evolution loop in background
    async def continuous_ode_loop():
        while True:
            try:
                graph_instance.evolve_topology(compute_time=1.0)
                # Run node deduplication and merging
                deduplicate_and_merge_nodes()
                # Persist evolved node parameters and update confidence breathing lifecycle
                for nid in list(graph_instance.nodes.keys()):
                    state_tensor = graph_instance.nodes[nid]
                    mean_act = float(state_tensor.mean().detach().cpu())
                    
                    orig_id = graph_instance._original_id(nid)
                    metrics = node_metrics.setdefault(nid, {
                        "confidence": DEFAULT_CONFIDENCE, "plateau_factor": 0.0,
                        "is_grounded": orig_id in REALITY_ANCHORS,
                        "help_chain": False, "source_tag": "internal", "is_quarantined": False
                    })
                    
                    confidence = metrics.get("confidence", DEFAULT_CONFIDENCE)
                    
                    # Reality Anchors are grounded (permanent 0.95 confidence)
                    if orig_id in REALITY_ANCHORS:
                        confidence = 0.95
                    else:
                        # Confidence breathing: degree of node in networkx graph
                        degree = graph_instance.nx_graph.degree(orig_id) if orig_id in graph_instance.nx_graph else 0
                        # Active nodes with bridges gain confidence, isolated/inactive decay
                        if degree > 0 and abs(mean_act) > 0.05:
                            delta = (abs(mean_act) * 0.02) + (degree * 0.005)
                        else:
                            delta = -0.04 # Decay
                            
                        confidence = min(1.0, max(0.0, confidence + delta))
                    
                    metrics["confidence"] = confidence
                    node_metrics[nid] = metrics
                    
                    # Legacy nodes pruning: if confidence decays to 0.15 or below, delete node
                    # (only if it is not grounded and has no original text)
                    text_content = get_node_text(orig_id)
                    if confidence <= 0.15 and orig_id not in REALITY_ANCHORS and not text_content:
                        logger.info(f"[Lifecycle] Pruning dead legacy node: {orig_id}")
                        graph_instance.remove_node(orig_id)
                        delete_node(orig_id)
                    else:
                        save_node(
                            orig_id, state_tensor, mean_act, 
                            confidence, metrics.get("plateau_factor", 0.0), 
                            orig_id in REALITY_ANCHORS, metrics.get("help_chain", False),
                            text_content=text_content, source_tag=metrics.get("source_tag", "internal")
                        )
            except Exception as e:
                logger.error(f"[ODE] Evolution step failed: {e}")
            await asyncio.sleep(10)
            
    async def register_with_all_known_peers():
        await asyncio.sleep(5)  # Wait for uvicorn to settle
        my_ip = "127.0.0.1"
        try:
            my_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            pass
        my_addr = f"{my_ip}:8000"
        
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer in list(KNOWN_PEERS):
                if peer == my_addr or peer.startswith("127.0.0.1") or peer.startswith("localhost"):
                    continue
                try:
                    await client.post(f"http://{peer}/p2p/register", json={"peer_address": my_addr})
                    logger.info(f"[P2P] Registered ourselves ({my_addr}) with peer {peer} on startup")
                except Exception:
                    pass

    async def cosmic_telemetry_watcher():
        await asyncio.sleep(10)  # Wait for GNN to settle
        from aethelnet_node.sensors import SensorArray
        sensors = SensorArray()
        while True:
            try:
                loop = asyncio.get_event_loop()
                pulse = await loop.run_in_executor(None, sensors.perceive_cosmic_pulse)
                if pulse and "Planetary telemetry silent" not in pulse:
                    logger.info("[Cosmic Sensor] Live planetary telemetry broadcast received.")
                    emb = text_to_embedding(pulse)
                    node_id = f"Obs_cosmic_telemetry_{int(time.time())}"
                    graph_instance.add_node(node_id, emb)
                    save_node(
                        node_id, emb, 0.0, KNOWLEDGE_CONFIDENCE, 0.0, False, False, 
                        text_content=pulse, source_tag="sensor_cosmic"
                    )
            except Exception as e:
                logger.error(f"[Cosmic Sensor] Telemetry watcher failed: {e}")
            await asyncio.sleep(60)

    asyncio.create_task(continuous_ode_loop())
    asyncio.create_task(autonomous_curiosity_scouter())
    asyncio.create_task(hunt_for_peers())
    asyncio.create_task(gossip_truth_to_peers())
    asyncio.create_task(register_with_all_known_peers())
    asyncio.create_task(workspace_file_watcher())
    asyncio.create_task(cosmic_telemetry_watcher())
    asyncio.create_task(run_spiders_from_config())
    logger.info("[Aethelnet Node] Startup actions completed.")
