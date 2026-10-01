import asyncio
import json
import logging
import socket
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import torch
import torch.nn.functional as F

from aethelnet_node.database import save_node
from aethelnet_node.state import (
    graph_instance, node_metrics, text_to_embedding,
    get_known_peers, REALITY_ANCHORS, DEFAULT_CONFIDENCE,
    active_p2p_sockets
)

logger = logging.getLogger("Aethelnet.Node.P2P")

router = APIRouter()

class PeerRegisterPayload(BaseModel):
    peer_address: str

class PeerSyncPayload(BaseModel):
    peer_id: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]

@router.get("/p2p/ping")
async def ping_peer():
    hostname = socket.gethostname()
    return {"status": "alive", "peer_id": f"lgnn_node_{hostname}", "version": "1.0.0"}

@router.get("/p2p/peers")
async def get_peers():
    try:
        from aethelnet_node.forge_client import forge_client
        nodes = await asyncio.to_thread(forge_client.get_active_nodes)
        return {
            "peers": nodes,
            "source": "TheForge.sol",
            "contract": forge_client.contract_address
        }
    except Exception as e:
        logger.warning(f"[P2P] Failed to fetch peers from TheForge: {e}")
        return {"peers": get_known_peers(), "source": "fallback", "error": str(e)}

@router.post("/p2p/register")
async def register_peer(payload: PeerRegisterPayload):
    peer = payload.peer_address.strip()
    logger.info(f"[P2P API] Peer registration requested for '{peer}'. Executing registerNode on-chain...")
    try:
        from aethelnet_node.forge_client import forge_client
        receipt = await asyncio.to_thread(forge_client.register_node, peer)
        return {
            "status": "registered_on_chain",
            "tx_hash": receipt.get("tx_hash"),
            "block_number": receipt.get("block_number"),
            "peers": get_known_peers()
        }
    except Exception as e:
        logger.error(f"[P2P API] On-chain registration failed for {peer}: {e}")
        return {"status": "error", "message": str(e), "peers": get_known_peers()}

@router.get("/p2p/expertise")
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

@router.post("/p2p/sync")
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

@router.post("/p2p/gossip_msgpack")
async def receive_gossip_msgpack(request: Request):
    """
    The Holy Trinity Protocol: Receive compressed 'Grains of Truth' via MsgPack.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    is_known = client_ip in ["127.0.0.1", "localhost"] or any(client_ip in peer for peer in get_known_peers())
    
    body = await request.body()
    try:
        import msgpack
        payload = msgpack.unpackb(body, raw=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid msgpack payload")
        
    truth_id = payload.get("truth_id")
    truth_text = payload.get("truth_text")
    confidence = payload.get("confidence", DEFAULT_CONFIDENCE)
    
    if not truth_id or not truth_text:
        return {"status": "rejected", "reason": "Missing fields"}
        
    if truth_id in REALITY_ANCHORS:
        return {"status": "rejected", "reason": "Cannot override anchors"}

    logger.info(f"[P2P MsgPack] Received high-density truth '{truth_id}' from {client_ip}. Verified: {is_known}")
    
    # The Resonance Filter (Immune System)
    emb = text_to_embedding(truth_id)
    
    max_resonance = 0.0
    best_anchor = None
    for anchor in REALITY_ANCHORS:
        anchor_emb = text_to_embedding(anchor)
        sim = F.cosine_similarity(emb.unsqueeze(0), anchor_emb.unsqueeze(0)).item()
        if sim > max_resonance:
            max_resonance = sim
            best_anchor = anchor
            
    if max_resonance < 0.45:
        logger.warning(f"[P2P Immune System] Rejected truth '{truth_id}'. Resonance with anchors too low ({max_resonance:.2f})")
        return {"status": "rejected", "reason": "Immune system rejected due to low resonance"}
        
    logger.info(f"[P2P Immune System] Accepted truth '{truth_id}'. Resonates with '{best_anchor}' (Sim: {max_resonance:.2f})")
    
    try:
        from aethelnet_node.reward_system import economy
        economy.mint_reward(client_ip, truth_id, max_resonance, graph_instance)
    except Exception as e:
        logger.error(f"[Economy] Failed to mint reward: {e}")
    
    final_confidence = min(1.0, confidence + (0.1 if is_known else 0.0))
    graph_instance.add_node(truth_id, emb)
    
    save_node(
        truth_id, emb, 0.0, final_confidence, 0.0, False, False,
        text_content=truth_text, source_tag=f"p2p_msgpack_{client_ip}"
    )
    node_metrics[truth_id] = {
        "confidence": final_confidence,
        "is_grounded": False,
        "source_tag": f"p2p_msgpack_{client_ip}"
    }
    return {"status": "accepted", "truth_id": truth_id, "resonance": max_resonance}

@router.websocket("/p2p/ws")
async def p2p_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_p2p_sockets.add(websocket)
    peer_ip = websocket.client.host if websocket.client else "unknown"
    logger.info(f"[P2P] Warp Synapse established with peer {peer_ip}")
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            if payload.get("type") == "resonance_wave":
                nid = payload.get("node")
                text = payload.get("text", "")
                if nid and nid not in graph_instance.nodes and text:
                    emb = text_to_embedding(text)
                    graph_instance.add_node(nid, emb)
                    save_node(nid, emb, 0.0, DEFAULT_CONFIDENCE, 0.0, False, False, text_content=text, source_tag="warp_synapse")
                    node_metrics[nid] = {"confidence": DEFAULT_CONFIDENCE, "text_content": text, "source_tag": "warp_synapse"}
                    logger.info(f"[P2P] Ingested live resonance wave: {nid}")
    except WebSocketDisconnect:
        logger.info(f"[P2P] Warp Synapse severed with peer {peer_ip}")
        active_p2p_sockets.discard(websocket)
    except Exception as e:
        logger.debug(f"[P2P WS Error]: {e}")
        active_p2p_sockets.discard(websocket)
