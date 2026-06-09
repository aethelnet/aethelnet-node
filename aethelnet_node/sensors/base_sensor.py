import os
import asyncio
import logging
import httpx

logger = logging.getLogger("Aethelnet.Sensor")

class BaseSensor:
    def __init__(self, config: dict):
        self.name = config.get("name", self.__class__.__name__)
        self.confidence = config.get("confidence", 0.8)
        self.base_tags = config.get("tags", [])
        
    async def run(self):
        """Main loop for the sensor. Must be implemented by subclasses."""
        raise NotImplementedError
        
    async def ingest_to_lgnn(self, observation: str, additional_tags: list = None):
        """Sends extracted data to the LGNN Node API."""
        tags = self.base_tags.copy()
        if additional_tags:
            tags.extend(additional_tags)
            
        payload = {
            "bot_name": self.name,
            "observation": observation,
            "confidence": self.confidence,
            "context_tags": tags
        }
        
        target_url = os.getenv("AETHELNET_NODE_URL", "http://127.0.0.1:8001/api/lgnn/universal_ingest")
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(target_url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"[{self.name}] Successfully ingested observation.")
                else:
                    logger.error(f"[{self.name}] API rejected data: {resp.text}")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to send data to LGNN: {e}")
