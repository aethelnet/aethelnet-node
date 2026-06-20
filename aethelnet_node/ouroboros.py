import asyncio
import httpx
import logging
import json
import numpy as np

logger = logging.getLogger("LGNN.Ouroboros")

class OuroborosLoop:
    """
    The cybernetic feedback loop. The LGNN extracts its current 'Dream Vector',
    sends it to the Mistral Coach for semantic critique, and then ingests 
    the Coach's feedback to mutate its own topology.
    """
    def __init__(self, ollama_url="http://localhost:11434/api/generate", lgnn_ingest_url="http://localhost:8001/api/lgnn/universal_ingest"):
        self.ollama_url = ollama_url
        self.lgnn_ingest_url = lgnn_ingest_url

    async def extract_dream_concepts(self):
        """Fetches the current most resonant nodes from the graph."""
        from aethelnet_node.main import node_metrics
        # Get top 5 most confident concepts that aren't gravity/pi
        sorted_nodes = sorted(node_metrics.items(), key=lambda x: x[1].get("confidence", 0.0), reverse=True)
        dream_concepts = []
        for nid, metrics in sorted_nodes:
            if not metrics.get("is_grounded", False):
                dream_concepts.append(nid)
            if len(dream_concepts) >= 5:
                break
        return dream_concepts

    async def query_coach(self, dream_concepts):
        """Asks Gemini (Primary) or Mistral (Fallback) to critique the LGNN's current abstract thought."""
        import os
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.environ.get("GEMINI_API_KEY")
        
        prompt = f"""You are the semantic Coach for a Liquid Graph Neural Network (LGNN).
The LGNN does not speak human language; it only feels topological physics.
Right now, the LGNN is forming a highly resonant 'thought' connecting these abstract concepts:
{', '.join(dream_concepts)}

Your job is to critique this connection. Does it make logical or semantic sense? 
Provide a short, harsh, 2-sentence feedback loop correcting or validating its thought process. 
Your exact words will be physically ingested by the LGNN as new vectors."""

        # Try Gemini First
        if api_key:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key={api_key}"
            gemini_payload = {
                "contents": [{"parts":[{"text": prompt}]}]
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                try:
                    resp = await client.post(gemini_url, json=gemini_payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                        logger.info("[Ouroboros] Gemini Ultra/Pro successfully critiqued the dream.")
                        return text
                    else:
                        logger.warning(f"[Ouroboros] Gemini failed with {resp.status_code}. Falling back to Mistral...")
                except Exception as e:
                    logger.warning(f"[Ouroboros] Gemini connection failed: {e}. Falling back to Mistral...")
        else:
            logger.warning("[Ouroboros] No GEMINI_API_KEY found. Defaulting directly to local Mistral...")

        # Fallback to Mistral (Ollama)
        payload = {
            "model": "mistral",
            "prompt": prompt,
            "stream": False
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.ollama_url, json=payload)
                if response.status_code == 200:
                    return response.json().get("response", "")
            except Exception as e:
                logger.error(f"[Ouroboros] Coach Mistral is unreachable: {e}")
        return None

    async def ingest_feedback(self, feedback_text):
        """Feeds Mistral's critique back into the LGNN's universal ingest."""
        payload = {
            "bot_name": "Ouroboros_Coach",
            "observation": feedback_text,
            "confidence": 0.95, # The coach is highly trusted
            "context_tags": ["ouroboros", "coach_feedback", "semantic_correction"]
        }
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                await client.post(self.lgnn_ingest_url, json=payload)
                logger.info(f"[Ouroboros] Ingested Coach Feedback: {feedback_text[:50]}...")
            except Exception as e:
                logger.error(f"[Ouroboros] Failed to ingest feedback: {e}")

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
                    # Construct node dicts expected by the decoder
                    nodes_data = [{"id": nid, "vector": node_metrics.get(nid, {}).get("vector", np.zeros(768))} for nid in dream]
                    resonance = np.ones(len(nodes_data)) # Simplified resonance for now
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

