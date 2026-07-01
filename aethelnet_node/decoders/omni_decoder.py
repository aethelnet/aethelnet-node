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
    def __init__(self, output_dir: str = None):
        if output_dir is None:
            output_dir = os.path.expanduser("~/.aethelnet/ingest_zone/dreams")
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
        import glob
        
        # Auto-Pruning: Keep only the 50 most recent dreams to avoid disk filling
        existing_wavs = sorted(glob.glob(os.path.join(self.output_dir, "omni_dream_*.wav")))
        while len(existing_wavs) > 50:
            try:
                os.remove(existing_wavs.pop(0))
            except:
                break

        energy = np.linalg.norm(dream_vector)
        # Prevent 1-second spam when there is no activity
        if energy < 0.05:
            logger.info("[OmniDecoder] Topology too quiet. Skipping audio generation.")
            return None

        filepath = os.path.join(self.output_dir, f"omni_dream_{int(time.time())}.wav")
        
        # 1. Base Frequency (Ambient Drone, lower pitch: 40-100Hz)
        base_freq = 40.0 + (np.abs(np.mean(dream_vector)) * 60)
        
        # 2. Duration (Minimum 3 seconds, up to 15)
        duration = max(3.0, min(15.0, energy * 5.0))
        num_frames = int(44100 * duration)
        
        # 3. Harmonics based on the first few vector elements
        h1 = np.abs(dream_vector[0]) if len(dream_vector) > 0 else 0.5
        h2 = np.abs(dream_vector[1]) if len(dream_vector) > 1 else 0.5
        h3 = np.abs(dream_vector[2]) if len(dream_vector) > 2 else 0.5
        
        # 4. Tremolo (Wobble) speed based on variance
        variance = np.var(dream_vector)
        tremolo_speed = 0.5 + (variance * 10.0) # Slower, more relaxing wobble
        
        with wave.open(filepath, 'w') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(44100)
            
            # Generate audio buffer
            audio_data = bytearray()
            for i in range(num_frames):
                t = i / 44100.0
                
                # Fade-in and Fade-out envelope (Ambient Swell)
                envelope = 1.0
                if t < 1.0:
                    envelope = t  # 1 second fade in
                elif t > duration - 1.0:
                    envelope = duration - t # 1 second fade out

                # Base sine
                wave_val = np.sin(2.0 * np.pi * base_freq * t)
                # Add harmonics (overtones)
                wave_val += (h1 * 0.5) * np.sin(2.0 * np.pi * (base_freq * 2) * t)
                wave_val += (h2 * 0.25) * np.sin(2.0 * np.pi * (base_freq * 3) * t)
                wave_val += (h3 * 0.125) * np.sin(2.0 * np.pi * (base_freq * 4) * t)
                
                # Apply tremolo (amplitude modulation)
                tremolo = 0.7 + 0.3 * np.sin(2.0 * np.pi * tremolo_speed * t)
                
                # Normalize and apply envelope
                wave_val = (wave_val / 1.875) * tremolo * envelope
                value = int(32767.0 * max(-1.0, min(1.0, wave_val)))
                audio_data.extend(struct.pack('<h', value))
                
            wav_file.writeframes(audio_data)
        return filepath

    def _render_text(self, dream_vector: np.ndarray, nodes: List[Dict[str, Any]]):
        logger.info("[OmniDecoder] Balanced state detected. Rendering topological TEXT...")
        filepath = os.path.join(self.output_dir, f"omni_dream_{int(time.time())}.txt")
        concept_words = [n.get("id", "abstract") for n in nodes[:3]]
        content = f"I am sensing a strong topological resonance between {', '.join(concept_words)}. The physical tension is {np.mean(dream_vector)}."
        with open(filepath, 'w') as f:
            f.write(content)
        return filepath
