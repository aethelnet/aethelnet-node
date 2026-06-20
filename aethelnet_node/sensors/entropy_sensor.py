import asyncio
import logging
import time
import os
import math
from aethelnet_node.sensors.base_sensor import BaseSensor

logger = logging.getLogger("Aethelnet.EntropySensor")

class EntropySensor(BaseSensor):
    def __init__(self, config: dict):
        super().__init__(config)
        self.interval = config.get("interval", 180)  # default 3 minutes

    def _get_shannon_entropy(self, data: bytes) -> float:
        if not data:
            return 0.0
        entropy = 0
        for x in range(256):
            p_x = float(data.count(x))/len(data)
            if p_x > 0:
                entropy += - p_x*math.log(p_x, 2)
        return entropy

    async def run(self):
        logger.info(f"[{self.name}] Starting Entropy Sensor. Interval: {self.interval}s")
        
        while True:
            try:
                # Read 1024 bytes of true randomness from the OS
                raw_entropy = os.urandom(1024)
                shannon_val = self._get_shannon_entropy(raw_entropy)
                
                # Check system load average
                load1, load5, load15 = 0.0, 0.0, 0.0
                try:
                    with open("/proc/loadavg", "r") as f:
                        parts = f.read().split()
                        load1, load5, load15 = float(parts[0]), float(parts[1]), float(parts[2])
                except Exception:
                    pass

                state_desc = "calm and structured"
                if shannon_val > 7.99:
                    state_desc = "highly chaotic"
                
                observation = (
                    f"Quantum/System Entropy Telemetry: "
                    f"Measured local entropy density is {shannon_val:.4f} bits/byte ({state_desc}). "
                    f"1-min systemic load pressure is {load1:.2f}."
                )
                
                await self.ingest_to_lgnn(observation, additional_tags=["entropy", "chaos", "systemic_pressure"])
                logger.info(f"[{self.name}] Entropy data ingested.")
            except Exception as e:
                logger.error(f"[{self.name}] Error reading entropy data: {e}")
            
            await asyncio.sleep(self.interval)
