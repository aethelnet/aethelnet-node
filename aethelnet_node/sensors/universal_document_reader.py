import os
import asyncio
import logging
import json
from unstructured.partition.auto import partition
from aethelnet_node.sensors.base_sensor import BaseSensor

logger = logging.getLogger("Aethelnet.UniversalDocument")

class UniversalDocumentSensor(BaseSensor):
    def __init__(self, config: dict):
        super().__init__(config)
        self.directory = os.path.expanduser(config.get("directory", "~/.aethelnet/ingest_zone"))
        self.visited_file = os.path.join(os.path.dirname(__file__), ".visited_unidocs.json")
        self.visited = self._load_visited()
        
    def _load_visited(self):
        if os.path.exists(self.visited_file):
            try:
                with open(self.visited_file, 'r') as f:
                    return set(json.load(f))
            except:
                return set()
        return set()

    def _save_visited(self):
        with open(self.visited_file, 'w') as f:
            json.dump(list(self.visited), f)

    def read_document(self, filepath):
        try:
            # unstructured automatically detects PDF, Word, Excel, PPT, EML, HTML, EPUB, etc.
            elements = partition(filename=filepath)
            content = "\n\n".join([str(el) for el in elements])
            
            if not content.strip():
                return None
                
            filename = os.path.basename(filepath)
            # Limit the observation length to avoid massive payloads for giant PDFs
            observation = f"Universal Document Extraction '{filename}':\n\n{content[:8000]}"
            return observation
        except Exception as e:
            logger.error(f"Error reading {filepath} with unstructured: {e}")
            return None

    async def run(self):
        logger.info(f"[{self.name}] Starting scan of {self.directory}")
        if not os.path.exists(self.directory):
            logger.error(f"[{self.name}] Directory {self.directory} not found.")
            return

        # Expanded list of formats that unstructured can handle
        valid_exts = {".txt", ".md", ".csv", ".json", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".eml", ".html", ".epub"}
        files_to_process = []
        
        for root, _, files in os.walk(self.directory):
            for f in files:
                if os.path.splitext(f)[1].lower() in valid_exts:
                    full_path = os.path.join(root, f)
                    if full_path not in self.visited:
                        files_to_process.append(full_path)
                        
        logger.info(f"[{self.name}] Found {len(files_to_process)} new documents.")
        
        for filepath in files_to_process:
            logger.info(f"[{self.name}] Partitioning {os.path.basename(filepath)}...")
            
            observation = self.read_document(filepath)
            
            if observation:
                await self.ingest_to_lgnn(observation, additional_tags=["local_document", "universal_ingest"])
                self.visited.add(filepath)
                self._save_visited()
                
            await asyncio.sleep(1.0)
