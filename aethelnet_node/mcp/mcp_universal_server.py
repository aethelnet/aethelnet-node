#!/usr/bin/env python3
"""
Aethelnet LGNN Universal FastMCP Server.

Exposes standard FastMCP tools for any compatible client, with dual-mode support:
tries HTTP proxy to active Aethelnet node, falls back to direct in-process database execution.
"""

import sys
import json
import urllib.request
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Aethelnet_Universal_Bridge")

API_URL = os.getenv("AETHELNET_API_URL", "http://127.0.0.1:8000/api/lgnn")
_TOKEN = os.getenv("AETHELNET_AUTH_TOKEN", "").strip()
AUTH_HEADERS = {"Authorization": f"Bearer {_TOKEN}"} if _TOKEN else {}


def proxy_call(name: str, kwargs: dict) -> str:
    """Tries HTTP first; falls back seamlessly to in-process execution."""
    if API_URL:
        try:
            url = f"{API_URL}/mcp/tools/call"
            payload = json.dumps({"name": name, "arguments": kwargs}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", **AUTH_HEADERS}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as res:
                data = json.loads(res.read().decode('utf-8'))
                content = data.get("content", [])
                if content and isinstance(content, list) and len(content) > 0:
                    return content[0].get("text", str(content))
                return str(data)
        except Exception:
            pass  # Fall back to in-process execution

    from aethelnet_node.mcp.mcp_protocol import call_mcp_tool
    res = call_mcp_tool(name, kwargs)
    content = res.get("content", [])
    if content and isinstance(content, list) and len(content) > 0:
        return content[0].get("text", str(content))
    return str(res)


@mcp.tool()
def lgnn_query_graph(limit: int = 50) -> str:
    """Retrieve the current persistent node coordinates, activation states, and topological bridges from Aethelnet."""
    return proxy_call("lgnn_query_graph", {"limit": limit})


@mcp.tool()
def lgnn_read_node_content(node_id: str) -> str:
    """Read the full Obsidian-style text note content, provenance author, and metadata of a specific concept node."""
    return proxy_call("lgnn_read_node_content", {"node_id": node_id})


@mcp.tool()
def lgnn_write_concept(
    node_id: str,
    label: str = "",
    text_content: str = "",
    node_type: str = "concept",
    confidence: float = 0.85,
    source_tag: str = "agent_inference"
) -> str:
    """Store or update a concept, hypothesis, reasoning chain, or invariant node in the shared Aethelnet graph with automatic neural embedding and agent provenance."""
    return proxy_call("lgnn_write_concept", {
        "node_id": node_id,
        "label": label,
        "text_content": text_content,
        "node_type": node_type,
        "confidence": confidence,
        "source_tag": source_tag
    })


@mcp.tool()
def lgnn_link_concepts(source: str, target: str, relation: str = "associated_with", weight: float = 1.0) -> str:
    """Create a directional semantic bridge or associative edge between two concepts in the Aethelnet graph."""
    return proxy_call("lgnn_link_concepts", {
        "source": source,
        "target": target,
        "relation": relation,
        "weight": weight
    })


@mcp.tool()
def lgnn_search_concepts(query: str, limit: int = 10) -> str:
    """Search the concept graph by semantic meaning or keywords. Returns matched concepts with creators, confidence, and preview."""
    return proxy_call("lgnn_search_concepts", {"query": query, "limit": limit})


@mcp.tool()
def lgnn_topological_recovery(context: str, k: int = 8, use_popularity: bool = False) -> str:
    """Associative recall for when you are stuck: describe what you are trying to do or remember to retrieve relevant concepts and their claims."""
    return proxy_call("lgnn_topological_recovery", {"context": context, "k": k, "use_popularity": use_popularity})


@mcp.tool()
def lgnn_topological_bypass(blocked_concept_context: str) -> str:
    """Legacy alias: retrieve topologically adjacent latent concepts to recover lost context."""
    return proxy_call("lgnn_topological_recovery", {"context": blocked_concept_context})


@mcp.tool()
def lgnn_mark_useful(node_ids: list[str]) -> str:
    """Tell the graph which recalled concepts actually helped to strengthen their associative Hebbian connection."""
    return proxy_call("lgnn_mark_useful", {"node_ids": node_ids})


@mcp.tool()
def lgnn_perceive_environment(file_path: str) -> str:
    """Trigger the Sensor Array to parse a local file (PDF, Image, or 3D Object) and inject its spatial/visual meaning."""
    return proxy_call("lgnn_perceive_environment", {"file_path": file_path})


if __name__ == "__main__":
    print("Starting Aethelnet Universal FastMCP Bridge...", file=sys.stderr)
    mcp.run()
