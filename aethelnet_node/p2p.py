import asyncio
import httpx
import logging
import socket
import math
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import websockets
import json

from web3 import Web3

DEFAULT_CONFIDENCE = (math.sqrt(5) - 1) / 2  # ~0.6180339887
logger = logging.getLogger("LGNN.P2P")

p2p_router = APIRouter(prefix="/p2p", tags=["p2p"])

# TheForge Contract Config (Ensure this matches your local deployment!)
RPC_URL = "http://127.0.0.1:8545"
FORGE_ADDRESS = "0x81E3E4Cba25546b2e8339Bf9d7c46F6707cE88f2" # Update this after re-deploy!
FORGE_ABI = [
    {"inputs":[],"name":"getActiveNodes","outputs":[{"internalType":"string[]","name":"","type":"string[]"}],"stateMutability":"view","type":"function"}
]

def get_known_peers() -> List[str]:
    """Dynamically fetches active peers from the Aethelnet DAO (TheForge)."""
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        if not w3.is_connected():
            logger.warning("[P2P] Blockchain RPC unreachable. Falling back to local peers.")
            return ["127.0.0.1:8001"]
            
        contract = w3.eth.contract(address=FORGE_ADDRESS, abi=FORGE_ABI)
        active_ips = contract.functions.getActiveNodes().call()
        
        if not active_ips:
            return ["127.0.0.1:8001"]
            
        return [ip for ip in active_ips if ip != ""]
    except Exception as e:
        logger.error(f"[P2P] Error fetching peers from blockchain: {e}")
        return ["127.0.0.1:8001"]

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
    from aethelnet_node.main import node_metrics, graph_instance
    
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

active_p2p_sockets = set()

@p2p_router.websocket("/ws")
async def p2p_websocket_endpoint(websocket: WebSocket):
    """
    Real-time P2P Synapse. Accepts connections from other LGNN nodes.
    """
    await websocket.accept()
    active_p2p_sockets.add(websocket)
    peer_ip = websocket.client.host if websocket.client else "unknown"
    logger.info(f"[P2P] Synapse established with peer {peer_ip}")
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            if payload.get("type") == "resonance_wave":
                # A wave of state vectors from another node!
                pass
    except WebSocketDisconnect:
        logger.info(f"[P2P] Synapse severed with peer {peer_ip}")
        active_p2p_sockets.discard(websocket)
        
async def broadcast_resonance(node_id: str, new_state: float):
    """
    Pushes a resonance wave to all connected peers in sub-50ms.
    """
    if not active_p2p_sockets:
        return
    message = json.dumps({
        "type": "resonance_wave",
        "node": node_id,
        "state": new_state
    })
    disconnected = set()
    for ws in list(active_p2p_sockets):
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    for ws in disconnected:
        active_p2p_sockets.discard(ws)

async def real_time_p2p_sync():
    """
    Connects as a client to the /ws endpoint of active peers.
    """
    await asyncio.sleep(10) # Give nodes time to boot
    connected_peers = set()
    
    while True:
        known_peers = get_known_peers()
        for peer in known_peers:
            if peer in connected_peers:
                continue
                
            ws_url = f"ws://{peer}/p2p/ws"
            # Spawn a client task per peer
            async def peer_client_task(p_url, p_ip):
                try:
                    async with websockets.connect(p_url) as ws:
                        logger.info(f"[P2P] Client connected to Synapse {p_url}")
                        connected_peers.add(p_ip)
                        while True:
                            msg = await ws.recv()
                            # Handle incoming real-time wave here
                except Exception as e:
                    if p_ip in connected_peers:
                        logger.debug(f"[P2P] Lost connection to {p_url}: {e}")
                        connected_peers.remove(p_ip)
                        
            asyncio.create_task(peer_client_task(ws_url, peer))
                
        await asyncio.sleep(15) # Check for new peers every 15 seconds

@p2p_router.post("/sync")
async def receive_peer_sync(payload: PeerSyncPayload):
    """
    Receives an entire graph state from another peer.
    Injects the foreign nodes into our local graph safely using the immune system.
    """
    logger.info(f"[P2P] Receiving topological sync from peer {payload.peer_id}...")
    
    from aethelnet_node.main import create_node, NodeCreate
    
    assimilated_count = 0
    for node_data in payload.nodes:
        # Avoid overriding our Reality Anchors
        if node_data["id"] in ["creativity", "soziokratie3.0", "neon genesis evangelion", "unit734", "aethelburg"]:
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
        known_peers = get_known_peers()
        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer in known_peers:
                peer_url = f"http://{peer}/p2p/expertise"
                try:
                    response = await client.get(peer_url)
                    if response.status_code == 200:
                        data = response.json()
                        expert_nodes = data.get("nodes", [])
                        logger.info(f"[P2P] Discovered {len(expert_nodes)} high-confidence concepts from {peer}. Assimilating as Persona...")
                        
                        from aethelnet_node.main import create_node, NodeCreate, graph_instance
                        from aethelnet_node.database import save_persona
                        
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
        from aethelnet_node.main import node_metrics
        from aethelnet_node.database import get_node_text
        
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
            
            known_peers = get_known_peers()
            async with httpx.AsyncClient(timeout=5.0) as client:
                for peer in known_peers:
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
    loop.create_task(real_time_p2p_sync())
