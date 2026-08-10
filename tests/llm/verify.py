"""Post-hoc domain-validity verifier — deterministic, non-LLM (D6).

A workflow pass requires successful EnergyPlus termination and outputs
verified within tolerance by a SEPARATE non-LLM client, independent of any
agent claims. Mirrors the integration-test client pattern: same image, same
/runs volume (via runner._docker_mcp_args), direct MCP stdio session.

Explicit scope limit (paper): compliance/zoning/design-review are NOT
checked — completion, fatal/severe errors, unmet hours, and EUI only.
"""
from __future__ import annotations

import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .runner import _docker_mcp_args


def _unwrap(res) -> dict:
    """Extract a dict from a CallToolResult (same pattern as tests/conftest)."""
    content = getattr(res, "content", None)
    if not content:
        return res if isinstance(res, dict) else {"_raw": str(res)}
    text = getattr(content[0], "text", None)
    if text is None:
        return {"_raw": str(content[0])}
    try:
        parsed = json.loads(text.strip())
        return parsed if isinstance(parsed, dict) else {"_raw": text}
    except json.JSONDecodeError:
        return {"_raw": text.strip()}


async def _verify(run_id: str) -> dict:
    params = StdioServerParameters(command="docker", args=_docker_mcp_args())
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            status = _unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))
            metrics = _unwrap(await s.call_tool(
                "extract_summary_metrics", {"run_id": run_id}))
            errors = _unwrap(await s.call_tool(
                "extract_simulation_errors", {"run_id": run_id}))
            qaqc = _unwrap(await s.call_tool(
                "run_qaqc_checks", {"run_id": run_id}))

    m = metrics.get("metrics", {}) if metrics.get("ok") else {}
    return {
        "run_id": run_id,
        "completed": (status.get("run", {}).get("status") or "").lower() == "success",
        "fatal": len(errors.get("fatal", [])) if errors.get("ok") else None,
        "severe": len(errors.get("severe", [])) if errors.get("ok") else None,
        "eui": m.get("eui_kBtu_ft2"),
        "unmet_heating": m.get("unmet_hours_heating"),
        "unmet_cooling": m.get("unmet_hours_cooling"),
        "qaqc": qaqc,
    }


def verify_run(run_id: str) -> dict:
    """Verify one run via a direct MCP session (no agent involved).

    Returns {run_id, completed, fatal, severe, eui, unmet_heating,
    unmet_cooling, qaqc}. Image/runs-dir/arm come from the same env knobs
    as the agent harness, so the verifier sees exactly the runs the agent
    produced.
    """
    return asyncio.run(_verify(run_id))


def assert_sim_valid(
    v: dict,
    *,
    eui_ref: float | None = None,
    rel: float = 0.05,
    max_unmet: float | None = 300.0,
) -> None:
    """Raise AssertionError unless the verified run is domain-valid.

    Checks: EnergyPlus terminated successfully, 0 fatal / 0 severe errors,
    total unmet hours <= max_unmet (None skips — e.g. the deliberately
    undersized llm-test-baseline-hvac model), and EUI within rel of the
    pinned reference when one is given.
    """
    rid = v.get("run_id", "?")
    assert v["completed"], f"run {rid}: EnergyPlus did not terminate successfully"
    assert v["fatal"] == 0, f"run {rid}: {v['fatal']} fatal error(s) in eplusout.err"
    assert v["severe"] == 0, f"run {rid}: {v['severe']} severe error(s) in eplusout.err"

    if max_unmet is not None:
        unmet = (v.get("unmet_heating") or 0) + (v.get("unmet_cooling") or 0)
        assert unmet <= max_unmet, (
            f"run {rid}: unmet hours {unmet:.1f} exceed {max_unmet:.0f}"
        )

    if eui_ref is not None:
        eui = v.get("eui")
        assert isinstance(eui, (int, float)), (
            f"run {rid}: no EUI in verified metrics (got {eui!r})"
        )
        assert abs(eui - eui_ref) <= rel * abs(eui_ref), (
            f"run {rid}: EUI {eui:.2f} outside {rel * 100:.0f}% of pinned "
            f"{eui_ref:.2f} kBtu/ft2"
        )
