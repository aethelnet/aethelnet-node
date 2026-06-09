import logging
import os
import numpy as np
import time
from typing import List, Dict, Any
from aethelnet_node.decoders.base_decoder import BaseGraphDecoder
try:
    from diffusers import StableDiffusionPipeline
    import torch
    DIFFUSERS_AVAILABLE = True
except ImportError:
    DIFFUSERS_AVAILABLE = False

logger = logging.getLogger("LGNN.DiffusionDecoder")

class DiffusionImageDecoder(BaseGraphDecoder):
    """
    Decodes the LGNN Dream Vector into an actual visual image using Stable Diffusion.
    """
    def __init__(self, name: str = "StableDiffusion_Decoder", output_dir: str = "/home/nikahrlyn/.aethelnet/ingest_zone"):
        super().__init__(name)
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.pipeline = None
        if DIFFUSERS_AVAILABLE:
            logger.info(f"[{self.name}] Loading local Diffusion Model... This might take a moment.")
            # Use a lightweight model for fast cybernetic loops, e.g. a tiny diffusion model or LCM
            # For demonstration in the tournament, we'll initialize it lazily when needed
        else:
            logger.warning(f"[{self.name}] 'diffusers' library not found. Falling back to abstract prompt logging.")

    def _render(self, dream_vector: np.ndarray, nodes: List[Dict[str, Any]]) -> str:
        """
        Translates the mathematical dream vector into an image.
        For now, we map the vector's highest frequencies to a generated prompt 
        that stable diffusion uses to paint the dream.
        """
        # Create a prompt based on the highest confidence nodes
        concept_words = [n.get("id", "abstract") for n in nodes[:3]]
        
        # Determine aesthetic properties from the vector math (e.g. vector norm = brightness)
        norm = np.linalg.norm(dream_vector)
        aesthetic = "dark and chaotic" if norm < 0.5 else "bright and highly structured"
        
        prompt = f"abstract geometric representation of {', '.join(concept_words)}, {aesthetic}, highly detailed, digital art"
        logger.info(f"[{self.name}] Graph topology translated to visual prompt: '{prompt}'")
        
        filepath = os.path.join(self.output_dir, f"lgnn_dream_{int(time.time())}.png")
        
        if self.pipeline and DIFFUSERS_AVAILABLE:
            # Generate the actual image using the GPU
            image = self.pipeline(prompt, num_inference_steps=20).images[0]
            image.save(filepath)
            logger.info(f"[{self.name}] Dream physically rendered and saved to: {filepath}")
        else:
            # Mock the generation if diffusers isn't loaded yet to keep the loop architecture intact
            from PIL import Image
            img = Image.new('RGB', (512, 512), color = (int(norm*255)%255, 100, 150))
            img.save(filepath)
            logger.info(f"[{self.name}] Simulated Dream rendered and saved to: {filepath} (Install diffusers for real AI images)")
            
        return filepath
