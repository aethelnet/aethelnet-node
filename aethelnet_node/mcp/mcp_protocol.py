from typing import Dict, Any, List
import logging
from aethelnet_node.database import load_graph_state, load_kanban_board, get_node_text

# command_runner / research_scouter are optional modules that are not part of this repository;
# they are imported lazily so that this module (and the MCP HTTP route) can load without them.

logger = logging.getLogger("LGNN.MCP")

def get_mcp_tools() -> List[Dict[str, Any]]:
    """
    Returns standard MCP tool definitions so external agents can interface with LGNN.
    """
    return [
        {
            "name": "lgnn_query_graph",
            "description": "Retrieve the current persistent node coordinates, activation states, and topological bridges.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "lgnn_read_node_content",
            "description": "Read the full Obsidian-style text note content of a specific graph concept node.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "The unique ID/label of the target concept node."}
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
    """
    logger.info(f"[MCP] External agent calling tool '{name}' with arguments {arguments}")
    
    try:
        if name == "lgnn_query_graph":
            nodes, edges, metrics = load_graph_state()
            nodes_summary = []
            for nid, m in metrics.items():
                nodes_summary.append({
                    "id": nid,
                    "confidence": m["confidence"],
                    "plateau_factor": m["plateau_factor"]
                })
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Graph contains {len(nodes_summary)} nodes and {len(edges)} bridges.\nNodes: {nodes_summary}"
                    }
                ]
            }
            
        elif name == "lgnn_read_node_content":
            nid = arguments.get("node_id")
            text = get_node_text(nid)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": text if text else f"Concept '{nid}' is empty or does not exist."
                    }
                ]
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

        elif name in ("lgnn_topological_recovery", "lgnn_topological_bypass"):
            # Associative recall (aethelnet_node/recall.py). The previous version ignored the context and
            # returned the first five nodes; see aethelnet-core/research/recall_benchmark for the comparison.
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
        logger.error(f"[MCP] Tool execution failure: {str(e)}")
        return {"isError": True, "content": [{"type": "text", "text": f"Execution Error: {str(e)}"}]}
