"""Integration tests for Python EMS phase 2: per-user plugin packages,
edit_python_plugin, the node_setpoint_reset template, and trend variables.
"""
from __future__ import annotations

import asyncio
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


async def _load_example(s, name: str) -> str:
    cr = unwrap(await s.call_tool("create_example_osm", {"name": name}))
    assert cr["ok"] is True, cr
    lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr["ok"] is True, lr
    zr = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
    return zr["thermal_zones"][0]["name"]


async def _short_run_period(s) -> None:
    rp = unwrap(await s.call_tool("set_run_period", {
        "begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 2,
    }))
    assert rp["ok"] is True, rp


async def _save_and_simulate(s, name: str) -> str:
    save_path = f"/runs/{name}/model.osm"
    sr = unwrap(await s.call_tool("save_osm_model", {"osm_path": save_path}))
    assert sr["ok"] is True, sr
    sim = unwrap(await s.call_tool("run_simulation", {
        "osm_path": save_path, "epw_path": EPW_PATH,
    }))
    assert sim["ok"] is True, sim
    return sim["run_id"]


def _series_by_timestamp(result: dict) -> dict[tuple, float]:
    series = {(d["month"], d["day"], d["hour"], d["minute"]): d["value"]
              for d in result["data"]}
    assert len(series) == len(result["data"]), (
        f"duplicate timestamps: query matched more than one series "
        f"(key '{result.get('key')}', {len(result['data'])} rows)")
    return series


_NUMPY_PLUGIN = """from pyenergyplus.plugin import EnergyPlusPlugin
import numpy as np


class NumpyCheck(EnergyPlusPlugin):

    def __init__(self):
        super().__init__()
        self.handles = None
        self.global_handle = None

    def on_end_of_zone_timestep_before_zone_reporting(self, state) -> int:
        if not self.api.exchange.api_data_fully_ready(state):
            return 0
        if self.handles is None:
            zone_names = self.api.exchange.get_object_names(state, "Zone")
            self.handles = [
                self.api.exchange.get_variable_handle(
                    state, "Zone Mean Air Temperature", z)
                for z in zone_names
            ]
            if -1 in self.handles:
                self.api.runtime.issue_severe(state, "python_ems numpy test: bad handle")
                return 1
            self.global_handle = self.api.exchange.get_global_handle(state, "NumpyDiff")
        temps = [self.api.exchange.get_variable_value(state, h) for h in self.handles]
        diff = abs(float(np.mean(temps)) - sum(temps) / len(temps))
        self.api.exchange.set_global_value(state, self.global_handle, diff)
        return 0
"""


@pytest.mark.integration
def test_install_plugin_packages_numpy_in_plugin():
    # Validates: wheels-only pip install into the per-user package dir reaches the
    # EnergyPlus embedded interpreter via PythonPlugin:SearchPaths + sandbox RO
    # grant — a plugin imports numpy and np.mean equals plain-Python mean (diff
    # series is exactly 0.0 at every timestep)
    name = _unique("ems_numpy")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                installed = unwrap(await session.call_tool(
                    "install_plugin_packages", {"packages": ["numpy"]}))
                assert installed["ok"] is True, installed
                names = {p["name"] for p in installed["installed"]}
                assert "numpy" in names, f"numpy missing from pip list: {installed}"
                assert installed["packages_dir"].endswith("python_packages")
                assert installed["total_size_mb"] > 1.0, (
                    f"numpy install should be tens of MB, got {installed['total_size_mb']}")

                await _load_example(session, name)
                await _short_run_period(session)

                # Custom plugins must request their sensed variables themselves
                # (templates do this automatically) — without it, handles are -1.
                ov = unwrap(await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Mean Air Temperature",
                    "reporting_frequency": "Timestep",
                }))
                assert ov["ok"] is True, ov

                created = unwrap(await session.call_tool("create_python_plugin", {
                    "name": "Numpy Check",
                    "template": "custom",
                    "class_name": "NumpyCheck",
                    "code": _NUMPY_PLUGIN,
                    "global_variables": ["NumpyDiff"],
                    "output_variable_name": "Numpy Mean Diff",
                    "units": "C",
                }))
                assert created["ok"] is True, created
                assert created["packages_search_path_added"] is True, (
                    f"create must wire the packages dir into SearchPaths: {created}")

                plugins = unwrap(await session.call_tool("get_python_plugin", {}))
                assert plugins["ok"] is True
                assert installed["packages_dir"] in plugins["search_paths"], plugins

                run_id = await _save_and_simulate(session, name)
                status = await poll_until_done(session, run_id)
                assert status["run"]["status"] == "success", (
                    f"numpy plugin sim failed — check get_run_logs('{run_id}')")

                diff = unwrap(await session.call_tool("query_timeseries", {
                    "run_id": run_id,
                    "variable_name": "PythonPlugin:OutputVariable",
                    "key_value": "Numpy Mean Diff",
                    "start_month": 1, "start_day": 1, "end_month": 1, "end_day": 2,
                }))
                assert diff["ok"] is True, diff
                values = [d["value"] for d in diff["data"]]
                assert len(values) >= 48, f"expected 2 days of data, got {len(values)}"
                assert all(v == 0.0 for v in values), (
                    f"np.mean must equal plain mean exactly, max diff {max(values)}")

    asyncio.run(_run())


