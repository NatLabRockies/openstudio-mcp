"""Integration tests for the Python EMS skill (EnergyPlus Python Plugins).

Covers: template scaffolding end-to-end (plugin executes inside EnergyPlus and
its output is queryable), schedule actuation, actuator discovery via .edd,
loud failure on bad actuators, source validation, and save/load portability
of the companion files/ dir.
"""
from __future__ import annotations

import asyncio
import json
import os
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

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


def _unique(prefix: str) -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    return f"{prefix}_{worker}_{token}" if worker else f"{prefix}_{token}"


async def _load_example(s, name: str) -> None:
    cr = unwrap(await s.call_tool("create_example_osm", {"name": name}))
    assert cr["ok"] is True, cr
    lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr["ok"] is True, lr


async def _short_run_period(s) -> None:
    rp = unwrap(await s.call_tool("set_run_period", {
        "begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 2,
    }))
    assert rp["ok"] is True, rp


async def _save_and_simulate(s, name: str) -> str:
    """Save to a fresh dir (exercises files/ carry), run, return run_id."""
    save_path = f"/runs/{name}/model.osm"
    sr = unwrap(await s.call_tool("save_osm_model", {"osm_path": save_path}))
    assert sr["ok"] is True, sr
    sim = unwrap(await s.call_tool("run_simulation", {
        "osm_path": save_path, "epw_path": EPW_PATH,
    }))
    assert sim["ok"] is True, sim
    return sim["run_id"]


async def _err_text(s, run_id: str) -> str:
    resp = unwrap(await s.call_tool("read_file", {
        "file_path": f"/runs/{run_id}/run/eplusout.err", "max_bytes": 200000,
    }))
    assert resp.get("ok") is True, resp
    text = resp.get("text", "")
    assert text, f"eplusout.err came back empty: {resp}"
    return text


def _series_by_timestamp(result: dict) -> dict[tuple, float]:
    series = {(d["month"], d["day"], d["hour"], d["minute"]): d["value"]
              for d in result["data"]}
    # A LIKE-filter over-match (two keys in one query) would collapse duplicate
    # timestamps here and corrupt the comparison — fail loudly instead.
    assert len(series) == len(result["data"]), (
        f"duplicate timestamps: query matched more than one series "
        f"(key '{result.get('key')}', {len(result['data'])} rows)")
    return series


@pytest.mark.integration
def test_zone_metric_plugin_end_to_end():
    # Validates: zone_metric_aggregate template executes inside EnergyPlus and its
    # reported PythonPlugin:OutputVariable equals the mean of the 10 per-zone
    # Zone Mean Air Temperature series recomputed from the same SQL
    name = _unique("ems_zonemetric")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # --- Arrange: 10-zone baseline + weather/design days + 2-day run ---
                cr = unwrap(await session.call_tool("create_baseline_osm", {"name": name}))
                assert cr["ok"] is True, cr
                lr = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": cr["osm_path"]}))
                assert lr["ok"] is True, lr
                zr = unwrap(await session.call_tool(
                    "list_thermal_zones", {"max_results": 0}))
                zone_names = [z["name"] for z in zr["thermal_zones"]]
                assert len(zone_names) == 10, f"baseline model must have 10 zones, got {len(zone_names)}"
                wr = unwrap(await session.call_tool(
                    "change_building_location", {"weather_file": EPW_PATH}))
                assert wr["ok"] is True, wr
                await _short_run_period(session)

                # --- Act: create plugin, save (files/ travels), simulate ---
                created = unwrap(await session.call_tool("create_python_plugin", {
                    "name": "Avg Zone Temp",
                    "template": "zone_metric_aggregate",
                    "variable_name": "Zone Mean Air Temperature",
                    "aggregation": "average",
                    "output_variable_name": "Average Zone Temperature",
                    "units": "C",
                }))
                assert created["ok"] is True, created
                assert created["class_name"] == "ZoneMetricAggregate"
                assert created["callbacks"] == ["on_end_of_zone_timestep_before_zone_reporting"]
                assert created["script_path"].endswith("files/avg_zone_temp.py")

                run_id = await _save_and_simulate(session, name)
                status = await poll_until_done(session, run_id)
                assert status["run"]["status"] == "success", status

                # Plugin actually loaded inside EnergyPlus
                err_text = await _err_text(session, run_id)
                assert "PythonPlugin: Class ZoneMetricAggregate imported" in err_text, \
                    f"plugin not imported by EnergyPlus:\n{err_text[-2000:]}"
                assert "** Fatal **" not in err_text

                # --- Assert: aggregate equals mean of the 10 per-zone series ---
                agg = unwrap(await session.call_tool("query_timeseries", {
                    "run_id": run_id,
                    "variable_name": "PythonPlugin:OutputVariable",
                    "key_value": "Average Zone Temperature",
                    "start_month": 1, "start_day": 1, "end_month": 1, "end_day": 2,
                }))
                assert agg["ok"] is True, agg
                agg_series = _series_by_timestamp(agg)
                assert len(agg_series) >= 48, \
                    f"expected at least hourly points over 2 days, got {len(agg_series)}"

                zone_series: list[dict[tuple, float]] = []
                for zone in zone_names:
                    zq = unwrap(await session.call_tool("query_timeseries", {
                        "run_id": run_id,
                        "variable_name": "Zone Mean Air Temperature",
                        "key_value": zone,
                        "start_month": 1, "start_day": 1, "end_month": 1, "end_day": 2,
                    }))
                    assert zq["ok"] is True, f"zone series missing for {zone}: {zq}"
                    zone_series.append(_series_by_timestamp(zq))

                compared = 0
                for ts, agg_value in agg_series.items():
                    zone_values = [zs[ts] for zs in zone_series if ts in zs]
                    if len(zone_values) != len(zone_names):
                        continue
                    expected = sum(zone_values) / len(zone_values)
                    assert agg_value == pytest.approx(expected, rel=1e-4, abs=1e-6), (
                        f"aggregate at {ts} is {agg_value}, mean of 10 zones is {expected}")
                    compared += 1
                assert compared >= 48, f"only {compared} timestamps aligned across all zones"

    asyncio.run(_run())


