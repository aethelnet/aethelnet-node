import os
import re
import time
import json
import logging
import asyncio
import httpx
from typing import Dict, Any, Optional, List

from aethelnet_node.database import (
    init_db, get_node_text, save_synthesis, get_synthesis_by_id,
    get_syntheses, get_syntheses_for_node, crystallize_synthesis
)
from aethelnet_node.routers.vault import find_vault_root

init_db()

logger = logging.getLogger("Aethelnet.Node.Synthesis")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:latest")

class SynthesisEngine:
    """
    Translates mathematical Hebbian resonance into actionable cognitive markdown.
    When the continuous LGNN discovers a high-resonance bridge between two concepts,
    this engine queries the local LLM to synthesize the connection into Obsidian.
    """
    def __init__(self, ollama_url: str = OLLAMA_URL, model: str = OLLAMA_MODEL):
        self.ollama_url = ollama_url
        self.model = model
        self.is_synthesizing = False
        self._lock = asyncio.Lock()

    async def synthesize_pair(self, node_a: str, node_b: str, resonance: float) -> Optional[Dict[str, Any]]:
        """
        Executes a neurosymbolic synthesis between two resonant concepts.
        """
        synth_id = f"SYN_{min(node_a, node_b)}_AND_{max(node_a, node_b)}"
        
        # Check if already synthesized
        existing = get_synthesis_by_id(synth_id)
        if existing:
            logger.debug(f"[Synthesis] Synthesis already exists for {node_a} <-> {node_b}")
            return existing

        async with self._lock:
            # Double check after acquiring lock
            existing = get_synthesis_by_id(synth_id)
            if existing:
                return existing

            self.is_synthesizing = True
            try:
                text_a = get_node_text(node_a) or f"Concept node representing [{node_a}]."
                text_b = get_node_text(node_b) or f"Concept node representing [{node_b}]."

                # Keep excerpts compact for swift CPU inference
                clean_a = text_a.split("---", 2)[-1].strip()[:500]
                clean_b = text_b.split("---", 2)[-1].strip()[:500]

                logger.info(f"[Synthesis] Triggering LLM synthesis for bridge: {node_a} <-> {node_b} (Resonance: {resonance:.3f})")

                prompt = (
                    f"Du bist der autonome kognitive Synthesizer von Unit 734.\n"
                    f"Ein kontinuierliches neuronales Graphnetzwerk (LGNN ODE) hat eine hohe Hebbsche Resonanz ({resonance:.3f}) "
                    f"zwischen zwei Konzepten im Knowledge Graph entdeckt:\n\n"
                    f"KONZEPT A: [[{node_a}]]\n{clean_a}\n\n"
                    f"KONZEPT B: [[{node_b}]]\n{clean_b}\n\n"
                    f"AUFGABE:\n"
                    f"Synthetisiere das emergente Bindeglied zwischen Konzept A und B auf Deutsch, präzise und ohne Floskeln:\n\n"
                    f"## 1. Das emergente Bindeglied\n"
                    f"[2-3 Sätze zur funktionalen Schnittmenge beider Konzepte]\n\n"
                    f"## 2. Kausale Implikation\n"
                    f"[1-2 Sätze zur konkreten architektonischen Konsequenz]\n\n"
                    f"## 3. Offene Hypothese / Aktionspunkt\n"
                    f"- [ ] [Konkrete Hypothese für den Operator]\n"
                )

                synthesis_text = await self._query_llm(prompt)

                if not synthesis_text:
                    synthesis_text = (
                        f"## 1. Das emergente Bindeglied\n"
                        f"Das neuronale Substrat hat eine mathematische Ko-Resonanz von {resonance:.3f} zwischen [[{node_a}]] und [[{node_b}]] gemessen.\n\n"
                        f"## 2. Kausale Implikation\n"
                        f"Die Aktivierungsvektoren beider Konzepte streben im Phasenraum aufeinander zu und deuten auf eine funktionale Abhängigkeit hin.\n\n"
                        f"## 3. Offene Hypothese / Aktionspunkt\n"
                        f"- [ ] Überprüfe die semantische Kopplung zwischen [[{node_a}]] und [[{node_b}]] im Observer.\n"
                    )

                # Format full Markdown Document
                title = f"Synaptische Synthese: [[{node_a}]] // [[{node_b}]]"
                doc_content = (
                    f"---\n"
                    f"type: synaptic_synthesis\n"
                    f"sources:\n"
                    f"  - \"{node_a}\"\n"
                    f"  - \"{node_b}\"\n"
                    f"resonance_score: {round(resonance, 4)}\n"
                    f"created_at: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
                    f"is_crystallized: false\n"
                    f"---\n\n"
                    f"# {title}\n\n"
                    f"> **Topologische Hebbsche Resonanz:** `{resonance:.4f}`  \n"
                    f"> **Entdeckt von:** Unit 734 Unified Hebbian Cognitive Core  \n\n"
                    f"{synthesis_text}\n"
                )

                # Persist to physical Obsidian Vault
                vault_root = find_vault_root()
                vault_rel_path = ""
                if vault_root:
                    synth_dir = os.path.join(vault_root, "03_MEMORY_BANK", "SYNTHESES")
                    os.makedirs(synth_dir, exist_ok=True)
                    safe_filename = f"{synth_id}.md"
                    target_path = os.path.join(synth_dir, safe_filename)
                    with open(target_path, "w", encoding="utf-8") as fh:
                        fh.write(doc_content)
                    vault_rel_path = os.path.relpath(target_path, vault_root)
                    logger.info(f"[Synthesis] Saved physical note to {target_path}")

                # Persist to SQLite
                save_synthesis(
                    synth_id=synth_id,
                    source_a=node_a,
                    source_b=node_b,
                    resonance=resonance,
                    title=title,
                    content=doc_content,
                    vault_path=vault_rel_path,
                    is_crystallized=0
                )

                result_payload = {
                    "id": synth_id,
                    "source_a": node_a,
                    "source_b": node_b,
                    "resonance": resonance,
                    "title": title,
                    "content": doc_content,
                    "vault_path": vault_rel_path,
                    "created_at": time.time()
                }

                logger.info(f"[Synthesis] Successfully created insight '{synth_id}'")
                return result_payload

            except Exception as e:
                logger.error(f"[Synthesis] Error synthesizing {node_a} <-> {node_b}: {e}", exc_info=True)
                return None
            finally:
                self.is_synthesizing = False

    async def _query_llm(self, prompt: str) -> Optional[str]:
        """
        Sends prompt to local Ollama with timeout and error handling.
        """
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                res = await client.post(
                    self.ollama_url,
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.2,
                            "top_p": 0.9,
                            "num_predict": 300
                        }
                    }
                )
                if res.status_code == 200:
                    data = res.json()
                    return data.get("response", "").strip()
                else:
                    logger.warn(f"[Synthesis LLM] Ollama returned status {res.status_code}: {res.text}")
                    return None
        except Exception as e:
            logger.warn(f"[Synthesis LLM] Failed to query Ollama ({e}). Using heuristic fallback.")
            return None

# Global Singleton
synthesis_engine = SynthesisEngine()
