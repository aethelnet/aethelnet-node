"""
"Used together" memory (Idea #3 in aethelnet-core/docs/IDEAS.md).

When an agent writes nodes or claims, or marks recalled nodes as useful, within one task, those nodes
become linked. The edge weight counts the distinct tasks in which a pair occurred together, so
repeating the same pair inside one task does not inflate it. Associative recall (recall.py) spreads
activation over these edges.

The research benchmark (aethelnet-core/research/recall_benchmark) found that edges meaning "changed
together" improve recall beyond a popularity control, while similarity edges and embedding smoothing
do not. This module is the node-side analogue.

What counts:
- writes by an identified agent (node upserts, claims: source and target) and explicit "useful" feedback
- not recall results themselves (that would reinforce whatever was retrieved), and not daemon
  ("system") writes

Task boundaries: the X-Aethelnet-Task header if given (shared across agents, e.g. an issue number),
otherwise a per-agent session that ends after SESSION_GAP_SECONDS without touches.
"""

import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from aethelnet_node.agents import SYSTEM_AGENT, get_current_agent, current_task

logger = logging.getLogger("Aethelnet.CoAccess")

SESSION_GAP_SECONDS = 30 * 60
RECENT_PER_TASK = 50  # each new touch links to at most this many recent nodes of the same task
DEFAULT_HALF_LIFE_DAYS = 30.0
DECAY_GRACE_SECONDS = 60.0  # preserve exact integer weights inside immediate write/test bursts


def _parse_sqlite_timestamp(ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    s = str(ts).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _decay_factor(updated_at: Optional[str], now_ts: float, half_life_days: Optional[float]) -> float:
    """Continuous-time exponential Hebbian decay factor 2^(-age_days / half_life)."""
    if half_life_days is None or half_life_days <= 0.0:
        return 1.0
    ts = _parse_sqlite_timestamp(updated_at)
    if ts is None:
        return 1.0
    age_s = max(0.0, now_ts - ts)
    if age_s < DECAY_GRACE_SECONDS:
        return 1.0
    return math.pow(0.5, (age_s / 86400.0) / half_life_days)

_sessions: Dict[str, Tuple[str, float]] = {}
_sessions_lock = threading.Lock()


def _task_for(agent_id: str) -> str:
    explicit = current_task.get()
    if explicit:
        return f"task:{explicit}"
    now = time.time()
    with _sessions_lock:
        session, last = _sessions.get(agent_id, ("", 0.0))
        if not session or now - last > SESSION_GAP_SECONDS:
            session = f"session:{agent_id}:{int(now)}"
        _sessions[agent_id] = (session, now)
        return session


def touch(node_ids: Iterable[str], kind: str = "write") -> int:
    """Record that the current agent used these nodes in its current task. Returns new pair links."""
    agent = get_current_agent()
    if agent == SYSTEM_AGENT:
        return 0
    ids = [n for n in dict.fromkeys(node_ids) if n]
    if not ids:
        return 0
    from aethelnet_node.database import get_db_connection

    task = _task_for(agent)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT node_id FROM agent_touch_log WHERE task_id = ? GROUP BY node_id ORDER BY MAX(id) DESC LIMIT ?",
            (task, RECENT_PER_TASK),
        )
        recent = [r["node_id"] for r in cur.fetchall()]
        for node_id in ids:
            cur.execute("INSERT INTO agent_touch_log (agent_id, task_id, node_id, kind) VALUES (?, ?, ?, ?)",
                        (agent, task, node_id, kind))
        new_links = 0
        now_ts = time.time()
        group = list(dict.fromkeys(recent + ids))
        for node_id in ids:
            for other in group:
                if other == node_id:
                    continue
                a, b = sorted((node_id, other))
                cur.execute("INSERT INTO agent_coaccess_seen (task_id, node_a, node_b) VALUES (?, ?, ?) "
                            "ON CONFLICT DO NOTHING", (task, a, b))
                if cur.rowcount == 1:  # first time this pair occurs in this task
                    cur.execute(
                        "SELECT weight, updated_at FROM agent_coaccess_edges WHERE node_a = ? AND node_b = ?",
                        (a, b),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        decayed_prev = float(existing["weight"]) * _decay_factor(
                            existing["updated_at"], now_ts, DEFAULT_HALF_LIFE_DAYS
                        )
                        cur.execute(
                            """
                            UPDATE agent_coaccess_edges
                            SET weight = ?, last_agent = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE node_a = ? AND node_b = ?
                            """,
                            (decayed_prev + 1.0, agent, a, b),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO agent_coaccess_edges (node_a, node_b, weight, last_agent, updated_at)
                            VALUES (?, ?, 1.0, ?, CURRENT_TIMESTAMP)
                            """,
                            (a, b, agent),
                        )
                    new_links += 1
        conn.commit()
        return new_links
    except Exception as e:
        conn.rollback()
        logger.debug(f"[CoAccess] touch failed: {e}")
        return 0
    finally:
        conn.close()


def edges_among(
    node_ids: Iterable[str],
    half_life_days: Optional[float] = DEFAULT_HALF_LIFE_DAYS,
    now_ts: Optional[float] = None,
) -> List[Tuple[str, str, float]]:
    """Return active co-access edges among node_ids with continuous exponential age decay."""
    wanted = set(node_ids)
    from aethelnet_node.database import get_db_connection

    conn = get_db_connection()
    cur = conn.cursor()
    ref_ts = time.time() if now_ts is None else float(now_ts)
    try:
        cur.execute("SELECT node_a, node_b, weight, updated_at FROM agent_coaccess_edges")
        out: List[Tuple[str, str, float]] = []
        for r in cur.fetchall():
            if r["node_a"] in wanted and r["node_b"] in wanted:
                w = float(r["weight"]) * _decay_factor(r["updated_at"], ref_ts, half_life_days)
                if w > 1e-6:
                    out.append((r["node_a"], r["node_b"], w))
        return out
    except Exception as e:
        logger.debug(f"[CoAccess] edge load failed: {e}")
        return []
    finally:
        conn.close()


def touch_counts() -> Dict[str, int]:
    """Popularity signal: how often each node was touched by agents (optional in recall)."""
    from aethelnet_node.database import get_db_connection

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT node_id, COUNT(*) AS n FROM agent_touch_log GROUP BY node_id")
        return {r["node_id"]: int(r["n"]) for r in cur.fetchall()}
    except Exception:
        return {}
    finally:
        conn.close()
