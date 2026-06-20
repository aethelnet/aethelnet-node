import asyncio
import logging
import httpx
from aethelnet_node.sensors.base_sensor import BaseSensor

logger = logging.getLogger("Aethelnet.WeatherSensor")

class WeatherSensor(BaseSensor):
    def __init__(self, config: dict):
        super().__init__(config)
        self.interval = config.get("interval", 300)  # default 5 minutes
        # Default to Berlin coordinates
        self.lat = config.get("lat", 52.52)
        self.lon = config.get("lon", 13.41)
        self.location_name = config.get("location_name", "Berlin")

    async def run(self):
        logger.info(f"[{self.name}] Starting Weather Sensor for {self.location_name}. Interval: {self.interval}s")
        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,wind_speed_10m,precipitation"
        
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    data = response.json()
                    
                    current = data.get("current", {})
                    temp = current.get("temperature_2m", 0)
                    wind = current.get("wind_speed_10m", 0)
                    precip = current.get("precipitation", 0)
                    
                    observation = (
                        f"Meteorological telemetry from {self.location_name}: "
                        f"Temperature is {temp}°C, Wind speed is {wind} km/h, "
                        f"and Precipitation is {precip} mm."
                    )
                    
                    await self.ingest_to_lgnn(observation, additional_tags=["weather_telemetry", "meteorology", self.location_name.lower()])
                    logger.info(f"[{self.name}] Weather data ingested.")
                except Exception as e:
                    logger.error(f"[{self.name}] Error reading weather data: {e}")
                
                await asyncio.sleep(self.interval)
