from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

# -----------------------------------------------------------------------------
# Defaults (override via environment variables in CI or locally)
# -----------------------------------------------------------------------------
DEFAULT_OSW_2013 = os.environ.get(
    "MCP_OSW_2013",
    "tests/assets/SEB_model/SEB4_baseboard/workflow.osw",
)
DEFAULT_OSW_2012_HARDCODED = os.environ.get(
    "MCP_OSW_2012_HARDCODED",
    "tests/assets/SEB_model/SEB4_baseboard/workflow2.osw",
)
DEFAULT_OSW_2013_BAD_WEATHER = os.environ.get(
    "MCP_OSW_2013_BAD_WEATHER",
    "tests/assets/SEB_model/SEB4_baseboard/workflow3.osw",
)
DEFAULT_EPW_2012 = os.environ.get(
    "MCP_EPW_2012",
    "tests/assets/SEB_model/SEB4_baseboard/files/SRRL_2012AMY_60min.epw",
)

# Expected values (override if OpenStudio/E+ versions change results)
EXPECTED_2013_EUI = float(os.environ.get("EXPECTED_2013_EUI", "0.08220719519609203"))
EXPECTED_2012_EUI = float(os.environ.get("EXPECTED_2012_EUI", "0.0822079882501734"))
EXPECTED_2012_TOTAL_SITE_ENERGY = float(os.environ.get("EXPECTED_2012_TOTAL_SITE_ENERGY", "141.05"))

# Tolerances (defaults intentionally lenient; tighten once stable)
EUI_RTOL = float(os.environ.get("EXPECTED_EUI_RTOL", "0.02"))
EUI_ATOL = float(os.environ.get("EXPECTED_EUI_ATOL", "0.0"))
SITE_RTOL = float(os.environ.get("EXPECTED_SITE_RTOL", "0.02"))
SITE_ATOL = float(os.environ.get("EXPECTED_SITE_ATOL", "0.0"))


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _extract_run_status(status: Any) -> str:
    """openstudio-mcp returns: {"ok": True, "run": {"status": "..."}}."""
    if isinstance(status, dict):
        run = status.get("run")
        if isinstance(run, dict):
            return str(run.get("status") or "")
        return str(status.get("status") or status.get("state") or "")
    return str(status)


_DRIVE_ABS_RE = re.compile(r"^[A-Za-z]:[\\/].+")


def _looks_absolute_on_host(p: str) -> bool:
    """True if p is an absolute path on the host OS (Posix or Windows-drive)."""
    if not p:
        return False
    if p.startswith("/"):
        return True
    if _DRIVE_ABS_RE.match(p):
        return True
    return False


def _is_containerish_path(p: str) -> bool:
    """Heuristic: paths that are meant for a container filesystem.

    Notes:
      - In Git Bash/MSYS, values like /inputs/... can be rewritten into
        C:/Program Files/Git/inputs/... before Python sees them. Those are
        still container-intended, so we treat anything containing '/inputs/'
        (or '\\inputs\\') as containerish too.
    """
    if not p:
        return False

    norm = p.replace("\\", "/")

    # Common container mount roots for this project
    if norm.startswith(("/repo/", "/inputs/", "/runs/")) or norm == "/repo":
        return True

    # MSYS path-rewrite form: C:/Program Files/Git/inputs/...
    if "/inputs/" in norm or norm.endswith("/inputs") or "/repo/" in norm or "/runs/" in norm:
        # If it includes these mount roots, it's not a real host path we should validate.
        # This avoids false failures like C:\Program Files\Git\inputs\...
        return True

    # Any absolute posix path is *likely* containerish when running tests on Windows hosts
    if p.startswith("/"):
        return True

    return False


async def _call_tool(session: ClientSession, name: str, args: dict, timeout: float | None = None) -> Any:
    if timeout is None:
        raw = await session.call_tool(name, args)
    else:
        raw = await asyncio.wait_for(session.call_tool(name, args), timeout=timeout)
    return unwrap(raw)


