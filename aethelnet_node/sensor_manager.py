import os
import yaml
import logging
import asyncio
try:
    from aethelnet_node.sensors.web_spider import WebSpiderSensor
    from aethelnet_node.sensors.audio_analyzer import AudioAnalyzerSensor
    from aethelnet_node.sensors.document_reader import DocumentReaderSensor
    from aethelnet_node.sensors.image_analyzer import ImageAnalyzerSensor
    from aethelnet_node.sensors.universal_document_reader import UniversalDocumentSensor
    from aethelnet_node.sensors.vitals_sensor import VitalsSensor
    SENSORS_AVAILABLE = True
except ImportError as e:
    import logging
    logging.warning(f"Some sensor dependencies are missing. Sensors disabled: {e}")
    SENSORS_AVAILABLE = False

logger = logging.getLogger("Aethelnet.SensorManager")

if SENSORS_AVAILABLE:
    SENSOR_REGISTRY = {
        "web_spider": WebSpiderSensor,
        "audio_analyzer": AudioAnalyzerSensor,
        "document_reader": DocumentReaderSensor,
        "image_analyzer": ImageAnalyzerSensor,
        "universal_document_reader": UniversalDocumentSensor,
        "vitals_sensor": VitalsSensor
    }
else:
    SENSOR_REGISTRY = {}

async def run_sensors_from_config():
    """Reads sensors.yaml and starts all configured sensors asynchronously."""
    await asyncio.sleep(5)  # Let node fully boot
    
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins", "sensors.yaml")
    if not os.path.exists(config_path):
        logger.info(f"[SensorManager] No plugins/sensors.yaml found. Skipping.")
        return
        
    tasks = []
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            configs = yaml.safe_load(f)
            
        if not isinstance(configs, list):
            logger.error("[SensorManager] sensors.yaml must contain a list of sensor configurations.")
            return
            
        for config in configs:
           for sensor_type, cfg in config.get("sensors", {}).items():
            if not SENSORS_AVAILABLE:
                logger.warning(f"Skipping sensor {sensor_type} due to missing dependencies.")
                continue
            if sensor_type in SENSOR_REGISTRY:
                sensor_class = SENSOR_REGISTRY[sensor_type]
                sensor_instance = sensor_class(config)
                tasks.append(asyncio.create_task(sensor_instance.run()))
            else:
                logger.error(f"[SensorManager] Unknown sensor type: {sensor_type}")
                
    except Exception as e:
        logger.error(f"[SensorManager] Failed to load sensors: {e}")
                
    if tasks:
        logger.info(f"[SensorManager] Launched {len(tasks)} configured sensors in the background.")
        await asyncio.gather(*tasks, return_exceptions=True)
