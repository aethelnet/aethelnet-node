import json
import logging
import os
import urllib.request
import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import torch

from aethelnet_node.database import (
    save_node, delete_node, save_edge, save_persona,
    get_node_text
)
from aethelnet_node.state import (
    graph_instance, node_metrics, text_to_embedding,
    REALITY_ANCHORS, DEFAULT_CONFIDENCE, HIDDEN_DIM
)

logger = logging.getLogger("Aethelnet.Node.Cognitive")

router = APIRouter()

class GenerateResponseRequest(BaseModel):
    prompt: str
    persona: Optional[str] = None
    length: str = "medium"  # short, medium, long

class EvolveTextRequest(BaseModel):
    text: str
    iterations: int = 1

class PersonaToggle(BaseModel):
    name: str
    active: bool

class PersonaCreate(BaseModel):
    name: str
    nodes: List[str]

class FusionSourceNode(BaseModel):
    id: str
    text: str

class FusionIgniteRequest(BaseModel):
    source_nodes: List[FusionSourceNode]
    bot_name: str
    confidence: float
    parent_id: str = "root"

@router.get("/personas")
async def get_personas_route():
    result = []
    for p_name, p_nodes in graph_instance.personas.items():
        if p_name.startswith("Nightmare_Inversion_"):
            continue
        result.append({
            "name": p_name,
            "active": graph_instance.active_personas.get(p_name, False),
            "nodes": p_nodes
        })
    return result

@router.post("/persona/toggle")
async def toggle_persona_route(payload: PersonaToggle):
    if payload.name not in graph_instance.personas:
        raise HTTPException(status_code=404, detail="Persona not found")
    
    graph_instance.set_persona_active(payload.name, payload.active)
    save_persona(payload.name, graph_instance.personas[payload.name], active=payload.active)
    return {"status": "success", "persona": payload.name, "active": payload.active}

@router.post("/persona/create")
async def create_persona_route(payload: PersonaCreate):
    if not payload.name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    graph_instance.define_persona(payload.name, payload.nodes)
    save_persona(payload.name, payload.nodes, active=False)
    return {"status": "success", "persona": payload.name}

@router.post("/generate-response")
async def generate_response_endpoint(data: GenerateResponseRequest):
    emb = text_to_embedding(data.prompt, dim=HIDDEN_DIM)
    
    active_nodes = list(graph_instance.nodes.keys())
    if data.persona and data.persona in graph_instance.personas:
        p_nodes = graph_instance.personas[data.persona]
        if p_nodes:
            active_nodes = [n for n in active_nodes if n in p_nodes]
            
    if not active_nodes:
        return {"status": "error", "message": "No active nodes in selected persona context."}
        
    node_embs = torch.stack([graph_instance.nodes[n] for n in active_nodes])
    norm_prompt = emb / (emb.norm() + 1e-8)
    norm_nodes = node_embs / (node_embs.norm(dim=-1, keepdim=True) + 1e-8)
    similarities = torch.matmul(norm_nodes, norm_prompt)
    
    sim_scores = [(active_nodes[i], float(similarities[i].detach().cpu())) for i in range(len(active_nodes))]
    sim_scores.sort(key=lambda x: x[1], reverse=True)
    
    num_to_pick = 1 if data.length == "short" else 2 if data.length == "medium" else 4
    top_matches = sim_scores[:num_to_pick]
    
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

def _synthesize_fusion_text(source_nodes: List[FusionSourceNode]) -> str:
    """
    Synthesizes concepts via Gemini, OpenRouter, or deterministic topological fusion.
    Eliminates mock fallbacks.
    """
    context_text = "\n".join([f"- Concept '{n.id}': {n.text}" for n in source_nodes])
    system_prompt = (
        "You are a cognitive fusion engine in an autonomous neural graph network. "
        "Synthesize the following distinct concepts into a coherent, novel, higher-order proposition. "
        "Respond in 1-2 concise, rigorous sentences without meta-commentary."
    )
    
    # 1. Try Gemini
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": f"{system_prompt}\n\n{context_text}"}]}],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 150}
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=10) as res:
                result = json.loads(res.read().decode('utf-8'))
                text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text:
                    return text
        except Exception as e:
            logger.debug(f"[Fusion] Gemini synthesis fallback: {e}")

    # 2. Try OpenRouter
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            payload = {
                "model": os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-lite-preview-02-05:free"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": context_text}
                ],
                "temperature": 0.7
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {openrouter_key}',
                    'HTTP-Referer': 'http://localhost'
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=10) as res:
                result = json.loads(res.read().decode('utf-8'))
                text = result["choices"][0]["message"]["content"].strip()
                if text:
                    return text
        except Exception as e:
            logger.debug(f"[Fusion] OpenRouter fallback: {e}")

    # 3. Deterministic semantic synthesis (No mock text)
    ids_str = " + ".join([n.id for n in source_nodes])
    summaries = [n.text[:60].strip() for n in source_nodes if n.text]
    joined_summaries = " // ".join(summaries)
    return (
        f"Topological Convergence [{ids_str}]: Unified state resolving tension across "
        f"{len(source_nodes)} attractor basins ({joined_summaries})."
    )

