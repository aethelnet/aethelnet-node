import base64
import json
import logging
import os
import re
import urllib.request
from typing import Dict, Any, List

logger = logging.getLogger("Aethelnet.Sensors")

class SensorArray:
    """
    Multimodal Ingestion Module for Aethelnet.
    Parses PDFs, audio, and spatial geometry into standardized semantic observations.
    """
    def __init__(self, ollama_host="http://127.0.0.1:11434"):
        self.ollama_host = ollama_host
        self.vision_model = "llava:latest"
        
    def _call_ollama(self, model: str, prompt: str, images: List[str] = None) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        if images:
            payload["images"] = images
            
        req = urllib.request.Request(
            f"{self.ollama_host}/api/generate",
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as res:
                return json.loads(res.read().decode('utf-8')).get('response', '')
        except Exception as e:
            return f"[Sensor Error]: {e}"

    def parse_pdf(self, file_path: str, chunk_size: int = 1000) -> List[Dict[str, Any]]:
        """
        Extracts text and visual layouts from PDFs.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.warning("[Sensors] PyMuPDF (fitz) is not installed. PDF ingestion will fail.")
            return [{"type": "error", "content": "PyMuPDF not installed. Install via pip install pymupdf"}]

        doc = fitz.open(file_path)
        sensory_chunks = []
        
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text()
            if text.strip():
                words = text.split()
                for i in range(0, len(words), chunk_size):
                    chunk = " ".join(words[i:i+chunk_size])
                    sensory_chunks.append({
                        "type": "text",
                        "content": chunk,
                        "metadata": f"Page {page_num+1}"
                    })
                    
            image_list = page.get_images(full=True)
            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                
                b64_img = base64.b64encode(image_bytes).decode('utf-8')
                logger.info(f"[Sensors] Analyzing page {page_num+1} image layout...")
                vision_desc = self._call_ollama(
                    model=self.vision_model,
                    prompt="Describe this image in detail. Extract any data, charts, or graphical meaning.",
                    images=[b64_img]
                )
                
                if "[Sensor Error]" in vision_desc or not vision_desc.strip():
                    vision_desc = f"Visual element extracted from Page {page_num+1} index {img_index}."
                
                sensory_chunks.append({
                    "type": "visual_description",
                    "content": vision_desc,
                    "metadata": f"Image {img_index} on Page {page_num+1}"
                })
                
        return sensory_chunks

    def perceive_spatial_geometry(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Parses 3D objects (.obj, .stl) into topological descriptors.
        """
        sensory_chunks = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            vertices = []
            for line in lines:
                if line.startswith("v "):
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            
            if vertices:
                x_coords = [v[0] for v in vertices]
                y_coords = [v[1] for v in vertices]
                z_coords = [v[2] for v in vertices]
                
                bounding_box = {
                    "width": max(x_coords) - min(x_coords),
                    "height": max(y_coords) - min(y_coords),
                    "depth": max(z_coords) - min(z_coords)
                }
                
                spatial_desc = (
                    f"Physical Object perceived in 3D Space. "
                    f"Vertices count: {len(vertices)}. "
                    f"Bounding Box: {bounding_box['width']:.2f} x {bounding_box['height']:.2f} x {bounding_box['depth']:.2f}."
                )
                
                sensory_chunks.append({
                    "type": "spatial_geometry",
                    "content": spatial_desc,
                    "metadata": file_path
                })
        except Exception as e:
            return [{"type": "error", "content": f"Failed to perceive spatial geometry: {e}"}]
            
        return sensory_chunks

    def extract_keywords(self, text: str) -> List[str]:
        """
        Extracts scientific/mathematical keywords from text to trigger Research Scouter.
        """
        keywords = ["neural ode", "graph neural network", "hebbian learning", "dynamical system", "differential equation", "chaos theory", "topological data analysis", "manifold learning"]
        found = []
        lower_text = text.lower()
        for kw in keywords:
            if kw in lower_text:
                found.append(kw)
        return found

    def query_wikipedia(self, query: str) -> Dict[str, Any]:
        """
        Fetches summary definition of a mathematical/scientific term from Wikipedia REST API.
        """
        import urllib.parse
        clean_query = query.replace(" ", "_").strip()
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(clean_query)}"
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'AethelnetSensors/1.0 (contact: nika.hrlyn@gmail.com)'}
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                return {
                    "title": data.get("title", query),
                    "summary": data.get("extract", ""),
                    "url": data.get("content_urls", {}).get("desktop", {}).get("page", "")
                }
        except Exception as e:
            logger.debug(f"[Wikipedia Sensor] Failed to query '{query}': {e}")
            return {}

    def query_github(self, query: str) -> List[Dict[str, Any]]:
        """
        Searches GitHub for top open source repositories related to the active concept.
        """
        import urllib.parse
        url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}&sort=stars&order=desc"
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'AethelnetSensors/1.0 (contact: nika.hrlyn@gmail.com)'}
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                repos = []
                for item in data.get("items", [])[:3]:  # Top 3 repos
                    repos.append({
                        "name": item.get("full_name"),
                        "description": item.get("description", ""),
                        "url": item.get("html_url"),
                        "stars": item.get("stargazers_count", 0)
                    })
                return repos
        except Exception as e:
            logger.debug(f"[GitHub Sensor] Failed to query '{query}': {e}")
            return []
