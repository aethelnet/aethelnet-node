import os
import re
import json
import logging
import datetime
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import yaml
import torch

from aethelnet_node.database import (
    save_node, save_edge, get_node_text, get_db_connection
)
from aethelnet_node.state import (
    graph_instance, node_metrics, text_to_embedding,
    DOCUMENT_CONFIDENCE, broadcast_resonance
)

from aethelnet_node.security import is_within_directory

logger = logging.getLogger("Aethelnet.Node.Vault")
router = APIRouter()

VAULT_LAST_SYNC: Optional[str] = None

class VaultNoteSaveRequest(BaseModel):
    id: str
    text_content: str
    vault_path: Optional[str] = None

class VaultSyncRequest(BaseModel):
    vault_path: Optional[str] = None
    force_reembed: Optional[bool] = False

def find_vault_root(custom_path: Optional[str] = None) -> Optional[str]:
    """
    Locates the active Obsidian Vault directory.
    """
    if custom_path and os.path.isdir(custom_path):
        return os.path.abspath(custom_path)
        
    env_path = os.environ.get("AETHELNET_VAULT_PATH")
    if env_path and os.path.isdir(env_path):
        return os.path.abspath(env_path)
        
    candidates = [
        os.path.expanduser("~/Documents/AethelnetBrain"),
        os.path.expanduser("~/aethelburg-observer/backend/AethelnetBrain_Vault"),
        "/var/data/AethelnetBrain"
    ]
    for c in candidates:
        if os.path.isdir(c):
            return os.path.abspath(c)
    return None

