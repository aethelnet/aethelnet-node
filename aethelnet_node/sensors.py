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

    def perceive_image(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Uses Ollama Vision model to describe standalone images (PNG, JPG, etc.)
        """
        try:
            with open(file_path, "rb") as f:
                image_bytes = f.read()
            b64_img = base64.b64encode(image_bytes).decode('utf-8')
            logger.info(f"[Sensors] Perceiving standalone image: {os.path.basename(file_path)}")
            desc = self._call_ollama(
                model=self.vision_model,
                prompt="Describe this image in detail. Identify any text, objects, mathematical diagrams, or charts.",
                images=[b64_img]
            )
            if "[Sensor Error]" in desc or not desc.strip():
                desc = f"Visual element perceived from {os.path.basename(file_path)}."
            return [{
                "type": "visual_description",
                "content": desc,
                "metadata": file_path
            }]
        except Exception as e:
            return [{"type": "error", "content": f"Failed to perceive image: {e}"}]

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

    def perceive_cosmic_pulse(self) -> str:
        """
        Fetches live cosmic and planetary telemetry from NOAA SWPC, USGS, Open-Meteo, and NDBC.
        """
        results = []
        # 1. Earthquakes
        try:
            req = urllib.request.Request("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson", headers={'User-Agent': 'Aethelnet/1.0'})
            with urllib.request.urlopen(req, timeout=3.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                quakes = data.get("features", [])
                mags = [q["properties"]["mag"] for q in quakes if q["properties"]["mag"] is not None]
                if mags:
                    results.append(f"Seismic Activity: {len(mags)} earthquakes in the last hour. Max magnitude: {max(mags):.1f}. Cumulative magnitude: {sum(mags):.1f}")
        except Exception:
            pass

        # 2. Solar Wind & Magnetics (NOAA SWPC)
        try:
            req = urllib.request.Request("https://services.swpc.noaa.gov/products/solar-wind/mag-5-minute.json", headers={'User-Agent': 'Aethelnet/1.0'})
            with urllib.request.urlopen(req, timeout=3.0) as res:
                latest = json.loads(res.read().decode('utf-8'))[-1]
                bt = float(latest[6])
                bz = float(latest[3])
                results.append(f"Magnetosphere: IMF Bt={bt:.1f} nT, Bz={bz:.1f} nT (polarity {'negative' if bz < 0 else 'positive'})")
        except Exception:
            pass

        # 3. Kp-Index (Geomagnetic Activity)
        try:
            req = urllib.request.Request("https://services.swpc.noaa.gov/json/planetary_k_index_1m.json", headers={'User-Agent': 'Aethelnet/1.0'})
            with urllib.request.urlopen(req, timeout=3.0) as res:
                latest = json.loads(res.read().decode('utf-8'))[-1]
                kp = float(latest.get("kp_index", 0.0))
                results.append(f"Geomagnetism: Planetary Kp-index is {kp:.1f}")
        except Exception:
            pass

        # 4. Kyoto Dst Index (Magnetospheric Stress)
        try:
            req = urllib.request.Request("https://services.swpc.noaa.gov/products/kyoto-dst.json", headers={'User-Agent': 'Aethelnet/1.0'})
            with urllib.request.urlopen(req, timeout=3.0) as res:
                latest = json.loads(res.read().decode('utf-8'))[-1]
                dst = float(latest[1])
                results.append(f"Magnetospheric Stress: Dst Index is {dst:.1f} nT")
        except Exception:
            pass

        # 5. Differential Alpha Particle Flux
        try:
            req = urllib.request.Request("https://services.swpc.noaa.gov/json/goes/primary/differential-alphas-6-hour.json", headers={'User-Agent': 'Aethelnet/1.0'})
            with urllib.request.urlopen(req, timeout=3.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                channel_data = [d for d in data if d.get("energy") == "3790-6780 keV"]
                if channel_data:
                    flux = float(channel_data[-1].get("flux", 1.0))
                    results.append(f"Space Weather: GOES Primary Alpha flux (3790-6780 keV) is {flux:.4f}")
        except Exception:
            pass

        # 6. Global Jetstream & Winds (Open-Meteo)
        try:
            url = "https://api.open-meteo.com/en/v1/forecast?latitude=51.5074&longitude=-0.1278&current=surface_pressure,wind_speed_10m,wind_speed_800hpa&wind_speed_unit=ms"
            req = urllib.request.Request(url, headers={'User-Agent': 'Aethelnet/1.0'})
            with urllib.request.urlopen(req, timeout=3.0) as res:
                current = json.loads(res.read().decode('utf-8')).get("current", {})
                results.append(f"Atmospheric Dynamics: Surface pressure {current.get('surface_pressure', 1013):.1f} hPa, Wind Speed (10m) {current.get('wind_speed_10m', 0):.1f} m/s, Jetstream (800hPa) {current.get('wind_speed_800hpa', 0):.1f} m/s")
        except Exception:
            pass

        # 7. NOAA Sentinel DART Buoys (Oceanic Pressure)
        try:
            buoys = ["21413", "44402"]
            buoy_pressures = []
            for bid in buoys:
                url = f"https://www.ndbc.noaa.gov/data/realtime2/{bid}.txt"
                req = urllib.request.Request(url, headers={'User-Agent': 'Aethelnet/1.0'})
                with urllib.request.urlopen(req, timeout=3.0) as res:
                    lines = res.read().decode('utf-8').split("\n")
                    if len(lines) > 2:
                        data = lines[2].split()
                        if len(data) > 12:
                            buoy_pressures.append(float(data[12]))
            if buoy_pressures:
                avg_pressure = sum(buoy_pressures) / len(buoy_pressures)
                results.append(f"Oceanographic Telemetry: Sentinel DART Buoy pressure average {avg_pressure:.2f} m")
        except Exception:
            pass

        if results:
            return " | ".join(results)
        return "Planetary telemetry silent."

    def query_open_library(self, query: str) -> List[Dict[str, Any]]:
        """
        Searches Open Library for books and pulls descriptions/summaries.
        """
        import urllib.parse
        url = f"https://openlibrary.org/search.json?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'AethelnetSensors/1.0 (contact: nika.hrlyn@gmail.com)'}
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                books = []
                for doc in data.get("docs", [])[:3]:  # Top 3 books
                    work_key = doc.get("key")
                    description = ""
                    if work_key:
                        work_url = f"https://openlibrary.org{work_key}.json"
                        work_req = urllib.request.Request(
                            work_url,
                            headers={'User-Agent': 'AethelnetSensors/1.0 (contact: nika.hrlyn@gmail.com)'}
                        )
                        try:
                            with urllib.request.urlopen(work_req, timeout=3.0) as work_res:
                                work_data = json.loads(work_res.read().decode('utf-8'))
                                desc_field = work_data.get("description", "")
                                if isinstance(desc_field, dict):
                                    description = desc_field.get("value", "")
                                else:
                                    description = desc_field
                        except Exception:
                            pass
                            
                    # Clean/limit description length
                    if description:
                        description = description[:800] + "..." if len(description) > 800 else description
                    else:
                        description = "No description available on Open Library."

                    books.append({
                        "title": doc.get("title", ""),
                        "author": ", ".join(doc.get("author_name", [])) if doc.get("author_name") else "Unknown",
                        "first_publish_year": doc.get("first_publish_year", ""),
                        "subject": ", ".join(doc.get("subject", [])[:5]) if doc.get("subject") else "",
                        "description": description
                    })
                return books
        except Exception as e:
            logger.debug(f"[Open Library Sensor] Failed to query '{query}': {e}")
            return []
