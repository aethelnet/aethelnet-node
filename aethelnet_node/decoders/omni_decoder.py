import logging
import os
import time
import numpy as np
from typing import List, Dict, Any

logger = logging.getLogger("LGNN.OmniDecoder")

class UniversalOmniDecoder:
    """
    The 'Salatsauce' for output. One single decoder that reads the LGNN Dream Vector
    and organically decides which physical format (Image, Audio, or Text) best 
    represents the current topology.
    """
    def __init__(self, output_dir: str = "/home/nikahrlyn/.aethelnet/ingest_zone/dreams"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def decode(self, persona_nodes: List[Dict[str, Any]], resonance_matrix: np.ndarray):
        """
        Calculates the Dream Vector and routes it to the correct format generator.
        """
        logger.info("[OmniDecoder] Scanning topological heat...")
        
        dream_vector = self._calculate_dream_vector(persona_nodes, resonance_matrix)
        
        # Determine format based on vector properties
        # For example, variance -> Image, high frequency -> Audio, low variance -> Text
        variance = np.var(dream_vector)
        mean_val = np.mean(dream_vector)
        
        if variance > 0.5:
            return self._render_image(dream_vector, persona_nodes)
        elif mean_val < 0.2:
            return self._render_audio(dream_vector)
        else:
            return self._render_text(dream_vector, persona_nodes)

    def _calculate_dream_vector(self, nodes: List[Dict[str, Any]], resonance: np.ndarray) -> np.ndarray:
        dimensions = len(nodes[0].get("vector", np.zeros(512))) if nodes else 512
        dream = np.zeros(dimensions)
        for i, node in enumerate(nodes):
            weight = resonance[i] if i < len(resonance) else 1.0
            dream += np.array(node.get("vector", np.zeros(dimensions))) * weight
        return dream / (np.linalg.norm(dream) + 1e-9)

    def _render_image(self, dream_vector: np.ndarray, nodes: List[Dict[str, Any]]):
        logger.info("[OmniDecoder] High variance detected. Rendering topological IMAGE...")
        from PIL import Image
        norm = np.linalg.norm(dream_vector)
        img = Image.new('RGB', (512, 512), color=(int(norm*255)%255, 100, 150))
        filepath = os.path.join(self.output_dir, f"omni_dream_{int(time.time())}.png")
        img.save(filepath)
        return filepath

    def _render_audio(self, dream_vector: np.ndarray):
        logger.info("[OmniDecoder] Low mean detected. Rendering topological AUDIO...")
        import wave
        import struct
        filepath = os.path.join(self.output_dir, f"omni_dream_{int(time.time())}.wav")
        # Generate simple sine wave based on vector
        freq = 440.0 + (np.mean(dream_vector) * 1000)
        with wave.open(filepath, 'w') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(44100)
            for i in range(44100):
                value = int(32767.0 * np.sin(2.0 * np.pi * freq * i / 44100.0))
                wav_file.writeframes(struct.pack('<h', value))
        return filepath

    def _render_text(self, dream_vector: np.ndarray, nodes: List[Dict[str, Any]]):
        logger.info("[OmniDecoder] Balanced state detected. Rendering topological TEXT...")
        filepath = os.path.join(self.output_dir, f"omni_dream_{int(time.time())}.txt")
        concept_words = [n.get("id", "abstract") for n in nodes[:3]]
        content = f"I am sensing a strong topological resonance between {', '.join(concept_words)}. The physical tension is {np.mean(dream_vector)}."
        with open(filepath, 'w') as f:
            f.write(content)
        return filepath
