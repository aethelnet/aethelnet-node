import asyncio
import logging
from aethelnet_node.sensor_manager import run_sensors_from_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

if __name__ == "__main__":
    print("Starting Aethelnet Sensor Node...")
    asyncio.run(run_sensors_from_config())
