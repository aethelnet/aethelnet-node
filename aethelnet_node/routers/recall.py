"""
Associative recall over HTTP (for agents that don't use MCP).

GET  /api/lgnn/recall?q=...&k=8&popularity=false   — hybrid retrieval + spreading activation + claims
POST /api/lgnn/recall/feedback {"node_ids": [...], "task_id": "..."}  — mark recalled nodes as useful
     (a write: needs the agent's token, links the nodes as "used together" for the agent's task)
"""

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from aethelnet_node.agents import clean_task_id, current_task
from aethelnet_node.coaccess import touch
from aethelnet_node.recall import recall

router = APIRouter()


class RecallFeedback(BaseModel):
    node_ids: List[str]
    task_id: Optional[str] = None


@router.get("/recall")
def recall_endpoint(q: str, k: int = 8, popularity: bool = False, claims: bool = True):
    return recall(q, k=k, use_popularity=popularity, include_claims=claims)


@router.post("/recall/feedback")
def recall_feedback(payload: RecallFeedback):
    task = clean_task_id(payload.task_id or "")
    ctx = current_task.set(task) if task else None
    try:
        links = touch([n for n in payload.node_ids if n.strip()], kind="useful")
    finally:
        if ctx is not None:
            current_task.reset(ctx)
    return {"status": "ok", "nodes": len(payload.node_ids), "new_links": links}
