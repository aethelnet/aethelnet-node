"""
Agent identities for an Aethelnet node.

One token = one agent (maintainer decision #4 in aethelnet-core/docs/VISION.md). Every write is
attributed to the agent whose token made it, so claims carry provenance and agents can build up
reputation later.

Registry file (git-ignored), default `agents.json` next to the database, override with
AETHELNET_AGENTS_FILE. Only SHA-256 hashes of tokens are stored:

    {"agents": {"gemini": {"token_sha256": "...", "role": "writer", "created_at": "...", "description": ""}}}

Manage it from the command line; tokens are printed once and never stored in clear text:

    python -m aethelnet_node.agents add gemini --description "Gemini in the maintainer's editor"
    python -m aethelnet_node.agents list
    python -m aethelnet_node.agents rotate gemini
    python -m aethelnet_node.agents revoke gemini

The legacy AETHELNET_AUTH_TOKEN keeps working as the agent "operator".
"""

import argparse
import contextvars
import datetime
import hashlib
import json
import os
import re
import secrets
import sys
import threading
from dataclasses import dataclass
from typing import Dict, Optional

OPERATOR_AGENT = "operator"   # legacy AETHELNET_AUTH_TOKEN
LOCAL_AGENT = "local"         # direct localhost writes when no auth is configured
SYSTEM_AGENT = "system"       # daemons and other work outside a request
WRITE_ROLES = {"writer", "operator"}
AGENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")

# Which agent the current request / WebSocket message acts for. The HTTP middleware sets it;
# database writes read it to fill created_by / updated_by.
current_agent: contextvars.ContextVar[str] = contextvars.ContextVar("aethelnet_current_agent", default=SYSTEM_AGENT)
# Optional shared task id (header X-Aethelnet-Task, e.g. an issue number). Nodes touched within one task
# become "used together" (see coaccess.py); several agents may share a task id.
current_task: contextvars.ContextVar[str] = contextvars.ContextVar("aethelnet_current_task", default="")
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:#/-]{1,128}$")


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    role: str

    @property
    def can_write(self) -> bool:
        return self.role in WRITE_ROLES


def default_agents_file() -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.getenv("AETHELNET_AGENTS_FILE", "").strip() or os.path.join(repo_root, "agents.json")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_cache_lock = threading.Lock()
_cache: Dict[str, object] = {"path": None, "mtime": None, "agents": {}}


def load_agents(path: Optional[str] = None) -> Dict[str, dict]:
    """Registered agents keyed by id. Re-read automatically when the file changes."""
    path = path or default_agents_file()
    try:
        st = os.stat(path)
        mtime = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    with _cache_lock:
        if _cache["path"] == path and _cache["mtime"] == mtime:
            return _cache["agents"]  # type: ignore[return-value]
        try:
            with open(path, "r", encoding="utf-8") as f:
                agents = json.load(f).get("agents", {})
        except (OSError, ValueError):
            agents = {}
        _cache.update(path=path, mtime=mtime, agents=agents)
        return agents


def save_agents(agents: Dict[str, dict], path: Optional[str] = None) -> None:
    path = path or default_agents_file()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"agents": agents}, f, indent=2, sort_keys=True)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def has_registered_agents() -> bool:
    return any(not a.get("revoked") for a in load_agents().values())


def resolve_token(provided: str) -> Optional[AgentIdentity]:
    """Map a presented token to an agent: registered agents first, then the legacy operator token."""
    if not provided:
        return None
    digest = hash_token(provided)
    for agent_id, entry in load_agents().items():
        stored = str(entry.get("token_sha256", ""))
        if not entry.get("revoked") and stored and secrets.compare_digest(digest, stored):
            return AgentIdentity(agent_id, str(entry.get("role", "writer")))
    legacy = os.getenv("AETHELNET_AUTH_TOKEN", "").strip()
    if legacy and secrets.compare_digest(digest, hash_token(legacy)):
        return AgentIdentity(OPERATOR_AGENT, "operator")
    return None


def get_current_agent() -> str:
    return current_agent.get()


def clean_task_id(raw: str) -> str:
    raw = (raw or "").strip()
    return raw if TASK_ID_PATTERN.match(raw) else ""


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def add_agent(agent_id: str, role: str = "writer", description: str = "", path: Optional[str] = None) -> str:
    if not AGENT_ID_PATTERN.match(agent_id):
        raise ValueError("agent id must be lowercase letters, digits, '.', '_' or '-' (max 64 chars)")
    if agent_id in (OPERATOR_AGENT, LOCAL_AGENT, SYSTEM_AGENT):
        raise ValueError(f"'{agent_id}' is reserved")
    if role not in WRITE_ROLES:
        raise ValueError(f"role must be one of {sorted(WRITE_ROLES)}")
    agents = dict(load_agents(path))
    if agent_id in agents and not agents[agent_id].get("revoked"):
        raise ValueError(f"agent '{agent_id}' already exists; use 'rotate' for a new token")
    token = secrets.token_urlsafe(32)
    agents[agent_id] = {"token_sha256": hash_token(token), "role": role,
                        "description": description, "created_at": _now()}
    save_agents(agents, path)
    return token


def rotate_agent(agent_id: str, path: Optional[str] = None) -> str:
    agents = dict(load_agents(path))
    if agent_id not in agents:
        raise ValueError(f"unknown agent '{agent_id}'")
    token = secrets.token_urlsafe(32)
    entry = dict(agents[agent_id], token_sha256=hash_token(token), rotated_at=_now())
    entry.pop("revoked", None)
    agents[agent_id] = entry
    save_agents(agents, path)
    return token


def revoke_agent(agent_id: str, path: Optional[str] = None) -> None:
    agents = dict(load_agents(path))
    if agent_id not in agents:
        raise ValueError(f"unknown agent '{agent_id}'")
    agents[agent_id] = dict(agents[agent_id], revoked=True, revoked_at=_now())
    save_agents(agents, path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aethelnet_node.agents", description="Manage agent identities")
    parser.add_argument("--file", help="registry file (default: AETHELNET_AGENTS_FILE or agents.json next to the DB)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="register an agent and print its token once")
    p_add.add_argument("agent_id")
    p_add.add_argument("--role", default="writer", choices=sorted(WRITE_ROLES))
    p_add.add_argument("--description", default="")
    sub.add_parser("list", help="list agents (never shows tokens)")
    p_rot = sub.add_parser("rotate", help="issue a new token, invalidating the old one")
    p_rot.add_argument("agent_id")
    p_rev = sub.add_parser("revoke", help="disable an agent")
    p_rev.add_argument("agent_id")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "add":
            token = add_agent(args.agent_id, args.role, args.description, args.file)
            print(f"Agent '{args.agent_id}' registered. Token (shown once, store it in that agent's config):")
            print(token)
        elif args.cmd == "rotate":
            token = rotate_agent(args.agent_id, args.file)
            print(f"New token for '{args.agent_id}' (the old one no longer works):")
            print(token)
        elif args.cmd == "revoke":
            revoke_agent(args.agent_id, args.file)
            print(f"Agent '{args.agent_id}' revoked.")
        else:
            agents = load_agents(args.file)
            if not agents:
                print("No agents registered.")
            for agent_id, entry in sorted(agents.items()):
                state = "revoked" if entry.get("revoked") else entry.get("role", "writer")
                print(f"{agent_id:<20} {state:<9} {entry.get('created_at', ''):<26} {entry.get('description', '')}")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
