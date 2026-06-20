import torch
import logging
from typing import Dict, Any, List, Tuple
from aethelnet_node.liquid_graph import LiquidGraph
from aethelnet_node.database import load_graph_state

logger = logging.getLogger("LGNN.Coherence")

def evaluate_graph_coherence(prioritized_nodes: List[str], hidden_dim: int = 128) -> Dict[str, Any]:
    """
    Evaluates the mathematical coherence and flags cognitive conflicts
    between user-prioritized nodes and the rest of the persistent graph topology.
    """
    nodes, edges, metrics = load_graph_state(dim=hidden_dim)
    if not nodes:
        return {"status": "error", "message": "Graph is empty."}
        
    conflicts = []
    coherence_score = 1.0
    suggestions = []
    
    # Calculate pairwise similarities between prioritized nodes and existing nodes
    node_ids = list(nodes.keys())
    states = torch.stack([nodes[nid] for nid in node_ids])
    norm_states = states / (states.norm(dim=-1, keepdim=True) + 1e-8)
    similarity_matrix = torch.matmul(norm_states, norm_states.T)
    
    for p_node in prioritized_nodes:
        if p_node not in node_ids:
            continue
            
        p_idx = node_ids.index(p_node)
        
        # Check alignment against reality anchors
        for j, other_node in enumerate(node_ids):
            if p_node == other_node:
                continue
                
            sim = float(similarity_matrix[p_idx, j].detach().cpu())
            
            # Significant negative similarity indicates a conceptual/semantic contradiction
            if sim < -0.3:
                # If conflicting with a reality anchor, flag high-severity conflict
                is_anchor = metrics[other_node].get("is_grounded", False)
                severity = "HIGH" if is_anchor else "MEDIUM"
                
                conflicts.append({
                    "severity": severity,
                    "source": p_node,
                    "conflicts_with": other_node,
                    "similarity": round(sim, 3),
                    "description": f"Concept '{p_node}' mathematically contradicts reality anchor '{other_node}'." if is_anchor 
                                  else f"Concept '{p_node}' is semantically misaligned with '{other_node}'."
                })
                
                # Deduct coherence
                coherence_score -= 0.15 if is_anchor else 0.08
                
    coherence_score = max(0.0, min(1.0, coherence_score))
    
    # Generate personality/attractor suggestions
    if conflicts:
        for c in conflicts:
            if c["severity"] == "HIGH":
                suggestions.append(
                    f"Prioritize '{c['conflicts_with']}' to force '{c['source']}' to stabilize via continuous ODE flow."
                )
            else:
                suggestions.append(
                    f"Adjust the Hebbian pruning threshold to allow '{c['source']}' and '{c['conflicts_with']}' to drift apart."
                )
    else:
        suggestions.append("Graph states are in complete coherence. Attractor fields are aligned.")
        
    return {
        "status": "success",
        "coherence_score": round(coherence_score, 3),
        "conflicts": conflicts,
        "suggestions": list(set(suggestions)) # Deduplicate
    }
