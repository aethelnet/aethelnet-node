import asyncio
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import httpx
from aethelnet_node.sensors.base_sensor import BaseSensor

logger = logging.getLogger("Aethelnet.WebSpider")

class WebSpiderSensor(BaseSensor):
    def __init__(self, config: dict):
        super().__init__(config)
        self.sources = config.get("sources", [])
        self.priority_keywords = config.get("priority_keywords", [])
        self.queue = self.sources.copy()
        self.visited = set()
        
    async def run(self, max_pages=5000):
        logger.info(f"[{self.name}] Starting WebSpider with {len(self.sources)} seed URLs.")
        pages_crawled = 0
        
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            while self.queue and pages_crawled < max_pages:
                url = self.queue.pop(0)
                if url in self.visited:
                    continue
                    
                self.visited.add(url)
                logger.info(f"[{self.name}] Spinning web at: {url}")
                
                try:
                    headers = {'User-Agent': f'{self.name}/1.0 (Aethelnet Node Sensor)'}
                    resp = await client.get(url, headers=headers)
                    if resp.status_code != 200:
                        continue
                        
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    
                    paragraphs = soup.find_all('p')
                    text_content = " ".join([p.get_text() for p in paragraphs])
                    
                    if len(text_content.split()) >= 50:
                        domain = urlparse(url).netloc
                        await self.ingest_to_lgnn(text_content, additional_tags=["web_scrape", domain])

                    for link in soup.find_all('a', href=True):
                        next_url = urljoin(url, link['href'])
                        if next_url.startswith("http") and next_url not in self.visited:
                            if any(kw.lower() in next_url.lower() for kw in self.priority_keywords):
                                self.queue.insert(0, next_url)
                            else:
                                self.queue.append(next_url)
                            
                    pages_crawled += 1
                    await asyncio.sleep(1.5)
                    
                except Exception as e:
                    logger.error(f"[{self.name}] Error crawling {url}: {e}")
