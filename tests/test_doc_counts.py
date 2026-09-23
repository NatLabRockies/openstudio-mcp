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
    ".github/copilot-instructions.md",
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
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _EXACT_TOOL_COUNT.search(line)
            if m:
                offenders.append(f"{rel}:{i}: '{m.group().strip()}'")
    assert not offenders, (
        "exact tool-count literals in normative docs (use '150+ tools'; the "
        "roster lives in EXPECTED_TOOLS):\n" + "\n".join(offenders)
    )


def test_normative_docs_exist():
    # Regression: .claude/rules/*.md were gitignored, so the count check above
    # silently skipped them on every checkout but one maintainer's machine
    missing = [rel for rel in NORMATIVE_DOCS if not (REPO / rel).is_file()]
    assert not missing, f"normative docs missing (untracked or gitignored?): {missing}"


def test_claude_md_imports_shared_agents_rules():
    # Validates: CLAUDE.md pulls shared rules from AGENTS.md instead of a
    # divergent copy (CLAUDE.md had 16 rules, AGENTS.md 6 before consolidation)
    claude_lines = (REPO / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    assert "@AGENTS.md" in claude_lines, "CLAUDE.md must import AGENTS.md on its own line"
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Coding Rules" in agents, "AGENTS.md must hold the shared coding rules"
    assert "## Coding Rules" not in claude_lines,"coding rules duplicated in CLAUDE.md; keep them in AGENTS.md"


def test_copilot_instructions_fit_review_read_limit():
    # Validates: Copilot code review reads only the first ~4,000 chars of
    # .github/copilot-instructions.md; anything past that is silently ignored
    size = len((REPO / ".github/copilot-instructions.md").read_text(encoding="utf-8"))
    assert size <= 4000, f"copilot-instructions.md is {size} chars; review reads only the first 4000"


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
