import os
import asyncio
import httpx
import logging
import json
import numpy as np

from aethelnet_node.security import auth_headers

logger = logging.getLogger("LGNN.Ouroboros")

class OuroborosLoop:
    """
    The cybernetic feedback loop. The LGNN extracts its current 'Dream Vector',
    sends it to the Mistral Coach for semantic critique, and then ingests 
    the Coach's feedback to mutate its own topology.
    """
    def __init__(self, ollama_url="http://localhost:11434/api/generate", lgnn_ingest_url=None):
        self.ollama_url = ollama_url
        port = os.getenv("PORT", "8000")
        self.lgnn_ingest_url = lgnn_ingest_url or os.getenv("AETHELNET_NODE_URL", f"http://127.0.0.1:{port}/api/lgnn/universal_ingest")

    async def extract_dream_concepts(self):
        """Fetches the current most resonant nodes from the graph using topological energy and graph centrality."""
        from aethelnet_node.main import node_metrics, graph_instance
        
        # 1. Rank nodes by topological activation energy and degree centrality
        ranked_nodes = []
        for safe_id in list(graph_instance.nodes.keys()):
            orig_id = graph_instance._original_id(safe_id)
            metrics = node_metrics.get(orig_id, {})
            if metrics.get("is_grounded", False):
                continue
            energy = graph_instance.get_node_energy(orig_id)
            degree = graph_instance.nx_graph.degree(orig_id) if graph_instance.nx_graph.has_node(orig_id) else 0
            score = energy + 0.15 * degree
            ranked_nodes.append((orig_id, score))

        ranked_nodes.sort(key=lambda x: x[1], reverse=True)
        dream_concepts = [nid for nid, _ in ranked_nodes[:5]]

        # Fallback to node_metrics if graph has no ungrounded nodes
        if not dream_concepts:
            sorted_nodes = sorted(node_metrics.items(), key=lambda x: x[1].get("confidence", 0.0), reverse=True)
            for nid, metrics in sorted_nodes:
                if not metrics.get("is_grounded", False):
                    dream_concepts.append(nid)
                if len(dream_concepts) >= 5:
                    break
        return dream_concepts

    async def query_coach(self, dream_concepts):
        """Asks Gemini, OpenRouter, or local Mistral to critique the LGNN's thought, with autonomous offline fallback."""
        if not dream_concepts:
            return None
            
        import os
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        gemini_api_key = os.environ.get("GEMINI_API_KEY")
        openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")

        prompt = (
            "You are the semantic Coach for a Liquid Graph Neural Network (LGNN).\n"
            "The LGNN does not speak human language; it only feels topological physics.\n"
            f"Right now, the LGNN is forming a highly resonant 'thought' connecting these abstract concepts:\n"
            f"{', '.join(dream_concepts)}\n\n"
            "Your job is to critique this connection. Does it make logical or semantic sense?\n"
            "Provide a short, harsh, 2-sentence feedback loop correcting or validating its thought process.\n"
            "Your exact words will be physically ingested by the LGNN as new vectors."
        )

        # 1. Try Gemini
        if gemini_api_key:
            model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(gemini_url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                        logger.info(f"[Ouroboros] Gemini ({model}) successfully critiqued the dream.")
                        return text.strip()
                    else:
                        logger.warning(f"[Ouroboros] Gemini returned status {resp.status_code}. Falling back...")
            except Exception as e:
                logger.warning(f"[Ouroboros] Gemini connection failed: {e}. Falling back...")

        # 2. Try OpenRouter
        if openrouter_api_key:
            model = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a harsh, precise cybernetic coach."},
                    {"role": "user", "content": prompt}
                ]
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        json=payload,
                        headers={"Authorization": f"Bearer {openrouter_api_key}"}
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        text = data["choices"][0]["message"]["content"]
                        logger.info(f"[Ouroboros] OpenRouter ({model}) successfully critiqued the dream.")
                        return text.strip()
            except Exception as e:
                logger.warning(f"[Ouroboros] OpenRouter connection failed: {e}")

        # 3. Try Local Mistral via Ollama
        try:
            payload = {"model": "mistral", "prompt": prompt, "stream": False}
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.ollama_url, json=payload)
                if response.status_code == 200:
                    text = response.json().get("response", "")
                    if text:
                        logger.info("[Ouroboros] Local Mistral coach successfully critiqued the dream.")
                        return text.strip()
        except Exception:
            pass

        # 4. Offline Algorithmic Topological Synthesis Fallback
        logger.info("[Ouroboros] All LLM providers offline. Performing autonomous topological synthesis.")
        from aethelnet_node.main import graph_instance
        resonances = []
        for i in range(len(dream_concepts)):
            for j in range(i + 1, len(dream_concepts)):
                res = graph_instance.get_node_resonance(dream_concepts[i], dream_concepts[j])
                resonances.append((dream_concepts[i], dream_concepts[j], res))

        if resonances:
            highest = max(resonances, key=lambda x: x[2])
            lowest = min(resonances, key=lambda x: x[2])
            feedback = (
                f"Topological tension detected: '{highest[0]}' resonates strongly with '{highest[1]}' (r={highest[2]:.2f}), "
                f"while '{lowest[0]}' and '{lowest[1]}' diverge (r={lowest[2]:.2f}). Synthesizing bridge."
            )
        else:
            feedback = f"Topological cluster formed around {', '.join(dream_concepts)}. Re-aligning latent flow."
        return feedback

    async def ingest_feedback(self, feedback_text):
        """Feeds the coach's critique back into the LGNN, preferring direct in-memory ingest."""
        import time
        from aethelnet_node.main import text_to_embedding, graph_instance, node_metrics
        from aethelnet_node.database import save_node

        node_id = "Obs_Ouroboros_Coach"
        try:
            emb = text_to_embedding(feedback_text)
            graph_instance.add_node(node_id, emb)
            node_metrics[node_id] = {
                "confidence": 0.95,
                "text_content": feedback_text,
                "source_tag": "Ouroboros_Coach",
                "is_grounded": False
            }
            save_node(
                node_id, emb, 0.0, 0.95, 0.0, False, False,
                text_content=feedback_text, source_tag="Ouroboros_Coach"
            )
            logger.info(f"[Ouroboros] In-Memory Feedback Ingested: {node_id} -> {feedback_text[:60]}...")
            return True
        except Exception as e:
            logger.warning(f"[Ouroboros] In-memory ingest failed ({e}), falling back to HTTP: {self.lgnn_ingest_url}")
            payload = {
                "bot_name": "Ouroboros_Coach",
                "observation": feedback_text,
                "confidence": 0.95,
                "context_tags": ["ouroboros", "coach_feedback", "semantic_correction"]
            }
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(self.lgnn_ingest_url, json=payload, headers=auth_headers())
                    return True
            except Exception as e2:
                logger.error(f"[Ouroboros] HTTP fallback also failed: {e2}")
                return False

    async def run_loop(self):
        logger.info("[Ouroboros] The cybernetic feedback loop has awakened.")
        while True:
            # 1. The LGNN dreams
            dream = await self.extract_dream_concepts()
            if dream:
                logger.info(f"[Ouroboros] LGNN is dreaming about: {dream}")
                
                # Render the dream to a physical file using OmniDecoder
                from aethelnet_node.decoders.omni_decoder import UniversalOmniDecoder
                from aethelnet_node.main import node_metrics
                try:
                    nodes_data = [{"id": nid, "vector": node_metrics.get(nid, {}).get("vector", np.zeros(768))} for nid in dream]
                    resonance = np.ones(len(nodes_data))
                    decoder = UniversalOmniDecoder()
                    decoder.decode(nodes_data, resonance)
                except Exception as e:
                    logger.error(f"[Ouroboros] OmniDecoder failed to render: {e}")

                # 2. The Coach critiques
                feedback = await self.query_coach(dream)
                if feedback:
                    # 3. The LGNN eats the critique
                    await self.ingest_feedback(feedback)
            
            # Rest before the next cycle
            await asyncio.sleep(120)