@pytest.mark.integration
def test_schedule_override_plugin_actuates_schedule():
    # Validates: schedule_override template actuates a Schedule:Constant via EMS —
    # Schedule Value series contains exactly the rule values 21.0/15.6 in equal
    # counts (12h on / 12h off over full days), and the plugin's mirrored output
    # variable equals the schedule series pointwise
    name = _unique("ems_schedoverride")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # --- Arrange ---
                await _load_example(session, name)
                await _short_run_period(session)

                # --- Act ---
                created = unwrap(await session.call_tool("create_python_plugin", {
                    "name": "Test Override",
                    "template": "schedule_override",
                    "schedule_name": "Always On Discrete",
                    "default_value": 15.6,
                    "rules": [{"days": "all", "start_hour": 6, "end_hour": 18, "value": 21.0}],
                }))
                assert created["ok"] is True, created
                assert created["class_name"] == "ScheduleOverride"

                run_id = await _save_and_simulate(session, name)
                status = await poll_until_done(session, run_id)
                assert status["run"]["status"] == "success", status
                err_text = await _err_text(session, run_id)
                assert "PythonPlugin: Class ScheduleOverride imported" in err_text

                # --- Assert: schedule series is exactly the two rule values ---
                sched = unwrap(await session.call_tool("query_timeseries", {
                    "run_id": run_id,
                    "variable_name": "Schedule Value",
                    "key_value": "Always On Discrete",
                    "start_month": 1, "start_day": 1, "end_month": 1, "end_day": 2,
                }))
                assert sched["ok"] is True, sched
                values = [round(d["value"], 6) for d in sched["data"]]
                assert len(values) >= 48, f"expected 2 days of data, got {len(values)} points"
                assert set(values) == {15.6, 21.0}, (
                    f"schedule must be exactly the rule values, got {sorted(set(values))}")
                n_on = sum(1 for v in values if v == 21.0)
                assert n_on == len(values) // 2, (
                    f"12h/day at 21.0 over full days means half the points, "
                    f"got {n_on}/{len(values)}")

                # Plugin's mirrored output equals the schedule series pointwise
                mirrored = unwrap(await session.call_tool("query_timeseries", {
                    "run_id": run_id,
                    "variable_name": "PythonPlugin:OutputVariable",
                    "key_value": "Test Override Applied Value",
                    "start_month": 1, "start_day": 1, "end_month": 1, "end_day": 2,
                }))
                assert mirrored["ok"] is True, mirrored
                sched_ts = _series_by_timestamp(sched)
                mirrored_ts = _series_by_timestamp(mirrored)
                assert len(mirrored_ts) == len(sched_ts)
                for ts, sched_value in sched_ts.items():
                    assert mirrored_ts[ts] == pytest.approx(sched_value, abs=1e-9), (
                        f"mirrored global diverges from schedule at {ts}")

    asyncio.run(_run())


@pytest.mark.integration
def test_list_ems_actuators_discovers_triples():
    # Validates: list_ems_actuators runs the hidden sizing-only discovery sim and
    # parses exact (component type, control type, key) triples from eplusout.edd
    name = _unique("ems_actuators")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _load_example(session, name)

                result = unwrap(await session.call_tool("list_ems_actuators", {
                    "component_type": "Schedule:Constant",
                    "max_results": 0,
                }))
                assert result["ok"] is True, result
                assert result["total_actuators"] >= 1
                triples = {(a["component_type"], a["control_type"], a["actuator_key"])
                           for a in result["actuators"]}
                assert ("Schedule:Constant", "Schedule Value", "ALWAYS ON DISCRETE") in triples, \
                    f"expected the example model's Always On Discrete actuator, got {sorted(triples)}"

                internals = unwrap(await session.call_tool("list_ems_actuators", {
                    "include_internal_variables": True,
                    "key": "People",
                    "max_results": 0,
                }))
                assert internals["ok"] is True, internals
                internal_types = {v["type"] for v in internals["internal_variables"]}
                assert "People Count Design Level" in internal_types, (
                    f"expected people design-level internal variable, got {sorted(internal_types)}")

    asyncio.run(_run())