@pytest.mark.integration
def test_install_plugin_packages_rejects_bad_specs():
    # Validates: pip flags, URLs, and paths are refused before pip ever runs
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for bad in ["-e .", "https://evil.example/pkg.whl", "../local", "numpy; rm -rf /"]:
                    result = unwrap(await session.call_tool(
                        "install_plugin_packages", {"packages": [bad]}))
                    assert result["ok"] is False, f"spec '{bad}' must be rejected"
                    assert "Invalid package spec" in result["error"], result

    asyncio.run(_run())


@pytest.mark.integration
def test_edit_python_plugin_flow():
    # Validates: edit_python_plugin rewrites the files/ script copy after
    # re-validation, and a rejected edit (renamed class) leaves it untouched
    name = _unique("ems_edit")
    marker = "EDITED_BY_TEST_9f3a"
    edited_code = f'''from pyenergyplus.plugin import EnergyPlusPlugin


class ScheduleOverride(EnergyPlusPlugin):
    """{marker}"""

    def on_begin_timestep_before_predictor(self, state) -> int:
        return 0
'''

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _load_example(session, name)
                created = unwrap(await session.call_tool("create_python_plugin", {
                    "name": "Editable Override",
                    "template": "schedule_override",
                    "schedule_name": "Always On Discrete",
                    "default_value": 1.0,
                    "rules": [{"days": "weekends", "start_hour": 0, "end_hour": 24, "value": 0.0}],
                }))
                assert created["ok"] is True, created

                edited = unwrap(await session.call_tool("edit_python_plugin", {
                    "name": "Editable Override", "code": edited_code,
                }))
                assert edited["ok"] is True, edited
                assert edited["class_name"] == "ScheduleOverride"

                detail = unwrap(await session.call_tool(
                    "get_python_plugin", {"name": "Editable Override"}))
                assert detail["ok"] is True
                assert marker in detail["source"], "edit must rewrite the files/ copy"

                # Renaming the class breaks the instance reference — rejected,
                # and the previous (marker) source stays in place.
                rejected = unwrap(await session.call_tool("edit_python_plugin", {
                    "name": "Editable Override",
                    "code": ("from pyenergyplus.plugin import EnergyPlusPlugin\n\n"
                             "class RenamedClass(EnergyPlusPlugin):\n"
                             "    def on_begin_timestep_before_predictor(self, state):\n"
                             "        return 0\n"),
                }))
                assert rejected["ok"] is False
                assert "'ScheduleOverride' not found" in "\n".join(rejected["details"]), rejected

                detail2 = unwrap(await session.call_tool(
                    "get_python_plugin", {"name": "Editable Override"}))
                assert marker in detail2["source"], "rejected edit must not touch the script"

    asyncio.run(_run())


