# Aethelnet Node 🕸️📡

**Aethelnet Node** is the execution, API, and P2P layer that brings the `aethelnet-core` mathematical engine to life. It serves as a persistent, autonomous entity capable of crawling the web, ingesting data, and communicating with other nodes.

## Core Features

- **Asynchronous Hygiene Ingestion:** Features a robust `SKIP LOCKED` PostgreSQL/SQLite queue for high-throughput data ingestion (e.g., from web spiders) without locking the main execution thread.
- **MsgPack Binary P2P Protocol:** Nodes gossip and share "Grains of Truth" with each other using a highly compressed binary protocol, cutting bandwidth costs by 80-90% compared to JSON.
- **Living Loop:** An autonomous background process (`living_loop.py`) that constantly evaluates graph confidence, breaks conceptual plateaus by crawling for opposing viewpoints, and prunes toxic nodes.
- **OmniRouter Bridge:** Connects high-activation, deeply verified graph concepts to real-world execution (e.g., automated trading or server actions).

## Architecture Stack

- **Framework:** FastAPI / Uvicorn
- **Database:** PostgreSQL (Cloud) / SQLite (Local) with abstract cursor wrappers.
- **Engine:** `aethelnet-core` LGNN 
- **Networking:** Async HTTPX & MsgPack Binary Serialization

## Setup

```bash
pip install -r requirements.txt
# Ensure aethelnet-core is installed
```

## Running the Node

Start the background engine and API layer:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Start the autonomous Spider to feed the graph:
```bash
python -m aethelnet_node.spider
```
