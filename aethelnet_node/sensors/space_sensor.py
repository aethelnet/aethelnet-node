import asyncio
import logging
import httpx
from aethelnet_node.sensors.base_sensor import BaseSensor

logger = logging.getLogger("Aethelnet.SpaceSensor")

class SpaceSensor(BaseSensor):
    def __init__(self, config: dict):
        super().__init__(config)
        self.interval = config.get("interval", 300)  # default 5 minutes

    async def run(self):
        logger.info(f"[{self.name}] Starting Space Sensor (ISS tracking). Interval: {self.interval}s")
        url = "http://api.open-notify.org/iss-now.json"
        
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    data = response.json()
                    
                    if data.get("message") == "success":
                        pos = data.get("iss_position", {})
                        lat = pos.get("latitude", "0")
                        lon = pos.get("longitude", "0")
                        
                        observation = (
                            f"Orbital telemetry: The International Space Station (ISS) "
                            f"is currently traversing above coordinates Latitude {lat}, Longitude {lon}."
                        )
                        
                        await self.ingest_to_lgnn(observation, additional_tags=["space_telemetry", "orbit", "iss"])
                        logger.info(f"[{self.name}] ISS telemetry ingested.")
                except Exception as e:
                    logger.error(f"[{self.name}] Error reading ISS data: {e}")
                
                await asyncio.sleep(self.interval)
