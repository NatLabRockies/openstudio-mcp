"""Tier 1: No-model tool selection — verify Claude finds tools without model state.

These test tool discovery for operations that don't require a loaded model
(server info, skills, building creation). With-model tool selection tests
are in test_06_progressive.py which covers L1/L2/L3 specificity levels.

Assumptions:
  - ToolSearch (deferred tool loading) consumes 1-3 turns before MCP tools
  - Agent may call context-gathering tools beyond the expected ones
  - 90s timeout is enough for these operations
"""
from __future__ import annotations

import pytest

from .conftest import get_tier
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier1]

NO_MODEL_CASES = [
    ("What is the server status?",
     ["get_server_status"]),
    ("List available skills",
     ["list_skills"]),
    # Geometry creation tools (no model needed — they create one)
    ("Create a small office building using create_new_building",
     ["create_new_building"]),
    ("Create bar geometry for a retail building using create_bar_building",
     ["create_bar_building"]),
]


@pytest.mark.parametrize(("prompt", "expected"), NO_MODEL_CASES,
                         ids=[c[0][:35] for c in NO_MODEL_CASES])
def test_tool_selection_no_model(prompt, expected):
    """Agent calls expected tool without needing model state.

    Verifies:
      - At least one expected tool appears in the tool call sequence
      - No model loading needed (these tools work without model state)
    """
    tier = get_tier()
    if tier not in ("all", "1"):
        pytest.skip("Tier 1 not selected")

    result = run_claude(prompt, timeout=90)
    tool_names = result.tool_names

    assert any(t in expected for t in tool_names), (
        f"Expected one of {expected} in sequence, got: {tool_names}"
    )
