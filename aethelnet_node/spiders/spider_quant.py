import os
import time
import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin, urlparse



logger = logging.getLogger("Aethelnet.Spider")
logging.basicConfig(level=logging.INFO)

class AethelSpider:
    def __init__(self, start_urls: list):
        self.queue = start_urls.copy()
        self.visited = set()
        logger.info("[SPIDER] Waking up the lightweight Web Spider...")
        logger.info("[SPIDER] Transformer removed. Backend will handle embedding.")

    def crawl(self, max_pages=5):
        """Crawls pages, encodes them, and sends them to the local Aethelnet API."""
        import requests

        pages_crawled = 0
        while self.queue and pages_crawled < max_pages:
            url = self.queue.pop(0)
            if url in self.visited:
                continue
                
            self.visited.add(url)
            logger.info(f"[SPIDER] 🕸️ Spinning web at: {url}")
            
            try:
                headers = {'User-Agent': 'AethelSpider/1.0 (https://auratic-systems.com; spider@auratic.com)'}
                resp = requests.get(url, timeout=10, headers=headers)
                if resp.status_code != 200:
                    continue
                    
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Extract text
                paragraphs = soup.find_all('p')
                text_content = " ".join([p.get_text() for p in paragraphs])
                
                # We only want substantive pages
                if len(text_content.split()) < 50:
                    logger.info(f"[SPIDER] 🗑️ Too short, dropping: {url}")
                    continue
                    
                logger.info(f"[SPIDER] 🧠 Encoding {len(text_content.split())} words into 768-D Vector...")
                # Backend handles embedding! We just send the raw text.
                
                payload = {
                    "bot_name": "AethelSpider_Quant",
                    "observation": text_content,
                    "confidence": 0.90,
                    "context_tags": ["spider", "quant_finance", "arxiv", urlparse(url).netloc]
                }
                api_resp = requests.post("http://127.0.0.1:8000/api/lgnn/universal_ingest", json=payload)
                
                if api_resp.status_code == 200:
                    logger.info(f"[SPIDER] 💧 Queued '{url}' via Async Hygiene Protocol!")
                else:
                    logger.error(f"[SPIDER] ❌ API rejected data: {api_resp.text}")
                
                # Extract new links to follow (The Pheromone Trail)
                for link in soup.find_all('a', href=True):
                    next_url = urljoin(url, link['href'])
                    # Simple heuristic: only follow HTTP links (no mailto, javascript)
                    if next_url.startswith("http") and next_url not in self.visited:
                        self.queue.append(next_url)
                        
                pages_crawled += 1
                time.sleep(1) # Be polite to servers
                
            except Exception as e:
                logger.error(f"[SPIDER] ❌ Error crawling {url}: {e}")

if __name__ == "__main__":
    # Quant Trading Run - The Holy Grails
    sources = [
        "https://arxiv.org/list/q-fin/recent",          # Cutting edge quant finance papers
        "https://www.investopedia.com/terms/q/quantitative-trading.asp", # The Wikipedia of Finance
        "https://www.quantstart.com/articles/",         # Top tier algorithmic trading tutorials
        "https://academy.binance.com/en/articles",      # Crypto specific market dynamics and AMMs
        "https://papers.ssrn.com/sol3/JELJOUR_Results.cfm?form_name=journalbrowse&journal_id=1504392", # SSRN Financial Economics
        "https://finance.yahoo.com/news/",              # TradFi & Global Macro News
        "https://tradingeconomics.com/articles",        # Global Macro Economic Indicators
        "https://www.kitco.com/news/"                   # Gold, Silver & Commodities (TradFi anchors)
    ]
    spider = AethelSpider(sources)
    spider.crawl(max_pages=5000)
