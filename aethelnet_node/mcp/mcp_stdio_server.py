#!/usr/bin/env python3
"""
Aethelnet LGNN Dual-Mode Stdio MCP Server.

Provides a robust, foolproof JSON-RPC stdio MCP interface for ANY external agent
(Cursor, Claude Desktop, Antigravity, local scripts, custom bots).

Dual-Mode Architecture:
1. Network Mode: If an Aethelnet Node HTTP server is running at AETHELNET_API_URL, proxies to it.
2. Direct Mode: If the HTTP server is unreachable or offline, seamlessly executes
   tools directly in-process against the local SQLite database.
Never crashes with 'Connection Refused'.
"""

import sys
import json
import urllib.request
import traceback
import os

API_URL = os.getenv("AETHELNET_API_URL", "http://127.0.0.1:8000/api/lgnn")
_TOKEN = os.getenv("AETHELNET_AUTH_TOKEN", "").strip()
AUTH_HEADERS = {"Authorization": f"Bearer {_TOKEN}"} if _TOKEN else {}

# Configure agent identity for in-process direct mode
def setup_direct_mode_agent():
    try:
        from aethelnet_node.agents import current_agent, load_agents, hash_token
        agent_id_env = os.getenv("AETHELNET_AGENT_ID", "").strip()
        if agent_id_env:
            current_agent.set(agent_id_env)
            return

        if _TOKEN:
            agents = load_agents()
            hashed = hash_token(_TOKEN)
            for aid, meta in agents.items():
                if meta.get("token_sha256") == hashed:
                    current_agent.set(aid)
                    return
        current_agent.set("local")
    except Exception:
        pass


def execute_tools_list() -> list:
    """Tries HTTP first; falls back seamlessly to in-process definitions."""
    if API_URL:
        try:
            r = urllib.request.Request(f"{API_URL}/mcp/tools", method="GET")
            with urllib.request.urlopen(r, timeout=1.5) as res:
                data = json.loads(res.read().decode('utf-8'))
                return data.get("tools", [])
        except Exception:
            pass

    from aethelnet_node.mcp.mcp_protocol import get_mcp_tools
    return get_mcp_tools()


def execute_tool_call(name: str, args: dict) -> dict:
    """Tries HTTP first; falls back seamlessly to in-process tool execution."""
    if API_URL:
        try:
            payload = json.dumps({"name": name, "arguments": args}).encode("utf-8")
            r = urllib.request.Request(
                f"{API_URL}/mcp/tools/call",
                data=payload,
                headers={"Content-Type": "application/json", **AUTH_HEADERS},
                method="POST"
            )
            with urllib.request.urlopen(r, timeout=30) as res:
                data = json.loads(res.read().decode('utf-8'))
                return {
                    "content": data.get("content", [{"type": "text", "text": "Empty response"}]),
                    "isError": data.get("isError", False)
                }
        except Exception:
            pass

    # Direct in-process execution fallback
    setup_direct_mode_agent()
    from aethelnet_node.mcp.mcp_protocol import call_mcp_tool
    res = call_mcp_tool(name, args)
    return {
        "content": res.get("content", [{"type": "text", "text": str(res)}]),
        "isError": res.get("isError", False)
    }


def send_response(req_id, result=None, error=None):
    response = {"jsonrpc": "2.0", "id": req_id}
    if error:
        response["error"] = error
    else:
        response["result"] = result
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def handle_request(req):
    method = req.get("method")
    params = req.get("params", {})
    req_id = req.get("id")

    try:
        if method == "initialize":
            send_response(req_id, result={
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "aethelnet_node_mcp", "version": "2.0.0"}
            })

        elif method == "notifications/initialized":
            pass

        elif method == "tools/list":
            tools = execute_tools_list()
            send_response(req_id, result={"tools": tools})

        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments", {})
            call_res = execute_tool_call(name, args)
            send_response(req_id, result=call_res)

        else:
            send_response(req_id, error={"code": -32601, "message": f"Method '{method}' not found"})

    except Exception as e:
        send_response(req_id, error={"code": -32603, "message": f"Internal error: {str(e)}"})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            handle_request(req)
        except Exception as e:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": f"Parse error: {str(e)}"}
            }) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
