import logging
import json
import time
import os
import urllib.request
import asyncio
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from aethelnet_node.database import save_node, save_edge

logger = logging.getLogger("Aethelnet.Node.SystemApps")

router = APIRouter()

def call_openrouter_with_retry(
    prompt: str, 
    is_json_object: bool = True, 
    max_retries: int = 3, 
    base_wait: float = 2.0,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    custom_model: Optional[str] = None
) -> str:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if key:
        payload = {
            "model": custom_model or "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}]
        }
        if is_json_object:
            payload["response_format"] = {"type": "json_object"}
            
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(
                    "https://api.openai.com/v1/chat/completions",
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=15) as res:
                    result = json.loads(res.read().decode('utf-8'))
                    return result['choices'][0]['message']['content']
            except Exception as e:
                if attempt == max_retries - 1: return f"LLM Execution Error: {e}"
                time.sleep(base_wait * (2 ** attempt))
    return f"LLM Execution Error: No API key configured. Provide OPENAI_API_KEY in ENV."

class SpiderCrawlRequest(BaseModel):
    spider_node_id: str
    url: str
    parent_id: Optional[str] = "root"

@router.post("/spider/crawl")
async def spider_crawl_endpoint(req: SpiderCrawlRequest, request: Request):
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse
    
    graph_instance = request.app.state.graph_instance
    node_metrics = request.app.state.node_metrics
    text_to_embedding = request.app.state.text_to_embedding
    
    try:
        if not req.url.startswith("http"):
            return {"status": "error", "error": "Search queries not fully implemented. Please enter a valid URL."}
            
        headers = {'User-Agent': 'Mozilla/5.0 LGNN-Spider/1.0'}
        response = requests.get(req.url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        title = soup.title.string if soup.title else req.url
        
        headings = [h.get_text(strip=True) for h in soup.find_all(['h1', 'h2']) if h.get_text(strip=True) and len(h.get_text(strip=True)) > 5]
        
        meta_desc = ""
        meta = soup.find('meta', attrs={'name': 'description'})
        if meta:
            meta_desc = meta.get('content', '')
            
        extracted_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('http') and req.url not in href:
                extracted_links.append(href)
                if len(extracted_links) >= 3:
                    break
                    
        domain = urlparse(req.url).netloc
        nodes_to_create = []
        if title: nodes_to_create.append(f"PAGE: {title} ({domain})")
        if meta_desc: nodes_to_create.append(f"META: {meta_desc}")
        for h in headings[:3]: nodes_to_create.append(f"H: {h}")
        for l in extracted_links: nodes_to_create.append(f"LINK: {l}")
            
        results = []
        for content in set(nodes_to_create):
            node_id = f"spider_{domain}_{int(time.time()*1000)}_{hash(content) % 10000}"
            emb = text_to_embedding(content)
            graph_instance.add_node(node_id, emb, connections=[req.spider_node_id])
            
            node_metrics[node_id] = {
                "confidence": 0.6, "plateau_factor": 0.0, "is_grounded": False,
                "help_chain": False, "source_tag": "spider", "is_quarantined": False,
                "node_type": "standard", "meta_data": "{}", "parent_id": req.parent_id
            }
            
            save_node(node_id, emb, 0.0, 0.6, 0.0, False, False, text_content=content, source_tag="spider", parent_id=req.parent_id)
            save_edge(node_id, req.spider_node_id, 1.0)
            results.append(content)
            
        return {"status": "success", "results": results, "dom_nodes": len(soup.find_all())}
    except Exception as e:
        return {"status": "error", "error": str(e)}

class MacroExecuteRequest(BaseModel):
    node_id: str
    inputs: Dict[str, Any] = {}
    text_content: str = ""

@router.post("/macro/execute")
async def execute_macro_endpoint(req: MacroExecuteRequest, request: Request):
    graph_instance = request.app.state.graph_instance
    node_metrics = request.app.state.node_metrics
    text_to_embedding = request.app.state.text_to_embedding
    
    logger.info(f"Executing Macro {req.node_id} with inputs: {req.inputs}")
    
    out_id = f"MacroOutput_{int(time.time())}"
    out_text = f"[Macro Output] Executed: {req.node_id}\nInputs processed: {len(req.inputs)}"
    
    emb = text_to_embedding(out_text)
    graph_instance.add_node(out_id, emb, connections=[req.node_id])
    if req.node_id in graph_instance.nodes:
        graph_instance.nx_graph.add_edge(req.node_id, out_id, weight=0.9)
        save_edge(req.node_id, out_id, 0.9)
        
    save_node(out_id, emb, 0.0, 0.9, 0.0, False, False, text_content=out_text)
    node_metrics[out_id] = {
        "confidence": 0.9, "plateau_factor": 0.0, "is_grounded": False, "help_chain": False,
        "parent_id": node_metrics.get(req.node_id, {}).get("parent_id", "root")
    }
    
    return {"status": "executed", "macro": req.node_id, "outputs": [out_id]}