def _parse_metrics(metrics_payload: Any) -> tuple[float | None, float | None, str | None]:
    """Returns (eui, total_site_energy_value, eui_units)."""
    if not isinstance(metrics_payload, dict):
        return None, None, None
    m = metrics_payload.get("metrics")
    if not isinstance(m, dict):
        return None, None, None

    eui = m.get("eui")
    eui_units = m.get("eui_units")

    tse = m.get("total_site_energy")
    tse_val = None
    if isinstance(tse, dict):
        tse_val = tse.get("value")

    try:
        eui_f = float(eui) if eui is not None else None
    except Exception:
        eui_f = None

    try:
        tse_f = float(tse_val) if tse_val is not None else None
    except Exception:
        tse_f = None

    return eui_f, tse_f, str(eui_units) if eui_units is not None else None


def _format_metrics(metrics: Any) -> str:
    if not isinstance(metrics, dict):
        return str(metrics)

    m = metrics.get("metrics") if isinstance(metrics.get("metrics"), dict) else {}
    total = m.get("total_site_energy") if isinstance(m.get("total_site_energy"), dict) else {}
    val = total.get("value")
    units = total.get("units")
    kbtu = total.get("kbtu")
    src = total.get("source")
    eui = m.get("eui")
    eui_units = m.get("eui_units")
    uh_h = m.get("unmet_hours_heating")
    uh_c = m.get("unmet_hours_cooling")

    parts = []
    if val is not None:
        parts.append(f"Total Site Energy: {val} {units or ''} (kbtu={kbtu}) src={src}")
    if eui is not None:
        parts.append(f"EUI: {eui} {eui_units or ''}".rstrip())
    if uh_h is not None or uh_c is not None:
        parts.append(f"Unmet Hours (H/C): {uh_h}/{uh_c}")

    if not parts:
        return json.dumps(metrics, indent=2, sort_keys=True, default=str)

    return " | ".join(parts)


def _assert_close(name: str, got: float, expected: float, *, rtol: float, atol: float, units: str | None = None) -> None:
    ok = math.isclose(got, expected, rel_tol=rtol, abs_tol=atol)
    u = f" {units}" if units else ""
    print(f"[openstudio-mcp] {name}_check: got={got}{u} expected={expected}{u} rtol={rtol} atol={atol} ok={ok}")
    assert ok, f"{name} mismatch: got={got}{u} expected={expected}{u} rtol={rtol} atol={atol}"


async def _run_once_and_wait(*, osw_path: str, epw_path: str | None, allow_failure: bool = False) -> dict:
    poll_seconds = float(os.environ.get("MCP_POLL_SECONDS", "2"))
    log_tail = int(os.environ.get("MCP_LOG_TAIL", "200"))
    hard_timeout = float(os.environ.get("MCP_HARD_TIMEOUT", str(60 * 30)))  # 30 min default
    tool_timeout = float(os.environ.get("MCP_TOOL_TIMEOUT", "30"))

    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            run_args: dict[str, Any] = {"osw_path": osw_path, "epw_path": epw_path, "name": "SEB4_baseboard"}
            run_res = await _call_tool(session, "run_osw", run_args, timeout=tool_timeout)

            # If the tool returns ok=false (validation / missing inputs), allow tests to assert on that.
            if isinstance(run_res, dict) and run_res.get("ok") is False:
                if allow_failure:
                    return {"run_res": run_res}
                raise AssertionError(f"run_osw returned ok=false: {run_res}")

            run_id = None
            if isinstance(run_res, dict):
                run_id = run_res.get("run_id") or run_res.get("id")
            if not run_id:
                if allow_failure:
                    return {"run_id": None, "state": "failed", "run_res": run_res, "status": None, "metrics": None}
                raise AssertionError(f"Could not determine run_id from: {run_res}")

            last_log_fp = None
            terminal = {"success", "failed", "error", "cancelled", "canceled"}
            started = time.time()

            while True:
                if time.time() - started > hard_timeout:
                    raise AssertionError(f"Timed out after {hard_timeout}s waiting for run to finish. run_id={run_id}")

                status = await _call_tool(session, "get_run_status", {"run_id": run_id}, timeout=tool_timeout)
                logs = await _call_tool(
                    session,
                    "get_run_logs",
                    {"run_id": run_id, "stream": "openstudio", "tail": log_tail},
                    timeout=tool_timeout,
                )

                logs_text = None
                if isinstance(logs, dict):
                    logs_text = logs.get("logs") or logs.get("text")
                elif isinstance(logs, str):
                    logs_text = logs

                if logs_text:
                    fp = hash(logs_text)
                    if fp != last_log_fp:
                        print("----- log tail (openstudio) -----")
                        print(logs_text.rstrip())
                        print("----- end log tail (openstudio) -----\n")
                        last_log_fp = fp

                state = _extract_run_status(status).lower()
                if state in terminal:
                    metrics = await _call_tool(
                        session, "extract_summary_metrics", {"run_id": run_id}, timeout=tool_timeout,
                    )
                    return {"run_id": run_id, "status": status, "state": state, "metrics": metrics}

                await asyncio.sleep(poll_seconds)