class VerticalFarmLoop:
    """
    The Pure Topo-Predictive Manifold: 
    Measures how well the LGNN's continuous mathematical evolution (ODE drift) 
    predicts the actual incoming reality vectors.
    """
    def __init__(self):
        self.last_evaluated = {} # Tracks the last node we checked for each stream

    async def run_loop(self):
        logger.info("[VerticalFarm] The pure topological manifold has sprouted. No LLMs required here.")
        
        while True:
            await asyncio.sleep(30) # Check alignment frequently
            
            from aethelnet_node.main import node_metrics, graph_instance, text_to_embedding
            from aethelnet_node.reward_system import economy
            import torch
            
            # Group observations by source
            streams = {}
            for nid, metrics in list(node_metrics.items()):
                tag = metrics.get("source_tag", "")
                text = metrics.get("text_content", "")
                
                if tag:
                    if tag not in streams:
                        streams[tag] = []
                    streams[tag].append((nid, text))
            
            for stream_name, history in streams.items():
                if len(history) < 2:
                    continue
                
                # Sort chronologically by timestamp in ID Obs_Name_Timestamp
                try:
                    history.sort(key=lambda x: int(x[0].split("_")[-1]))
                except:
                    continue
                    
                latest_node_id, latest_text = history[-1]
                prev_node_id, _ = history[-2]
                
                # Have we already evaluated this specific future?
                if self.last_evaluated.get(stream_name) == latest_node_id:
                    continue
                
                self.last_evaluated[stream_name] = latest_node_id
                
                safe_latest = graph_instance._safe_id(latest_node_id)
                safe_prev = graph_instance._safe_id(prev_node_id)
                
                if safe_prev not in graph_instance.nodes or safe_latest not in graph_instance.nodes:
                    continue
                    
                # The "Predicted" state is simply the *current* mathematically evolved state of the previous observation
                evolved_prev_vector = graph_instance.nodes[safe_prev]
                
                # The "Reality" is the fresh static embedding of the new observation
                ground_truth_vector = text_to_embedding(latest_text)
                
                # Calculate resonance / accuracy (Cosine Similarity)
                cos_sim = torch.nn.functional.cosine_similarity(
                    evolved_prev_vector.unsqueeze(0), 
                    ground_truth_vector.unsqueeze(0)
                ).item()
                
                logger.info(f"[VerticalFarm] Topo-Prediction Accuracy for {stream_name}: {cos_sim:.4f}")
                
                if cos_sim > 0.85: # High predictive alignment
                    reward = economy.mint_reward(
                        peer_identifier="VerticalFarm_Physics",
                        truth_id=prev_node_id,
                        resonance_score=cos_sim,
                        graph_instance=graph_instance
                    )
                    logger.info(f"[VerticalFarm] 🌱 Physics Aligned with Reality! Minted {reward} fertilizer for {prev_node_id}.")
                    
                    # Optional: We could broadcast this success to Ouroboros Coach to brag about it!

def start_ouroboros():
    loop = asyncio.get_event_loop()
    loop.create_task(OuroborosLoop().run_loop())
    loop.create_task(VerticalFarmLoop().run_loop())

