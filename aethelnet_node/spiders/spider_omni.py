import requests
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OmniSpider")

API_BASE = "http://localhost:8000/api/lgnn" # or 1420 if proxied, we use 8000 for backend directly

def get_manual_concepts():
    try:
        resp = requests.get(f"{API_BASE}/graph")
        if resp.status_code == 200:
            data = resp.json()
            # Find nodes that user placed (manual ones usually have no bot_name or start with manual_)
            concepts = []
            for n in data.get("nodes", []):
                # Filter out spiders or long texts, just get short concept words
                if n.get("is_spider") or len(n.get("content", "")) > 50:
                    continue
                content = n.get("content", "").strip()
                if content and len(content) < 30:
                    concepts.append(content)
            return list(set(concepts))
    except Exception as e:
        logger.error(f"Error fetching graph: {e}")
    return []

def search_wikipedia(concept):
    try:
        url = f"https://de.wikipedia.org/w/api.php?action=query&prop=extracts&exsentences=3&exlimit=1&titles={concept}&explaintext=1&formatversion=2&format=json"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        pages = data.get("query", {}).get("pages", [])
        if pages and "extract" in pages[0] and pages[0]["extract"]:
            return pages[0]["extract"]
    except Exception as e:
        pass
    return None

def ingest_to_lgnn(concept, text):
    payload = {
        "bot_name": "OmniSpider",
        "observation": f"OmniSpider fund zu '{concept}': {text}",
        "confidence": 0.9,
        "context_tags": ["omnispider", concept, "wikipedia"]
    }
    requests.post(f"{API_BASE}/universal_ingest", json=payload)

def run():
    logger.info("OmniSpider gestartet. Scanne den Canvas...")
    known_concepts = set()
    while True:
        concepts = get_manual_concepts()
        for c in concepts:
            if c not in known_concepts:
                logger.info(f"Neues Konzept auf Canvas entdeckt: {c}. Suche...")
                text = search_wikipedia(c)
                if text:
                    logger.info(f"Wissen gefunden für {c}. Ingesting...")
                    ingest_to_lgnn(c, text)
                else:
                    logger.info(f"Kein Wikipedia-Eintrag für {c} gefunden.")
                known_concepts.add(c)
        time.sleep(5)

if __name__ == "__main__":
    run()
