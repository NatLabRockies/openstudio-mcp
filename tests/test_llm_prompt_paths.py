"""LLM test prompts must only name server paths the server actually allows."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILES = sorted(ROOT.glob("tests/llm/test_*.py")) + sorted(ROOT.glob(".claude/skills/*/eval.md"))

# tests/assets is mounted at both /test-assets and /inputs in the harness, but only
# /inputs is in the server's _SHARED_READ_ROOTS, so a /test-assets path is denied
# on every transport and the agent has to find the file again under /inputs.
_FORBIDDEN = re.compile(r"[\"'|] *[^\"'|\n]*(/test-assets/)")


def test_prompts_do_not_name_test_assets():
    # Regression: #236 — three prompts named /test-assets/sddc_office/floorplan.json;
    # every run's first import_floorspacejs call failed "Path not allowed" and over
    # HTTP the agent searched the host for the folder first
    offenders = []
    for path in PROMPT_FILES:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _FORBIDDEN.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Prompts must use /inputs/ (the server never allows /test-assets/):\n" + "\n".join(offenders))
