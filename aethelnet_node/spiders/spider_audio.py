import os
import time
import json
import logging
import asyncio
import httpx
import librosa
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("AudioSpider")

TARGET_URL = "http://141.147.20.191:8000/api/lgnn/universal_ingest"
MUSIC_DIR = os.path.expanduser("~/Everything_Music")
VISITED_FILE = os.path.join(os.path.dirname(__file__), ".visited_audio.json")

def load_visited():
    if os.path.exists(VISITED_FILE):
        try:
            with open(VISITED_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_visited(visited):
    with open(VISITED_FILE, 'w') as f:
        json.dump(list(visited), f)

def analyze_audio(filepath):
    try:
        # Load audio (limit duration to speed up)
        y, sr = librosa.load(filepath, duration=30.0, mono=True)
        
        # Extract features
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo_val = float(tempo[0]) if isinstance(tempo, np.ndarray) else float(tempo)
        
        spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        brightness = float(np.mean(spectral_centroids))
        
        rms = librosa.feature.rms(y=y)[0]
        energy = float(np.mean(rms))
        
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        percussiveness = float(np.mean(zcr))
        
        # Classify roughly
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
        return observation
    except Exception as e:
        logger.error(f"Error analyzing {filepath}: {e}")
        return None

async def crawl_audio():
    visited = load_visited()
    logger.info(f"Loaded {len(visited)} visited tracks.")
    
    if not os.path.exists(MUSIC_DIR):
        logger.error(f"Directory {MUSIC_DIR} not found.")
        return

    # Find audio files
    valid_exts = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}
    files_to_process = []
    
    for root, _, files in os.walk(MUSIC_DIR):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in valid_exts:
                full_path = os.path.join(root, f)
                if full_path not in visited:
                    files_to_process.append(full_path)
                    
    logger.info(f"Found {len(files_to_process)} new audio files to process.")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for filepath in files_to_process:
            logger.info(f"Analyzing {os.path.basename(filepath)}...")
            
            # Analyze synchronously (could be offloaded to thread pool, but fine for sequential)
            observation = analyze_audio(filepath)
            
            if observation:
                logger.info(f"Extracted features: {observation}")
                
                payload = {
                    "bot_name": "AudioSpider",
                    "observation": observation,
                    "confidence": 0.85,
                    "context_tags": ["audio", "music_analysis", "local_library"]
                }
                
                try:
                    resp = await client.post(TARGET_URL, json=payload)
                    if resp.status_code == 200:
                        logger.info("Successfully ingested into LGNN.")
                        visited.add(filepath)
                        save_visited(visited)
                    else:
                        logger.error(f"Node rejected data: {resp.text}")
                except httpx.RequestError as e:
                    logger.error(f"Connection failed: {e}")
                    
            await asyncio.sleep(1.0)

if __name__ == "__main__":
    asyncio.run(crawl_audio())
