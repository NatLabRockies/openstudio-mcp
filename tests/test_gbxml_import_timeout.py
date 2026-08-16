"""Tests for the configurable gbXML import wall-clock cap — requires OpenStudio (Docker).

The cap exists because the gbXML measure workflow's runtime is almost entirely one measure's
single-threaded surface matching, so it tracks the host's per-core speed and nothing else. A
hardcoded literal was raised 300 -> 600 once for a boundary flake and then flaked again at ~625s
on a slower machine, taking
tests/test_gbxml_import.py::test_geometry_repair_pipeline_on_austin_apartment_fixture with it.
The same import on that host measured 622-687s run on its own and 1228s with the rest of its own
test file alongside it, which is why the default has headroom over the observed worst case rather
than sitting just above the number that happened to be measured first.

These run in seconds rather than the ~10 minutes a real import costs: setting the cap to ~1s makes
the subprocess get killed almost immediately, which exercises the genuine timeout path. Driven
in-process with monkeypatch.setattr on the module constant, the pattern
tests/test_sim_queue.py uses for SIM_TIMEOUT_SECONDS.
"""
from __future__ import annotations

import os
import subprocess
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_OPENSTUDIO_INTEGRATION"),
        reason="requires OpenStudio (set RUN_OPENSTUDIO_INTEGRATION=1)",
    ),
]

GBXML_PATH_AUSTIN_SLIVERS = "/repo/tests/assets/gbxml/austin_apartment_slivers.xml"
AUSTIN_EPW_PATH = "/repo/tests/assets/USA_TX_Austin-Camp.Mabry.ANGB.722544_TMYx.2009-2023.epw"


@pytest.mark.parametrize(("cap", "rendered"), [(1.0, "1s"), (0.5, "0.5s")])
def test_timeout_returns_an_actionable_error_naming_the_cap_and_the_knob(
    monkeypatch, cap, rendered,
):
    # Regression: the timeout message was a hardcoded "gbXML import timed out (10 min)". It went
    # stale the moment the cap moved and named nothing the caller could change, so a timeout was
    # a dead end. It must report the cap actually in force and the env var that sets it.
    #
    # The cap it reports has to be the real one. Formatting it with .0f rendered a 0.5s cap as
    # "0s" — not merely lossy but self-contradicting, since <= 0 is documented as "no cap" in
    # config.py, docs/testing/testing.md and at the call site, so the message claimed a timeout
    # against a cap meaning "no timeout". Sub-second caps are reachable: _safe_float accepts any
    # finite value, and the call site treats anything > 0 as live. 0.5 is here because it is
    # both the reported case and the one that lands exactly on .0f's half-to-even boundary.
    from mcp_server.skills.gbxml_import import operations as ops

    monkeypatch.setattr(ops, "GBXML_IMPORT_TIMEOUT_SECONDS", cap)

    result = ops.import_gbxml_op(
        gbxml_path=GBXML_PATH_AUSTIN_SLIVERS,
        epw_path=AUSTIN_EPW_PATH,
        run_name=f"pytest_timeout_{uuid.uuid4().hex[:10]}",
    )

    # Returned, not raised — operations never raise through the MCP layer.
    assert result["ok"] is False, result
    assert "OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS" in result["error"], result
    assert f"{rendered} wall-clock cap" in result["error"], result
    assert "10 min" not in result["error"], result
    # The specific contradiction, not just the general rounding.
    assert "the 0s" not in result["error"], result


@pytest.mark.parametrize("cap", [0.0, -1.0, -0.5])
def test_non_positive_cap_disables_rather_than_timing_out_instantly(monkeypatch, cap):
    # Regression: <= 0 means "no cap" across this server's timeouts (SIM_TIMEOUT_SECONDS
    # gates on `<= 0`; resolve_gc_days clamps with max(0.0, ...)). This call site used
    # `X or None`, which caught only 0.0 — a negative from a misconfigured env var stayed
    # truthy and reached subprocess.run. That does not raise ValueError: it puts the
    # deadline in the past, so TimeoutExpired fires in ~0ms and lands in the dedicated
    # handler, which reported "exceeded the -1s wall-clock cap" — a confident, wrong
    # diagnosis pointing at the workload instead of the config. -0.5 is here because it
    # formats as "-0s", losing even the minus sign that hints at the real cause.
    from mcp_server.skills.gbxml_import import operations as ops

    monkeypatch.setattr(ops, "GBXML_IMPORT_TIMEOUT_SECONDS", cap)

    seen: dict[str, object] = {}
    real_run = subprocess.run

    def _capture(*args, **kwargs):
        # Only the workflow invocation matters; anything else the op shells out to runs for real.
        if "timeout" in kwargs and "openstudio" in " ".join(str(a) for a in args[0]):
            seen["timeout"] = kwargs["timeout"]
            raise subprocess.TimeoutExpired(cmd="openstudio", timeout=cap)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(ops.subprocess, "run", _capture)

    result = ops.import_gbxml_op(
        gbxml_path=GBXML_PATH_AUSTIN_SLIVERS,
        epw_path=AUSTIN_EPW_PATH,
        run_name=f"pytest_nocap_{uuid.uuid4().hex[:10]}",
    )

    assert seen["timeout"] is None, seen
    assert result["ok"] is False, result  # the stub raises TimeoutExpired to end the call early


def test_cap_defaults_to_1800_and_is_overridable_by_either_env_var(monkeypatch):
    # Validates: the constant follows this server's established two-name env convention
    # (OPENSTUDIO_MCP_* taking precedence over OSMCP_*), and that a malformed or non-finite value
    # falls back to the default instead of disabling enforcement — _safe_float rejects NaN/inf
    # precisely because a non-finite cap makes every comparison against it false.
    import importlib

    from mcp_server import config

    def _reload_with(**env):
        for name in ("OPENSTUDIO_MCP_GBXML_IMPORT_TIMEOUT_SECONDS",
                     "OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS"):
            monkeypatch.delenv(name, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(config).GBXML_IMPORT_TIMEOUT_SECONDS

    try:
        assert _reload_with() == 1800.0
        # Both overrides use values distinct from the default, so an override that was silently
        # ignored would fail here rather than coincidentally matching.
        assert _reload_with(OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS="900") == 900.0
        assert _reload_with(OPENSTUDIO_MCP_GBXML_IMPORT_TIMEOUT_SECONDS="2400") == 2400.0
        # The long name wins when both are set.
        assert _reload_with(
            OPENSTUDIO_MCP_GBXML_IMPORT_TIMEOUT_SECONDS="2400",
            OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS="900",
        ) == 2400.0
        assert _reload_with(OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS="not-a-number") == 1800.0
        assert _reload_with(OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS="nan") == 1800.0
        assert _reload_with(OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS="inf") == 1800.0
        # 0 is a legitimate value meaning "no cap", not a parse failure.
        assert _reload_with(OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS="0") == 0.0
    finally:
        # Other tests in this session import the same module object.
        importlib.reload(config)
