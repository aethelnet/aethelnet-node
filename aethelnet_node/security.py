"""
Aethelnet Node security helpers.

- Token authentication for state-changing HTTP requests (AETHELNET_AUTH_TOKEN).
- The same rules for WebSocket sessions (operator and peer sockets).
- Opt-in switch for executing node content as code (AETHELNET_ALLOW_CODE_EXEC).
- Configurable CORS origins (AETHELNET_CORS_ORIGINS).
- Path containment checks for file writes.
"""

import os
import secrets
import logging
from typing import Dict, List, Optional

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.requests import HTTPConnection

from aethelnet_node.agents import (
    LOCAL_AGENT, clean_task_id, current_agent, current_task, has_registered_agents, load_agents, resolve_token
)

logger = logging.getLogger("Aethelnet.Security")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# GET routes that execute node content and therefore need the token as well.
PROTECTED_GET_PREFIXES = ("/api/lgnn/naas/",)

# Node-to-node gossip. Peers do not share an operator token, so these routes stay
# open unless AETHELNET_PEER_TOKEN is set, in which case peers must send that one.
PEER_PATH_PREFIXES = ("/p2p/", "/api/p2p/")

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def get_auth_token() -> str:
    return os.getenv("AETHELNET_AUTH_TOKEN", "").strip()


def get_peer_token() -> str:
    return os.getenv("AETHELNET_PEER_TOKEN", "").strip()


def auth_headers(token: Optional[str] = None) -> Dict[str, str]:
    """Headers for calls to an Aethelnet node API (own node by default)."""
    token = get_auth_token() if token is None else token.strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def is_code_exec_enabled() -> bool:
    return os.getenv("AETHELNET_ALLOW_CODE_EXEC", "").strip().lower() in ("1", "true", "yes")


def get_cors_origins() -> List[str]:
    raw = os.getenv("AETHELNET_CORS_ORIGINS", "*")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or ["*"]


def extract_request_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-aethelnet-token", "").strip()


def token_matches(provided: str, expected: str) -> bool:
    """Constant-time comparison that also copes with non-ASCII input (str compare_digest raises on it)."""
    if not provided or not expected:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def is_direct_loopback(conn: HTTPConnection) -> bool:
    """
    True only for requests/sockets that originate on this machine without passing a proxy.
    Behind nginx/Caddy every request comes from 127.0.0.1, so forwarded requests
    never count as local.
    """
    if conn.headers.get("x-forwarded-for") or conn.headers.get("forwarded"):
        return False
    host = conn.client.host if conn.client else ""
    return host in LOOPBACK_HOSTS


def ws_query_token(websocket: WebSocket) -> str:
    """Browsers cannot set headers on WebSockets, so a token may also come as ?token=..."""
    return websocket.query_params.get("token", "").strip()


def auth_configured() -> bool:
    """Writes need a token once an operator token or at least one agent identity exists."""
    return bool(get_auth_token()) or has_registered_agents()


def ws_agent(websocket: WebSocket, provided: str = "") -> Optional[str]:
    """Agent id for a WebSocket session, using the same rule as HTTP writes; None if not authorised."""
    if auth_configured():
        identity = resolve_token(provided)
        return identity.agent_id if identity and identity.can_write else None
    return LOCAL_AGENT if is_direct_loopback(websocket) else None


def is_ws_operator(websocket: WebSocket, provided: str = "") -> bool:
    return ws_agent(websocket, provided) is not None


def is_ws_peer(websocket: WebSocket, provided: str = "") -> bool:
    """Peer sockets are open unless AETHELNET_PEER_TOKEN is set (same rule as /p2p/* over HTTP)."""
    peer_token = get_peer_token()
    return token_matches(provided, peer_token) if peer_token else True


def requires_operator_auth(method: str, path: str) -> bool:
    if path.startswith(PEER_PATH_PREFIXES):
        return False
    return method.upper() not in SAFE_METHODS or path.startswith(PROTECTED_GET_PREFIXES)


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": detail})


async def token_auth_middleware(request: Request, call_next):
    path = request.url.path
    provided = extract_request_token(request)

    if path.startswith(PEER_PATH_PREFIXES):
        peer_token = get_peer_token()
        if peer_token and request.method.upper() not in SAFE_METHODS:
            if not token_matches(provided, peer_token):
                return _unauthorized("Invalid or missing peer token.")
        return await call_next(request)

    identity = resolve_token(provided) if provided else None

    if not requires_operator_auth(request.method, path):
        request.state.agent_id = identity.agent_id if identity else None
        return await call_next(request)

    if auth_configured():
        if identity is None:
            return _unauthorized("Invalid or missing token. Send 'Authorization: Bearer <agent token>'.")
        if not identity.can_write:
            return JSONResponse(status_code=403, content={"detail": f"Agent '{identity.agent_id}' may not write."})
        agent_id = identity.agent_id
    elif is_direct_loopback(request):
        agent_id = LOCAL_AGENT
    else:
        return _unauthorized("Remote write access is disabled. Set AETHELNET_AUTH_TOKEN or register agents on the node.")

    # Database writes made while handling this request are attributed to agent_id (created_by / updated_by),
    # and nodes touched within one task (X-Aethelnet-Task, or the agent's session) count as used together.
    request.state.agent_id = agent_id
    ctx = current_agent.set(agent_id)
    task_ctx = current_task.set(clean_task_id(request.headers.get("x-aethelnet-task", "")))
    try:
        response = await call_next(request)
    finally:
        current_task.reset(task_ctx)
        current_agent.reset(ctx)
    record_agent_write(agent_id, request.method.upper(), path, response.status_code)
    return response


def record_agent_write(agent_id: str, method: str, path: str, status_code: int) -> None:
    """Append to the audit log. Never lets logging failures break a request."""
    try:
        from aethelnet_node.database import log_agent_write
        log_agent_write(agent_id, method, path, status_code)
    except Exception as e:  # e.g. DB not initialised yet
        logger.debug(f"[Security] audit log write failed: {e}")


def log_security_posture() -> None:
    if not auth_configured():
        logger.warning(
            "[Security] No AETHELNET_AUTH_TOKEN and no registered agents: write requests are only "
            "accepted from localhost. Register agents with `python -m aethelnet_node.agents add <id>`."
        )
    else:
        agents = [a for a, e in load_agents().items() if not e.get("revoked")]
        logger.info(f"[Security] Write access by token. Agents: {', '.join(agents) or '-'}"
                    f"{' + operator token' if get_auth_token() else ''}")
    if is_code_exec_enabled():
        logger.warning(
            "[Security] AETHELNET_ALLOW_CODE_EXEC is enabled: NaaS nodes can run Python/Lua "
            "on this machine. Only enable this on trusted, private nodes."
        )
    if get_cors_origins() == ["*"]:
        logger.info("[Security] CORS allows all origins (credentials disabled). Set AETHELNET_CORS_ORIGINS to restrict.")


def is_within_directory(root: str, candidate: str) -> bool:
    root_real = os.path.realpath(root)
    cand_real = os.path.realpath(candidate)
    try:
        return os.path.commonpath([root_real, cand_real]) == root_real
    except ValueError:
        # Different drives on Windows
        return False