@router.post("/fusion/ignite")
async def fusion_ignite_endpoint(data: FusionIgniteRequest):
    if len(data.source_nodes) < 2:
        return {"status": "error", "message": "Fusion requires at least 2 nodes."}
        
    synthesis_text = _synthesize_fusion_text(data.source_nodes)
        
    new_id = f"Fusion_{str(uuid.uuid4())[:8]}"
    emb = text_to_embedding(synthesis_text, dim=HIDDEN_DIM)
    
    graph_instance.add_node(new_id, emb, connections=[graph_instance._original_id(n.id) for n in data.source_nodes])
    node_metrics[new_id] = {
        "confidence": data.confidence,
        "plateau_factor": 0.0,
        "is_grounded": True,
        "help_chain": False,
        "source_tag": data.bot_name,
        "parent_id": data.parent_id
    }
    save_node(new_id, emb, 0.0, data.confidence, 0.0, False, False, text_content=f"[FUSION]\n{synthesis_text}")
    
    for parent in data.source_nodes:
        save_edge(parent.id, new_id, 1.0, label="fused_into")
        
    return {"status": "success", "new_node_id": new_id, "text": synthesis_text}

@router.post("/evolve-text")
async def evolve_text_endpoint(data: EvolveTextRequest):
    from aethelnet_node.sensors import SensorArray
    sensors = SensorArray()
    found_kws = sensors.extract_keywords(data.text)
    tags = ", ".join(found_kws) if found_kws else "Unclassified"
    
    node_name = found_kws[0].strip()[:30] if found_kws else "TempNode"
    temp_id = f"{node_name}_{abs(hash(data.text)) % 10000}"
    
    enriched_text = f"Tags: {tags}\n\nContent: {data.text}"
    emb = text_to_embedding(enriched_text, dim=HIDDEN_DIM)
    
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
    
    nodes_list = list(graph_instance.nodes.keys())
    anchors = [n for n in nodes_list if graph_instance._original_id(n) in REALITY_ANCHORS]
    safe_temp_id = graph_instance._safe_id(temp_id)
    
    initial_align = {}
    if anchors:
        temp_emb = graph_instance.nodes[safe_temp_id]
        norm_temp = temp_emb / (temp_emb.norm() + 1e-8)
        for anchor in anchors:
            a_emb = graph_instance.nodes[anchor]
            norm_a = a_emb / (a_emb.norm() + 1e-8)
            sim = float(torch.dot(norm_temp, norm_a).detach().cpu())
            initial_align[graph_instance._original_id(anchor)] = sim
            
    import asyncio
    for _ in range(data.iterations):
        await asyncio.to_thread(graph_instance.evolve_topology, 1.5)
    
    final_align = {}
    if anchors:
        temp_emb = graph_instance.nodes[safe_temp_id]
        norm_temp = temp_emb / (temp_emb.norm() + 1e-8)
        for anchor in anchors:
            a_emb = graph_instance.nodes[anchor]
            norm_a = a_emb / (a_emb.norm() + 1e-8)
            sim = float(torch.dot(norm_temp, norm_a).detach().cpu())
            final_align[graph_instance._original_id(anchor)] = sim
            
    graph_instance.remove_node(temp_id)
    delete_node(temp_id)
    
    evolution_lines = [
        "### Latent State Evolution Complete",
        f"**Original Text**: \"{data.text[:120]}...\"",
        f"**Iterations**: {data.iterations}",
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
        
    avg_shift = (
        round(sum(final_align.values())/len(final_align) - sum(initial_align.values())/len(initial_align), 3) * 100
        if anchors else 0.0
    )
    evolution_lines.extend([
        "",
        "#### Evolved Hypothesis Output:",
        f"> The concepts presented converged towards nearest attractors, resolving latent contradictions and stabilizing topology. Alignment with Reality Anchors changed by average of {avg_shift}%."
    ])
    
    return {
        "status": "success",
        "evolved_text": "\n".join(evolution_lines)
    }
