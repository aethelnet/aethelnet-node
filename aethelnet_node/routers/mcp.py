"""
HTTP endpoints behind the MCP bridges (mcp/mcp_stdio_server.py, mcp/mcp_universal_server.py).

GET  /api/lgnn/mcp/tools        — tool definitions
POST /api/lgnn/mcp/tools/call   — {"name": ..., "arguments": {...}}; a POST, so it needs the agent's token,
                                  which also attributes every write and "used together" link to that agent

Only tools that are safe to reach over the network are exposed. Shell execution, local file access
and network scouting stay unreachable here: they need a sandbox first (see aethelnet-core/docs/IDEAS.md #2).
"""

from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from aethelnet_node.mcp.mcp_protocol import call_mcp_tool, get_mcp_tools

router = APIRouter()

HTTP_EXPOSED_TOOLS = {
    "lgnn_topological_recovery",
    "lgnn_mark_useful",
    "lgnn_read_node_content",
    "lgnn_query_graph",
}


class ToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any] = {}


@router.get("/mcp/tools")
def list_tools():
    return {"tools": [t for t in get_mcp_tools() if t["name"] in HTTP_EXPOSED_TOOLS]}


@router.post("/mcp/tools/call")
def call_tool(call: ToolCall):
    if call.name not in HTTP_EXPOSED_TOOLS:
        return {"isError": True, "content": [{"type": "text", "text": f"Tool '{call.name}' is not available over HTTP."}]}
    return call_mcp_tool(call.name, call.arguments or {})
