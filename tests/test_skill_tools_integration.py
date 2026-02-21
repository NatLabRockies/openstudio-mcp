"""Integration test for skill discovery tools (list_skills, get_skill).

Exercises: list_skills → get_skill(found) → get_skill(not found).
Requires skills directory mounted at /skills inside the container.
"""
import asyncio

import pytest

from conftest import unwrap, integration_enabled, server_params
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_skill_tools_workflow():
    """list_skills → get_skill → get_skill(missing)."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                # 1. List skills — should return skills if mounted
                ls = unwrap(await s.call_tool("list_skills", {}))
                assert ls.get("ok") is True, ls

                # If skills are mounted, verify we get results
                if ls["count"] > 0:
                    names = {sk["name"] for sk in ls["skills"]}
                    # At least one known skill should be present
                    known = {"simulate", "retrofit", "qaqc", "new-building"}
                    assert names & known, (
                        f"Expected at least one known skill, got {names}"
                    )

                    # 2. Get a specific skill
                    skill = unwrap(await s.call_tool("get_skill", {
                        "name": "simulate",
                    }))
                    assert skill.get("ok") is True, skill
                    assert "content" in skill
                    # Content should mention simulation-related tools
                    assert "run_simulation" in skill["content"]

                # 3. Get nonexistent skill
                missing = unwrap(await s.call_tool("get_skill", {
                    "name": "nonexistent_skill_xyz",
                }))
                assert missing.get("ok") is False
                assert "not found" in missing.get("error", "")

    asyncio.run(_run())
