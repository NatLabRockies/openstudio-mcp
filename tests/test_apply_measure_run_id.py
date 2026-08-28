"""apply_measure must accept run_id over MCP for ReportingMeasures (plan B1).

The operation (measures/operations.py) fully implements the
ReportingMeasure-on-completed-run path — stage SQL/IDF from the run, execute
`openstudio run --postprocess_only` — but the MCP wrapper's schema dropped
run_id, so the documented create_measure -> test_measure -> apply_measure
workflow was unreachable over MCP for ReportingMeasures.
"""
import asyncio
import uuid

import pytest
from conftest import (
    EPW_PATH,
    integration_enabled,
    poll_until_done,
    server_params,
    unwrap,
)
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_amri") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# Reporting body that actually reads the simulation SQL, so a green run
# proves the postprocess path wired the artifacts — not just that the
# schema accepted the kwarg.
RUBY_REPORTING_BODY = (
    '    query = "SELECT Value FROM TabularDataWithStrings '
    "WHERE ReportName='AnnualBuildingUtilityPerformanceSummary' "
    "AND TableName='Site and Source Energy' "
    "AND RowName='Total Site Energy' "
    "AND ColumnName='Total Energy' "
    "AND Units='GJ'\"\n"
    "    val = sql.execAndReturnFirstDouble(query)\n"
    "    if val.is_initialized\n"
    '      runner.registerValue("total_site_energy_gj", val.get)\n'
    '      runner.registerInfo("Total Site Energy: #{val.get} GJ")\n'
    "    end\n"
    '    runner.registerFinalCondition("Report complete")'
)


@pytest.mark.integration
def test_apply_measure_accepts_run_id_for_reporting_measure():
    """apply_measure(measure_dir, run_id=...) postprocesses a completed run."""
    # Regression: MCP wrapper accepted only (measure_dir, arguments) and
    # dropped run_id — the schema rejected the call both served skills
    # instruct (measure-authoring, tool-workflows), leaving the implemented
    # ReportingMeasure path unreachable over MCP (plan B1)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                # --- Arrange: model + completed simulation ---
                name = _unique("amri_model")
                cr = unwrap(await s.call_tool("create_example_osm", {"name": name}))
                assert cr["ok"] is True, cr
                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": cr["osm_path"],
                    "epw_path": EPW_PATH,
                }))
                assert sim["ok"] is True, sim
                run_id = sim["run_id"]
                status = await poll_until_done(s, run_id)
                assert status["run"]["status"] == "success", status

                # --- Arrange: a ReportingMeasure that reads the run's SQL ---
                mname = _unique("amri_report")
                create = unwrap(await s.call_tool("create_measure", {
                    "name": mname,
                    "description": "EUI report for run_id wiring test",
                    "run_body": RUBY_REPORTING_BODY,
                    "language": "Ruby",
                    "measure_type": "ReportingMeasure",
                }))
                assert create["ok"] is True, create

                # --- Act: the call the served skills instruct ---
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": create["measure_dir"],
                    "run_id": run_id,
                }))

                # --- Assert: postprocess ran and read the simulation SQL ---
                assert res["ok"] is True, res
                msgs = res.get("runner_messages") or {}
                assert msgs.get("final_condition") == "Report complete", res
                infos = msgs.get("info") or []
                assert any("Total Site Energy" in m for m in infos), (
                    f"reporting measure did not read the run's SQL: {res}"
                )

                # --- Assert: clean error for a missing run stays intact ---
                bad = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": create["measure_dir"],
                    "run_id": "run_does_not_exist_123",
                }))
                assert bad["ok"] is False
                assert "not found" in bad["error"].lower(), bad

    asyncio.run(_run())
