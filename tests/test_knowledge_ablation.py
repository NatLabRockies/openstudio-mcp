"""Benchmark ablation arm: OSMCP_DISABLE_KNOWLEDGE_SKILLS over real stdio.

The knowledge-layer tools must be truly absent from the advertised roster —
client-side tool blocking leaves them visible and the refusals contaminate
agent behavior (reviewer-response plan D3).
"""
import asyncio
import os

import pytest
from conftest import integration_enabled, server_params
from mcp import ClientSession
from mcp.client.stdio import stdio_client

KNOWLEDGE_TOOLS = {"list_skills", "get_skill", "get_skill_file", "recommend_tools"}


async def _tool_names() -> set:
    async with stdio_client(server_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            listed = await s.list_tools()
            return {t.name for t in listed.tools}


@pytest.mark.integration
def test_knowledge_skills_ablation_over_stdio(monkeypatch):
    # Validates: with OSMCP_DISABLE_KNOWLEDGE_SKILLS=1 the advertised MCP
    # roster loses exactly the 3 knowledge-layer tools; default env keeps them
    if not integration_enabled():
        pytest.skip("integration disabled")

    monkeypatch.delenv("OSMCP_DISABLE_KNOWLEDGE_SKILLS", raising=False)
    full = asyncio.run(_tool_names())
    assert KNOWLEDGE_TOOLS <= full, (
        f"default roster must include knowledge tools, missing: "
        f"{KNOWLEDGE_TOOLS - full}"
    )

    monkeypatch.setenv("OSMCP_DISABLE_KNOWLEDGE_SKILLS", "1")
    ablated = asyncio.run(_tool_names())
    assert ablated == full - KNOWLEDGE_TOOLS, (
        f"ablation must remove exactly {KNOWLEDGE_TOOLS}; "
        f"unexpected diff: {full.symmetric_difference(ablated) - KNOWLEDGE_TOOLS}"
    )
    assert "create_new_building" in ablated, "domain tools must be untouched"
    assert os.environ.get("OSMCP_DISABLE_KNOWLEDGE_SKILLS") == "1"