def _host_path_exists_if_applicable(p: str) -> None:
    """Fail fast if OSW path is host-relative and missing; skip for absolute/container paths.

    Key rule: only validate existence for *relative* paths (repo-relative on the host).
    Any absolute path is either:
      - truly absolute on the host (not something we can reliably validate across platforms), or
      - a container-intended path (e.g. /inputs/...) possibly rewritten by MSYS.
    """
    if not p:
        return
    if _is_containerish_path(p) or _looks_absolute_on_host(p):
        return
    pp = Path(p)
    if not pp.exists():
        pytest.fail(f"Missing workflow at {pp}")


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------
@pytest.mark.integration
def test_mcp_run_seb4_2013_default_weather():
    """Run the default SEB4 OSW (2013 EPW via file_paths) and sanity-check EUI."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable OpenStudio integration tests.")

    _host_path_exists_if_applicable(DEFAULT_OSW_2013)

    result = asyncio.run(_run_once_and_wait(osw_path=DEFAULT_OSW_2013, epw_path=None))
    state = (result.get("state") or "").lower()
    metrics = result.get("metrics")

    print(f"[openstudio-mcp] run_id={result.get('run_id')} state={state}")
    if metrics is not None:
        print(f"[openstudio-mcp] metrics: {_format_metrics(metrics)}")

    assert state == "success", f"Run did not succeed. state={state} status={result.get('status')}"

    eui, _, units = _parse_metrics(metrics)
    assert eui is not None, "Expected EUI to be present in metrics."
    _assert_close("eui_2013", eui, EXPECTED_2013_EUI, rtol=EUI_RTOL, atol=EUI_ATOL, units=units)


@pytest.mark.integration
def test_mcp_run_seb4_2012_hardcoded_weather_in_osw():
    """Run workflow2.osw which hardcodes the 2012 EPW, and check EUI + total site energy."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable OpenStudio integration tests.")

    _host_path_exists_if_applicable(DEFAULT_OSW_2012_HARDCODED)

    result = asyncio.run(_run_once_and_wait(osw_path=DEFAULT_OSW_2012_HARDCODED, epw_path=None))
    state = (result.get("state") or "").lower()
    metrics = result.get("metrics")

    print(f"[openstudio-mcp] run_id={result.get('run_id')} state={state}")
    if metrics is not None:
        print(f"[openstudio-mcp] metrics: {_format_metrics(metrics)}")

    assert state == "success", f"Run did not succeed. state={state} status={result.get('status')}"

    eui, total_site, units = _parse_metrics(metrics)
    assert eui is not None, "Expected EUI to be present in metrics."
    assert total_site is not None, "Expected Total Site Energy to be present in metrics."
    _assert_close("eui_2012", eui, EXPECTED_2012_EUI, rtol=EUI_RTOL, atol=EUI_ATOL, units=units)
    _assert_close("total_site_energy_2012", total_site, EXPECTED_2012_TOTAL_SITE_ENERGY, rtol=SITE_RTOL, atol=SITE_ATOL)


