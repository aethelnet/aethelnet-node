import sqlite3
import json
import numpy as np
import torch
import os
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv

load_dotenv()
DB_PROVIDER = os.getenv("DB_PROVIDER", "sqlite").lower()
DATABASE_URL = os.getenv("DATABASE_URL", "")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lgnn.db")

class PostgresCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query, params=None):
        # PostgreSQL uses %s instead of ? for placeholders
        query = query.replace("?", "%s")
        # Handle SQLite's BLOB vs Postgres BYTEA
        if "BLOB" in query:
            query = query.replace("BLOB", "BYTEA")
        if "INTEGER PRIMARY KEY AUTOINCREMENT" in query:
            query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        try:
            return self.cursor.execute(query, params)
        except Exception as e:
            # Fallback to rollback on error so transaction isn't aborted
            self.cursor.connection.rollback()
            raise e

    def executemany(self, query, params_list):
        query = query.replace("?", "%s")
        if "BLOB" in query:
            query = query.replace("BLOB", "BYTEA")
        if "INTEGER PRIMARY KEY AUTOINCREMENT" in query:
            query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        try:
            return self.cursor.executemany(query, params_list)
        except Exception as e:
            self.cursor.connection.rollback()
            raise e

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def close(self):
        self.cursor.close()

    @property
    def rowcount(self):
        return self.cursor.rowcount

class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return PostgresCursorWrapper(self.conn.cursor())

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()
        
    def close(self):
        self.conn.close()

