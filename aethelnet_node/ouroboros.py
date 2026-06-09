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

    async def query_mistral_coach(self, dream_concepts):
        """Asks Mistral to critique the LGNN's current abstract thought."""
        prompt = f"""You are the semantic Coach for a Liquid Graph Neural Network (LGNN).
The LGNN does not speak human language; it only feels topological physics.
Right now, the LGNN is forming a highly resonant 'thought' connecting these abstract concepts:
{', '.join(dream_concepts)}

Your job is to critique this connection. Does it make logical or semantic sense? 
Provide a short, harsh, 2-sentence feedback loop correcting or validating its thought process. 
Your exact words will be physically ingested by the LGNN as new vectors."""

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
                
                # 2. The Coach critiques
                feedback = await self.query_mistral_coach(dream)
                if feedback:
                    # 3. The LGNN eats the critique
                    await self.ingest_feedback(feedback)
            
            # Rest before the next cycle
            await asyncio.sleep(120)

def start_ouroboros():
    loop = asyncio.get_event_loop()
    loop.create_task(OuroborosLoop().run_loop())
