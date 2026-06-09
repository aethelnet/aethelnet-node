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
                    
                # Active Process Scan (Strict Opt-In Privacy)
                active_apps = []
                whitelist_path = os.path.expanduser("~/.aethelnet/privacy_whitelist.json")
                target_apps = []
                
                try:
                    if os.path.exists(whitelist_path):
                        import json
                        with open(whitelist_path, "r") as f:
                            target_apps = json.load(f)
                    else:
                        # Create a default template if it doesn't exist, but keep it safe
                        os.makedirs(os.path.dirname(whitelist_path), exist_ok=True)
                        with open(whitelist_path, "w") as f:
                            f.write('[\n  "renoise",\n  "code",\n  "blender",\n  "ableton"\n]\n')
                except Exception:
                    pass

                if target_apps:
                    for proc in psutil.process_iter(['name', 'cpu_percent']):
                        try:
                            name = proc.info['name'].lower()
                            if proc.info['cpu_percent'] > 0.5 and any(app in name for app in target_apps):
                                if name not in active_apps:
                                    active_apps.append(name)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                process_str = f" The user is actively focusing on: {', '.join(active_apps)}." if active_apps else ""

                observation = (
                    f"Hardware Vitals Reading: The system is {stress_level}. "
                    f"CPU Load is at {cpu_percent}%. "
                    f"RAM saturation is at {mem_percent}%. "
                    f"Swap usage is {swap_percent}%. "
                    f"Average core temperature is {temp}.{process_str}"
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