def get_db_connection():
    if DB_PROVIDER == "postgresql" and DATABASE_URL:
        import psycopg2
        from psycopg2.extras import DictCursor
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
        return PostgresConnectionWrapper(conn)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    """
    Initializes the SQLite database schema for persistent LGNN topologies.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create Nodes Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lgnn_nodes (
        id TEXT PRIMARY KEY,
        embedding BLOB NOT NULL,
        text_content TEXT DEFAULT '',
        mean_activation REAL DEFAULT 0.0,
        confidence REAL DEFAULT 0.8,
        plateau_factor REAL DEFAULT 0.0,
        is_grounded INTEGER DEFAULT 0,
        help_chain INTEGER DEFAULT 0,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    
    # Run dynamic migration if column doesn't exist
    try:
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN text_content TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        conn.rollback()
        
    try:
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN is_archived INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        conn.rollback()
        
    try:
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN source_tag TEXT DEFAULT 'internal'")
        conn.commit()
    except Exception:
        conn.rollback()

    try:
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN is_quarantined INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        conn.rollback()

    try:
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN x REAL")
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN y REAL")
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN fx REAL")
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN fy REAL")
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN color TEXT")
        conn.commit()
    except Exception:
        conn.rollback()

    try:
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN node_type TEXT DEFAULT 'standard'")
        conn.commit()
    except Exception:
        conn.rollback()
        
    try:
        cursor.execute("ALTER TABLE lgnn_nodes ADD COLUMN meta_data TEXT")
        conn.commit()
    except Exception:
        conn.rollback()


    # Create Commits Table for Git-like version tracking of snapshots
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lgnn_commits (
        hash TEXT PRIMARY KEY,
        parent_hash TEXT,
        coherence_score REAL,
        description TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    
    # Create Commit Nodes Table to store embeddings and states for each commit
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lgnn_commit_nodes (
        commit_hash TEXT,
        node_id TEXT,
        embedding BLOB NOT NULL,
        text_content TEXT,
        mean_activation REAL,
        confidence REAL,
        plateau_factor REAL,
        is_grounded INTEGER,
        help_chain INTEGER,
        is_archived INTEGER,
        source_tag TEXT,
        is_quarantined INTEGER,
        PRIMARY KEY (commit_hash, node_id),
        FOREIGN KEY (commit_hash) REFERENCES lgnn_commits(hash) ON DELETE CASCADE
    )
    """)
    conn.commit()

    # Create Commit Edges Table to store edges for each commit snapshot
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lgnn_commit_edges (
        commit_hash TEXT,
        source TEXT,
        target TEXT,
        weight REAL,
        PRIMARY KEY (commit_hash, source, target),
        FOREIGN KEY (commit_hash) REFERENCES lgnn_commits(hash) ON DELETE CASCADE
    )
    """)
    conn.commit()
    
    # Create Edges Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lgnn_edges (
        source TEXT,
        target TEXT,
        weight REAL DEFAULT 1.0,
        PRIMARY KEY (source, target),
        FOREIGN KEY (source) REFERENCES lgnn_nodes(id) ON DELETE CASCADE,
        FOREIGN KEY (target) REFERENCES lgnn_nodes(id) ON DELETE CASCADE
    )
    """)
    conn.commit()
    
    # Create Kanban Columns Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS kanban_columns (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    
    # Create Kanban Cards Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS kanban_cards (
        id TEXT PRIMARY KEY,
        column_id TEXT,
        title TEXT NOT NULL,
        description TEXT,
        tags TEXT, -- JSON array of strings
        node_ref TEXT,
        FOREIGN KEY (column_id) REFERENCES kanban_columns(id) ON DELETE CASCADE,
        FOREIGN KEY (node_ref) REFERENCES lgnn_nodes(id) ON DELETE SET NULL
    )
    """)
    conn.commit()
    
    # Create Agent Registry Tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS agent_registry (
        agent_id TEXT PRIMARY KEY,
        metadata TEXT,
        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    
    # 🚀 MASS-INGESTION QUEUE (PostgreSQL native Queue via SKIP LOCKED)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lgnn_ingest_queue (
        id SERIAL PRIMARY KEY,
        payload TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS agent_cooperation_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT,
        requested_skill TEXT,
        success INTEGER DEFAULT 1,
        notes TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (agent_id) REFERENCES agent_registry(agent_id) ON DELETE CASCADE
    )
    """)
    conn.commit()
    
    # Create Persona Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lgnn_personas (
        name TEXT PRIMARY KEY,
        node_ids TEXT, -- JSON array of node_ids
        active INTEGER DEFAULT 0
    )
    """)
    
    # Seed default columns if empty
    cursor.execute("SELECT COUNT(*) as count FROM kanban_columns")
    if cursor.fetchone()["count"] == 0:
        columns = [
            ("backlog", "Backlog", 0),
            ("todo", "To Do", 1),
            ("in_progress", "In Progress", 2),
            ("done", "Done", 3)
        ]
        cursor.executemany("INSERT INTO kanban_columns (id, title, sort_order) VALUES (?, ?, ?)", columns)
        
    conn.commit()
    conn.close()

# Serialization helpers
def serialize_tensor(tensor: torch.Tensor) -> bytes:
    arr = tensor.detach().cpu().numpy().astype(np.float32)
    return arr.tobytes()

def deserialize_tensor(blob: bytes, dim: int = 128) -> torch.Tensor:
    arr = np.frombuffer(blob, dtype=np.float32)
    # Ensure correct dimension
    if len(arr) != dim:
        arr = np.resize(arr, (dim,))
    return torch.tensor(arr)

def save_node(node_id: str, embedding: torch.Tensor, mean_activation: float, confidence: float, plateau_factor: float, is_grounded: bool, help_chain: bool, text_content: str = "", is_archived: bool = False, source_tag: str = "internal", is_quarantined: bool = False, node_type: str = "standard", meta_data: str = "{}"):
    conn = get_db_connection()
    cursor = conn.cursor()
    emb_bytes = serialize_tensor(embedding)
    cursor.execute("""
    INSERT INTO lgnn_nodes (id, embedding, text_content, mean_activation, confidence, plateau_factor, is_grounded, help_chain, is_archived, source_tag, is_quarantined, node_type, meta_data, last_updated)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(id) DO UPDATE SET
        embedding = excluded.embedding,
        text_content = excluded.text_content,
        mean_activation = excluded.mean_activation,
        confidence = excluded.confidence,
        plateau_factor = excluded.plateau_factor,
        is_grounded = excluded.is_grounded,
        help_chain = excluded.help_chain,
        is_archived = excluded.is_archived,
        source_tag = excluded.source_tag,
        is_quarantined = excluded.is_quarantined,
        node_type = excluded.node_type,
        meta_data = excluded.meta_data,
        last_updated = CURRENT_TIMESTAMP
    """, (node_id, emb_bytes, text_content, mean_activation, confidence, plateau_factor, 1 if is_grounded else 0, 1 if help_chain else 0, 1 if is_archived else 0, source_tag, 1 if is_quarantined else 0, node_type, meta_data))
    conn.commit()
    conn.close()

def delete_node(node_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lgnn_nodes WHERE id = ?", (node_id,))
    conn.commit()
    conn.close()

def update_node_physics(nodes_physics: List[Dict[str, Any]]):
    if not nodes_physics:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    # Execute batch update
    query = """
        UPDATE lgnn_nodes 
        SET x = ?, y = ?, fx = ?, fy = ?, color = COALESCE(?, color)
        WHERE id = ?
    """
    params = [
        (n.get("x"), n.get("y"), n.get("fx"), n.get("fy"), n.get("color"), n.get("id"))
        for n in nodes_physics if n.get("id")
    ]
    cursor.executemany(query, params)
    conn.commit()
    conn.close()

# =====================================================================
# ASYNC HYGIENE MASS INGESTION (POSTGRESQL QUEUE)
# =====================================================================
def enqueue_observation(payload_json: str):
    """Puts an observation into the Postgres Queue for background processing."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO lgnn_ingest_queue (payload, status) VALUES (?, 'pending')", (payload_json,))
    conn.commit()
    conn.close()

