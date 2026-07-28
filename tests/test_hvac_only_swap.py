"""hvac_only HVAC swap on create_typical_building (issue #97).

Proves the standards-tuned HVAC-only replacement path: swapping systems on an
already-configured model must preserve loads and produce results equivalent to
building the model fresh with that system_type (the sanctioned full path).

Dev benchmark (2026-07-28, 10k ft2 SmallOffice bar, Boston 5A, 90.1-2019,
PVAV with gas boiler reheat): full build vs Inferred+swap were identical to
0.007% site energy (746.74 vs 746.79 GJ) with unmet heating 343.67 in both.
"""
import asyncio
import time
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

EPW = ("/opt/comstock-measures/ChangeBuildingLocation"
       "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
SYSTEM = "PVAV with gas boiler reheat"
TEMPLATE = "90.1-2019"
CZ = "ASHRAE 169-2013-5A"


def _unique(prefix: str = "pytest_hvaconly") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _build_bar(s):
    bar = unwrap(await s.call_tool("create_bar_building", {
        "building_type": "SmallOffice", "climate_zone": "5A"}))
    assert bar["ok"] is True, f"create_bar failed: {bar.get('error')}"
    wr = unwrap(await s.call_tool("change_building_location", {"weather_file": EPW}))
    assert wr["ok"] is True, f"change_building_location failed: {wr.get('error')}"


async def _lights_snapshot(s):
    objs = unwrap(await s.call_tool("list_model_objects", {
        "object_type": "Lights", "max_results": 0}))
    assert objs["ok"] is True, objs
    snapshot = {}
    for o in objs["objects"]:
        det = unwrap(await s.call_tool("get_load_details", {"load_name": o["name"]}))
        assert det["ok"] is True, det
        snapshot[o["name"]] = det
    return snapshot


async def _sim_metrics(s, name):
    sv = unwrap(await s.call_tool("save_osm_model", {"osm_path": f"/runs/{name}.osm"}))
    assert sv["ok"] is True, sv
    sim = unwrap(await s.call_tool("run_simulation", {"osm_path": f"/runs/{name}.osm"}))
    assert sim["ok"] is True, f"run_simulation failed: {sim.get('error')}"
    t0 = time.time()
    while True:
        st = unwrap(await s.call_tool("get_run_status", {"run_id": sim["run_id"]}))
        state = (st.get("run", {}).get("status") or "?").lower()
        if state in ("success", "failed", "error", "cancelled"):
            break
        assert time.time() - t0 < 1200, "simulation timed out"
        await asyncio.sleep(3)
    assert state == "success", f"simulation failed: {st}"
    m = unwrap(await s.call_tool("extract_summary_metrics", {"run_id": sim["run_id"]}))
    assert m["ok"] is True, m
    return m["metrics"]


@pytest.mark.integration
def test_hvac_only_swap_matches_full_build():
    """Inferred build + hvac_only swap == full build with explicit system_type."""
    # Regression: issue #97 — HVAC system sweeps needed a load-preserving,
    # standards-tuned swap; generic add_* templates gave non-decision-grade
    # results (718-953 unmet hrs) and full re-typical wiped custom loads.
    # Parity with the full build proves the swap path loses nothing.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        # Arm A (control): full typical straight to the target system
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _build_bar(s)
                typ = unwrap(await s.call_tool("create_typical_building", {
                    "template": TEMPLATE, "climate_zone": CZ,
                    "system_type": SYSTEM}))
                assert typ["ok"] is True, f"full build failed: {typ.get('error')}"
                control_metrics = await _sim_metrics(s, _unique("ctl"))

        # Arm B: full typical (Inferred) then hvac_only swap to the target
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _build_bar(s)
                typ = unwrap(await s.call_tool("create_typical_building", {
                    "template": TEMPLATE, "climate_zone": CZ}))
                assert typ["ok"] is True, f"inferred build failed: {typ.get('error')}"
                lights_before = await _lights_snapshot(s)
                summary_before = unwrap(await s.call_tool("get_model_summary", {}))["summary"]

                swap = unwrap(await s.call_tool("create_typical_building", {
                    "template": TEMPLATE, "climate_zone": CZ,
                    "system_type": SYSTEM, "hvac_only": True}))
                assert swap["ok"] is True, f"hvac_only swap failed: {swap.get('error')}"
                assert swap["hvac_only"] is True

                # Loads, constructions, geometry untouched — exact values
                lights_after = await _lights_snapshot(s)
                assert lights_after == lights_before, (
                    "hvac_only swap must not touch lighting loads:\n"
                    f"before={lights_before}\nafter={lights_after}"
                )
                summary_after = unwrap(await s.call_tool("get_model_summary", {}))["summary"]
                for key in ("people", "lights", "electric_equipment", "constructions",
                            "materials", "spaces", "thermal_zones", "surfaces"):
                    assert summary_after[key] == summary_before[key], (
                        f"hvac_only swap changed {key}: "
                        f"{summary_before[key]} -> {summary_after[key]}"
                    )

                # HVAC actually replaced: 9 PSZ-AC loops -> 1 multizone PVAV
                loops = unwrap(await s.call_tool("list_air_loops", {}))
                names = [al["name"] for al in loops["air_loops"]]
                assert len(names) == 1 and "PVAV" in names[0], (
                    f"expected single multizone PVAV loop after swap, got {names}"
                )

                swap_metrics = await _sim_metrics(s, _unique("swap"))

        # Parity: the swap path must be equivalent to the sanctioned full build
        assert swap_metrics["eui_MJ_m2"] == pytest.approx(
            control_metrics["eui_MJ_m2"], rel=0.02), (
            f"EUI diverged: control {control_metrics['eui_MJ_m2']:.1f} vs "
            f"swap {swap_metrics['eui_MJ_m2']:.1f} MJ/m2"
        )
        assert swap_metrics["unmet_hours_heating"] == pytest.approx(
            control_metrics["unmet_hours_heating"], abs=25), (
            f"unmet heating diverged: control {control_metrics['unmet_hours_heating']} "
            f"vs swap {swap_metrics['unmet_hours_heating']}"
        )
        assert swap_metrics["unmet_hours_cooling"] == pytest.approx(
            control_metrics["unmet_hours_cooling"], abs=25), (
            f"unmet cooling diverged: control {control_metrics['unmet_hours_cooling']} "
            f"vs swap {swap_metrics['unmet_hours_cooling']}"
        )
    asyncio.run(_run())
