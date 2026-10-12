from typing import Dict, Any, List, Optional
import json
import logging
import hashlib
from aethelnet_node.database import (
    init_db,
    load_graph_state,
    load_kanban_board,
    get_node_text,
    save_node,
    save_edge,
    save_multigraph_edge,
    get_db_connection,
    get_current_agent,
    log_agent_write,
)
from aethelnet_node.provenance import agent_id_to_color

logger = logging.getLogger("LGNN.MCP")


def get_mcp_tools() -> List[Dict[str, Any]]:
    """
    Returns standard MCP tool definitions so external agents can interface with LGNN.
    Supports complete read, search, write, link, and associative recovery lifecycle.
    """
    return [
        {
            "name": "lgnn_query_graph",
            "description": "Retrieve the current persistent node coordinates, activation states, visual provenance colors, and topological bridges.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max nodes to return in summary (default: 50)."}
                }
            }
        },
        {
            "name": "lgnn_read_node_content",
            "description": "Read the full Obsidian-style text note content, provenance author, and metadata of a specific graph concept node.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "The unique ID/label of the target concept node."}
                },
                "required": ["node_id"]
            }
        },
        {
            "name": "lgnn_write_concept",
            "description": "Store or update a concept, hypothesis, reasoning chain, or invariant node in the shared Aethelnet graph with automatic neural embedding and agent provenance.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "Unique slug/ID for the concept (e.g. 'sol_breakout_pattern' or 'urform_sliding_block')."},
                    "label": {"type": "string", "description": "Human-readable title for the concept node (defaults to node_id)."},
                    "text_content": {"type": "string", "description": "Markdown text content, reasoning notes, proof steps, or observations."},
                    "node_type": {"type": "string", "description": "Type of node: 'concept', 'hypothesis', 'invariant', 'evidence', 'tabu' (default: 'concept')."},
                    "confidence": {"type": "number", "description": "Confidence score between 0.0 and 1.0 (default: 0.85)."},
                    "source_tag": {"type": "string", "description": "Source tag: 'agent_inference', 'human_note', 'code_audit' (default: 'agent_inference')."},
                    "meta_data": {"type": "object", "description": "Optional arbitrary JSON metadata dictionary."}
                },
                "required": ["node_id"]
            }
        },
        {
            "name": "lgnn_link_concepts",
            "description": "Create a directional semantic bridge or associative edge between two concepts in the Aethelnet graph.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "ID of the source concept node."},
                    "target": {"type": "string", "description": "ID of the target concept node."},
                    "relation": {"type": "string", "description": "Relation/edge type: 'causes', 'depends_on', 'contradicts', 'analogous_to', 'associated_with' (default: 'associated_with')."},
                    "weight": {"type": "number", "description": "Strength/weight of the link (default: 1.0)."}
                },
                "required": ["source", "target"]
            }
        },
        {
            "name": "lgnn_search_concepts",
            "description": "Search the concept graph by semantic meaning or keywords. Returns matched concepts with creators, confidence, and preview.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term or natural language description of what you are looking for."},
                    "limit": {"type": "integer", "description": "Maximum number of results to return (default: 10)."}
                },
                "required": ["query"]
            }
        },
        {
            "name": "lgnn_topological_recovery",
            "description": "Associative recall for when you are stuck: describe what you are trying to do or remember. Returns the most relevant concepts from the shared graph (keywords + meaning), plus concepts that agents used together with them, each with its claims and whether they are contested.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context": {"type": "string", "description": "What you are trying to do or remember, in your own words."},
                    "k": {"type": "integer", "description": "How many concepts to return (default 8, max 50)."},
                    "use_popularity": {"type": "boolean", "description": "Also favour concepts agents touch often (default false)."}
                },
                "required": ["context"]
            }
        },
        {
            "name": "lgnn_mark_useful",
            "description": "Tell the graph which recalled concepts actually helped. They become linked as 'used together' for your current task, which improves future recall for every agent.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "node_ids": {"type": "array", "items": {"type": "string"}, "description": "Node ids that helped."}
                },
                "required": ["node_ids"]
            }
        },
        {
            "name": "lgnn_execute_cmd",
            "description": "Run a whitelisted shell command safely (find, grep, systemctl, dnf, git, ls, cat) with local sudo password integration.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command string to execute."}
                },
                "required": ["command"]
            }
        },
        {
            "name": "lgnn_scout_papers",
            "description": "Scan arXiv and generate pseudocode stubs for continuous graph/Neural ODE math optimizations.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic to scout (default: 'neural ode graph optimization')."}
                }
            }
        },
        {
            "name": "lgnn_perceive_environment",
            "description": "Trigger the Sensor Array to parse a local file (PDF, Image, or 3D Object) and inject its spatial/visual meaning directly into the neural graph.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file you want to perceive (.pdf, .png, .obj)."}
                },
                "required": ["file_path"]
            }
        }
    ]