@pytest.mark.integration
def test_list_ems_actuators_requires_model():
    # Validates: list_ems_actuators without a loaded model fails gracefully with guidance
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = unwrap(await session.call_tool("list_ems_actuators", {}))
                assert result["ok"] is False
                assert "no model loaded" in result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_plugin_bad_actuator_fails_loudly():
    # Validates: a plugin hitting a -1 actuator handle issues a severe message and
    # aborts the run (nonzero callback return) — failure is surfaced through
    # run status and extract_simulation_errors, never silent
    name = _unique("ems_badactuator")
    marker = "python_ems test: intentional missing actuator"
    code = f"""from pyenergyplus.plugin import EnergyPlusPlugin


class BrokenControl(EnergyPlusPlugin):

    def on_begin_timestep_before_predictor(self, state) -> int:
        if not self.api.exchange.api_data_fully_ready(state):
            return 0
        handle = self.api.exchange.get_actuator_handle(
            state, "Schedule:Constant", "Schedule Value", "No Such Schedule XYZ")
        if handle == -1:
            self.api.runtime.issue_severe(state, "{marker}")
            return 1
        return 0
"""

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _load_example(session, name)
                await _short_run_period(session)

                created = unwrap(await session.call_tool("create_python_plugin", {
                    "name": "Broken Control",
                    "template": "custom",
                    "class_name": "BrokenControl",
                    "code": code,
                }))
                assert created["ok"] is True, created

                run_id = await _save_and_simulate(session, name)
                status = await poll_until_done(session, run_id)
                assert status["run"]["status"] == "failed", (
                    f"run must fail when the plugin aborts, got {status['run']['status']}")

                errors = unwrap(await session.call_tool(
                    "extract_simulation_errors", {"run_id": run_id}))
                assert errors["ok"] is True, errors
                assert marker in json.dumps(errors), (
                    f"plugin severe message must be surfaced, got: {json.dumps(errors)[:2000]}")

    asyncio.run(_run())


@pytest.mark.integration
def test_custom_template_rejects_bad_source():
    # Validates: custom source with a syntax error (or missing contract) is rejected
    # before any model object is created — the model stays clean
    name = _unique("ems_badsource")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _load_example(session, name)

                # Syntax error
                bad = unwrap(await session.call_tool("create_python_plugin", {
                    "name": "Broken Syntax",
                    "template": "custom",
                    "class_name": "Broken",
                    "code": "class Broken(EnergyPlusPlugin)\n    pass\n",
                }))
                assert bad["ok"] is False
                assert "validation" in bad["error"].lower()
                assert any("syntax error at line 1" in d.lower() for d in bad["details"]), bad

                # No plugin callback overridden
                no_callback = unwrap(await session.call_tool("create_python_plugin", {
                    "name": "No Callback",
                    "template": "custom",
                    "class_name": "NoCallback",
                    "code": ("from pyenergyplus.plugin import EnergyPlusPlugin\n\n"
                             "class NoCallback(EnergyPlusPlugin):\n    pass\n"),
                }))
                assert no_callback["ok"] is False
                assert any("overrides no plugin callback" in d for d in no_callback["details"]), no_callback

                # Model has no plugin objects after both rejections
                plugins = unwrap(await session.call_tool("get_python_plugin", {}))
                assert plugins["ok"] is True
                assert plugins["count"] == 0, f"rejected sources must not leave objects: {plugins}"

    asyncio.run(_run())


@pytest.mark.integration
def test_plugin_travels_through_save_load():
    # Validates: save_osm_model carries the companion files/ dir and a reloaded
    # model still resolves its plugin script (portability of EMS controls)
    name = _unique("ems_roundtrip")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _load_example(session, name)

                created = unwrap(await session.call_tool("create_python_plugin", {
                    "name": "Roundtrip Metric",
                    "template": "zone_metric_aggregate",
                    "aggregation": "volume_weighted_average",
                }))
                assert created["ok"] is True, created

                save_path = f"/runs/{name}/model.osm"
                saved = unwrap(await session.call_tool(
                    "save_osm_model", {"osm_path": save_path}))
                assert saved["ok"] is True, saved
                assert saved["files_dir"] == f"/runs/{name}/files", (
                    f"save-as must carry the companion files dir: {saved}")

                loaded = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": save_path}))
                assert loaded["ok"] is True, loaded

                plugin = unwrap(await session.call_tool(
                    "get_python_plugin", {"name": "Roundtrip Metric"}))
                assert plugin["ok"] is True, plugin
                assert plugin["plugin"]["class_name"] == "ZoneMetricAggregate"
                assert plugin["plugin"]["script_path"] == f"/runs/{name}/files/roundtrip_metric.py"
                assert "class ZoneMetricAggregate(EnergyPlusPlugin):" in plugin["source"], (
                    "script source must be readable from the carried files/ dir")

    asyncio.run(_run())
