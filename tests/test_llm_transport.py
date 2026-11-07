"""LLM harness transport selection: prompt rewriting, config, cap handling."""
from __future__ import annotations

import json
import subprocess

import pytest

from tests.llm import runner, transport, verify

pytestmark = pytest.mark.unit

STDIO_PROMPT = (
    "Load /runs/examples/llm-test-baseline/baseline_model.osm, test "
    "/measures/local/custom/my_measure, read /inputs/SystemD_baseline.osm "
    "and /opt/runs/keep.txt."
)


@pytest.fixture
def http_env(monkeypatch):
    monkeypatch.setenv("LLM_TESTS_TRANSPORT", "http")
    monkeypatch.setenv("LLM_TESTS_MCP_URL", "http://127.0.0.1:8100/mcp")
    monkeypatch.setenv("LLM_TESTS_MCP_TOKEN", "tok")


def test_http_prompt_moves_to_user_area(http_env):
    # Regression: the HTTP server denies /runs/examples/... for a token user,
    # so unrewritten prompts fail every baseline-model test on a path error
    assert transport.agent_prompt(STDIO_PROMPT) == (
        "Load /runs/bench/examples/llm-test-baseline/baseline_model.osm, test "
        "/measures/bench/custom/my_measure, read /inputs/SystemD_baseline.osm "
        "and /opt/runs/keep.txt."
    )


def test_stdio_prompt_unchanged(monkeypatch):
    # Validates: the default transport keeps prompts byte-identical, so stdio
    # legs stay comparable with every earlier benchmark
    monkeypatch.delenv("LLM_TESTS_TRANSPORT", raising=False)
    assert transport.agent_prompt(STDIO_PROMPT) == STDIO_PROMPT


def test_unknown_transport_rejected(monkeypatch):
    # Validates: a typo must abort, not silently run the stdio arm as "http"
    monkeypatch.setenv("LLM_TESTS_TRANSPORT", "htpp")
    with pytest.raises(ValueError, match="stdio or http"):
        transport.is_http()


def test_http_mcp_config_keeps_server_name(http_env):
    # Validates: tool names are parsed via the mcp__openstudio__ prefix, so a
    # renamed server would count every call as the wrong tool
    config = json.loads(runner._write_mcp_config().read_text())
    assert config == {"mcpServers": {"openstudio": {
        "type": "http",
        "url": "http://127.0.0.1:8100/mcp",
        "headers": {"Authorization": "Bearer tok"},
    }}}


@pytest.mark.parametrize(("floor", "timeout", "expected"), [
    ("600", 120, 600),
    ("600", 900, 900),
    ("0", 120, 120),
])
def test_timeout_floor(monkeypatch, floor, timeout, expected):
    # Regression: LLM_TESTS_TIMEOUT_BASE only reaches test_06, so a 600 s
    # budget left every other file at its hardcoded 120 s
    monkeypatch.setenv("LLM_TESTS_TIMEOUT_FLOOR", floor)
    assert transport.effective_timeout(timeout) == expected


@pytest.mark.parametrize(("text", "expected"), [
    ("You've hit your limit, resets 3pm", True),
    ("Claude usage limit reached", True),
    ("API Error: 429 rate_limit_error", True),
    ("Session limit reached", True),
    ("MCP server failed to start", False),
    ("Timed out after 600s", False),
])
def test_usage_cap_detection(text, expected):
    # Regression: opus48-v1.2.1 lost 9 legs to a session cap
    assert transport.looks_like_usage_cap(text) is expected


def _proc(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["claude"], rc, stdout, stderr)


def test_success_mentioning_limit_is_not_a_cap():
    # Validates: an agent's answer about a rate limit must not stall the leg
    stdout = json.dumps({"type": "result", "is_error": False,
                         "result": "The usage limit of the cooling tower is 5"})
    assert runner._cli_capped(_proc(0, stdout)) is False


def test_is_error_result_with_cap_text_is_a_cap():
    # Validates: the CLI can report a cap with rc=0 and an error result
    stdout = json.dumps({"type": "result", "is_error": True,
                         "result": "You've hit your limit, resets 3pm"})
    assert runner._cli_capped(_proc(0, stdout)) is True


def test_nonzero_rc_with_other_error_is_not_a_cap():
    # Validates: a real CLI failure surfaces at once, not after a 24 h wait
    assert runner._cli_capped(_proc(1, stderr="MCP config invalid")) is False


def test_wait_out_cap_retries_until_clear():
    # Validates: a capped prompt reruns after the wait and returns the real result
    calls = iter([(True, "capped"), (True, "capped"), (False, "real")])
    slept = []
    value = transport.wait_out_cap(lambda: next(calls), budget_s=3600, poll_s=600,
                                   sleep=slept.append)
    assert value == "real"
    assert slept == [600, 600]


def test_wait_out_cap_gives_up_at_budget():
    # Validates: the wait is bounded, so a permanent failure ends the test
    slept = []
    value = transport.wait_out_cap(lambda: (True, "capped"), budget_s=1200,
                                   poll_s=600, sleep=slept.append)
    assert value == "capped"
    assert slept == [600, 600]


def test_wait_out_cap_off_by_default(monkeypatch):
    # Validates: outside a sweep a cap fails fast instead of hanging pytest
    monkeypatch.delenv("LLM_TESTS_CAP_WAIT_S", raising=False)
    slept = []
    value = transport.wait_out_cap(lambda: (True, "capped"), sleep=slept.append)
    assert value == "capped"
    assert slept == []


def test_http_verifier_uses_the_http_server(http_env, monkeypatch):
    # Regression: verify_run opened a stdio server for HTTP legs, which answers
    # "Unknown run_id" for an HTTP user's runs, so every simulation chain test
    # failed its EnergyPlus check whatever the simulation actually did
    seen = {}

    class Stop(Exception):
        pass

    def fake_http(url, headers=None):
        seen.update(url=url, headers=headers)
        raise Stop

    def no_stdio(_params):
        raise AssertionError("HTTP leg must not verify over stdio")

    monkeypatch.setattr(verify, "streamablehttp_client", fake_http)
    monkeypatch.setattr(verify, "stdio_client", no_stdio)
    with pytest.raises(Stop):
        verify.verify_run("run_x")
    assert seen == {"url": "http://127.0.0.1:8100/mcp",
                    "headers": {"Authorization": "Bearer tok"}}
