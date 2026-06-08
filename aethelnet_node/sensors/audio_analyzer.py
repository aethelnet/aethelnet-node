import os
import asyncio
import logging
import json
import librosa
import numpy as np
from tinytag import TinyTag
from aethelnet_node.sensors.base_sensor import BaseSensor

logger = logging.getLogger("Aethelnet.AudioAnalyzer")

class AudioAnalyzerSensor(BaseSensor):
    def __init__(self, config: dict):
        super().__init__(config)
        self.directory = os.path.expanduser(config.get("directory", "~/Everything_Music"))
        self.visited_file = os.path.join(os.path.dirname(__file__), ".visited_audio.json")
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

    def analyze_audio(self, filepath):
        try:
            # Extract metadata tags
            tag = TinyTag.get(filepath)
            meta_tags = []
            if tag.artist:
                meta_tags.append(f"artist:{tag.artist}")
            if tag.genre:
                meta_tags.append(f"genre:{tag.genre}")
            if tag.year:
                meta_tags.append(f"year:{tag.year}")
            
            # Extract acoustic features
            y, sr = librosa.load(filepath, duration=30.0, mono=True)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            tempo_val = float(tempo[0]) if isinstance(tempo, np.ndarray) else float(tempo)
            
            spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
            brightness = float(np.mean(spectral_centroids))
            
            rms = librosa.feature.rms(y=y)[0]
            energy = float(np.mean(rms))
            
            zcr = librosa.feature.zero_crossing_rate(y)[0]
            percussiveness = float(np.mean(zcr))
            
            energy_desc = "high" if energy > 0.1 else ("medium" if energy > 0.02 else "low")
            bright_desc = "bright and sharp" if brightness > 2500 else ("warm and muddy" if brightness < 1000 else "balanced")
            percussive_desc = "highly percussive/noisy" if percussiveness > 0.08 else "smooth/melodic"
            
            filename = os.path.basename(filepath)
            observation = (
                f"Audio analysis of track '{filename}': "
                f"The track has a tempo of {tempo_val:.1f} BPM. "
                f"Its timbral profile is {bright_desc} (centroid: {brightness:.0f} Hz). "
                f"The texture is {percussive_desc} and the overall energy level is {energy_desc}."
            )
            
            if tag.artist or tag.title:
                observation += f" Metadata claims it is '{tag.title}' by '{tag.artist}'."
                
            return observation, meta_tags
        except Exception as e:
            logger.error(f"Error analyzing {filepath}: {e}")
            return None, []

    async def run(self):
        logger.info(f"[{self.name}] Starting scan of {self.directory}")
        if not os.path.exists(self.directory):
            logger.error(f"[{self.name}] Directory {self.directory} not found.")
            return

        valid_exts = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}
        files_to_process = []
        
        for root, _, files in os.walk(self.directory):
            for f in files:
                if os.path.splitext(f)[1].lower() in valid_exts:
                    full_path = os.path.join(root, f)
                    if full_path not in self.visited:
                        files_to_process.append(full_path)
                        
        logger.info(f"[{self.name}] Found {len(files_to_process)} new tracks.")
        
        for filepath in files_to_process:
            logger.info(f"[{self.name}] Analyzing {os.path.basename(filepath)}...")
            
            # Blocking call in async loop (fine for this prototype node running locally)
            observation, meta_tags = self.analyze_audio(filepath)
            
            if observation:
                logger.info(f"[{self.name}] Extracted features: {observation}")
                meta_tags.append("audio_analysis")
                await self.ingest_to_lgnn(observation, additional_tags=meta_tags)
                self.visited.add(filepath)
                self._save_visited()
                
            await asyncio.sleep(1.0)
