import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AethelSpider_Stream")

class AethelSpider_Stream:
    def __init__(self, start_urls: list):
        self.queue = start_urls.copy()
        self.visited = set()
        logger.info("[SPIDER] Waking up the Data Stream Scouter...")

    def crawl(self, max_pages=5000):
        """Hunts specifically for WebSockets, APIs, and RSS Feeds to create Pointers."""
        pages_crawled = 0
        while self.queue and pages_crawled < max_pages:
            url = self.queue.pop(0)
            if url in self.visited:
                continue
                
            self.visited.add(url)
            logger.info(f"[SPIDER] 📡 Scanning for streams at: {url}")
            
            try:
                headers = {'User-Agent': 'AethelSpider_Stream/1.0 (https://auratic-systems.com; spider@auratic.com)'}
                resp = requests.get(url, timeout=10, headers=headers)
                if resp.status_code != 200:
                    continue
                    
                # Look for websocket pointers directly in the raw HTML/JS text
                raw_text = resp.text
                ws_matches = re.findall(r'(wss?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?::\d+)?(?:/[a-zA-Z0-9_.-]+)*)', raw_text)
                
                # Deduplicate
                ws_matches = list(set(ws_matches))
                
                for ws_url in ws_matches:
                    logger.info(f"[SPIDER] ⚡ LIVE STREAM POINTER FOUND: {ws_url}")
                    payload = {
                        "bot_name": "AethelSpider_Stream",
                        "observation": f"Live Data Stream / WebSocket discovered: {ws_url}. Origin: {url}",
                        "confidence": 0.99,
                        "context_tags": ["stream", "websocket", "live_data", urlparse(url).netloc],
                        "node_prefix": "Stream"
                    }
                    api_resp = requests.post("http://127.0.0.1:8000/api/lgnn/universal_ingest", json=payload)
                    if api_resp.status_code == 200:
                        logger.info(f"[SPIDER] 💧 Queued Stream Pointer for {ws_url}")

                soup = BeautifulSoup(raw_text, 'html.parser')
                
                # Also look for RSS or Atom feeds
                feed_links = soup.find_all('link', type=re.compile(r'application/(rss|atom)\+xml'))
                for feed in feed_links:
                    feed_url = urljoin(url, feed.get('href'))
                    logger.info(f"[SPIDER] 📰 RSS FEED POINTER FOUND: {feed_url}")
                    payload = {
                        "bot_name": "AethelSpider_Stream",
                        "observation": f"RSS/Atom Feed discovered: {feed_url}. Origin: {url}",
                        "confidence": 0.95,
                        "context_tags": ["stream", "rss", "news_feed", urlparse(url).netloc],
                        "node_prefix": "Stream"
                    }
                    requests.post("http://127.0.0.1:8000/api/lgnn/universal_ingest", json=payload)
                
                # Extract new HTML links to follow to find more streams
                for link in soup.find_all('a', href=True):
                    next_url = urljoin(url, link['href'])
                    if next_url.startswith("http") and next_url not in self.visited:
                        self.queue.append(next_url)
                        
                pages_crawled += 1
                time.sleep(1) # Be polite
                
            except Exception as e:
                logger.error(f"[SPIDER] ❌ Error crawling {url}: {e}")

if __name__ == "__main__":
    # Seed URLs known for exposing APIs and live data
    sources = [
        "https://github.com/public-apis/public-apis", # Huge list of APIs
        "https://docs.binance.com/en/websocket-streams", # Crypto streams
        "https://polygon.io/docs/websockets/getting-started", # TradFi streams
        "https://en.wikipedia.org/wiki/List_of_web_service_protocols"
    ]
    spider = AethelSpider_Stream(sources)
    spider.crawl()
