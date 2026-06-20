# The Aethelburg Ecosystem: Observer Guide

Welcome to the Aethelburg Ecosystem. This guide covers how to interact with your local **Monadic Core** (the Aethelnet Node) using the **Observer** web interface.

## 1. The Monadic Architecture

Your Aethelnet setup consists of two entirely decoupled layers:
*   **The Monadic Core (`aethelnet-node`)**: The offline-first Python backend running the LGNN (Liquid Graph Neural Network) and ODE topological evolution.
*   **The Observer (`aethelnet-observer`)**: The Vue/Vite-based 3D HUD that visualizes the manifold in real-time.

By design, the Core has no windows. It requires the Observer to give you visual access to the topological data.

## 2. Navigating the Manifold

### Subgraph Dive-In (`[ DIVE ]`)
The graph is not flat. It is hierarchical and deeply nested. 
When viewing a complex Node (like a Macro or a Folder), you can press the **`[ DIVE ]`** button in the Node Inspector panel. 
This action instructs the backend to filter the topology down to just the children of that specific `parent_id`. You are now inside a sub-monad.

To return to the global view, simply hit the **Root** or **Back** button in the top navigation bar.

## 3. The Command Palette (`Cmd+K` / `Ctrl+K`)

The Observer HUD includes a global Command Palette that directly triggers System Apps inside the Monadic Core.

### `/spider <url>`
**Autonomous Knowledge Ingestion.**
Typing `/spider https://example.com` dispatches a Web Spider node. The backend will autonomously crawl the URL, extract headings, metadata, and links, and instantly plant them into the graph topology around a central spider node.

### `/exec <node_id>`
**Macro Execution.**
Typing `/exec Macro_123` triggers a complex research or execution chain. The backend will parse the inputs of the given Node, run any predefined automated logic (e.g., querying external literature or evaluating algorithms), and generate output nodes dynamically.

### `/naas <node_id>`
**Node-as-a-Service Execution.**
If you have created a Script Node (Python/Lua), typing `/naas <node_id>` commands the Core to execute the code inside its secure sandbox. The console output and results will instantly materialize as child nodes in the graph.

## 4. The Time Machine (Reality Forks)
At the bottom of the Observer UI, the Timeline HUD allows you to scrub through the history of the graph's evolution. Dragging the slider back in time will issue a `fork_reality` command to the WebSocket, instructing the backend to prune any nodes that did not exist at that specific timestamp. 

*Warning: Forking reality permanently branches the ODE timeline. Use with caution.*

---
*“A monad has no windows through which anything could come in or go out. But in its reflection, it contains the universe.”*