def parse_markdown_file(filepath: str, vault_root: str) -> Dict[str, Any]:
    """
    Parses an Obsidian markdown document, extracting YAML frontmatter,
    inline tags, wikilinks, and clean body text.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    rel_path = os.path.relpath(filepath, vault_root)
    basename = os.path.splitext(os.path.basename(filepath))[0]
    folder = os.path.dirname(rel_path) or "root"
    mtime = os.path.getmtime(filepath)

    frontmatter = {}
    body = content

    # 1. Parse YAML Frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except Exception as e:
                logger.debug(f"[Vault] Failed to parse frontmatter in {rel_path}: {e}")
            body = parts[2].strip()

    # 2. Extract Tags from frontmatter and inline text
    tags = set()
    raw_tags = frontmatter.get("tags") or frontmatter.get("tag") or []
    if isinstance(raw_tags, list):
        tags.update(str(t).strip().lstrip("#") for t in raw_tags if t)
    elif isinstance(raw_tags, str):
        tags.update(t.strip().lstrip("#") for t in raw_tags.split(",") if t.strip())

    # Inline tags: #tag (excluding markdown headings # Heading)
    inline_tags = re.findall(r'(?:^|\s)#([a-zA-Z0-9_\-\/]+)', body)
    tags.update(inline_tags)

    # 3. Extract Aliases
    aliases = []
    raw_aliases = frontmatter.get("aliases") or frontmatter.get("alias") or []
    if isinstance(raw_aliases, list):
        aliases = [str(a).strip() for a in raw_aliases if a]
    elif isinstance(raw_aliases, str):
        aliases = [a.strip() for a in raw_aliases.split(",") if a.strip()]

    # 4. Extract [[WikiLinks]]
    wiki_raw = re.findall(r'\[\[(.*?)\]\]', content)
    wiki_targets = []
    for w in wiki_raw:
        # Strip display alias [[Target|Alias]] and heading anchor [[Target#Heading]]
        target = w.split("|")[0].split("#")[0].strip()
        if target and target not in wiki_targets and target != basename:
            wiki_targets.append(target)

    title = frontmatter.get("title") or basename

    return {
        "id": basename,
        "rel_path": rel_path,
        "folder": folder,
        "title": title,
        "frontmatter": frontmatter,
        "tags": sorted(list(tags)),
        "aliases": aliases,
        "wiki_targets": wiki_targets,
        "body": content,  # Preserve full content including frontmatter for exact sync
        "mtime": mtime
    }

@router.get("/vault/status")
async def get_vault_status():
    vault_root = find_vault_root()
    if not vault_root:
        return {
            "vault_exists": False,
            "vault_path": None,
            "file_count": 0,
            "synced_nodes": 0,
            "last_sync": VAULT_LAST_SYNC
        }

    md_files = []
    for root, _, files in os.walk(vault_root):
        if ".obsidian" in root or ".trash" in root or ".git" in root:
            continue
        for f in files:
            if f.endswith(".md"):
                md_files.append(os.path.join(root, f))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM lgnn_nodes WHERE node_type = 'vault_note'")
    synced_nodes = cursor.fetchone()["cnt"]
    conn.close()

    return {
        "vault_exists": True,
        "vault_path": vault_root,
        "file_count": len(md_files),
        "synced_nodes": synced_nodes,
        "last_sync": VAULT_LAST_SYNC
    }

@router.post("/vault/sync")
async def sync_vault(payload: Optional[VaultSyncRequest] = None):
    global VAULT_LAST_SYNC
    custom_path = payload.vault_path if payload else None
    force_reembed = payload.force_reembed if payload else False

    vault_root = find_vault_root(custom_path)
    if not vault_root:
        raise HTTPException(
            status_code=404,
            detail="Obsidian Vault not found on filesystem. Configure AETHELNET_VAULT_PATH."
        )

    logger.info(f"[Vault Sync] Commencing scan of {vault_root}...")
    scanned_docs = []
    for root, _, files in os.walk(vault_root):
        if ".obsidian" in root or ".trash" in root or ".git" in root:
            continue
        for f in files:
            if f.endswith(".md"):
                filepath = os.path.join(root, f)
                doc = parse_markdown_file(filepath, vault_root)
                scanned_docs.append(doc)

    created_count = 0
    updated_count = 0
    wired_edges = 0

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, text_content, meta_data FROM lgnn_nodes WHERE node_type = 'vault_note'")
    existing_nodes = {row["id"]: row for row in cursor.fetchall()}
    conn.close()

    # Step 1: Ingest / Update nodes
    for doc in scanned_docs:
        nid = doc["id"]
        safe_id = graph_instance._safe_id(nid)
        meta_dict = {
            "vault_path": doc["rel_path"],
            "folder": doc["folder"],
            "title": doc["title"],
            "tags": doc["tags"],
            "aliases": doc["aliases"],
            "mtime": doc["mtime"],
            "parent_id": "root"
        }
        meta_json = json.dumps(meta_dict)

        existing = existing_nodes.get(nid)
        text_changed = True
        if existing:
            if existing["text_content"] == doc["body"]:
                text_changed = False

        if existing is None:
            created_count += 1
            emb = text_to_embedding(doc["body"][:2500])
            graph_instance.add_node(nid, emb)
            save_node(
                nid, emb, 0.0, DOCUMENT_CONFIDENCE, 0.0, False, False,
                text_content=doc["body"], source_tag="obsidian_vault",
                node_type="vault_note", meta_data=meta_json
            )
            metric_entry = {
                "confidence": DOCUMENT_CONFIDENCE,
                "plateau_factor": 0.0,
                "is_grounded": False,
                "help_chain": False,
                "source_tag": "obsidian_vault",
                "is_quarantined": False,
                "parent_id": "root",
                "node_type": "vault_note",
                "meta_data": meta_json,
                "text_content": doc["body"]
            }
            node_metrics[nid] = metric_entry
            node_metrics[safe_id] = metric_entry
        elif text_changed or force_reembed:
            updated_count += 1
            emb = text_to_embedding(doc["body"][:2500])
            if safe_id in graph_instance.nodes:
                with torch.no_grad():
                    graph_instance.nodes[safe_id].copy_(emb)
            else:
                graph_instance.add_node(nid, emb)

            save_node(
                nid, emb, 0.0, DOCUMENT_CONFIDENCE, 0.0, False, False,
                text_content=doc["body"], source_tag="obsidian_vault",
                node_type="vault_note", meta_data=meta_json
            )
            metric_entry = {
                "confidence": DOCUMENT_CONFIDENCE,
                "plateau_factor": 0.0,
                "is_grounded": False,
                "help_chain": False,
                "source_tag": "obsidian_vault",
                "is_quarantined": False,
                "parent_id": "root",
                "node_type": "vault_note",
                "meta_data": meta_json,
                "text_content": doc["body"]
            }
            node_metrics[nid] = metric_entry
            node_metrics[safe_id] = metric_entry

    # Step 2: Wire Synaptic Edges from [[WikiLinks]]
    for doc in scanned_docs:
        src = doc["id"]
        for tgt in doc["wiki_targets"]:
            # Only wire if target exists or is recognized
            src_safe = graph_instance._safe_id(src)
            tgt_safe = graph_instance._safe_id(tgt)
            graph_instance.nx_graph.add_edge(src, tgt, weight=1.0, label="wiki_link")
            graph_instance.nx_graph.add_edge(src_safe, tgt_safe, weight=1.0, label="wiki_link")
            save_edge(src, tgt, 1.0, "wiki_link")
            wired_edges += 1

    VAULT_LAST_SYNC = datetime.datetime.utcnow().isoformat() + "Z"
    logger.info(
        f"[Vault Sync Complete] Files: {len(scanned_docs)} | Created: {created_count} | "
        f"Updated: {updated_count} | Synapses Wired: {wired_edges}"
    )

    return {
        "status": "success",
        "vault_path": vault_root,
        "scanned_files": len(scanned_docs),
        "created_nodes": created_count,
        "updated_nodes": updated_count,
        "wired_edges": wired_edges,
        "synced_at": VAULT_LAST_SYNC
    }

@router.post("/vault/save_note")
async def save_vault_note(payload: VaultNoteSaveRequest):
    """
    Saves modifications from Aethelnet note editor back into the physical markdown file in Obsidian.
    """
    vault_root = find_vault_root()
    if not vault_root:
        raise HTTPException(status_code=404, detail="Obsidian Vault directory not found")

    # Note ids become file names: reject separators and parent references so a
    # request cannot write outside the vault (e.g. id="../../.bashrc").
    if not payload.id or payload.id in (".", "..") or any(sep in payload.id for sep in ("/", "\\", "\x00")):
        raise HTTPException(status_code=400, detail="Invalid note id.")

    target_file = None
    if payload.vault_path:
        candidate = os.path.join(vault_root, payload.vault_path)
        if not is_within_directory(vault_root, candidate):
            raise HTTPException(status_code=400, detail="vault_path must point inside the vault.")
        if os.path.isfile(candidate):
            target_file = candidate

    if not target_file:
        # Search by basename
        for root, _, files in os.walk(vault_root):
            for f in files:
                if f == f"{payload.id}.md" or os.path.splitext(f)[0] == payload.id:
                    target_file = os.path.join(root, f)
                    break
            if target_file:
                break

    if not target_file:
        # Default to saving in 03_MEMORY_BANK or root
        target_file = os.path.join(vault_root, "03_MEMORY_BANK", f"{payload.id}.md")

    if not is_within_directory(vault_root, target_file):
        raise HTTPException(status_code=400, detail="Refusing to write outside the vault.")

    # Write file to disk
    os.makedirs(os.path.dirname(target_file), exist_ok=True)
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(payload.text_content)

    # Re-parse doc
    doc = parse_markdown_file(target_file, vault_root)
    emb = text_to_embedding(doc["body"][:2500])

    safe_id = graph_instance._safe_id(payload.id)
    if safe_id in graph_instance.nodes:
        with torch.no_grad():
            graph_instance.nodes[safe_id].copy_(emb)
        graph_instance.set_anchor(payload.id, emb)
    else:
        graph_instance.add_node(payload.id, emb)

    meta_dict = {
        "vault_path": doc["rel_path"],
        "folder": doc["folder"],
        "title": doc["title"],
        "tags": doc["tags"],
        "aliases": doc["aliases"],
        "mtime": doc["mtime"],
        "parent_id": "root"
    }
    meta_json = json.dumps(meta_dict)

    save_node(
        payload.id, emb, 0.0, DOCUMENT_CONFIDENCE, 0.0, False, False,
        text_content=payload.text_content, source_tag="obsidian_vault",
        node_type="vault_note", meta_data=meta_json
    )

    metric_entry = {
        "confidence": DOCUMENT_CONFIDENCE,
        "plateau_factor": 0.0,
        "is_grounded": False,
        "help_chain": False,
        "source_tag": "obsidian_vault",
        "is_quarantined": False,
        "parent_id": "root",
        "node_type": "vault_note",
        "meta_data": meta_json,
        "text_content": payload.text_content
    }
    node_metrics[payload.id] = metric_entry
    node_metrics[safe_id] = metric_entry

    # Wire new targets
    for tgt in doc["wiki_targets"]:
        save_edge(payload.id, tgt, 1.0, "wiki_link")
        graph_instance.nx_graph.add_edge(payload.id, tgt, weight=1.0, label="wiki_link")

    return {
        "status": "saved",
        "id": payload.id,
        "vault_path": doc["rel_path"],
        "tags": doc["tags"],
        "wiki_targets": doc["wiki_targets"]
    }
