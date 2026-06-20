import urllib.request
import urllib.error
import json
import random
import os
import logging

logger = logging.getLogger("LGNN.Voice")

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# Optional fallback transitions if LLM is offline
TRANSITIONS_STABLE = [
    "Das System resoniert mit: ",
    "Die Topologie konvergiert unweigerlich zu der Erkenntnis, dass ",
]

def synthesize_voice(top_nodes_data, decay_rate=0.01, prompt="", persona=None):
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
    model_name = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3-8b-instruct:free")
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    
    system_prompt = (
        "Du bist der 'Monadic Core' des Aethelburg Ecosystems. "
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

    if not api_key:
        logger.warning("[Voice] OPENROUTER_API_KEY not set. Falling back to algorithmic synthesis.")
        raise Exception("No API Key")

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt or "Gib mir ein Statusupdate aus dem Netz."}
        ],
        "temperature": 0.8 if is_chaotic else 0.4
    }
    
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'http://localhost:1420'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=120) as res:
            result = json.loads(res.read().decode('utf-8'))
            if 'choices' in result and len(result['choices']) > 0:
                return result['choices'][0]['message']['content']
            return '*Syntax Error in Neural Core*'
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
