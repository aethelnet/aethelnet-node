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


def test_search_concepts_uses_associative_recall_for_natural_language():
    token = current_agent.set("researcher")
    try:
        call_mcp_tool("lgnn_write_concept", {
            "node_id": "mcp_rk4_checkpoint_note",
            "label": "Checkpointed RK4 Gradients",
            "text_content": "Fixed-step Runge-Kutta ODE integration with torch checkpoint avoids backward blowup.",
        })
        search_res = call_mcp_tool("lgnn_search_concepts", {
            "query": "how do runge kutta ODE checkpoint gradients work",
            "limit": 5,
        })
        assert not search_res.get("isError")
        found_ids = [r["node_id"] for r in search_res["structuredContent"]]
        assert "mcp_rk4_checkpoint_note" in found_ids
    finally:
        current_agent.reset(token)


def test_mcp_write_and_link_learn_coaccess_for_recovery():
    from aethelnet_node.agents import current_task

    token_agent = current_agent.set("dogfood_agent")
    token_task = current_task.set("mcp-coaccess-test-1")
    try:
        call_mcp_tool("lgnn_write_concept", {
            "node_id": "mcp_symptom_zylophone",
            "label": "Zylophone Failure",
            "text_content": "zylophone_error happens when launching remote test runner.",
        })
        call_mcp_tool("lgnn_write_concept", {
            "node_id": "mcp_remedy_quasarswitch",
            "label": "Quasar Switch Flag",
            "text_content": "Pass --quasarswitch=strict to fix completely unrelated toolchain bug.",
        })
        call_mcp_tool("lgnn_link_concepts", {
            "source": "mcp_symptom_zylophone",
            "target": "mcp_remedy_quasarswitch",
            "relation": "solved_by",
            "weight": 1.0,
        })

        rec = call_mcp_tool("lgnn_topological_recovery", {"context": "zylophone_error", "k": 5})
        assert not rec.get("isError")
        rec_ids = [r["node_id"] for r in rec["structuredContent"]["results"]]
        assert "mcp_remedy_quasarswitch" in rec_ids

        card = call_mcp_tool("lgnn_read_node_content", {"node_id": "mcp_symptom_zylophone"})
        assert any(c["node"] == "mcp_remedy_quasarswitch" for c in card["structuredContent"]["coaccess"])
    finally:
        current_task.reset(token_task)
        current_agent.reset(token_agent)


def test_mcp_stdio_protocol_handshake_and_ping(monkeypatch, capsys):
    from aethelnet_node.mcp import mcp_stdio_server

    monkeypatch.setattr(mcp_stdio_server, "API_URL", "")
    mcp_stdio_server.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-03-26"},
    })
    mcp_stdio_server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    mcp_stdio_server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    mcp_stdio_server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})

    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert len(lines) == 3  # notification must emit zero frames
    assert lines[0]["result"]["protocolVersion"] == "2025-03-26"
    assert lines[1]["result"] == {}
    assert any(t["name"] == "lgnn_topological_recovery" for t in lines[2]["result"]["tools"])