@pytest.mark.integration
def test_mcp_run_seb4_2012_override_weather_via_tool_arg():
    """Run workflow.osw but override weather to the 2012 EPW via run_osw(epw_path)."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable OpenStudio integration tests.")

    _host_path_exists_if_applicable(DEFAULT_OSW_2013)

    result = asyncio.run(_run_once_and_wait(osw_path=DEFAULT_OSW_2013, epw_path=DEFAULT_EPW_2012))
    state = (result.get("state") or "").lower()
    metrics = result.get("metrics")

    print(f"[openstudio-mcp] run_id={result.get('run_id')} state={state}")
    if metrics is not None:
        print(f"[openstudio-mcp] metrics: {_format_metrics(metrics)}")

    assert state == "success", f"Run did not succeed. state={state} status={result.get('status')}"

    # Expect to match the 2012 hardcoded workflow within tolerance
    eui, total_site, units = _parse_metrics(metrics)
    assert eui is not None, "Expected EUI to be present in metrics."
    assert total_site is not None, "Expected Total Site Energy to be present in metrics."
    _assert_close("eui_2012_override", eui, EXPECTED_2012_EUI, rtol=EUI_RTOL, atol=EUI_ATOL, units=units)
    _assert_close("total_site_energy_2012_override", total_site, EXPECTED_2012_TOTAL_SITE_ENERGY, rtol=SITE_RTOL, atol=SITE_ATOL)


@pytest.mark.integration
def test_mcp_run_seb4_bad_weather_in_osw_fails_validation():
    """workflow3.osw references a missing EPW; server should fail fast with a clear error."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable OpenStudio integration tests.")

    _host_path_exists_if_applicable(DEFAULT_OSW_2013_BAD_WEATHER)

    # This should fail *before* starting a run, via validate_osw.
    result = asyncio.run(_run_once_and_wait(osw_path=DEFAULT_OSW_2013_BAD_WEATHER, epw_path=None, allow_failure=True))

    # allow_failure=True returns the raw run_osw response in `run_res`
    run_res = result.get("run_res") if isinstance(result, dict) else None
    assert isinstance(run_res, dict) and run_res.get("ok") is False
    err = str(run_res.get("error") or "")
    issues = run_res.get("issues") or []
    joined = " | ".join(map(str, issues))
    assert ("weather" in err.lower()) or ("weather" in joined.lower()) or ("epw" in err.lower()) or ("epw" in joined.lower()), (
        f"Expected a weather/EPW validation error. error={err!r} issues={issues!r}"
    )


@pytest.mark.integration
def test_mcp_run_seb4_bad_weather_in_osw_succeeds_with_epw_override():
    """workflow3.osw has a bad weather_file, but an explicit --epw override should still work."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable OpenStudio integration tests.")

    _host_path_exists_if_applicable(DEFAULT_OSW_2013_BAD_WEATHER)
    _host_path_exists_if_applicable(DEFAULT_EPW_2012)

    result = asyncio.run(_run_once_and_wait(osw_path=DEFAULT_OSW_2013_BAD_WEATHER, epw_path=DEFAULT_EPW_2012))
    state = (result.get("state") or "").lower()
    assert state == "success", f"Run did not succeed. state={state} status={result.get('status')}"
    # extract_summary_metrics returns {"ok": True, "metrics": {...}, ...}
    eui, total_site, eui_units = _parse_metrics(result.get("metrics"))

    assert eui is not None, f"Expected EUI to be present. metrics={result.get('metrics')!r}"
    _assert_close(
        "eui_workflow3_override_2012",
        got=float(eui),
        expected=EXPECTED_2012_EUI,
        rtol=EUI_RTOL,
        atol=EUI_ATOL,
        units=eui_units,
    )
    if total_site is not None:
        _assert_close(
            "total_site_energy_workflow3_override_2012",
            got=float(total_site),
            expected=EXPECTED_2012_TOTAL_SITE_ENERGY,
            rtol=SITE_RTOL,
            atol=SITE_ATOL,
            units=None,
        )

@pytest.mark.integration
def test_mcp_bad_osw_path_fails_cleanly():
    """Regression guard: running a missing OSW should fail cleanly (no hang, no ExceptionGroup noise)."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable OpenStudio integration tests.")

    missing = os.environ.get("MCP_MISSING_OSW_PATH", "/definitely/not/a/real/workflow.osw")

    # Use allow_failure=True so the helper returns a structured error instead of raising
    # and triggering AnyIO/ExceptionGroup TaskGroup noise in pytest output.
    result = asyncio.run(_run_once_and_wait(osw_path=missing, epw_path=None, allow_failure=True))
    assert isinstance(result, dict), f"Unexpected result type: {type(result)} => {result!r}"

    run_res = result.get("run_res")
    assert isinstance(run_res, dict) and run_res.get("ok") is False, f"Expected ok=false. run_res={run_res!r}"

    err = str(run_res.get("error") or "").lower()
    assert ("osw" in err) or ("not found" in err), f"Unexpected error message: {run_res!r}"