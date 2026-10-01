import asyncio
import logging
import math
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import torch

from aethelnet_node.database import save_edge, delete_node, get_db_connection
from aethelnet_node.state import (
    graph_instance, node_metrics, text_to_embedding,
    calculate_centrality, active_websockets
)

logger = logging.getLogger("Aethelnet.Node.Telemetry")

router = APIRouter()

@router.websocket("/ws")
@router.websocket("/ws/stream")
@router.websocket("/api/lgnn/ws")
@router.websocket("/api/lgnn/ws/{client_id}")
@router.websocket("/api/stream/ws/stream")
async def websocket_endpoint(websocket: WebSocket, client_id: Optional[str] = None):
    await websocket.accept()
    active_websockets.add(websocket)
    stream_id = client_id or f"Stream_{int(time.time())}"
    logger.info(f"[WS] Client connected. Registering as {stream_id}")
    
    emb = text_to_embedding(stream_id)
    graph_instance.add_node(stream_id, emb)
    node_metrics[stream_id] = {
        "confidence": 1.0,
        "is_grounded": False,
        "is_quarantined": False,
        "source_tag": "websocket_observer",
        "text_content": "Active Dashboard Viewport Stream",
        "vector": emb.numpy(),
        "created_at": time.time()
    }
    
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=2.0)
                msg_type = data.get("type")
                if msg_type == "AUTH":
                    # Acknowledge authentication handshake
                    await websocket.send_json({"type": "AUTH_OK", "client_id": stream_id})
                elif msg_type == "update_params":
                    if "decay_rate" in data:
                        graph_instance.decay_rate = float(data["decay_rate"])
                    if "resonance_threshold" in data:
                        graph_instance.resonance_threshold = float(data["resonance_threshold"])
                    logger.info(f"[WS] Parameters updated: decay={graph_instance.decay_rate}, resonance={graph_instance.resonance_threshold}")
                elif msg_type == "tune_resonance" and data.get("query"):
                    query = data["query"]
                    logger.info(f"[WS] {stream_id} tuning resonance to: {query}")
                    new_emb = text_to_embedding(query)
                    
                    with torch.no_grad():
                        safe_id = graph_instance._safe_id(stream_id)
                        graph_instance.nodes[safe_id].copy_(new_emb)
                    
                    if stream_id in node_metrics:
                        node_metrics[stream_id]["text_content"] = f"Intent Vector: {query}"
                        node_metrics[stream_id]["vector"] = new_emb.numpy()
                
                elif data.get("type") == "create_link":
                    src = graph_instance._safe_id(data["source"])
                    tgt = graph_instance._safe_id(data["target"])
                    if src in graph_instance.nodes and tgt in graph_instance.nodes:
                        graph_instance.nx_graph.add_edge(src, tgt, weight=1.0)
                        save_edge(src, tgt, 1.0)
                        logger.info(f"[WS] Manual link created: {src} <-> {tgt}")
                        
                elif data.get("type") == "delete_nodes":
                    for node_id in data.get("nodes", []):
                        safe_id = graph_instance._safe_id(node_id)
                        if safe_id in graph_instance.nodes:
                            del graph_instance.nodes[safe_id]
                        if graph_instance.nx_graph.has_node(safe_id):
                            graph_instance.nx_graph.remove_node(safe_id)
                        delete_node(safe_id)
                        logger.info(f"[WS] Manual prune: Node {safe_id} deleted")
                        
                elif data.get("type") == "update_params":
                    if "decay_rate" in data:
                        graph_instance.decay_rate = float(data["decay_rate"])
                        logger.info(f"[WS] Updated decay_rate: {graph_instance.decay_rate}")
                    if "resonance_threshold" in data:
                        graph_instance.resonance_threshold = float(data["resonance_threshold"])
                        logger.info(f"[WS] Updated resonance_threshold: {graph_instance.resonance_threshold}")

                elif data.get("type") == "fork_reality":
                    timestamp = data.get("timestamp")
                    past_nodes = data.get("nodes", [])
                    past_ids = {n.get("id") for n in past_nodes}
                    
                    current_keys = list(graph_instance.nodes.keys())
                    removed_count = 0
                    for k in current_keys:
                        cid = graph_instance._original_id(k)
                        if cid not in past_ids and cid != stream_id:
                            delete_node(cid)
                            if k in graph_instance.nodes:
                                del graph_instance.nodes[k]
                            if graph_instance.nx_graph.has_node(k):
                                graph_instance.nx_graph.remove_node(k)
                            removed_count += 1
                    logger.info(f"Reality forked at T-{timestamp}. Removed {removed_count} future nodes.")

                elif data.get("type") == "toggle_privacy":
                    for node_id in data.get("nodes", []):
                        safe_id = graph_instance._safe_id(node_id)
                        if safe_id in node_metrics:
                            current = node_metrics[safe_id].get("is_public", True)
                            new_state = not current
                            node_metrics[safe_id]["is_public"] = new_state
                            
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute("UPDATE lgnn_nodes SET is_public = ? WHERE id = ?", (1 if new_state else 0, safe_id))
                            conn.commit()
                            conn.close()
            except asyncio.TimeoutError:
                pass

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
                    "centrality": centrality_scores.get(orig_id, 0.0),
                    "is_public": node_metrics.get(orig_id, {}).get("is_public", True),
                    "text_content": node_metrics.get(orig_id, {}).get("text_content", ""),
                    "parent_id": node_metrics.get(orig_id, {}).get("parent_id", "root")
                })
            for u, v, data in graph_instance.nx_graph.edges(data=True):
                orig_u = graph_instance._original_id(u)
                orig_v = graph_instance._original_id(v)
                links_data.append({"source": orig_u, "target": orig_v, "weight": data.get("weight", 1.0)})
                
            local_balance = 0.0
            try:
                from aethelnet_node.reward_system import economy
                local_balance = sum(amt for key, amt in economy.ledger.items() if key.startswith("LocalMiner_"))
            except Exception:
                pass

            await websocket.send_json({
                "type": "telemetry",
                "nodes": len(nodes_data),
                "bridges": len(links_data),
                "state": "Active",
                "balance": local_balance,
                "leader": leader_node if leader_node else "None",
                "graph": {
                    "nodes": nodes_data,
                    "links": links_data
                }
            })
    except WebSocketDisconnect:
        active_websockets.discard(websocket)
        logger.info(f"[WS] Client {stream_id} disconnected.")
        if stream_id in graph_instance.nodes:
            graph_instance.remove_node(stream_id)
            if stream_id in node_metrics:
                del node_metrics[stream_id]
    except Exception as e:
        active_websockets.discard(websocket)
        logger.debug(f"[WS Error]: {e}")