@pytest.mark.integration
def test_node_setpoint_reset_end_to_end():
    # Validates: node_setpoint_reset template actuates System Node Setpoint after
    # the traditional setpoint managers — reported node setpoint equals the
    # OAT-linear reset recomputed pointwise from the reported OAT series
    name = _unique("ems_nodereset")
    oat_low, oat_high, sp_low, sp_high = -20.0, 10.0, 15.0, 12.8

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _load_example(session, name)
                await _short_run_period(session)

                # The example model ships with an air loop whose supply outlet has
                # an active SPM:SingleZoneReheat — overriding IT is the point of
                # this template. (Adding a new system instead would steal the zone
                # and orphan that SPM, which EnergyPlus rejects at input.)
                loops = unwrap(await session.call_tool("list_air_loops", {}))
                assert loops["air_loops"], "example model must have an air loop"
                loop_name = loops["air_loops"][0]["name"]

                created = unwrap(await session.call_tool("create_python_plugin", {
                    "name": "SAT Reset",
                    "template": "node_setpoint_reset",
                    "air_loop_name": loop_name,
                    "oat_low": oat_low, "oat_high": oat_high,
                    "setpoint_at_oat_low": sp_low, "setpoint_at_oat_high": sp_high,
                }))
                assert created["ok"] is True, created
                assert created["class_name"] == "NodeSetpointReset"
                assert created["callbacks"] == ["on_after_predictor_after_hvac_managers"]

                run_id = await _save_and_simulate(session, name)
                status = await poll_until_done(session, run_id)
                assert status["run"]["status"] == "success", (
                    f"node reset sim failed — check get_run_logs('{run_id}')")

                window = {"start_month": 1, "start_day": 1, "end_month": 1, "end_day": 2}
                setpoint = unwrap(await session.call_tool("query_timeseries", {
                    "run_id": run_id,
                    "variable_name": "PythonPlugin:OutputVariable",
                    "key_value": "SAT Reset Setpoint", **window,
                }))
                assert setpoint["ok"] is True, setpoint
                oat = unwrap(await session.call_tool("query_timeseries", {
                    "run_id": run_id,
                    "variable_name": "Site Outdoor Air Drybulb Temperature",
                    "key_value": "Environment", **window,
                }))
                assert oat["ok"] is True, oat

                sp_series = _series_by_timestamp(setpoint)
                oat_series = _series_by_timestamp(oat)
                compared = 0
                for ts, sp_value in sp_series.items():
                    if ts not in oat_series:
                        continue
                    t = oat_series[ts]
                    if t <= oat_low:
                        expected = sp_low
                    elif t >= oat_high:
                        expected = sp_high
                    else:
                        expected = sp_low + (sp_high - sp_low) * (t - oat_low) / (oat_high - oat_low)
                    assert sp_value == pytest.approx(expected, abs=1e-4), (
                        f"setpoint at {ts} is {sp_value}, OAT {t} C implies {expected}")
                    compared += 1
                assert compared >= 48, f"only {compared} timestamps compared"
                # Boston in January must exercise the linear region, not just a clamp
                in_linear = [t for t in oat_series.values() if oat_low < t < oat_high]
                assert len(in_linear) >= 24, (
                    f"reset curve untested: only {len(in_linear)} OAT points in "
                    f"({oat_low}, {oat_high})")

    asyncio.run(_run())


@pytest.mark.integration
def test_trend_variable_created():
    # Validates: trend_timesteps creates a PythonPlugin:TrendVariable wired to the
    # plugin's global with the exact timestep count, visible via get_python_plugin
    name = _unique("ems_trend")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _load_example(session, name)
                created = unwrap(await session.call_tool("create_python_plugin", {
                    "name": "Trended Metric",
                    "template": "zone_metric_aggregate",
                    "aggregation": "average",
                    "output_variable_name": "Trended Avg Temp",
                    "trend_timesteps": 12,
                }))
                assert created["ok"] is True, created

                plugins = unwrap(await session.call_tool("get_python_plugin", {}))
                assert plugins["ok"] is True
                assert plugins["trend_variables"] == [{
                    "name": "Trended_Avg_Temp Trend",
                    "global": "Trended_Avg_Temp",
                    "timesteps_logged": 12,
                }], plugins["trend_variables"]

    asyncio.run(_run())
