import os
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aethelnet_node.database import (
    create_snapshot as db_create_snapshot,
    checkout_snapshot as db_checkout_snapshot,
    get_snapshot_history as db_get_snapshot_history
)
from aethelnet_node.state import graph_instance, load_all_from_db

logger = logging.getLogger("Aethelnet.Node.Snapshots")

router = APIRouter()

SNAPSHOTS_DIR = os.path.expanduser("~/.aethelnet/snapshots")
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

class SnapshotCreateRequest(BaseModel):
    description: Optional[str] = "Manual snapshot"
    coherence_score: Optional[float] = 1.0

class SnapshotCheckoutRequest(BaseModel):
    commit_hash: str

@router.get("/snapshot/history")
async def snapshot_history():
    """
    Returns a history list of all snapshot commits.
    """
    history = db_get_snapshot_history()
    return {"status": "success", "history": history}

@router.post("/snapshot/create")
async def snapshot_create(payload: SnapshotCreateRequest):
    """
    Creates a snapshot of the current active graph topology state:
    1. Persists complete PyTorch tensor & dynamic layer state via graph_instance.save_state()
    2. Persists DB metadata in lgnn_commits, lgnn_commit_nodes, lgnn_commit_edges
    """
    try:
        c_hash = db_create_snapshot(
            description=payload.description or "Manual snapshot",
            coherence_score=payload.coherence_score if payload.coherence_score is not None else 1.0
        )
        # Also persist full PyTorch state for high-fidelity restore
        pt_path = os.path.join(SNAPSHOTS_DIR, f"{c_hash}.pt")
        try:
            graph_instance.save_state(pt_path)
            logger.info(f"[Snapshot] Persisted PyTorch topological state to {pt_path}")
        except Exception as e:
            logger.warning(f"[Snapshot] PyTorch state save warning: {e}")

        return {"status": "success", "hash": c_hash}
    except Exception as e:
        logger.error(f"[Snapshot] Creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/snapshot/checkout")
async def snapshot_checkout(payload: SnapshotCheckoutRequest):
    """
    Reverts the active topology to a previous commit:
    1. Checks out snapshot in SQLite database
    2. Restores PyTorch state if available, or rebuilds from DB via load_all_from_db()
    """
    c_hash = payload.commit_hash
    if not c_hash:
        raise HTTPException(status_code=400, detail="commit_hash is required")
        
    success, msg = db_checkout_snapshot(c_hash)
    if not success:
        raise HTTPException(status_code=404, detail=msg)
        
    pt_path = os.path.join(SNAPSHOTS_DIR, f"{c_hash}.pt")
    if os.path.exists(pt_path):
        try:
            graph_instance.load_state(pt_path)
            logger.info(f"[Snapshot] Restored PyTorch state directly from {pt_path}")
        except Exception as e:
            logger.warning(f"[Snapshot] PyTorch restore failed, falling back to DB reload: {e}")
            load_all_from_db()
    else:
        load_all_from_db()
        
    return {"status": "success", "message": msg}
