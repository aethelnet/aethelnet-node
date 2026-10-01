# The Aethelburg Ecosystem: Operational & Investigation Guide

Welcome to the **Aethelburg Cognitive Ecosystem**. This guide explains how to operate, query, and investigate using the **Aethelnet Node** (`packages/aethelnet-node`) and the **Aethelnet Observer** (`apps/aethelnet-observer`).

---

## 1. System Topology & Dual Interaction Modes

The ecosystem operates across two decoupled surfaces:
1. **The Daemon Core (`aethelnet-node`)**:
   Runs headless on `server-141` (`https://aethelburg.network:8000`), executing continuous ODE state updates, SQLite WAL multigraph transactions, epistemic weighting, and on-chain notarization.
2. **The Observer Workspace (`apps/aethelnet-observer`)**:
   A Daylight Brutalism styled single-page application built on Vue 3, Vite, and D3/Three.js, providing interactive graph navigation, conflict analysis, and command orchestration.

---

## 2. Navigating the Evidentiary Multigraph

### 2.1 Case Selection & Schema Inspector
Investigations are partitioned by `app_id` (e.g. `project_echo`, `supply_chain_provenance`). In the top navigation:
* Select an active case from the dropdown.
* The header displays real-time metrics: active nodes, total edges, contested claims, and the Merkle SHA-256 state root.

### 2.2 Conflict & Dissonance Resolution Panel
When contradictory claims are detected (e.g., competing assertions regarding provenance or ownership):
1. Open the **Conflicts Panel** (`Ctrl+Shift+C` or click the balance scales icon).
2. Review the differential weight:
   $$\Delta W = |W_{\text{claim}_1} - W_{\text{claim}_2}|$$
3. If $\Delta W \ge 0.15$, the dispute is marked **Decisive Resolution** (`DEADLOCK_RESOLVED_DECISIVE`).
4. If $\Delta W < 0.04$, an **Epistemic Deadlock** is flagged (`DEADLOCK_TRIGGERED`), allowing human investigators to inspect source documents or provide supplementary evidence.

### 2.3 Entity Resolution & Disjoint-Set Deduplication
Historical archives frequently fragment identical entities across alternate spellings, inventory numbers, and titles:
1. Click **Scan Duplicates** to run the disjoint-set fuzzy clustering engine.
2. Review suggested alias pairs (e.g., `Hauptmann von Puttkamer` $\to$ `Jesko von Puttkamer`).
3. Click **Consolidate Entities** to execute atomic graph re-wiring: all incident edges are redirected to the canonical primary entity, and orphaned alias nodes are pruned.

---

## 3. The 3D Manifold & Monadic Diving

### Subgraph Dive-In (`[ DIVE ]`)
The graph is hierarchical. Complex entities (such as organizations, expeditions, or archival batches) contain child concepts:
* Click any clustered node in the 3D canvas and press **`[ DIVE ]`** in the Inspector panel.
* The viewport smoothly filters down to the sub-topology of that specific parent entity.
* Press **Root** or **Esc** to return to the global manifold.

---

## 4. The Observer Command Palette (`Cmd+K` / `Ctrl+K`)

The global Command Palette directly triggers backend operations on the node:

### `/spider <url>`
**Autonomous Knowledge Ingestion.**
Crawls the specified target URL, extracts semantic entities and predicates, matches them against institutional authority tiers, and commits them to the active multigraph.

### `/ingest <text>`
**Direct Dossier Ingestion.**
Sends raw text or Markdown to the zero-shot extraction pipeline. Automatically generates deterministic SHA-256 claim hashes and evaluates epistemic weights.

### `/notarize`
**On-Chain Merkle Root Notarization.**
Computes the canonical state root across all active nodes and edges, then submits an ERC-4337 gasless transaction to `TheForge.sol` via `AethelnetPaymaster.sol`.

### `/dedup`
**Run Disjoint-Set Entity Scan.**
Probes the active case for alias variants and presents consolidation proposals.

---

## 5. Timeline HUD & Time-Travel Debugging

At the bottom of the Observer UI, the Timeline HUD tracks graph evolution across time:
* Scrub backward through timestamps to inspect graph topology prior to specific document ingestions.
* Useful for auditing when an epistemic contradiction first entered the system and which document introduced the discrepancy.

---

*“A monad has no windows through which anything could come in or go out. But in its reflection, it contains the universe.”*
