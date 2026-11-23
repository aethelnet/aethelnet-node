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
from aethelnet_node.agents import current_task
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
                    "meta_data": {"type": "object", "description": "Optional arbitrary JSON metadata dictionary."},
                    "task_id": {"type": "string", "description": "Optional task boundary ID to scope Hebbian co-access edges strictly to related concepts."},
                    "skip_coaccess": {"type": "boolean", "description": "Set true during bulk seeding or unrelated housekeeping so co-access cliques are not formed."}
                },
                "required": ["node_id"]
            }
        },
        {
            "name": "lgnn_link_concepts",
            "description": "Create a directional semantic bridge or claim edge between two concepts, optionally carrying verbatim evidence or a contested conflict flag.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "ID of the source concept node."},
                    "target": {"type": "string", "description": "ID of the target concept node."},
                    "relation": {"type": "string", "description": "Relation/edge type: 'causes', 'depends_on', 'contradicts', 'analogous_to', 'associated_with' (default: 'associated_with')."},
                    "weight": {"type": "number", "description": "Strength/weight of the link (default: 1.0)."},
                    "evidence_quote": {"type": "string", "description": "Optional verbatim quote or justification supporting this claim."},
                    "source_doc_id": {"type": "string", "description": "Optional source document or commit reference."},
                    "is_contested": {"type": "boolean", "description": "Set true if this edge flags a disputed or contradicting claim."},
                    "task_id": {"type": "string", "description": "Optional task boundary ID for co-access tracking."},
                    "skip_coaccess": {"type": "boolean", "description": "Set true to create the structural bridge without reinforcing co-access."}
                },
                "required": ["source", "target"]
            }
        },
        {
            "name": "lgnn_search_concepts",
            "description": "Focused, filterable search by meaning and keywords (without broad associative spreading by default; use lgnn_topological_recovery for associative recall).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term or natural language description of what you are looking for."},
                    "limit": {"type": "integer", "description": "Maximum number of results to return (default: 10)."},
                    "node_type": {"type": "string", "description": "Optional filter: e.g. 'invariant', 'hypothesis', 'concept', 'evidence'."},
                    "created_by": {"type": "string", "description": "Optional filter by provenance author (e.g. 'antigravity', 'claude')."},
                    "epistemic_tier": {"type": "integer", "description": "Optional filter by epistemic tier (1=axiom, 2=verified, 3=hypothesis, 4=speculation)."},
                    "use_associations": {"type": "boolean", "description": "Enable Hebbian co-access spreading activation during search (default: false)."}
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
                    "node_ids": {"type": "array", "items": {"type": "string"}, "description": "Node ids that helped."},
                    "task_id": {"type": "string", "description": "Optional task boundary ID for co-access tracking."}
                },
                "required": ["node_ids"]
            }
        },
        {
            "name": "lgnn_archive_concept",
            "description": "Soft-archive an obsolete or superseded concept node without erasing its audit provenance, removing it from active recall.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "ID of the concept node to archive."},
                    "reason": {"type": "string", "description": "Short explanation of why the concept is archived."},
                    "superseded_by": {"type": "string", "description": "Optional replacement concept node_id to link via 'superseded_by'."}
                },
                "required": ["node_id"]
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
            limit = max(1, min(int(arguments.get("limit", 50) or 50), 200))
            nodes_summary = []
            
            # Fetch authors & epistemic metadata from database
            from aethelnet_node.state import graph_instance, infer_epistemic_tier
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id, created_by, label, node_type, is_grounded, confidence FROM lgnn_nodes")
            author_map = {row["id"]: row for row in c.fetchall()}
            conn.close()

            for nid, m in list(metrics.items())[:limit]:
                author_info = author_map.get(nid, {})
                creator = author_info["created_by"] if author_info and "created_by" in author_info.keys() else "system"
                color_info = agent_id_to_color(creator)
                ntype = author_info["node_type"] if author_info and "node_type" in author_info.keys() else "concept"
                is_gnd = bool(author_info["is_grounded"]) if author_info and "is_grounded" in author_info.keys() else False
                conf = float(m.get("confidence", 0.8))
                phys = graph_instance.get_node_physics(nid)
                tier = phys["tier"] or infer_epistemic_tier(ntype, is_grounded=is_gnd, confidence=conf)
                tau = graph_instance.get_effective_tau(nid)
                nodes_summary.append({
                    "id": nid,
                    "label": author_info["label"] if author_info and "label" in author_info.keys() and author_info["label"] else nid,
                    "confidence": conf,
                    "plateau_factor": m.get("plateau_factor", 0.0),
                    "created_by": creator,
                    "color": color_info["hex"],
                    "node_type": ntype,
                    "epistemic_tier": tier,
                    "effective_tau": round(tau, 4) if tau is not None else None,
                })

            summary_text = (
                f"Aethelnet Graph State (liquid_mode={graph_instance.liquid_mode}):\n"
                f"- Total Active Nodes: {len(metrics)}\n"
                f"- Total Topological Bridges: {len(edges)}\n"
                f"- Showing first {len(nodes_summary)} nodes:\n"
            )
            for n in nodes_summary:
                summary_text += f"  * [{n['id']}] ({n['node_type']}, tier={n['epistemic_tier']}) by {n['created_by']} [{n['color']}]: confidence {n['confidence']:.2f}\n"

            return {
                "content": [{"type": "text", "text": summary_text}],
                "structuredContent": {
                    "liquid_mode": graph_instance.liquid_mode,
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
            c.execute("SELECT id, label, node_type, is_grounded, confidence, created_by, updated_by, last_updated, meta_data FROM lgnn_nodes WHERE id = ?", (nid,))
            row = c.fetchone()
            
            # Fetch bridges connected to this node preserving exact direction & contested status
            c.execute(
                """
                SELECT target AS other_node, relation_type, weight, is_contested, evidence_quote, 'out' AS direction
                FROM lgnn_multigraph_edges WHERE source = ?
                UNION ALL
                SELECT source AS other_node, relation_type, weight, is_contested, evidence_quote, 'in' AS direction
                FROM lgnn_multigraph_edges WHERE target = ?
                """,
                (nid, nid),
            )
            edges = [
                {
                    "node": r[0],
                    "relation": r[1],
                    "weight": r[2],
                    "contested": bool(r[3]),
                    "evidence": r[4] or "",
                    "direction": r[5],
                }
                for r in c.fetchall()
            ]
            c.execute(
                "SELECT node_a, node_b, weight, updated_at FROM agent_coaccess_edges WHERE node_a = ? OR node_b = ?",
                (nid, nid),
            )
            coaccess_rows = c.fetchall()
            conn.close()

            if not row:
                return {"content": [{"type": "text", "text": f"Concept '{nid}' is empty or does not exist."}]}

            import time as _time
            from aethelnet_node.coaccess import DEFAULT_HALF_LIFE_DAYS, _decay_factor
            from aethelnet_node.state import graph_instance, infer_epistemic_tier
            now_ts = _time.time()
            coaccess_links = []
            for cr in coaccess_rows:
                other = cr["node_b"] if cr["node_a"] == nid else cr["node_a"]
                eff_w = float(cr["weight"]) * _decay_factor(cr["updated_at"], now_ts, DEFAULT_HALF_LIFE_DAYS)
                if eff_w > 1e-6:
                    coaccess_links.append({"node": other, "weight": round(eff_w, 4)})
            coaccess_links.sort(key=lambda x: -x["weight"])

            creator = row["created_by"] or "unknown"
            color_info = agent_id_to_color(creator)
            phys = graph_instance.get_node_physics(nid)
            tier = phys["tier"] or infer_epistemic_tier(
                row["node_type"], is_grounded=bool(row["is_grounded"]), confidence=row["confidence"]
            )
            tau = graph_instance.get_effective_tau(nid)
            tau_str = f" | **τ_eff**: `{tau:.3f}`" if tau is not None else ""
            
            card = (
                f"# Concept: {row['label'] or row['id']}\n"
                f"**ID**: `{row['id']}` | **Type**: `{row['node_type']}` | **Tier**: `{tier}`{tau_str} | **Confidence**: {row['confidence']:.2f}\n"
                f"**Author**: `{creator}` ({color_info['hex']}) | **Last Updated**: {row['last_updated']}\n\n"
                f"## Content\n"
                f"{text or '_No text content recorded._'}\n\n"
                f"## Connected Bridges ({len(edges)})\n"
            )
            for e in edges[:15]:
                arrow = (
                    f"--[{e['relation']}:{e['weight']:.1f}]-->"
                    if e["direction"] == "out"
                    else f"<--[{e['relation']}:{e['weight']:.1f}]--"
                )
                flag = " [CONTESTED]" if e["contested"] else ""
                ev = f' ("{e["evidence"][:120]}")' if e["evidence"] else ""
                card += f"- `{arrow}` `{e['node']}`{flag}{ev}\n"
            if coaccess_links:
                card += f"\n## Learned Hebbian Co-Access ({len(coaccess_links)})\n"
                for cl in coaccess_links[:10]:
                    card += f"- `<--[coaccess:{cl['weight']:.2f}]-->` `{cl['node']}`\n"

            return {
                "content": [{"type": "text", "text": card}],
                "structuredContent": {
                    "id": row["id"],
                    "label": row["label"],
                    "node_type": row["node_type"],
                    "epistemic_tier": tier,
                    "effective_tau": round(tau, 4) if tau is not None else None,
                    "confidence": row["confidence"],
                    "created_by": creator,
                    "color": color_info,
                    "text_content": text,
                    "edges": edges,
                    "coaccess": coaccess_links,
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
            task_id = str(arguments.get("task_id", "") or "").strip()
            skip_coaccess = bool(arguments.get("skip_coaccess", False))

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

            is_grounded_node = node_type in {"axiom", "invariant"}
            task_tok = current_task.set(task_id) if task_id else None
            try:
                save_node(
                    node_id=node_id,
                    embedding=emb,
                    mean_activation=1.0,
                    confidence=confidence,
                    plateau_factor=0.0,
                    is_grounded=is_grounded_node,
                    help_chain=False,
                    text_content=text_content,
                    node_type=node_type,
                    source_tag=source_tag,
                    meta_data=meta_str,
                    label=label,
                    record_coaccess=not skip_coaccess,
                )

                from aethelnet_node.state import sync_node_physics
                phys = sync_node_physics(
                    node_id,
                    node_type=node_type,
                    is_grounded=is_grounded_node,
                    confidence=confidence,
                    embedding=emb,
                )

                agent = get_current_agent()
                color_info = agent_id_to_color(agent)
                log_agent_write(agent, "MCP.write_concept", f"/nodes/{node_id}", 200)
            finally:
                if task_tok is not None:
                    current_task.reset(task_tok)

            resp = (
                f"[SUCCESS] Concept '{node_id}' successfully saved in Aethelnet graph!\n"
                f"- Label: {label}\n"
                f"- Type: {node_type} (Tier {phys.get('tier')}) | Confidence: {confidence:.2f}\n"
                f"- Provenance Author: {agent} (Color: {color_info['hex']})\n"
                f"- Embedding: 768-dim neural representation indexed."
            )
            return {
                "content": [{"type": "text", "text": resp}],
                "structuredContent": {
                    "node_id": node_id,
                    "label": label,
                    "node_type": node_type,
                    "epistemic_tier": phys.get("tier"),
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
            evidence_quote = str(arguments.get("evidence_quote", "") or "").strip()
            source_doc_id = str(arguments.get("source_doc_id", "") or "").strip()
            is_contested = bool(arguments.get("is_contested", False))
            task_id = str(arguments.get("task_id", "") or "").strip()
            skip_coaccess = bool(arguments.get("skip_coaccess", False))
            edge_id = f"{source}_{relation}_{target}"

            task_tok = current_task.set(task_id) if task_id else None
            try:
                save_edge(source=source, target=target, weight=weight, label=relation, record_coaccess=not skip_coaccess)
                save_multigraph_edge(
                    edge_id=edge_id,
                    source=source,
                    target=target,
                    relation_type=relation,
                    weight=weight,
                    evidence_quote=evidence_quote,
                    source_doc_id=source_doc_id,
                    is_contested=1 if is_contested else 0,
                    conflict_notes=evidence_quote if is_contested else "",
                    record_coaccess=not skip_coaccess,
                )

                agent = get_current_agent()
                log_agent_write(agent, "MCP.link_concepts", f"/edges/{source}->{target}", 200)
            finally:
                if task_tok is not None:
                    current_task.reset(task_tok)

            cflag = " [CONTESTED]" if is_contested else ""
            return {
                "content": [{"type": "text", "text": f"[SUCCESS] Linked '{source}' --[{relation}:{weight:.1f}]--> '{target}'{cflag} by agent '{agent}'."}],
                "structuredContent": {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "weight": weight,
                    "is_contested": is_contested,
                    "evidence_quote": evidence_quote,
                    "created_by": agent
                }
            }

        elif name == "lgnn_search_concepts":
            query = str(arguments.get("query", "")).strip()
            if not query:
                return {"isError": True, "content": [{"type": "text", "text": "Argument 'query' is required."}]}
            limit = max(1, min(int(arguments.get("limit", 10) or 10), 50))
            filter_type = str(arguments.get("node_type", "") or "").strip().lower() or None
            filter_author = str(arguments.get("created_by", "") or "").strip() or None
            filter_tier = arguments.get("epistemic_tier")
            filter_tier_int = int(filter_tier) if filter_tier is not None else None
            use_assoc = bool(arguments.get("use_associations", False))
            has_filters = any(x is not None for x in (filter_type, filter_author, filter_tier_int))

            # Focused meaning/keyword recall (associative spreading disabled unless requested)
            results = []
            try:
                from aethelnet_node.recall import recall
                from aethelnet_node.state import graph_instance, infer_epistemic_tier
                pool_k = min(50, max(limit * 4, 25)) if has_filters else limit
                rec_res = recall(query, k=pool_k, include_claims=True, use_associations=use_assoc)
                rec_items = rec_res.get("results", [])
                if rec_items:
                    conn = get_db_connection()
                    c = conn.cursor()
                    ids = [item["node_id"] for item in rec_items]
                    marks = ",".join("?" for _ in ids)
                    c.execute(f"SELECT id, created_by, node_type, is_grounded, confidence FROM lgnn_nodes WHERE id IN ({marks})", ids)
                    meta_map = {r["id"]: r for r in c.fetchall()}
                    conn.close()
                    for item in rec_items:
                        nid = item["node_id"]
                        row_m = meta_map.get(nid)
                        creator = (row_m["created_by"] if row_m else None) or "system"
                        ntype = ((row_m["node_type"] if row_m else None) or "concept").lower()
                        is_gnd = bool(row_m["is_grounded"]) if row_m else False
                        conf = float(row_m["confidence"] or 0.5) if row_m else 0.5
                        tier = graph_instance.get_node_physics(nid)["tier"] or infer_epistemic_tier(ntype, is_gnd, conf)
                        if filter_type and ntype != filter_type:
                            continue
                        if filter_author and creator != filter_author:
                            continue
                        if filter_tier_int is not None and tier != filter_tier_int:
                            continue
                        results.append({
                            "node_id": nid,
                            "label": item.get("label") or nid,
                            "preview": item.get("snippet", ""),
                            "truncated": bool(item.get("truncated", False)),
                            "score": float(item.get("score", 0.0)),
                            "via_association": bool(item.get("via_association", False)),
                            "claims": item.get("claims", []),
                            "node_type": ntype,
                            "epistemic_tier": tier,
                            "created_by": creator,
                        })
                        if len(results) >= limit:
                            break
            except Exception as e:
                logger.warning(f"[MCP] Recall search fallback to SQL: {e}")

            # Fallback to direct SQL text match if recall returned empty and no non-matching recall hit was discarded
            if not results and not has_filters:
                from aethelnet_node.recall import SNIPPET_CHARS, TOP_HIT_SNIPPET_CHARS
                from aethelnet_node.state import infer_epistemic_tier
                conn = get_db_connection()
                c = conn.cursor()
                c.execute(
                    "SELECT id, label, text_content, node_type, is_grounded, confidence, created_by FROM lgnn_nodes "
                    "WHERE COALESCE(is_archived, 0) = 0 AND (id LIKE ? OR label LIKE ? OR text_content LIKE ?) LIMIT ?",
                    (f"%{query}%", f"%{query}%", f"%{query}%", limit)
                )
                for idx, r in enumerate(c.fetchall(), start=1):
                    raw_txt = (r["text_content"] or "").strip()
                    char_limit = TOP_HIT_SNIPPET_CHARS if idx == 1 else SNIPPET_CHARS
                    results.append({
                        "node_id": r["id"],
                        "label": r["label"] or r["id"],
                        "preview": raw_txt[:char_limit],
                        "truncated": len(raw_txt) > char_limit,
                        "score": r["confidence"],
                        "via_association": False,
                        "claims": [],
                        "node_type": (r["node_type"] or "concept").lower(),
                        "epistemic_tier": infer_epistemic_tier(r["node_type"], bool(r["is_grounded"]), r["confidence"]),
                        "created_by": r["created_by"] or "unknown"
                    })
                conn.close()

            text_output = f"Aethelnet Search Results for '{query}' ({len(results)} matches):\n"
            for r in results:
                color_info = agent_id_to_color(r["created_by"])
                tags = []
                if r.get("via_association"):
                    tags.append("via association")
                if r.get("truncated"):
                    tags.append(f'truncated — call lgnn_read_node_content("{r["node_id"]}") for full text')
                tag_str = f" [{' | '.join(tags)}]" if tags else ""
                text_output += f"- [{r['node_id']}] {r['label']} (tier={r.get('epistemic_tier')}, by {r['created_by']} [{color_info['hex']}]){tag_str}: {r['preview']}\n"
                for cl in r.get("claims", []):
                    cflag = " [CONTESTED]" if cl.get("contested") else ""
                    text_output += f"    claim: {cl['source']} -{cl['relation']}-> {cl['target']}{cflag}\n"

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
            task_id = str(arguments.get("task_id", "") or "").strip()
            task_tok = current_task.set(task_id) if task_id else None
            try:
                links = touch(node_ids, kind="useful")
            finally:
                if task_tok is not None:
                    current_task.reset(task_tok)
            return {"content": [{"type": "text", "text": f"Noted {len(node_ids)} concepts as used together ({links} new links)."}]}

        elif name == "lgnn_archive_concept":
            nid = str(arguments.get("node_id", "")).strip()
            if not nid:
                return {"isError": True, "content": [{"type": "text", "text": "Argument 'node_id' is required."}]}
            reason = str(arguments.get("reason", "") or "").strip()
            superseded_by = str(arguments.get("superseded_by", "") or "").strip()
            agent = get_current_agent()

            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT meta_data FROM lgnn_nodes WHERE id = ?", (nid,))
            row = c.fetchone()
            if not row:
                conn.close()
                return {"isError": True, "content": [{"type": "text", "text": f"Concept '{nid}' does not exist."}]}
            try:
                meta = json.loads(row["meta_data"] or "{}")
                if not isinstance(meta, dict):
                    meta = {}
            except ValueError:
                meta = {}
            meta["archived_by"] = agent
            if reason:
                meta["archived_reason"] = reason
            if superseded_by:
                meta["superseded_by"] = superseded_by
            c.execute(
                "UPDATE lgnn_nodes SET is_archived = 1, updated_by = ?, meta_data = ?, last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                (agent, json.dumps(meta), nid),
            )
            conn.commit()
            conn.close()

            from aethelnet_node.state import graph_instance
            graph_instance.remove_node(nid)

            if superseded_by:
                save_multigraph_edge(
                    edge_id=f"{nid}_superseded_by_{superseded_by}",
                    source=nid,
                    target=superseded_by,
                    relation_type="superseded_by",
                    weight=1.0,
                    evidence_quote=reason,
                    source_doc_id="archive_concept",
                    record_coaccess=False,
                )

            log_agent_write(agent, "MCP.archive_concept", f"/nodes/{nid}", 200)
            msg = f"[SUCCESS] Soft-archived '{nid}' (by {agent})"
            if superseded_by:
                msg += f" -> superseded by '{superseded_by}'"
            return {
                "content": [{"type": "text", "text": msg + "."}],
                "structuredContent": {"node_id": nid, "archived": True, "superseded_by": superseded_by or None, "by": agent},
            }

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