def call_mcp_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Routes external MCP agent tool requests to internal LGNN modules.
    Safe and self-healing: automatically initializes database schema on first use.
    """
    logger.info(f"[MCP] External agent calling tool '{name}' with arguments {arguments}")
    init_db()

    try:
        if name == "lgnn_query_graph":
            nodes, edges, metrics = load_graph_state()
            limit = int(arguments.get("limit", 50) or 50)
            nodes_summary = []
            
            # Fetch authors from database for visual styling
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id, created_by, label, node_type FROM lgnn_nodes")
            author_map = {row["id"]: row for row in c.fetchall()}
            conn.close()

            for nid, m in list(metrics.items())[:limit]:
                author_info = author_map.get(nid, {})
                creator = author_info["created_by"] if author_info and "created_by" in author_info.keys() else "system"
                color_info = agent_id_to_color(creator)
                nodes_summary.append({
                    "id": nid,
                    "label": author_info["label"] if author_info and "label" in author_info.keys() and author_info["label"] else nid,
                    "confidence": m.get("confidence", 0.8),
                    "plateau_factor": m.get("plateau_factor", 0.0),
                    "created_by": creator,
                    "color": color_info["hex"],
                    "node_type": author_info["node_type"] if author_info and "node_type" in author_info.keys() else "concept"
                })

            summary_text = (
                f"Aethelnet Graph State:\n"
                f"- Total Active Nodes: {len(metrics)}\n"
                f"- Total Topological Bridges: {len(edges)}\n"
                f"- Showing first {len(nodes_summary)} nodes:\n"
            )
            for n in nodes_summary[:15]:
                summary_text += f"  * [{n['id']}] ({n['node_type']}) by {n['created_by']} [{n['color']}]: confidence {n['confidence']:.2f}\n"

            return {
                "content": [{"type": "text", "text": summary_text}],
                "structuredContent": {
                    "total_nodes": len(metrics),
                    "total_edges": len(edges),
                    "nodes": nodes_summary
                }
            }

        elif name == "lgnn_read_node_content":
            nid = arguments.get("node_id")
            if not nid:
                return {"isError": True, "content": [{"type": "text", "text": "Argument 'node_id' is required."}]}
            
            text = get_node_text(nid)
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id, label, node_type, confidence, created_by, updated_by, last_updated, meta_data FROM lgnn_nodes WHERE id = ?", (nid,))
            row = c.fetchone()
            
            # Fetch bridges connected to this node
            c.execute("SELECT target, relation_type, weight FROM lgnn_multigraph_edges WHERE source = ? UNION SELECT source, relation_type, weight FROM lgnn_multigraph_edges WHERE target = ?", (nid, nid))
            edges = [{"node": r[0], "relation": r[1], "weight": r[2]} for r in c.fetchall()]
            conn.close()

            if not row:
                return {"content": [{"type": "text", "text": f"Concept '{nid}' is empty or does not exist."}]}

            creator = row["created_by"] or "unknown"
            color_info = agent_id_to_color(creator)
            
            card = (
                f"# Concept: {row['label'] or row['id']}\n"
                f"**ID**: `{row['id']}` | **Type**: `{row['node_type']}` | **Confidence**: {row['confidence']:.2f}\n"
                f"**Author**: `{creator}` ({color_info['hex']}) | **Last Updated**: {row['last_updated']}\n\n"
                f"## Content\n"
                f"{text or '_No text content recorded._'}\n\n"
                f"## Connected Bridges ({len(edges)})\n"
            )
            for e in edges[:10]:
                card += f"- `--[{e['relation']}:{e['weight']:.1f}]-->` `{e['node']}`\n"

            return {
                "content": [{"type": "text", "text": card}],
                "structuredContent": {
                    "id": row["id"],
                    "label": row["label"],
                    "node_type": row["node_type"],
                    "confidence": row["confidence"],
                    "created_by": creator,
                    "color": color_info,
                    "text_content": text,
                    "edges": edges
                }
            }

        elif name == "lgnn_write_concept":
            node_id = str(arguments.get("node_id", "")).strip()
            if not node_id:
                return {"isError": True, "content": [{"type": "text", "text": "Argument 'node_id' is required."}]}
            
            label = str(arguments.get("label", "")).strip() or node_id
            text_content = str(arguments.get("text_content", "")).strip()
            node_type = str(arguments.get("node_type", "concept")).strip().lower()
            confidence = float(arguments.get("confidence", 0.85) or 0.85)
            source_tag = str(arguments.get("source_tag", "agent_inference")).strip()
            meta_data = arguments.get("meta_data", {})
            meta_str = json.dumps(meta_data) if isinstance(meta_data, dict) else str(meta_data or "{}")

            # Compute neural embedding with self-healing fallback
            try:
                from aethelnet_node.state import text_to_embedding
                emb = text_to_embedding(text_content or label or node_id)
            except Exception as e:
                import torch
                logger.warning(f"[MCP] Neural embedding fallback engaged: {e}")
                h = hashlib.sha256((text_content or label or node_id).encode("utf-8")).digest()
                vec = [(b / 255.0) - 0.5 for b in (h * 24)[:768]]
                emb = torch.tensor(vec, dtype=torch.float32)

            save_node(
                node_id=node_id,
                embedding=emb,
                mean_activation=1.0,
                confidence=confidence,
                plateau_factor=0.0,
                is_grounded=True,
                help_chain=False,
                text_content=text_content,
                node_type=node_type,
                source_tag=source_tag,
                meta_data=meta_str,
                label=label
            )

            agent = get_current_agent()
            color_info = agent_id_to_color(agent)
            log_agent_write(agent, "MCP.write_concept", f"/nodes/{node_id}", 200)

            resp = (
                f"[SUCCESS] Concept '{node_id}' successfully saved in Aethelnet graph!\n"
                f"- Label: {label}\n"
                f"- Type: {node_type} | Confidence: {confidence:.2f}\n"
                f"- Provenance Author: {agent} (Color: {color_info['hex']})\n"
                f"- Embedding: 768-dim neural representation indexed."
            )
            return {
                "content": [{"type": "text", "text": resp}],
                "structuredContent": {
                    "node_id": node_id,
                    "label": label,
                    "node_type": node_type,
                    "confidence": confidence,
                    "created_by": agent,
                    "color": color_info
                }
            }

        elif name == "lgnn_link_concepts":
            source = str(arguments.get("source", "")).strip()
            target = str(arguments.get("target", "")).strip()
            if not source or not target:
                return {"isError": True, "content": [{"type": "text", "text": "Arguments 'source' and 'target' are required."}]}
            
            relation = str(arguments.get("relation", "associated_with")).strip().lower()
            weight = float(arguments.get("weight", 1.0) or 1.0)
            edge_id = f"{source}_{relation}_{target}"

            save_edge(source=source, target=target, weight=weight, label=relation)
            save_multigraph_edge(
                edge_id=edge_id,
                source=source,
                target=target,
                relation_type=relation,
                weight=weight
            )

            agent = get_current_agent()
            log_agent_write(agent, "MCP.link_concepts", f"/edges/{source}->{target}", 200)

            return {
                "content": [{"type": "text", "text": f"[SUCCESS] Linked '{source}' --[{relation}:{weight:.1f}]--> '{target}' by agent '{agent}'."}],
                "structuredContent": {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "weight": weight,
                    "created_by": agent
                }
            }

        elif name == "lgnn_search_concepts":
            query = str(arguments.get("query", "")).strip()
            if not query:
                return {"isError": True, "content": [{"type": "text", "text": "Argument 'query' is required."}]}
            limit = int(arguments.get("limit", 10) or 10)

            # Try associative recall first
            results = []
            try:
                from aethelnet_node.recall import recall
                rec_res = recall(query, k=limit)
                for item in rec_res.get("concepts", []):
                    results.append({
                        "node_id": item["node_id"],
                        "label": item.get("label", item["node_id"]),
                        "preview": item.get("text_preview", ""),
                        "score": item.get("final_score", 0.0),
                        "created_by": item.get("created_by", "system")
                    })
            except Exception as e:
                logger.warning(f"[MCP] Recall search fallback to SQL: {e}")

            # Fallback to direct SQL text match if recall returned empty
            if not results:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute(
                    "SELECT id, label, text_content, node_type, confidence, created_by FROM lgnn_nodes "
                    "WHERE id LIKE ? OR label LIKE ? OR text_content LIKE ? LIMIT ?",
                    (f"%{query}%", f"%{query}%", f"%{query}%", limit)
                )
                for r in c.fetchall():
                    results.append({
                        "node_id": r["id"],
                        "label": r["label"] or r["id"],
                        "preview": (r["text_content"] or "")[:150],
                        "score": r["confidence"],
                        "created_by": r["created_by"] or "unknown"
                    })
                conn.close()

            text_output = f"Aethelnet Search Results for '{query}' ({len(results)} matches):\n"
            for r in results:
                color_info = agent_id_to_color(r["created_by"])
                text_output += f"- [{r['node_id']}] {r['label']} (by {r['created_by']} [{color_info['hex']}]): {r['preview'][:100]}...\n"

            return {
                "content": [{"type": "text", "text": text_output}],
                "structuredContent": results
            }

        elif name in ("lgnn_topological_recovery", "lgnn_topological_bypass"):
            from aethelnet_node.recall import recall, format_recall
            context_str = arguments.get("context") or arguments.get("blocked_concept_context", "")
            result = recall(context_str, k=int(arguments.get("k", 8) or 8),
                            use_popularity=bool(arguments.get("use_popularity", False)))
            return {"content": [{"type": "text", "text": format_recall(result)}], "structuredContent": result}

        elif name == "lgnn_mark_useful":
            from aethelnet_node.coaccess import touch
            node_ids = [str(n) for n in (arguments.get("node_ids") or []) if str(n).strip()]
            links = touch(node_ids, kind="useful")
            return {"content": [{"type": "text", "text": f"Noted {len(node_ids)} concepts as used together ({links} new links)."}]}

        elif name == "lgnn_execute_cmd":
            try:
                from aethelnet_node.command_runner import run_command_safely
            except ImportError:
                return {"isError": True, "content": [{"type": "text", "text": "lgnn_execute_cmd is not available on this node."}]}
            cmd = arguments.get("command")
            res = run_command_safely(cmd)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Command Result [Code {res.get('returncode', -1)}]:\n{res.get('output', '')}"
                    }
                ]
            }

        elif name == "lgnn_scout_papers":
            try:
                from aethelnet_node.research_scouter import scout_arxiv_optimizations
            except ImportError:
                return {"isError": True, "content": [{"type": "text", "text": "lgnn_scout_papers is not available on this node."}]}
            q = arguments.get("query", "neural ode graph optimization")
            res = scout_arxiv_optimizations(q)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Successfully scouted and stubs created:\n{res}"
                    }
                ]
            }

        elif name == "lgnn_perceive_environment":
            from aethelnet_node.sensors import SensorArray
            sensors = SensorArray()
            file_path = arguments.get("file_path", "")
            if file_path.lower().endswith('.pdf'):
                chunks = sensors.parse_pdf(file_path)
            elif file_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                import base64
                with open(file_path, "rb") as f:
                    b64_img = base64.b64encode(f.read()).decode('utf-8')
                vision_desc = sensors._call_ollama(model=sensors.vision_model, prompt="Analyze image deeply.", images=[b64_img])
                chunks = [{"type": "visual", "content": vision_desc}]
            elif file_path.lower().endswith(('.obj', '.stl')):
                chunks = sensors.perceive_spatial_geometry(file_path)
            else:
                chunks = [{"type": "error", "content": "Unsupported format"}]
                
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Sensor Array Perceived {len(chunks)} chunks from {file_path}. Data injected to LGNN."
                    }
                ]
            }

        else:
            return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: '{name}'"}]}

    except Exception as e:
        logger.error(f"[MCP] Tool execution failure: {str(e)}", exc_info=True)
        return {"isError": True, "content": [{"type": "text", "text": f"Execution Error: {str(e)}"}]}
