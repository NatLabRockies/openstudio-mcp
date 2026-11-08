"""Option checks in scripts/benchmark_sweep.py that must abort before any leg runs."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from benchmark_sweep import http_unsupported

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("transport", "arms", "env", "expected"), [
    ("http", ["full"], {}, None),
    ("http", ["full"], {"LLM_TESTS_CODE_MODE": "0"}, None),
    ("stdio", ["full", "noskills"], {"LLM_TESTS_CODE_MODE": "1"}, None),
    ("http", ["full", "noskills"], {}, "full arm, not ['noskills']"),
    ("http", ["nohost"], {}, "full arm, not ['nohost']"),
    ("http", ["full"], {"LLM_TESTS_CODE_MODE": "1"}, "code mode off"),
])
def test_http_sweeps_refuse_options_the_leg_server_does_not_receive(transport, arms, env, expected):
    # Regression: review of #238 — start_http_server never passes
    # OSMCP_DISABLE_KNOWLEDGE_SKILLS or OSMCP_CODE_MODE, so a noskills or
    # code-mode HTTP leg would have run as a full-arm leg and been saved as noskills
    reason = http_unsupported(transport, arms, env)
    if expected is None:
        assert reason is None
    else:
        assert expected in reason
