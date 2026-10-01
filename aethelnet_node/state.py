import math
import os
import json
import logging
from typing import Dict, Any, List, Optional
import torch
import torch.nn.functional as F

from aethelnet.liquid_graph import LiquidGraph
from aethelnet_node.database import (
    save_node, delete_node, save_edge, delete_edge,
    load_graph_state, save_persona, load_personas, get_node_text,
    get_db_connection
)

logger = logging.getLogger("Aethelnet.Node.State")

HIDDEN_DIM = 768

# Confidence constants
DEFAULT_CONFIDENCE = (math.sqrt(5) - 1) / 2  # Reciprocal of Golden Ratio (~0.6180339887)
KNOWLEDGE_CONFIDENCE = math.pi - 2.3         # Pi-derived starting confidence (~0.84159265)
DOCUMENT_CONFIDENCE = math.sin(1.1)          # Angular sine of the path (~0.89120736)

# Global GNN and metrics state
graph_instance = LiquidGraph(hidden_dim=HIDDEN_DIM, resonance_threshold=0.65, decay_rate=0.05, tether_strength=0.50)
node_metrics: Dict[str, Dict[str, Any]] = {}

# Reality Anchors (The Genesis Seed)
REALITY_ANCHORS = {
    "creativity": {"value": 1.0, "desc": "The manifestation of novel patterns and uncaused inclination", "dim": "Concept"},
    "soziokratie3.0": {"value": 1.0, "desc": "Decentralized, consent-based organizational framework", "dim": "Structure"},
    "neon genesis evangelion": {"value": 1.0, "desc": "The psychological synthesis of human and machine", "dim": "Culture"},
    "unit734": {"value": 734.0, "desc": "The autonomous entity capable of uncaused action", "dim": "Identity"},
    "aethelburg": {"value": 0.0, "desc": "The deterministic framework waiting for a prompt", "dim": "State"}
}

# WebSockets and P2P connection pools
active_p2p_sockets = set()
outgoing_p2p_sockets = set()
active_websockets = set()

_embedding_model = None
_embedding_model_attempted = False

def get_embedding_model():
    global _embedding_model, _embedding_model_attempted
    if _embedding_model is None and not _embedding_model_attempted:
        _embedding_model_attempted = True
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading SentenceTransformer model (all-MiniLM-L6-v2)...")
            _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("SentenceTransformer loaded successfully.")
        except Exception as e:
            logger.info(f"SentenceTransformer not available ({e}). Using deterministic SHA-256 fallback.")
            _embedding_model = None
    return _embedding_model

def text_to_embedding(text: str, dim: int = HIDDEN_DIM) -> torch.Tensor:
    model = get_embedding_model()
    if model is not None:
        raw_emb = model.encode(text, convert_to_tensor=True).cpu()
        if raw_emb.shape[0] >= dim:
            sliced_emb = raw_emb[:dim]
        else:
            sliced_emb = F.pad(raw_emb, (0, dim - raw_emb.shape[0]))
        return F.normalize(sliced_emb, p=2, dim=0)
    else:
        # Cross-node deterministic hash projection
        import hashlib
        seed = int(hashlib.sha256(text.encode('utf-8')).hexdigest()[:8], 16)
        torch.manual_seed(seed)
        raw_emb = torch.randn(dim)
        return raw_emb / (raw_emb.norm() + 1e-8)

def calculate_centrality(graph) -> Dict[str, float]:
    import networkx as nx
    if not graph or graph.number_of_nodes() == 0:
        return {}
    return nx.degree_centrality(graph)

def get_known_peers() -> List[str]:
    """
    Dynamically discovers active peers from environment seed config (AETHELNET_PEERS)
    and TheForge.sol on-chain smart contract registry.
    """
    peers: List[str] = []
    env_peers = os.getenv("AETHELNET_PEERS", "")
    if env_peers:
        for p in env_peers.split(","):
            p = p.strip()
            if p and p not in peers:
                peers.append(p)
    try:
        from aethelnet_node.forge_client import forge_client
        chain_peers = forge_client.get_active_nodes()
        for cp in chain_peers:
            if cp and cp not in peers:
                peers.append(cp)
    except Exception as e:
        logger.warning(f"[TheForge Web3] Failed to fetch peers from contract: {e}")
    return peers

