import os
import asyncio
import logging
import json
import numpy as np
from PIL import Image, ImageStat
from aethelnet_node.sensors.base_sensor import BaseSensor

logger = logging.getLogger("Aethelnet.ImageAnalyzer")

class ImageAnalyzerSensor(BaseSensor):
    def __init__(self, config: dict):
        super().__init__(config)
        self.directory = os.path.expanduser(config.get("directory", "~/.aethelnet/ingest_zone"))
        self.visited_file = os.path.join(os.path.dirname(__file__), ".visited_images.json")
        self.visited = self._load_visited()
        
    def _load_visited(self):
        if os.path.exists(self.visited_file):
            try:
                with open(self.visited_file, 'r') as f:
                    return set(json.load(f))
            except:
                return set()
        return set()

    def _save_visited(self):
        with open(self.visited_file, 'w') as f:
            json.dump(list(self.visited), f)

    def analyze_image(self, filepath):
        try:
            with Image.open(filepath) as img:
                img = img.convert('RGB')
                stat = ImageStat.Stat(img)
                
                # Basic visual feature extraction
                brightness = sum(stat.mean) / 3
                contrast = sum(stat.stddev) / 3
                
                # Dominant color approximation
                np_img = np.array(img)
                avg_color_per_row = np.average(np_img, axis=0)
                avg_color = np.average(avg_color_per_row, axis=0)
                r, g, b = avg_color
                
                # Heuristics for description
                brightness_desc = "bright" if brightness > 170 else ("dark" if brightness < 85 else "balanced")
                contrast_desc = "high contrast" if contrast > 60 else "low contrast"
                
                # Check color balance
                if r > g + 20 and r > b + 20: color_bias = "warm/reddish"
                elif b > r + 20 and b > g + 20: color_bias = "cool/bluish"
                elif g > r + 20 and g > b + 20: color_bias = "greenish/natural"
                else: color_bias = "monochrome/neutral"
                
                width, height = img.size
                orientation = "landscape" if width > height else "portrait"
                
                filename = os.path.basename(filepath)
                observation = (
                    f"Visual analysis of image '{filename}': "
                    f"The image is in {orientation} orientation ({width}x{height}). "
                    f"It has a {brightness_desc} and {contrast_desc} aesthetic "
                    f"with a {color_bias} color palette."
                )
                return observation
        except Exception as e:
            logger.error(f"Error analyzing image {filepath}: {e}")
            return None

    async def run(self):
        logger.info(f"[{self.name}] Starting scan of {self.directory}")
        if not os.path.exists(self.directory):
            logger.error(f"[{self.name}] Directory {self.directory} not found.")
            return

        valid_exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
        files_to_process = []
        
        for root, _, files in os.walk(self.directory):
            for f in files:
                if os.path.splitext(f)[1].lower() in valid_exts:
                    full_path = os.path.join(root, f)
                    if full_path not in self.visited:
                        files_to_process.append(full_path)
                        
        logger.info(f"[{self.name}] Found {len(files_to_process)} new images.")
        
        for filepath in files_to_process:
            logger.info(f"[{self.name}] Analyzing {os.path.basename(filepath)}...")
            
            observation = self.analyze_image(filepath)
            
            if observation:
                await self.ingest_to_lgnn(observation, additional_tags=["local_image", "visual_ingest"])
                self.visited.add(filepath)
                self._save_visited()
                
            await asyncio.sleep(1.0)
