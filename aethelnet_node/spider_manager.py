import os
import time
import yaml
import logging
import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("Aethelnet.SpiderManager")

class ConfiguredSpider:
    def __init__(self, config: dict):
        self.name = config.get("name", "UnknownSpider")
        self.confidence = config.get("confidence", 0.8)
        self.tags = config.get("tags", [])
        self.sources = config.get("sources", [])
        self.priority_keywords = config.get("priority_keywords", [])
        
        self.queue = self.sources.copy()
        self.visited = set()
        
    async def crawl(self, max_pages=5000):
        logger.info(f"[SpiderManager] Starting {self.name} with {len(self.sources)} seed URLs.")
        pages_crawled = 0
        
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            while self.queue and pages_crawled < max_pages:
                url = self.queue.pop(0)
                if url in self.visited:
                    continue
                    
                self.visited.add(url)
                logger.info(f"[{self.name}] 🕸️ Spinning web at: {url}")
                
                try:
                    headers = {'User-Agent': f'{self.name}/1.0 (Aethelnet Node Spider)'}
                    resp = await client.get(url, headers=headers)
                    if resp.status_code != 200:
                        continue
                        
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    
                    # Extract text
                    paragraphs = soup.find_all('p')
                    text_content = " ".join([p.get_text() for p in paragraphs])
                    
                    if len(text_content.split()) < 50:
                        continue
                        
                    logger.info(f"[{self.name}] 🎨 Sending {len(text_content.split())} words to local LGNN...")
                    
                    payload = {
                        "bot_name": self.name,
                        "observation": text_content,
                        "confidence": self.confidence,
                        "context_tags": self.tags + [urlparse(url).netloc]
                    }
                    
                    # We are running inside the node process, so we could theoretically call the functions directly,
                    # but posting to the local API endpoint tests the whole pipeline and is decoupled.
                    try:
                        api_resp = await client.post("http://127.0.0.1:8000/api/lgnn/universal_ingest", json=payload)
                        if api_resp.status_code == 200:
                            logger.info(f"[{self.name}] 💧 Queued '{url}' successfully!")
                        else:
                            logger.error(f"[{self.name}] ❌ API rejected data: {api_resp.text}")
                    except httpx.RequestError as e:
                        logger.error(f"[{self.name}] ❌ Could not connect to local API: {e}")

                    # Extract new links to follow
                    for link in soup.find_all('a', href=True):
                        next_url = urljoin(url, link['href'])
                        if next_url.startswith("http") and next_url not in self.visited:
                            # Prioritize URLs matching keywords
                            if any(kw.lower() in next_url.lower() for kw in self.priority_keywords):
                                self.queue.insert(0, next_url)
                            else:
                                self.queue.append(next_url)
                            
                    pages_crawled += 1
                    await asyncio.sleep(1.5)
                    
                except Exception as e:
                    logger.error(f"[{self.name}] ❌ Error crawling {url}: {e}")

async def run_spiders_from_config():
    """Reads all YAML files from plugins/spiders/ and starts them asynchronously."""
    # Let node fully boot first
    await asyncio.sleep(5)
    
    plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins", "spiders")
    if not os.path.exists(plugins_dir):
        logger.info(f"[SpiderManager] No plugins/spiders/ directory found. Skipping.")
        return
        
    tasks = []
    for filename in os.listdir(plugins_dir):
        if filename.endswith(".yaml") or filename.endswith(".yml"):
            filepath = os.path.join(plugins_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                if config:
                    spider = ConfiguredSpider(config)
                    tasks.append(asyncio.create_task(spider.crawl()))
            except Exception as e:
                logger.error(f"[SpiderManager] Failed to load {filename}: {e}")
                
    if tasks:
        logger.info(f"[SpiderManager] Launched {len(tasks)} configured spiders in the background.")
        await asyncio.gather(*tasks, return_exceptions=True)
