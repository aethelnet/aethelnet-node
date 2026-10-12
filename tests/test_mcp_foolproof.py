"""
Foolproof test suite for Aethelnet MCP protocols, write tools, and dual-mode stdio execution.
"""

import json
import pytest
from aethelnet_node.mcp.mcp_protocol import get_mcp_tools, call_mcp_tool
from aethelnet_node.provenance import agent_id_to_color
from aethelnet_node.agents import current_agent


def test_mcp_tools_list_has_full_lifecycle():
    tools = get_mcp_tools()
    tool_names = {t["name"] for t in tools}
    
    assert "lgnn_query_graph" in tool_names
    assert "lgnn_read_node_content" in tool_names
    assert "lgnn_write_concept" in tool_names
    assert "lgnn_link_concepts" in tool_names
    assert "lgnn_search_concepts" in tool_names
    assert "lgnn_topological_recovery" in tool_names
    assert "lgnn_mark_useful" in tool_names


def test_write_and_read_concept_with_provenance():
    # Set agent identity
    token = current_agent.set("test_trader_bot")
    try:
        # 1. Write a concept
        write_res = call_mcp_tool("lgnn_write_concept", {
            "node_id": "test_sol_breakout_v1",
            "label": "SOL Liquidity Breakout",
            "text_content": "# Hypothesis\nSOL breaks above 150 when funding is negative.",
            "node_type": "hypothesis",
            "confidence": 0.92,
            "meta_data": {"market": "SOL-PERP", "timeframe": "15m"}
        })
        assert not write_res.get("isError")
        assert "test_sol_breakout_v1" in write_res["content"][0]["text"]
        assert write_res["structuredContent"]["created_by"] == "test_trader_bot"

        # 2. Read the concept
        read_res = call_mcp_tool("lgnn_read_node_content", {
            "node_id": "test_sol_breakout_v1"
        })
        assert not read_res.get("isError")
        assert "SOL Liquidity Breakout" in read_res["content"][0]["text"]
        assert read_res["structuredContent"]["created_by"] == "test_trader_bot"
        assert read_res["structuredContent"]["color"]["hex"].startswith("#")

    finally:
        current_agent.reset(token)


def test_link_concepts():
    token = current_agent.set("agent_architect")
    try:
        call_mcp_tool("lgnn_write_concept", {"node_id": "node_alpha", "label": "Concept Alpha"})
        call_mcp_tool("lgnn_write_concept", {"node_id": "node_beta", "label": "Concept Beta"})

        link_res = call_mcp_tool("lgnn_link_concepts", {
            "source": "node_alpha",
            "target": "node_beta",
            "relation": "causes",
            "weight": 0.85
        })
        assert not link_res.get("isError")
        assert "node_alpha" in link_res["content"][0]["text"]
        assert link_res["structuredContent"]["relation"] == "causes"

        # Verify edge appears in read_node_content
        read_res = call_mcp_tool("lgnn_read_node_content", {"node_id": "node_alpha"})
        assert any(e["node"] == "node_beta" for e in read_res["structuredContent"]["edges"])
    finally:
        current_agent.reset(token)


def test_search_concepts():
    token = current_agent.set("researcher")
    try:
        call_mcp_tool("lgnn_write_concept", {
            "node_id": "concept_neural_ode_v5",
            "label": "Neural ODE Runge Kutta",
            "text_content": "Continuous-depth graph dynamics with adaptive step solver."
        })

        search_res = call_mcp_tool("lgnn_search_concepts", {
            "query": "Neural ODE"
        })
        assert not search_res.get("isError")
        assert any("concept_neural_ode_v5" == r["node_id"] for r in search_res["structuredContent"])
    finally:
        current_agent.reset(token)


def test_visual_provenance_color_hashing():
    c1 = agent_id_to_color("gemini")
    c2 = agent_id_to_color("claude")
    c3 = agent_id_to_color("nico")
    c4 = agent_id_to_color("gemini") # Deterministic check

    assert c1["hex"] == c4["hex"]
    assert c1["hex"] != c2["hex"]
    assert c1["hex"].startswith("#") and len(c1["hex"]) == 7
    assert 0 <= c1["hue"] <= 360