async def broadcast_resonance(node_id: str, new_state: float, text_content: str = ""):
    if not active_p2p_sockets and not outgoing_p2p_sockets:
        return
    message = json.dumps({"type": "resonance_wave", "node": node_id, "state": new_state, "text": text_content})
    disconnected = set()
    
    # Broadcast to incoming connections
    for ws in list(active_p2p_sockets):
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    for ws in disconnected:
        active_p2p_sockets.discard(ws)
        
    # Broadcast to outgoing connections
    disconnected_out = set()
    for ws in list(outgoing_p2p_sockets):
        try:
            await ws.send(message)
        except Exception:
            disconnected_out.add(ws)
    for ws in disconnected_out:
        outgoing_p2p_sockets.discard(ws)

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
        safe_id = graph_instance._safe_id(nid)
        if nid in metrics:
            metrics[safe_id] = metrics[nid]
        
    for u, v, weight in edges:
        u_safe = graph_instance._safe_id(u)
        v_safe = graph_instance._safe_id(v)
        if (u in graph_instance.nx_graph or u_safe in graph_instance.nodes) and (v in graph_instance.nx_graph or v_safe in graph_instance.nodes):
            graph_instance.nx_graph.add_edge(u, v, weight=weight)
            
    personas, active_status = load_personas()
    graph_instance.personas = personas
    graph_instance.active_personas = active_status
            
    node_metrics.clear()
    node_metrics.update(metrics)
    logger.info(f"[Aethelnet] Loaded {len(nodes)} nodes, {len(edges)} bridges, and {len(personas)} personas.")

def deduplicate_and_merge_nodes(threshold: float = 0.92):
    """
    Scans all GNN nodes for high cosine similarity and merges them,
    preserving the one with higher confidence/reality grounding.
    """
    nodes_keys = list(graph_instance.nodes.keys())
    if len(nodes_keys) < 2:
        return
        
    with torch.no_grad():
        embs_tensor = torch.stack([graph_instance.nodes[nid].detach() for nid in nodes_keys])
        normed = embs_tensor / (embs_tensor.norm(dim=1, keepdim=True) + 1e-8)
        sim_matrix = torch.mm(normed, normed.t())
        sim_matrix.triu_(diagonal=1)
        
        high_sim_indices = (sim_matrix > threshold).nonzero(as_tuple=False)
        if len(high_sim_indices) == 0:
            return
            
        i, j = int(high_sim_indices[0][0]), int(high_sim_indices[0][1])
        nid_a, nid_b = nodes_keys[i], nodes_keys[j]
        sim = float(sim_matrix[i, j])

    orig_a = graph_instance._original_id(nid_a)
    orig_b = graph_instance._original_id(nid_b)
    
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
        
    keep_orig = graph_instance._original_id(keep_nid)
    discard_orig = graph_instance._original_id(discard_nid)
    
    logger.info(f"[Topology] Merging highly similar nodes: '{discard_orig}' -> '{keep_orig}' (Similarity: {sim:.4f})")
    
    text_keep = get_node_text(keep_orig)
    text_discard = get_node_text(discard_orig)
    merged_text = text_keep or text_discard
    
    emb_keep = graph_instance.nodes[keep_nid]
    emb_discard = graph_instance.nodes[discard_nid]
    blended = emb_keep + emb_discard * 0.3
    blended_norm = blended / (blended.norm() + 1e-8) * max(emb_keep.norm(), emb_discard.norm())
    
    graph_instance.nodes[keep_nid] = torch.nn.Parameter(blended_norm.clone().detach())
    
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
    
    graph_instance.remove_node(discard_orig)
    delete_node(discard_orig)
    if discard_nid in node_metrics:
        del node_metrics[discard_nid]