def dequeue_observation():
    """Pops an observation from the Postgres Queue using SKIP LOCKED to prevent race conditions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # The 'SKIP LOCKED' trick turns Postgres into a highly scalable Message Queue (like Redis/Kafka)
    # It ensures multiple FastAPI workers don't grab the same grain.
    query = """
    UPDATE lgnn_ingest_queue 
    SET status = 'processing' 
    WHERE id = (
        SELECT id FROM lgnn_ingest_queue 
        WHERE status = 'pending' 
        ORDER BY created_at ASC 
        LIMIT 1 
        FOR UPDATE SKIP LOCKED
    ) RETURNING id, payload;
    """
    
    try:
        cursor.execute(query)
        row = cursor.fetchone()
        if row:
            conn.commit()
            conn.close()
            return row['id'], row['payload']
    except Exception as e:
        # Fallback for SQLite which doesn't support RETURNING or SKIP LOCKED in older versions
        cursor.execute("SELECT id, payload FROM lgnn_ingest_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE lgnn_ingest_queue SET status = 'processing' WHERE id = ?", (row['id'],))
            conn.commit()
            conn.close()
            return row['id'], row['payload']
            
    conn.commit()
    conn.close()
    return None, None

def mark_observation_done(job_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE lgnn_ingest_queue SET status = 'done' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()


def save_edge(source: str, target: str, weight: float):
    # Enforce alphabetical ordering of source/target to prevent duplicate bidirectional keys
    u, v = sorted([source, target])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO lgnn_edges (source, target, weight)
    VALUES (?, ?, ?)
    ON CONFLICT(source, target) DO UPDATE SET
        weight = excluded.weight
    """, (u, v, weight))
    conn.commit()
    conn.close()

def delete_edge(source: str, target: str):
    u, v = sorted([source, target])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lgnn_edges WHERE source = ? AND target = ?", (u, v))
    conn.commit()
    conn.close()

