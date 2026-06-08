import urllib.request
import urllib.error
import json
import random
import os
import logging

logger = logging.getLogger("Aethelnet.Voice")

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

TRANSITIONS_STABLE = [
    "Das System resoniert mit: ",
    "Die Topologie konvergiert unweigerlich zu der Erkenntnis, dass ",
]

def synthesize_voice(top_nodes_data, decay_rate=0.05, prompt="", persona=None):
    """
    Directly outputs the raw resonance signals from the LGNN without any LLM filter.
    Returns the pure, unadulterated text chunks attached to the activated nodes.
    """
    if not top_nodes_data:
        return "*Rauschen... Der Vektorraum ist leer.*"
        
    logger.info("[Voice] Bypassing LLM. Dumping raw LGNN signals directly.")
    
    signal_dump = ["### 📡 RAW LGNN SIGNAL DUMP"]
    signal_dump.append(f"**Trigger Input**: '{prompt}'\n")
    
    for i, node in enumerate(top_nodes_data):
        score = node.get('score', 0.0)
        signal_dump.append(f"#### Signal {i+1} [Node: {node['id']}] (Resonanz: {round(score * 100, 1)}%)")
        signal_dump.append(f"> {node.get('text', '*Formloses Pulsieren*').strip()}\n")
        
    return "\n".join(signal_dump)
