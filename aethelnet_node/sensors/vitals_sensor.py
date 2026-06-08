import os
import asyncio
import logging
import psutil
from aethelnet_node.sensors.base_sensor import BaseSensor

logger = logging.getLogger("Aethelnet.VitalsSensor")

class VitalsSensor(BaseSensor):
    def __init__(self, config: dict):
        super().__init__(config)
        self.interval = config.get("interval", 10)  # Seconds between readings
        
    def _get_temperatures(self):
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return "Unknown"
            
            core_temps = []
            for name, entries in temps.items():
                for entry in entries:
                    core_temps.append(entry.current)
            if core_temps:
                avg_temp = sum(core_temps) / len(core_temps)
                return f"{avg_temp:.1f}C"
        except Exception:
            pass
        return "Unknown"

    async def run(self):
        logger.info(f"[{self.name}] Starting hardware vitals monitor. Interval: {self.interval}s")
        
        while True:
            try:
                cpu_percent = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                mem_percent = mem.percent
                swap = psutil.swap_memory()
                swap_percent = swap.percent
                temp = self._get_temperatures()
                
                # Heuristics for the narrative
                stress_level = "relaxed"
                if cpu_percent > 80 or mem_percent > 85:
                    stress_level = "under extreme stress"
                elif cpu_percent > 50 or mem_percent > 70:
                    stress_level = "working heavily"
                    
                observation = (
                    f"Hardware Vitals Reading: The system is {stress_level}. "
                    f"CPU Load is at {cpu_percent}%. "
                    f"RAM saturation is at {mem_percent}%. "
                    f"Swap usage is {swap_percent}%. "
                    f"Average core temperature is {temp}."
                )
                
                # Only ingest if there is significant activity, to avoid spamming the graph
                # or if it's the very first few runs. We'll ingest probabilistically or if stressed.
                if cpu_percent > 20 or mem_percent > 50 or swap_percent > 5:
                    await self.ingest_to_lgnn(observation, additional_tags=["hardware_vitals", "system_telemetry"])
                    logger.info(f"[{self.name}] Vitals spiked. Ingested state.")
                
                await asyncio.sleep(self.interval)
                
            except Exception as e:
                logger.error(f"[{self.name}] Error reading vitals: {e}")
                await asyncio.sleep(self.interval)
