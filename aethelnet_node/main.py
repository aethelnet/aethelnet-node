import os
import socket
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from aethelnet_node.database import init_db
from aethelnet_node.state import (
    graph_instance, node_metrics, text_to_embedding,
    load_all_from_db, get_known_peers, HIDDEN_DIM,
    REALITY_ANCHORS, DEFAULT_CONFIDENCE, KNOWLEDGE_CONFIDENCE, DOCUMENT_CONFIDENCE
)
from aethelnet_node.daemons import start_all_daemons
from aethelnet_node.security import token_auth_middleware, get_cors_origins, log_security_posture

# Re-exports for backward compatibility with existing tests & legacy modules
__all__ = [
    "app", "graph_instance", "node_metrics", "text_to_embedding",
    "load_all_from_db", "HIDDEN_DIM", "REALITY_ANCHORS"
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Aethelnet.Node")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern FastAPI lifespan context: initializes database, loads graph state,
    and launches autonomous background cognitive daemons.
    """
    logger.info("[Aethelnet Node] Initializing database and storage...")
    init_db()
    load_all_from_db()
    
    app.state.graph_instance = graph_instance
    app.state.node_metrics = node_metrics
    app.state.text_to_embedding = text_to_embedding
    
    logger.info("[Aethelnet Node] Starting autonomous cognitive daemons...")
    tasks = start_all_daemons()
    
    yield
    
    logger.info("[Aethelnet Node] Shutting down daemons...")
    for task in tasks:
        task.cancel()

app = FastAPI(
    title="Aethelnet Node",
    version="2.0.0",
    description="Decentralized Liquid Graph Neural Network Node & Cognitive Substrate",
    lifespan=lifespan
)

# Token authentication for state-changing requests (see aethelnet_node/security.py)
app.middleware("http")(token_auth_middleware)
log_security_posture()

# CORS Setup (AETHELNET_CORS_ORIGINS, comma-separated; defaults to all origins without credentials)
_cors_origins = get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static media mount for Ingest Zone
ingest_zone = os.path.expanduser("~/.aethelnet/ingest_zone")
os.makedirs(ingest_zone, exist_ok=True)
app.mount("/media", StaticFiles(directory=ingest_zone), name="media")

# --- ROUTER REGISTRATION ---
from aethelnet_node.routers.p2p import router as p2p_router
from aethelnet_node.routers.graph import router as graph_router
from aethelnet_node.routers.cognitive import router as cognitive_router
from aethelnet_node.routers.snapshots import router as snapshots_router
from aethelnet_node.routers.economy import router as economy_router
from aethelnet_node.routers.telemetry import router as telemetry_router
from aethelnet_node.routers.node_runtime import router as compute_router
from aethelnet_node.routers.system_apps import router as system_apps_router
from aethelnet_node.routers.ontology import router as ontology_router
from aethelnet_node.routers.osint import router as osint_router

# Ontology & Multigraph V3 endpoints
app.include_router(ontology_router, tags=["Ontology & Multigraph"])
app.include_router(osint_router, tags=["Live OSINT Feeds"])

# P2P and Synapse WebSocket endpoints
app.include_router(p2p_router, tags=["P2P Network"])
app.include_router(p2p_router, prefix="/api", tags=["P2P Network"])

# Graph & Ingestion endpoints
app.include_router(graph_router, prefix="/api/lgnn", tags=["Graph & Ingestion"])
# File ingest also available at root /api/ingest/file for frontend compatibility
from aethelnet_node.routers.graph import ingest_file, FileIngestRequest
app.add_api_route("/api/ingest/file", ingest_file, methods=["POST"], tags=["Graph & Ingestion"])

# Cognitive, Personas, and Multi-Provider LLM Synthesis endpoints
app.include_router(cognitive_router, prefix="/api/lgnn", tags=["Cognitive & Synthesis"])

# Snapshots, Versioning, and LiquidGraph state persistence
app.include_router(snapshots_router, prefix="/api/lgnn", tags=["Snapshots & Versioning"])

# Economy & Capability Registry
app.include_router(economy_router, prefix="/api/lgnn", tags=["Economy & Market"])

# Dashboard WebSocket Viewport Streaming
app.include_router(telemetry_router, tags=["Telemetry Stream"])

# Compute Runtime & System Apps
app.include_router(compute_router, prefix="/api/lgnn", tags=["Node Compute Runtime"])
app.include_router(system_apps_router, prefix="/api/lgnn", tags=["System Apps"])

# Obsidian Vault Synchronization Engine
from aethelnet_node.routers.vault import router as vault_router
app.include_router(vault_router, prefix="/api/lgnn", tags=["Obsidian Vault"])

# Agent identities: whoami + registered agents with provenance counts
from aethelnet_node.routers.agents import router as agents_router
app.include_router(agents_router, prefix="/api", tags=["Agents"])

@app.get("/", tags=["System Vitals"])
def health():
    connected = False
    contract_addr = None
    try:
        from aethelnet_node.forge_client import forge_client
        connected = forge_client.is_connected()
        contract_addr = forge_client.contract_address
    except Exception:
        pass

    return {
        "status": "operational",
        "node": socket.gethostname(),
        "peers_active_on_chain": len(get_known_peers()),
        "forge_contract": contract_addr,
        "forge_connected": connected,
        "nodes_in_ram": len(graph_instance.nodes),
        "bridges_in_ram": graph_instance.nx_graph.number_of_edges()
    }


@app.get("/api/dossier/generate")
@app.get("/dossier/generate")
def legacy_dossier_redirect(case_id: str = "project_echo", format: str = "html"):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/api/ontology/multigraph/{case_id}/dossier?format={format}")

