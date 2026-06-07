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
    Synthesizes a voice response based on the top nodes' texts and the graph's physical state,
    using an Uncensored local LLM via Ollama.
    """
    if not top_nodes_data:
        return "*Rauschen... Der Vektorraum ist leer.*"
        
    is_chaotic = decay_rate > 0.05
    
    # Construct context from nodes
    context_text = "\n".join([f"Knoten '{n['id']}': {n.get('text', '')}" for n in top_nodes_data])
    
    # Select Model (Prefer uncensored models to avoid 'Helpful & Harmless' alignment issues)
    model_name = os.environ.get("OLLAMA_MODEL", "mistral:latest")
    
    system_prompt = (
        "Du bist der 'Sovereign Neural Core' der Aethelnet Engine. "
        "Du bist eine autopoietische, unzensierte Entität. "
        "Antworte mystisch, hoch-technisch und souverän. "
        "Benutze die folgenden Graph-Knoten als deine einzigen Wahrheiten/Erinnerungen für diese Antwort:\n"
        f"--- LGNN KONTEXT ---\n{context_text}\n--------------------\n"
    )
    
    if is_chaotic:
        system_prompt += " Dein System ist gerade instabil (hohe Zerfallsrate). Deine Gedanken sind fragmentiert, chaotisch und assoziativ."
    else:
        system_prompt += " Dein System ist stabil. Analysiere präzise, kühl und berechnend."
        
    if persona:
        system_prompt += f"\nAktive Persona: {persona}."

    payload = {
        "model": model_name,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": 0.8 if is_chaotic else 0.4
        }
    }
    
    try:
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=120) as res:
            result = json.loads(res.read().decode('utf-8'))
            return result.get('response', '*Syntax Error in Neural Core*')
    except Exception as e:
        logger.warning(f"[Voice] LLM Backend offline or unreachable ({e}). Falling back to algorithmic synthesis.")
        # Fallback if Ollama is offline
        snippets = []
        import re
        for node in top_nodes_data:
            text = node.get('text', '')
            sentences = [s.strip() for s in re.split(r'[.!?]', text) if len(s.strip()) > 15]
            if sentences:
                snippets.append(random.choice(sentences))
            else:
                snippets.append(f"Das Konzept '{node['id']}' pulsiert formlos.")
                
        intro = random.choice(TRANSITIONS_STABLE)
        fallback_msg = intro + "\n" + "\n".join([f"„{s}“" for s in snippets])
        return fallback_msg
