"""Option checks in scripts/benchmark_sweep.py that must abort before any leg runs."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from benchmark_sweep import http_unsupported

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("transport", "arms", "env", "providers", "expected"), [
    ("http", ["full"], {}, ["claude"], None),
    ("http", ["full"], {"LLM_TESTS_CODE_MODE": "0"}, ["claude"], None),
    ("http", ["nohost", "nodiscovery"], {}, ["claude"], None),  # client-side arms
    ("stdio", ["full", "noskills"], {"LLM_TESTS_CODE_MODE": "1"}, ["codex"], None),
    ("http", ["full", "noskills"], {}, ["claude"], "noskills arm(s) ['noskills']"),
    ("http", ["nodiscovery-noskills"], {}, ["claude"], "['nodiscovery-noskills']"),
    ("http", ["full"], {"LLM_TESTS_CODE_MODE": "1"}, ["claude"], "code mode off"),
    ("http", ["full"], {}, ["claude", "codex"], "claude backend only, not ['codex']"),
])
def test_http_sweeps_refuse_options_the_leg_server_does_not_receive(
        transport, arms, env, providers, expected):
    # Regression: review of #238 — start_http_server never passes
    # OSMCP_DISABLE_KNOWLEDGE_SKILLS or OSMCP_CODE_MODE, and codex has no HTTP
    # branch, so such a leg would have run as full/stdio and been saved as noskills/http
    reason = http_unsupported(transport, arms, env, providers)
    if expected is None:
        assert reason is None
    else:
        assert expected in reason