def load_graph_state(dim: int = 128) -> Tuple[Dict[str, torch.Tensor], List[Tuple[str, str, float]], Dict[str, Dict[str, Any]]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Load Nodes (only non-archived ones)
    cursor.execute("SELECT * FROM lgnn_nodes WHERE is_archived = 0 OR is_archived IS NULL")
    nodes = {}
    metrics = {}
    for row in cursor.fetchall():
        nid = row["id"]
        nodes[nid] = deserialize_tensor(row["embedding"], dim)
        metrics[nid] = {
            "mean_activation": row["mean_activation"],
            "confidence": row["confidence"],
            "plateau_factor": row["plateau_factor"],
            "is_grounded": bool(row["is_grounded"]),
            "help_chain": bool(row["help_chain"]),
            "source_tag": row["source_tag"] if "source_tag" in row.keys() else "internal",
            "is_quarantined": bool(row["is_quarantined"]) if "is_quarantined" in row.keys() else False,
            "node_type": row["node_type"] if "node_type" in row.keys() else "standard",
            "meta_data": row["meta_data"] if "meta_data" in row.keys() else "{}",
            "x": row["x"] if "x" in row.keys() else None,
            "y": row["y"] if "y" in row.keys() else None,
            "fx": row["fx"] if "fx" in row.keys() else None,
            "fy": row["fy"] if "fy" in row.keys() else None,
            "color": row["color"] if "color" in row.keys() else None
        }
        
    # Load Edges
    cursor.execute("SELECT * FROM lgnn_edges")
    edges = []
    for row in cursor.fetchall():
        edges.append((row["source"], row["target"], row["weight"]))
        
    conn.close()
    return nodes, edges, metrics

def search_archived_nodes(query_emb: torch.Tensor, dim: int = 128, top_k: int = 3, threshold: float = 0.75) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, embedding, text_content FROM lgnn_nodes WHERE is_archived = 1")
    
    results = []
    norm_query = query_emb / (query_emb.norm() + 1e-8)
    
    for row in cursor.fetchall():
        nid = row["id"]
        emb = deserialize_tensor(row["embedding"], dim)
        norm_emb = emb / (emb.norm() + 1e-8)
        sim = float(torch.dot(norm_query, norm_emb).detach().cpu())
        
        if sim >= threshold:
            results.append({"id": nid, "embedding": emb, "text_content": row["text_content"], "score": sim})
            
    conn.close()
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]

