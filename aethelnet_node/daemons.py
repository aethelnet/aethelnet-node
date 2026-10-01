import asyncio
import logging
import time
import json
from typing import Dict, Any, List, Optional
import torch

from aethelnet_node.database import (
    save_node, delete_node, save_edge, delete_edge,
    get_node_text, get_db_connection
)
from aethelnet_node.state import (
    graph_instance, node_metrics,
    REALITY_ANCHORS, DEFAULT_CONFIDENCE,
    active_websockets
)

logger = logging.getLogger("Aethelnet.Node.HebbianCore")

_hebbian_cycle_count = 0

def run_single_hebbian_cycle() -> Dict[str, Any]:
    """
    Executes a single step of the unified Hebbian learning cycle:
    1. ODE continuous integration + dynamic consensus diffusion.
    2. Vectorized resonance calculation (sim >= theta -> synapse +; sim < theta -> decay -).
    3. Edge persistence to SQLite (saving newly formed bridges, deleting severed edges).
    4. Node energy and confidence updates.
    """
    global _hebbian_cycle_count
    _hebbian_cycle_count += 1
    
    # 1. Evolve topology via ODE & Hebbian Plasticity
    report = graph_instance.evolve_topology(compute_time=1.0)
    
    # 2. Persist newly formed edges into SQLite
    for u, v, weight in report.get("new_edges", []):
        try:
            save_edge(u, v, weight=weight, label="hebbian")
        except Exception as e:
            logger.debug(f"[Hebbian DB] Failed to save new edge {u} <-> {v}: {e}")
            
    # 3. Persist pruned edges removal in SQLite
    for u, v in report.get("pruned_edges", []):
        try:
            delete_edge(u, v)
        except Exception as e:
            logger.debug(f"[Hebbian DB] Failed to delete edge {u} <-> {v}: {e}")
            
    # 4. Update Node Metrics (Energy & Confidence)
    for sid in list(graph_instance.nodes.keys()):
        state_tensor = graph_instance.nodes[sid]
        mean_act = float(state_tensor.mean().detach().cpu())
        orig_id = graph_instance._original_id(sid)
        
        metrics = node_metrics.setdefault(orig_id, {
            "confidence": DEFAULT_CONFIDENCE,
            "plateau_factor": 0.0,
            "is_grounded": orig_id in REALITY_ANCHORS,
            "help_chain": False,
            "source_tag": "vault_sync" if orig_id not in REALITY_ANCHORS else "genesis_anchor",
            "is_quarantined": False
        })
        node_metrics[sid] = metrics
        
        # Calculate confidence from connectivity degree and activity
        if orig_id in REALITY_ANCHORS:
            confidence = 0.98
        else:
            degree = graph_instance.nx_graph.degree(orig_id) if orig_id in graph_instance.nx_graph else 0
            # Notes with connections and positive activity gain confidence
            delta = (degree * 0.01) + (abs(mean_act) * 0.01) - 0.005
            confidence = min(0.99, max(0.20, metrics.get("confidence", DEFAULT_CONFIDENCE) + delta))
            
        metrics["confidence"] = confidence
        metrics["mean_activation"] = mean_act
        strain = graph_instance.get_node_strain(orig_id)
        metrics["tether_strain"] = round(strain, 4)
        
        # Periodically persist node state to SQLite
        try:
            text_content = get_node_text(orig_id)
            save_node(
                orig_id, state_tensor, mean_act,
                confidence, metrics.get("plateau_factor", 0.0),
                orig_id in REALITY_ANCHORS, metrics.get("help_chain", False),
                text_content=text_content,
                source_tag=metrics.get("source_tag", "internal"),
                node_type=metrics.get("node_type", "standard"),
                meta_data=metrics.get("meta_data")
            )
        except Exception as e:
            logger.debug(f"[Hebbian DB] Failed to save node {orig_id}: {e}")
            
    return report

