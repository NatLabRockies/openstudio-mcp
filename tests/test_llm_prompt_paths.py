"""LLM test prompts must only name server paths the server actually allows."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
LLM_TEST_FILES = sorted((ROOT / "tests" / "llm").glob("*.py"))
EVAL_FILES = sorted((ROOT / ".claude" / "skills").rglob("eval.md"))

# tests/assets is mounted at both /test-assets and /inputs in the harness, but only
# /inputs is in the server's _SHARED_READ_ROOTS, so a /test-assets path is denied
# on every transport and the agent has to find the file again under /inputs.
# "/test-assets:ro" is the mount spec itself (runner.py), not a prompt path.
_FORBIDDEN = re.compile(r"/test-assets(?![\w:-])")


def _string_constants(path: Path):
    """(lineno, value) for every string literal in a Python file, f-string parts included."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def _offenders() -> list[str]:
    found = []
    for path in LLM_TEST_FILES:
        for lineno, value in _string_constants(path):
            if _FORBIDDEN.search(value):
                found.append(f"{path.relative_to(ROOT)}:{lineno}: {value.strip()[:80]}")
    for path in EVAL_FILES:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _FORBIDDEN.search(line):
                found.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:80]}")
    return found


def test_prompts_do_not_name_test_assets():
    # Regression: #236 — three prompts named /test-assets/sddc_office/floorplan.json;
    # every run's first import_floorspacejs call failed "Path not allowed" and over
    # HTTP the agent searched the host for the folder first
    assert LLM_TEST_FILES and EVAL_FILES, "scan found nothing to check; paths moved?"
    offenders = _offenders()
    assert not offenders, (
        "Prompts must use /inputs/ (the server never allows /test-assets):\n" + "\n".join(offenders))


@pytest.mark.parametrize(("text", "flagged"), [
    ("Import /test-assets/sddc_office/floorplan.json", True),
    ("look in /test-assets", True),
    ("/test-assets/x\nsecond line", True),
    ("-v C:/x:/test-assets:ro", False),  # docker mount spec, not a prompt
    ("Import /inputs/sddc_office/floorplan.json", False),
    ("/test-assets-old/x", False),
])
def test_forbidden_pattern(text, flagged):
    # Validates: the scanner flags the directory with or without a trailing slash
    # and leaves the harness's own mount spec alone
    assert bool(_FORBIDDEN.search(text)) is flagged