def unarchive_node(node_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE lgnn_nodes SET is_archived = 0, plateau_factor = 0.0 WHERE id = ?", (node_id,))
    conn.commit()
    conn.close()

def get_node_text(node_id: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT text_content FROM lgnn_nodes WHERE id = ?", (node_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row["text_content"] or ""
    return ""

def get_all_node_texts() -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, text_content FROM lgnn_nodes")
    rows = cursor.fetchall()
    conn.close()
    return {r["id"]: (r["text_content"] or "") for r in rows}

def get_node_visuals(node_id: str) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT x, y, fx, fy, color FROM lgnn_nodes WHERE id = ?", (node_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"x": row["x"], "y": row["y"], "fx": row["fx"], "fy": row["fy"], "color": row["color"]}
    return {}

def get_all_node_visuals() -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, x, y, fx, fy, color FROM lgnn_nodes")
    rows = cursor.fetchall()
    conn.close()
    
    res = {}
    for r in rows:
        res[r["id"]] = {
            "x": r["x"], "y": r["y"], "fx": r["fx"], "fy": r["fy"], "color": r["color"]
        }
    return res

def save_kanban_card(card_id: str, column_id: str, title: str, description: str, tags: List[str], node_ref: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    tags_str = json.dumps(tags)
    cursor.execute("""
    INSERT INTO kanban_cards (id, column_id, title, description, tags, node_ref)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        column_id = excluded.column_id,
        title = excluded.title,
        description = excluded.description,
        tags = excluded.tags,
        node_ref = excluded.node_ref
    """, (card_id, column_id, title, description, tags_str, node_ref))
    conn.commit()
    conn.close()

def load_kanban_board() -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch columns
    cursor.execute("SELECT * FROM kanban_columns ORDER BY sort_order ASC")
    board = {"columns": {}}
    for col in cursor.fetchall():
        board["columns"][col["id"]] = {
            "id": col["id"],
            "title": col["title"],
            "cards": []
        }
        
    # Fetch cards
    cursor.execute("SELECT * FROM kanban_cards")
    for card in cursor.fetchall():
        col_id = card["column_id"]
        if col_id in board["columns"]:
            board["columns"][col_id]["cards"].append({
                "id": card["id"],
                "title": card["title"],
                "description": card["description"],
                "tags": json.loads(card["tags"]) if card["tags"] else [],
                "node_ref": card["node_ref"]
            })
            
    conn.close()
    return board

def register_agent(agent_id: str, metadata: Dict[str, Any]):
    conn = get_db_connection()
    cursor = conn.cursor()
    meta_str = json.dumps(metadata)
    cursor.execute("""
    INSERT INTO agent_registry (agent_id, metadata, last_active)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(agent_id) DO UPDATE SET
        metadata = excluded.metadata,
        last_active = CURRENT_TIMESTAMP
    """, (agent_id, meta_str))
    conn.commit()
    conn.close()

def log_cooperation(agent_id: str, requested_skill: str, success: bool, notes: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO agent_cooperation_log (agent_id, requested_skill, success, notes, timestamp)
    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (agent_id, requested_skill, 1 if success else 0, notes))
    conn.commit()
    conn.close()

def get_agent_history(agent_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM agent_cooperation_log WHERE agent_id = ? ORDER BY timestamp DESC", (agent_id,))
    logs = []
    for row in cursor.fetchall():
        logs.append({
            "id": row["id"],
            "requested_skill": row["requested_skill"],
            "success": bool(row["success"]),
            "notes": row["notes"],
            "timestamp": row["timestamp"]
        })
    conn.close()
    return logs

def save_persona(name: str, node_ids: List[str], active: bool):
    conn = get_db_connection()
    cursor = conn.cursor()
    nodes_str = json.dumps(node_ids)
    cursor.execute("""
    INSERT INTO lgnn_personas (name, node_ids, active)
    VALUES (?, ?, ?)
    ON CONFLICT(name) DO UPDATE SET
        node_ids = excluded.node_ids,
        active = excluded.active
    """, (name, nodes_str, 1 if active else 0))
    conn.commit()
    conn.close()

def delete_persona(name: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lgnn_personas WHERE name = ?", (name,))
    conn.commit()
    conn.close()

def load_personas() -> Tuple[Dict[str, List[str]], Dict[str, bool]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM lgnn_personas")
    personas = {}
    active_status = {}
    for row in cursor.fetchall():
        name = row["name"]
        personas[name] = json.loads(row["node_ids"]) if row["node_ids"] else []
        active_status[name] = bool(row["active"])
    conn.close()
    return personas, active_status

def create_snapshot(description: str, coherence_score: float) -> str:
    """
    Creates a Git-like commit hash of the current active graph topology state
    and saves all node states, parameters, and edges into the snapshot tables.
    Also implements a retention policy: retains at most the top 10 snapshots
    (prioritizing highest coherence_score and recentness), pruning older ones.
    Returns the snapshot commit hash.
    """
    import hashlib
    import time
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Fetch current parent commit hash (most recent commit)
    cursor.execute("SELECT hash FROM lgnn_commits ORDER BY timestamp DESC LIMIT 1")
    parent_row = cursor.fetchone()
    parent_hash = parent_row["hash"] if parent_row else None
    
    # 2. Get current nodes and edges
    cursor.execute("SELECT * FROM lgnn_nodes WHERE is_archived = 0 OR is_archived IS NULL")
    nodes_rows = cursor.fetchall()
    
    cursor.execute("SELECT * FROM lgnn_edges")
    edges_rows = cursor.fetchall()
    
    # 3. Create deterministic snapshot hash
    state_content = f"{parent_hash or ''}-{coherence_score}-{time.time()}-"
    for n in sorted(nodes_rows, key=lambda x: x["id"]):
        state_content += f"{n['id']}:{n['mean_activation']:.4f}-"
    commit_hash = hashlib.sha256(state_content.encode('utf-8')).hexdigest()[:16]
    
    # 4. Insert into lgnn_commits
    cursor.execute("""
    INSERT INTO lgnn_commits (hash, parent_hash, coherence_score, description)
    VALUES (?, ?, ?, ?)
    """, (commit_hash, parent_hash, coherence_score, description))
    
    # 5. Insert versioned nodes
    for n in nodes_rows:
        cursor.execute("""
        INSERT INTO lgnn_commit_nodes (
            commit_hash, node_id, embedding, text_content, mean_activation,
            confidence, plateau_factor, is_grounded, help_chain, is_archived,
            source_tag, is_quarantined
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            commit_hash, n["id"], n["embedding"], n["text_content"], n["mean_activation"],
            n["confidence"], n["plateau_factor"], n["is_grounded"], n["help_chain"],
            n["is_archived"], n["source_tag"], n["is_quarantined"]
        ))
        
    # 6. Insert versioned edges
    for e in edges_rows:
        cursor.execute("""
        INSERT INTO lgnn_commit_edges (commit_hash, source, target, weight)
        VALUES (?, ?, ?, ?)
        """, (commit_hash, e["source"], e["target"], e["weight"]))
        
    # --- PRUNING RETENTION POLICY (Limit to 10 snapshots) ---
    # Prioritizes keeping high coherence commits, reality anchor updates, and the very latest commits.
    cursor.execute("SELECT hash, parent_hash FROM lgnn_commits ORDER BY coherence_score DESC, timestamp DESC")
    all_commits = cursor.fetchall()
    
    if len(all_commits) > 10:
        # Keep the latest, the parent of the latest, and the highest coherence ones (up to 10)
        kept_hashes = set()
        # Ensure we keep the one we just made
        kept_hashes.add(commit_hash)
        if parent_hash:
            kept_hashes.add(parent_hash)
            
        for row in all_commits:
            if len(kept_hashes) >= 10:
                break
            kept_hashes.add(row["hash"])
            
        # Delete commits not in the kept set
        for row in all_commits:
            c_hash = row["hash"]
            if c_hash not in kept_hashes:
                # Due to CASCADE foreign key definitions, this deletes commit_nodes and commit_edges too
                cursor.execute("DELETE FROM lgnn_commits WHERE hash = ?", (c_hash,))
                # Repair broken parent chains by setting children's parent to the deleted commit's parent
                cursor.execute("UPDATE lgnn_commits SET parent_hash = ? WHERE parent_hash = ?", (row["parent_hash"], c_hash))
                
    conn.commit()
    conn.close()
    return commit_hash

def checkout_snapshot(commit_hash: str, dim: int = 128) -> Tuple[bool, str]:
    """
    Overwrites the current active graph topology state in the database
    with the snapshot state from the specified commit_hash.
    Returns (success, message).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify commit exists
    cursor.execute("SELECT hash FROM lgnn_commits WHERE hash = ?", (commit_hash,))
    if not cursor.fetchone():
        conn.close()
        return False, f"Snapshot commit '{commit_hash}' not found."
        
    # 1. Purge active nodes and edges
    cursor.execute("DELETE FROM lgnn_nodes")
    cursor.execute("DELETE FROM lgnn_edges")
    
    # 2. Restore nodes from snapshot
    cursor.execute("SELECT * FROM lgnn_commit_nodes WHERE commit_hash = ?", (commit_hash,))
    for cn in cursor.fetchall():
        cursor.execute("""
        INSERT INTO lgnn_nodes (
            id, embedding, text_content, mean_activation, confidence,
            plateau_factor, is_grounded, help_chain, is_archived, source_tag, is_quarantined
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cn["node_id"], cn["embedding"], cn["text_content"], cn["mean_activation"],
            cn["confidence"], cn["plateau_factor"], cn["is_grounded"], cn["help_chain"],
            cn["is_archived"], cn["source_tag"], cn["is_quarantined"]
        ))
        
    # 3. Restore edges from snapshot
    cursor.execute("SELECT * FROM lgnn_commit_edges WHERE commit_hash = ?", (commit_hash,))
    for ce in cursor.fetchall():
        cursor.execute("""
        INSERT INTO lgnn_edges (source, target, weight)
        VALUES (?, ?, ?)
        """, (ce["source"], ce["target"], ce["weight"]))
        
    conn.commit()
    conn.close()
    return True, f"Successfully checked out snapshot '{commit_hash}'."

def get_snapshot_history() -> List[Dict[str, Any]]:
    """
    Returns a history list of all snapshot commits.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM lgnn_commits ORDER BY timestamp DESC")
    commits = []
    for row in cursor.fetchall():
        commits.append({
            "hash": row["hash"],
            "parent_hash": row["parent_hash"],
            "coherence_score": row["coherence_score"],
            "description": row["description"],
            "timestamp": row["timestamp"]
        })
    conn.close()
    return commits
