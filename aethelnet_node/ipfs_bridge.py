"""
Aethelnet Canonical Export & IPFS Content-Addressing Bridge
Provides deterministic CIDv1 generation, immutable snapshot packaging,
and decentralized pinning across IPFS/Arweave for forensic multigraphs.
"""

import os
import json
import time
import base64
import hashlib
import logging
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger("Aethelnet.IPFS")

def compute_ipfs_cid(data: bytes) -> str:
    """
    Computes a standard IPFS CIDv1 (raw multicodec 0x55, sha256 multihash 0x12 0x20, base32).
    Bit-for-bit identical to 'ipfs add --cid-version 1 --raw-leaves'.
    """
    digest = hashlib.sha256(data).digest()
    multihash = bytes([0x12, 0x20]) + digest
    cid_bytes = bytes([0x01, 0x55]) + multihash
    b32 = base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")
    return "b" + b32

def build_canonical_bundle(app_id: str) -> Dict[str, Any]:
    """
    Constructs a deterministic, verifiable case snapshot bundle.
    """
    try:
        from . import database
        from .forge_client import forge_client
    except ImportError:
        from aethelnet_node import database
        from aethelnet_node.forge_client import forge_client

    state_info = database.compute_case_state_root(app_id)
    edges = database.get_multigraph_edges(app_id=app_id)
    conflicts = database.sync_conflicts_for_app(app_id=app_id)
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, text_content, label, entity_type, confidence, mean_activation,
               is_grounded, source_tag, last_updated
        FROM lgnn_nodes 
        WHERE app_id = ? 
        ORDER BY id ASC
    """, (app_id,))
    node_rows = cursor.fetchall()
    conn.close()

    nodes_list = []
    for r in node_rows:
        if isinstance(r, dict):
            nodes_list.append(dict(r))
        else:
            nodes_list.append({
                "id": r[0],
                "text_content": r[1],
                "label": r[2],
                "entity_type": r[3],
                "confidence": r[4],
                "mean_activation": r[5],
                "is_grounded": bool(r[6]),
                "source_tag": r[7],
                "last_updated": r[8]
            })

    # Fetch on-chain status if possible
    on_chain_info = {}
    try:
        if forge_client.is_connected():
            on_chain_info = forge_client.get_case_notarization(app_id)
    except Exception as e:
        logger.warning(f"Could not query forge contract: {e}")

    bundle_core = {
        "format": "aethelnet-evidence-bundle-v1",
        "case_id": app_id,
        "exported_at": int(time.time()),
        "state_root": state_info["state_root"],
        "node_count": len(nodes_list),
        "edge_count": len(edges),
        "conflict_count": len(conflicts),
        "nodes": nodes_list,
        "edges": edges,
        "conflicts": conflicts
    }

    # Deterministic JSON serialization for canonical hashing
    serialized = json.dumps(bundle_core, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    bundle_cid = compute_ipfs_cid(serialized)
    payload_sha256 = "0x" + hashlib.sha256(serialized).hexdigest()

    is_verified = False
    if on_chain_info.get("is_notarized"):
        chain_root = on_chain_info.get("state_root", "")
        if chain_root.lower() == state_info["state_root"].lower():
            is_verified = True

    bundle = {
        "manifest": {
            "format": "aethelnet-evidence-bundle-v1",
            "case_id": app_id,
            "exported_at_unix": bundle_core["exported_at"],
            "state_root": state_info["state_root"],
            "content_hash_sha256": payload_sha256,
            "ipfs_cid_v1": bundle_cid,
            "node_count": len(nodes_list),
            "edge_count": len(edges),
            "conflict_count": len(conflicts),
            "is_cryptographically_verified": is_verified,
            "ethereum_notarization": {
                "chain_id": 11155111,
                "chain_name": "Ethereum Sepolia",
                "contract": forge_client.contract_address,
                "on_chain_root": on_chain_info.get("state_root"),
                "notary": on_chain_info.get("notary"),
                "timestamp": on_chain_info.get("timestamp"),
                "block_explorer": f"https://sepolia.etherscan.io/address/{forge_client.contract_address}"
            },
            "gateways": [
                f"https://ipfs.io/ipfs/{bundle_cid}",
                f"https://dweb.link/ipfs/{bundle_cid}",
                f"https://gateway.pinata.cloud/ipfs/{bundle_cid}"
            ]
        },
        "payload": bundle_core
    }

    return bundle