async def unified_hebbian_daemon():
    """
    The Single Unified Cognitive Loop:
    Concentrates all compute into continuous Hebbian learning,
    broadcasting live telemetry to connected Observer frontends.
    """
    logger.info("[Hebbian Core] Unified Hebbian Cognitive Daemon ACTIVE. Starting learning cycles...")
    await asyncio.sleep(2) # Initial warmup
    
    while True:
        try:
            report = await asyncio.to_thread(run_single_hebbian_cycle)
            
            new_count = len(report.get("new_edges", []))
            strengthened_count = len(report.get("strengthened_edges", []))
            pruned_count = len(report.get("pruned_edges", []))
            node_count = report.get("active_nodes", 0)
            edge_count = report.get("active_edges", 0)
            mean_strain = report.get("mean_tether_strain", 0.0)
            max_node = report.get("max_strain_node", "none")
            max_strain = report.get("max_strain_val", 0.0)
            
            logger.info(
                f"[Hebbian Core] Cycle #{_hebbian_cycle_count} | "
                f"Nodes: {node_count} | Synapses: {edge_count} | "
                f"+{new_count} new, ~{strengthened_count} strong, -{pruned_count} pruned | "
                f"Tether Strain: {mean_strain:.4f} (Max: '{max_node}' @ {max_strain:.3f})"
            )
            
            # Broadcast real-time telemetry pulse to Observer UI
            if active_websockets:
                pulse_payload = {
                    "type": "hebbian_pulse",
                    "cycle": _hebbian_cycle_count,
                    "nodes": node_count,
                    "edges": edge_count,
                    "new_edges": report.get("new_edges", []),
                    "pruned_edges": report.get("pruned_edges", []),
                    "mean_tether_strain": mean_strain,
                    "max_strain_node": max_node,
                    "max_strain_val": max_strain,
                    "timestamp": time.time()
                }
                msg_str = json.dumps(pulse_payload)
                disconnected = set()
                for ws in list(active_websockets):
                    try:
                        await ws.send_text(msg_str)
                    except Exception:
                        disconnected.add(ws)
                for ws in disconnected:
                    active_websockets.discard(ws)

            # Trigger autonomous neurosymbolic synthesis on emergent Hebbian bridges
            new_edges = report.get("new_edges", [])
            for u, v, w in new_edges:
                if w >= 0.65:
                    from aethelnet_node.synthesis import synthesis_engine
                    if not synthesis_engine.is_synthesizing:
                        asyncio.create_task(_run_and_broadcast_synthesis(u, v, w))
                        break
                    
        except asyncio.CancelledError:
            logger.info("[Hebbian Core] Unified Hebbian loop cancelled.")
            break
        except Exception as e:
            logger.error(f"[Hebbian Core] Cycle #{_hebbian_cycle_count} exception: {e}", exc_info=True)
            
        await asyncio.sleep(10) # 10-second learning pulse

async def _run_and_broadcast_synthesis(u: str, v: str, resonance: float):
    try:
        from aethelnet_node.synthesis import synthesis_engine
        result = await synthesis_engine.synthesize_pair(u, v, resonance)
        if result and active_websockets:
            payload = json.dumps({
                "type": "synthesis_emerged",
                "synthesis": result,
                "timestamp": time.time()
            })
            for ws in list(active_websockets):
                try:
                    await ws.send_text(payload)
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"[Synthesis Daemon] Background synthesis failed for {u} <-> {v}: {e}")

def start_all_daemons():
    """
    Unified entrypoint: Spawns ONLY the clean Hebbian cognitive daemon.
    All legacy noise (arXiv crawlers, cosmic sensors, nightmare spawners, P2P flood) is decommissioned.
    """
    tasks = [
        asyncio.create_task(unified_hebbian_daemon())
    ]
    logger.info("[Daemons] Unified Hebbian Cognitive Core initialized (1 master task).")
    return tasks

# Backward compatibility alias
run_single_ode_cycle = run_single_hebbian_cycle

def get_hebbian_metrics() -> Dict[str, Any]:
    safe_ids = list(graph_instance.nodes.keys())
    node_ids = [graph_instance._original_id(sid) for sid in safe_ids]
    strains = [graph_instance.get_node_strain(orig_id) for orig_id in node_ids]
    mean_strain = float(sum(strains) / len(strains)) if strains else 0.0
    import numpy as np
    max_idx = int(np.argmax(strains)) if strains else 0
    max_node = node_ids[max_idx] if node_ids else None
    max_val = float(strains[max_idx]) if strains else 0.0
    return {
        "cycle": _hebbian_cycle_count,
        "nodes": len(node_ids),
        "edges": graph_instance.nx_graph.number_of_edges(),
        "mean_tether_strain": round(mean_strain, 4),
        "max_strain_node": max_node,
        "max_strain_val": round(max_val, 4)
    }


