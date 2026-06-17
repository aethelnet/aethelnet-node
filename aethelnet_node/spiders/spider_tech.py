import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AethelSpider_Tech")

class AethelSpider_Tech:
    def __init__(self, start_urls: list):
        self.queue = start_urls.copy()
        self.visited = set()
        logger.info("[SPIDER] Waking up the Cyber/Tech Spider...")

    def crawl(self, max_pages=5):
        """Crawls pages, encodes them, and sends them to the local Aethelnet API."""
        pages_crawled = 0
        while self.queue and pages_crawled < max_pages:
            url = self.queue.pop(0)
            if url in self.visited:
                continue
                
            self.visited.add(url)
            logger.info(f"[SPIDER] 🕸️ Spinning web at: {url}")
            
            try:
                headers = {'User-Agent': 'AethelSpider_Tech/1.0 (https://auratic-systems.com; spider@auratic.com)'}
                resp = requests.get(url, timeout=10, headers=headers)
                if resp.status_code != 200:
                    continue
                    
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Extract text
                paragraphs = soup.find_all('p')
                text_content = " ".join([p.get_text() for p in paragraphs])
                
                # We only want substantive pages
                if len(text_content.split()) < 50:
                    continue
                    
                logger.info(f"[SPIDER] 🧠 Sending {len(text_content.split())} words to Local Node...")
                
                payload = {
                    "bot_name": "AethelSpider_Tech",
                    "observation": text_content,
                    "confidence": 0.95,
                    "context_tags": ["spider", "linux", "open-source", "terminal", "cybernetics", urlparse(url).netloc]
                }
                api_resp = requests.post("http://127.0.0.1:8000/api/lgnn/universal_ingest", json=payload)
                
                if api_resp.status_code == 200:
                    logger.info(f"[SPIDER] 💧 Queued '{url}' via Async Hygiene Protocol!")
                
                # Extract new links to follow
                for link in soup.find_all('a', href=True):
                    next_url = urljoin(url, link['href'])
                    if next_url.startswith("http") and next_url not in self.visited:
                        self.queue.append(next_url)
                        
                pages_crawled += 1
                time.sleep(1) # Be polite
                
            except Exception as e:
                logger.error(f"[SPIDER] ❌ Error crawling {url}: {e}")

if __name__ == "__main__":
    # Tech Node - Linux, Open Source, Hacker Culture
    sources = [
        "https://wiki.archlinux.org/title/Main_page",
        "https://tldp.org/HOWTO/HOWTO-INDEX/categories.html", # The Linux Documentation Project
        "https://docs.fedoraproject.org/en-US/docs/", # Fedora Official Docs
        "https://developers.redhat.com/articles", # Red Hat Developer Articles
        "https://www.kernel.org/doc/html/latest/", # Linux Kernel Official Documentation
        "https://en.wikipedia.org/wiki/Unix_philosophy",
        "https://en.wikipedia.org/wiki/Cybernetics"
    ]
    spider = AethelSpider_Tech(sources)
    spider.crawl(max_pages=5000)
