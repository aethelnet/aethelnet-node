"""
Aethelnet Node security helpers.

- Token authentication for state-changing HTTP requests (AETHELNET_AUTH_TOKEN).
- Opt-in switch for executing node content as code (AETHELNET_ALLOW_CODE_EXEC).
- Configurable CORS origins (AETHELNET_CORS_ORIGINS).
- Path containment checks for file writes.
"""

import os
import secrets
import logging
from typing import Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

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


def is_direct_loopback(request: Request) -> bool:
    """
    True only for requests that originate on this machine without passing a proxy.
    Behind nginx/Caddy every request comes from 127.0.0.1, so forwarded requests
    never count as local.
    """
    if request.headers.get("x-forwarded-for") or request.headers.get("forwarded"):
        return False
    host = request.client.host if request.client else ""
    return host in LOOPBACK_HOSTS


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
            if not secrets.compare_digest(provided, peer_token):
                return _unauthorized("Invalid or missing peer token.")
        return await call_next(request)

    if requires_operator_auth(request.method, path):
        token = get_auth_token()
        if token:
            if not secrets.compare_digest(provided, token):
                return _unauthorized("Invalid or missing token. Send 'Authorization: Bearer <AETHELNET_AUTH_TOKEN>'.")
        elif not is_direct_loopback(request):
            return _unauthorized("Remote write access is disabled. Set AETHELNET_AUTH_TOKEN on the node to enable it.")

    return await call_next(request)


def log_security_posture() -> None:
    if not get_auth_token():
        logger.warning(
            "[Security] AETHELNET_AUTH_TOKEN is not set: write requests are only accepted "
            "from localhost. Set a token to allow authenticated remote access."
        )
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
