"""
Agent identity endpoints.

GET /api/agents/whoami  — which agent the presented token belongs to (agents use this to check their setup)
GET /api/agents         — registered agents with provenance counts (never tokens or hashes)
"""

from fastapi import APIRouter, Request

from aethelnet_node.agents import LOCAL_AGENT, load_agents
from aethelnet_node.database import get_agent_stats
from aethelnet_node.security import auth_configured, is_direct_loopback

router = APIRouter()


@router.get("/agents/whoami")
def whoami(request: Request):
    agent_id = getattr(request.state, "agent_id", None)
    configured = auth_configured()
    if agent_id:
        writes_as = agent_id
    elif not configured and is_direct_loopback(request):
        writes_as = LOCAL_AGENT
    else:
        writes_as = None
    return {
        "agent_id": agent_id,
        "authenticated": agent_id is not None,
        "auth_required_for_writes": configured,
        "writes_attributed_to": writes_as,
    }


@router.get("/agents")
def list_agents():
    registry = load_agents()
    stats = get_agent_stats()
    agents = []
    for agent_id in sorted(set(registry) | set(stats)):
        entry = registry.get(agent_id, {})
        agents.append({
            "agent_id": agent_id,
            "registered": agent_id in registry,
            "role": "revoked" if entry.get("revoked") else entry.get("role"),
            "description": entry.get("description", ""),
            "created_at": entry.get("created_at"),
            **stats.get(agent_id, {"nodes_created": 0, "claims_created": 0,
                                   "claims_contested": 0, "writes": 0, "last_write": None}),
        })
    return {"agents": agents}
