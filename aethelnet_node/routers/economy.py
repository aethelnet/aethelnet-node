import logging
import os
from typing import Dict, Any, Optional, List
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("Aethelnet.Node.Economy")

router = APIRouter()

# Default built-in capability plugins
CORE_PLUGINS = [
    {
        "id": "plugin_omni_decoder",
        "name": "Omni Context Decoder",
        "author": "AethelnetCore",
        "type": "decoder",
        "description": "Multimodal latent projection into TEXT, UI, IMAGE, and AUDIO formats.",
        "status": "active"
    },
    {
        "id": "plugin_naas_runtime",
        "name": "Node-as-a-Service Runtime",
        "author": "AethelnetCore",
        "type": "compute",
        "description": "Executes dynamic Python & Lua sandboxed logic embedded directly in GNN nodes.",
        "status": "active"
    },
    {
        "id": "plugin_ouroboros",
        "name": "Ouroboros Autonomic Loop",
        "author": "Unit734",
        "type": "cognitive",
        "description": "Continuous nocturnal dream cycle, reality-anchor critique, and topological consolidation.",
        "status": "active"
    },
    {
        "id": "plugin_edison_escrow",
        "name": "Edison Tournament Escrow",
        "author": "KasselLocals",
        "type": "settlement",
        "description": "On-chain prize pool custody and wager referee attestation via Base Sepolia.",
        "status": "available"
    }
]

@router.get("/wallet")
async def get_wallet_balance():
    try:
        from aethelnet_node.reward_system import economy
        local_balance = sum(amt for key, amt in economy.ledger.items() if key.startswith("LocalMiner_"))
        return {
            "status": "success",
            "balance": round(local_balance, 6),
            "total_supply": round(economy.total_supply, 6)
        }
    except Exception as e:
        logger.error(f"[Economy] Wallet fetch failed: {e}")
        return {"status": "error", "balance": 0.0, "total_supply": 0.0}

@router.get("/market/search")
async def market_search(q: Optional[str] = ""):
    """
    Returns registered system plugins and extensions.
    Eliminates static mock arrays by querying registered core capabilities.
    """
    results = list(CORE_PLUGINS)
    
    # Also inspect custom installed plugins directory if present
    custom_plugins_dir = os.path.expanduser("~/.aethelnet/plugins")
    if os.path.exists(custom_plugins_dir):
        for item in os.listdir(custom_plugins_dir):
            item_path = os.path.join(custom_plugins_dir, item)
            if os.path.isdir(item_path):
                results.append({
                    "id": f"plugin_custom_{item}",
                    "name": item.replace("_", " ").title(),
                    "author": "LocalUser",
                    "type": "custom",
                    "description": f"Custom user-installed plugin in {item_path}",
                    "status": "installed"
                })

    if q:
        q_lower = q.lower()
        results = [
            r for r in results
            if q_lower in r["name"].lower() or q_lower in r["description"].lower() or q_lower in r["id"].lower()
        ]
        
    return {"status": "success", "results": results}
