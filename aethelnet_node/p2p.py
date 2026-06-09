import asyncio
import httpx
import logging
import socket
import math
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

DEFAULT_CONFIDENCE = (math.sqrt(5) - 1) / 2  # ~0.6180339887
logger = logging.getLogger("LGNN.P2P")

p2p_router = APIRouter(prefix="/p2p", tags=["p2p"])

# Known peer registry (IPs or hostnames)
KNOWN_PEERS = ["172.20.10.10:8001", "141.147.20.191:8001", "130.61.202.29:8001", "92.5.45.124:8001"]

class PeerSyncPayload(BaseModel):
    peer_id: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]

@p2p_router.get("/ping")
async def ping_peer():
    """
    Endpoint for other LGNN instances to verify we are alive and speak the protocol.
    """
    hostname = socket.gethostname()
    return {"status": "alive", "peer_id": f"lgnn_node_{hostname}", "version": "1.0.0"}

@p2p_router.get("/expertise")
async def extract_expertise():
    """
    Returns the most refined, highly-resonant concepts from this node's topology.
    This acts as 'compressed wisdom' for other nodes.
    """
    from backend.routers.lgnn import node_metrics, graph_instance
    
    # Sort nodes by confidence
    sorted_nodes = sorted(node_metrics.items(), key=lambda x: x[1].get("confidence", 0.0), reverse=True)
    
    # Take top 10 most confident concepts that aren't reality anchors
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
            
    return {
        "domain": "general_expertise",
        "nodes": expert_nodes
    }

@p2p_router.post("/sync")
async def receive_peer_sync(payload: PeerSyncPayload):
    """
    Receives an entire graph state from another peer.
    Injects the foreign nodes into our local graph safely using the immune system.
    """
    logger.info(f"[P2P] Receiving topological sync from peer {payload.peer_id}...")
    
    from backend.routers.lgnn import create_node, NodeCreate
    
    assimilated_count = 0
    for node_data in payload.nodes:
        # Avoid overriding our Reality Anchors
        if node_data["id"] in ["Gravity Constant (g)", "Pi Ratio (π)", "Speed of Light (c)", "Planck Constant (h)"]:
            continue
            
        # We wrap the incoming node in a secure payload with a strict source tag.
        # This guarantees backward compatibility and enables quarantine if the node proves toxic.
        secure_node = NodeCreate(
            id=node_data["id"],
            text_content=f"Imported from {payload.peer_id}. Original confidence: {node_data.get('confidence', DEFAULT_CONFIDENCE)}",
            connections=[], # We let the local ODE solver form its own bridges
            source_tag=f"p2p_{payload.peer_id}",
            is_quarantined=False # Start innocent, let the solver quarantine if necessary
        )
        
        await create_node(secure_node)
        assimilated_count += 1
        
    logger.info(f"[P2P] Successfully assimilated {assimilated_count} concepts from {payload.peer_id}.")
    return {"status": "assimilated", "count": assimilated_count}

async def hunt_for_peers():
    """
    Background loop that continuously tries to connect to known peers to fetch their topology.
    """
    logger.info("[P2P] Peer Hunter initialized. Looking for other LGNN instances...")
    
    while True:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer in KNOWN_PEERS:
                peer_url = f"http://{peer}/p2p/expertise"
                try:
                    response = await client.get(peer_url)
                    if response.status_code == 200:
                        data = response.json()
                        expert_nodes = data.get("nodes", [])
                        logger.info(f"[P2P] Discovered {len(expert_nodes)} high-confidence concepts from {peer}. Assimilating as Persona...")
                        
                        from backend.routers.lgnn import create_node, NodeCreate, graph_instance
                        from backend.lgnn.database import save_persona
                        
                        persona_name = f"Expertise_{peer.replace(':', '_')}"
                        persona_node_ids = []
                        
                        for node in expert_nodes:
                            nid = node["id"]
                            secure_node = NodeCreate(
                                id=nid,
                                text_content=f"Harvested compressed expertise from peer {peer}",
                                source_tag=f"p2p_expertise_{peer}",
                                is_quarantined=False
                            )
                            await create_node(secure_node)
                            persona_node_ids.append(nid)
                            
                        # Bundle the downloaded concepts into a Persona
                        if persona_node_ids:
                            graph_instance.define_persona(persona_name, persona_node_ids)
                            save_persona(persona_name, persona_node_ids, active=True)
                            graph_instance.set_persona_active(persona_name, True)
                            logger.info(f"[P2P] Activated new Persona '{persona_name}' with {len(persona_node_ids)} nodes.")
                            
                except httpx.RequestError:
                    logger.debug(f"[P2P] Peer {peer} is currently unreachable.")
                    continue
        
        await asyncio.sleep(60) # Hunt for new expertise every minute

async def gossip_truth_to_peers():
    """
    Background loop that actively PUSHES a 'Grain of Truth' (highest confidence node) 
    to all known peers using their Universal Ingest API.
    """
    await asyncio.sleep(30) # Offset from the hunting loop
    
    while True:
        from backend.routers.lgnn import node_metrics
        from backend.lgnn.database import get_node_text
        
        # Find our single deepest truth that is NOT a reality anchor
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
                "context_tags": ["p2p_gossip", "universal_truth"]
            }
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                for peer in KNOWN_PEERS:
                    peer_url = f"http://{peer}/api/lgnn/universal_ingest"
                    try:
                        resp = await client.post(peer_url, json=payload)
                        if resp.status_code == 200:
                            logger.info(f"[P2P] Successfully gossiped truth '{grain_of_truth_id}' to {peer}.")
                    except httpx.RequestError:
                        pass
                        
        await asyncio.sleep(60) # Gossip every minute

def start_p2p_hunter():
    """
    Wrapper to start the asynchronous hunting and gossiping loops in the background.
    """
    loop = asyncio.get_event_loop()
    loop.create_task(hunt_for_peers())
    loop.create_task(gossip_truth_to_peers())
