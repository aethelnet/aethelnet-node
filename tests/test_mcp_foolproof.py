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


def test_search_concepts_preserves_full_top_hit_without_100_char_clip():
    token = current_agent.set("small_llm_tester")
    try:
        medium_body = (
            "Detailed Silverblue environment note explaining legacy venv relocation background "
            "with extra diagnostic context padding beyond one hundred characters so that "
            "the actual exact command sits late: uv run --no-project --python /usr/bin/python3.14 --with pytest"
        )
        assert 200 < len(medium_body) < 400
        call_mcp_tool("lgnn_write_concept", {
            "node_id": "mcp_progressive_medium",
            "label": "Medium Invariant Progressive Density",
            "text_content": medium_body,
        })
        res_med = call_mcp_tool("lgnn_search_concepts", {"query": "Medium Invariant Progressive Density", "limit": 3})
        assert not res_med.get("isError")
        assert "--with pytest" in res_med["content"][0]["text"]
        top_med = next(r for r in res_med["structuredContent"] if r["node_id"] == "mcp_progressive_medium")
        assert top_med["truncated"] is False

        long_body = "Long architectural specification uniquetoken9942 " + ("clause_detail " * 90)
        call_mcp_tool("lgnn_write_concept", {
            "node_id": "mcp_progressive_long",
            "label": "Long Architecture Spec uniquetoken9942",
            "text_content": long_body,
        })
        res_long = call_mcp_tool("lgnn_search_concepts", {"query": "Long Architecture Spec uniquetoken9942", "limit": 3})
        top_long = next(r for r in res_long["structuredContent"] if r["node_id"] == "mcp_progressive_long")
        assert top_long["truncated"] is True
        assert "lgnn_read_node_content" in res_long["content"][0]["text"]
    finally:
        current_agent.reset(token)


def test_read_node_content_preserves_edge_direction_and_contested():
    token = current_agent.set("direction_tester")
    try:
        call_mcp_tool("lgnn_write_concept", {"node_id": "dir_parent", "label": "Parent Node", "skip_coaccess": True})
        call_mcp_tool("lgnn_write_concept", {"node_id": "dir_child", "label": "Child Node", "skip_coaccess": True})
        call_mcp_tool("lgnn_link_concepts", {
            "source": "dir_parent",
            "target": "dir_child",
            "relation": "extended_by",
            "evidence_quote": "Verified conflict test quote.",
            "is_contested": True,
            "skip_coaccess": True,
        })

        parent_card = call_mcp_tool("lgnn_read_node_content", {"node_id": "dir_parent"})
        child_card = call_mcp_tool("lgnn_read_node_content", {"node_id": "dir_child"})

        assert "--[extended_by:1.0]-->" in parent_card["content"][0]["text"]
        assert "<--[extended_by:1.0]--" in child_card["content"][0]["text"]
        assert "[CONTESTED]" in child_card["content"][0]["text"]
        assert child_card["structuredContent"]["edges"][0]["direction"] == "in"
        assert child_card["structuredContent"]["edges"][0]["contested"] is True
    finally:
        current_agent.reset(token)


def test_query_graph_respects_limit_past_15():
    token = current_agent.set("limit_tester")
    try:
        for i in range(18):
            call_mcp_tool("lgnn_write_concept", {
                "node_id": f"limit_node_{i:02d}",
                "label": f"Limit Node {i}",
                "skip_coaccess": True,
            })
        res = call_mcp_tool("lgnn_query_graph", {"limit": 25})
        shown_lines = [ln for ln in res["content"][0]["text"].splitlines() if ln.strip().startswith("* [")]
        assert len(shown_lines) >= 18
        assert f"Showing first {len(res['structuredContent']['nodes'])} nodes:" in res["content"][0]["text"]
    finally:
        current_agent.reset(token)


def test_search_concepts_filters_by_type_creator_and_tier():
    tok_a = current_agent.set("alice_author")
    try:
        call_mcp_tool("lgnn_write_concept", {
            "node_id": "flt_alice_inv",
            "label": "FilterSharedKeyword Rule",
            "text_content": "filtersharedkeyword99 canonical invariant rule",
            "node_type": "invariant",
            "confidence": 0.99,
            "skip_coaccess": True,
        })
    finally:
        current_agent.reset(tok_a)

    tok_b = current_agent.set("bob_author")
    try:
        call_mcp_tool("lgnn_write_concept", {
            "node_id": "flt_bob_hyp",
            "label": "FilterSharedKeyword Guess",
            "text_content": "filtersharedkeyword99 speculative hypothesis note",
            "node_type": "hypothesis",
            "confidence": 0.45,
            "skip_coaccess": True,
        })
        res_inv = call_mcp_tool("lgnn_search_concepts", {
            "query": "filtersharedkeyword99",
            "node_type": "invariant",
            "created_by": "alice_author",
            "epistemic_tier": 1,
        })
        ids_inv = [r["node_id"] for r in res_inv["structuredContent"]]
        assert ids_inv == ["flt_alice_inv"]
    finally:
        current_agent.reset(tok_b)


def test_skip_coaccess_prevents_bulk_cliques_and_archive_hides_node():
    from aethelnet_node import coaccess
    from aethelnet_node.recall import recall

    token = current_agent.set("clique_guard")
    try:
        call_mcp_tool("lgnn_write_concept", {
            "node_id": "bulk_iso_alpha",
            "text_content": "bulkisolated991 first topic",
            "skip_coaccess": True,
        })
        call_mcp_tool("lgnn_write_concept", {
            "node_id": "bulk_iso_beta",
            "text_content": "bulkisolated991 second unrelated topic",
            "skip_coaccess": True,
        })
        assert coaccess.edges_among(["bulk_iso_alpha", "bulk_iso_beta"]) == []

        arch = call_mcp_tool("lgnn_archive_concept", {
            "node_id": "bulk_iso_alpha",
            "reason": "Obsolete draft",
            "superseded_by": "bulk_iso_beta",
        })
        assert not arch.get("isError")
        rec_ids = [r["node_id"] for r in recall("bulkisolated991", k=5)["results"]]
        assert "bulk_iso_alpha" not in rec_ids
        assert "bulk_iso_beta" in rec_ids

        card = call_mcp_tool("lgnn_read_node_content", {"node_id": "bulk_iso_beta"})
        assert any(e["relation"] == "superseded_by" and e["direction"] == "in" for e in card["structuredContent"]["edges"])
    finally:
        current_agent.reset(token)
