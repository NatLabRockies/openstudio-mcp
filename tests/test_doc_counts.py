"""Normative docs must not hardcode exact tool counts.

The roster's single source of truth is EXPECTED_TOOLS in
tests/test_skill_registration.py; prose says "150+ tools". Exact literals
("138 tools", "151 tools") go stale the moment a tool lands. Historical
records (dated benchmarks, archived plans) keep their point-in-time numbers
and are not covered here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]

# Living, normative docs — contributor guidance and current-state descriptions
NORMATIVE_DOCS = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/rules/testing.md",
    ".claude/rules/api-reference.md",
    ".claude/rules/component-types.md",
    "docs/testing/README.md",
    "docs/testing/testing.md",
    "docs/testing/frameworks-summary.md",
]

# "151 tools" / "138 tools" are stale the day they land; "150+ tools" is the
# sanctioned phrasing ("+" excluded by the lookbehind)
_EXACT_TOOL_COUNT = re.compile(r"\b\d{3}(?<!\+)\s+tools\b")


def test_normative_docs_use_150_plus_not_exact_tool_counts():
    # Regression: AGENTS.md said "138 tools", the testing rule said "151
    # tools" — both stale; doctrine is "150+ tools" with EXPECTED_TOOLS as
    # the only exact roster (plan F3)
    offenders = []
    for rel in NORMATIVE_DOCS:
        path = REPO / rel
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _EXACT_TOOL_COUNT.search(line)
            if m:
                offenders.append(f"{rel}:{i}: '{m.group().strip()}'")
    assert not offenders, (
        "exact tool-count literals in normative docs (use '150+ tools'; the "
        "roster lives in EXPECTED_TOOLS):\n" + "\n".join(offenders)
    )


def test_contributor_docs_point_at_expected_tools_only():
    # Regression: README's contributor section told people to "bump counts in
    # tests/test_tool_baseline.py" — there are no counts to bump; the roster
    # has ONE source of truth (plan F3)
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "bump counts" not in readme, (
        "contributor guidance must not instruct count-bumping — the roster "
        "is EXPECTED_TOOLS in tests/test_skill_registration.py"
    )
    assert "EXPECTED_TOOLS" in readme, (
        "contributor guidance must name EXPECTED_TOOLS as the roster source"
    )
