"""Comfort viability of generic HVAC templates (issue #97).

Replicates the issue's failure mode on a 10k ft2 SmallOffice bar (Boston 5A,
90.1-2019 typical loads + setback thermostats): strip HVAC, add the generic
system, simulate, check comfort/energy.

Dev benchmark (2026-07-28), unfixed -> fixed:
  system 5 (PVAV reheat): 1807.2 -> 222.2 unmet heating hrs
    (root cause: VAV terminal DamperHeatingAction=Normal caps heating at
    minimum airflow; standards uses Reverse. Standards PVAV on this same
    building: 343.7)
  DOAS FanCoil: 164.3 -> 125.1 kBtu/ft2 EUI, 51.0 -> 49.5 unmet htg hrs
    (root cause: no availability schedule, conditioning design OA 24/7; now
    defaults to the served zones' People schedule — OfficeSmall BLDG_OCC_SCH
    on this benchmark)
"""
import asyncio
import json
import time
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

EPW = ("/opt/comstock-measures/ChangeBuildingLocation"
       "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")


def _unique(prefix: str = "pytest_comfort97") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# Thresholds sit midway between the fixed dev-benchmark values and the pre-fix
# failures, so normal E+/standards version drift passes but a regression to
# the old behavior cannot.
SYS5_UNMET_HEATING_MAX = 700    # fixed: 222.2, broken: 1807.2
DOAS_EUI_MAX = 145.0            # fixed: 125.1, broken: 164.3
DOAS_UNMET_HEATING_MAX = 100    # fixed: 49.5 (sanity bound)
SYS4_UNMET_HEATING_MAX = 600    # fixed: 199.8, broken: 1416.5 (loose coils)
SYS4_UNMET_COOLING_MAX = 100    # fixed: 0.0 (continuous-fan variant hit 366)
VRF_UNMET_HEATING_MAX = 900     # fixed: 518.2, broken: E+ fatal (never ran)
VRF_UNMET_COOLING_MAX = 100     # fixed: 0.0


async def _strip_hvac(s):
    for tool, key in (("list_air_loops", "air_loops"),
                      ("list_plant_loops", "plant_loops"),
                      ("list_zone_hvac_equipment", "equipment")):
        listing = unwrap(await s.call_tool(tool, {}))
        for item in listing.get(key, []):
            r = unwrap(await s.call_tool("delete_object", {"object_name": item["name"]}))
            assert r["ok"] is True, f"delete {item['name']} failed: {r.get('error')}"


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
def test_generic_templates_comfort_viability():
    """Generic system 5 and DOAS produce livable comfort/energy out of the box."""
    # Regression: issue #97 — system 5 accumulated 1807 occupied unmet heating
    # hours (damper action Normal) and DOAS burned 164 kBtu/ft2 (24/7 design-
    # flow OA conditioning) on this exact benchmark before the fixes
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                bar = unwrap(await s.call_tool("create_bar_building", {
                    "building_type": "SmallOffice", "climate_zone": "5A"}))
                assert bar["ok"] is True, bar.get("error")
                wr = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW}))
                assert wr["ok"] is True, wr.get("error")
                typ = unwrap(await s.call_tool("create_typical_building", {
                    "template": "90.1-2019", "climate_zone": "ASHRAE 169-2013-5A"}))
                assert typ["ok"] is True, typ.get("error")
                zones = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                zone_names = [z["name"] for z in zones["thermal_zones"]]

                # --- System 5 (PVAV reheat) ---
                await _strip_hvac(s)
                r5 = unwrap(await s.call_tool("add_baseline_system", {
                    "system_type": 5, "thermal_zone_names": zone_names}))
                assert r5["ok"] is True, r5.get("error")
                assert r5["system"]["night_cycle_managers"], \
                    "system 5 air loop should get a night-cycle manager"
                m5 = await _sim_metrics(s, _unique("sys5"))
                assert m5["unmet_hours_heating"] < SYS5_UNMET_HEATING_MAX, (
                    f"system 5 unmet heating {m5['unmet_hours_heating']} hrs — "
                    f"regressed toward the pre-fix 1807 (damper action?)"
                )

                # --- DOAS (FanCoil) ---
                await _strip_hvac(s)
                rd = unwrap(await s.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "zone_equipment_type": "FanCoil"}))
                assert rd["ok"] is True, rd.get("error")
                assert rd["system"]["availability_schedule"] is not None, (
                    "DOAS on an occupied model must default to an occupancy-"
                    "derived availability schedule"
                )
                md = await _sim_metrics(s, _unique("doas"))
                assert md["eui_kBtu_ft2"] < DOAS_EUI_MAX, (
                    f"DOAS EUI {md['eui_kBtu_ft2']:.1f} kBtu/ft2 — regressed "
                    f"toward the pre-fix 164 (24/7 OA conditioning?)"
                )
                assert md["unmet_hours_heating"] < DOAS_UNMET_HEATING_MAX, (
                    f"DOAS unmet heating {md['unmet_hours_heating']} hrs"
                )
                print("benchmark:", json.dumps({
                    "sys5": {k: m5.get(k) for k in
                             ("unmet_hours_heating", "eui_kBtu_ft2")},
                    "doas": {k: md.get(k) for k in
                             ("unmet_hours_heating", "eui_kBtu_ft2")},
                }))
    asyncio.run(_run())


@pytest.mark.integration
def test_heat_pump_and_vrf_viability():
    """Generic system 4 (PSZ-HP) and VRF simulate and hold comfort."""
    # Regression: issue #97 follow-up — sys 4's loose coils sized the backup
    # electric coil to ~44% of design load and autosizing capped supplemental
    # supply air at 16.7C (1416 unmet htg hrs); VRF paired an FTC-HR outdoor
    # unit with standard terminals and shipped self-inconsistent PLR defaults,
    # so it had NEVER completed a simulation (E+ fatal)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                bar = unwrap(await s.call_tool("create_bar_building", {
                    "building_type": "SmallOffice", "climate_zone": "5A"}))
                assert bar["ok"] is True, bar.get("error")
                wr = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW}))
                assert wr["ok"] is True, wr.get("error")
                typ = unwrap(await s.call_tool("create_typical_building", {
                    "template": "90.1-2019", "climate_zone": "ASHRAE 169-2013-5A"}))
                assert typ["ok"] is True, typ.get("error")
                zones = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                zone_names = [z["name"] for z in zones["thermal_zones"]]

                # --- System 4 (PSZ-HP, unitary composite, fan-out) ---
                await _strip_hvac(s)
                r4 = unwrap(await s.call_tool("add_baseline_system", {
                    "system_type": 4, "thermal_zone_names": zone_names}))
                assert r4["ok"] is True, r4.get("error")
                assert r4["system"]["zones_served"] == len(zone_names)
                m4 = await _sim_metrics(s, _unique("sys4"))
                assert m4["unmet_hours_heating"] < SYS4_UNMET_HEATING_MAX, (
                    f"system 4 unmet heating {m4['unmet_hours_heating']} hrs — "
                    f"regressed toward the pre-fix 1416 (backup sizing/supply cap?)"
                )
                assert m4["unmet_hours_cooling"] < SYS4_UNMET_COOLING_MAX, (
                    f"system 4 unmet cooling {m4['unmet_hours_cooling']} hrs — "
                    f"continuous-fan heat regression?"
                )

                # --- VRF (was: EnergyPlus fatal, never simulated) ---
                await _strip_hvac(s)
                rv = unwrap(await s.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names}))
                assert rv["ok"] is True, rv.get("error")
                mv = await _sim_metrics(s, _unique("vrf"))
                assert mv["unmet_hours_heating"] < VRF_UNMET_HEATING_MAX, (
                    f"VRF unmet heating {mv['unmet_hours_heating']} hrs"
                )
                assert mv["unmet_hours_cooling"] < VRF_UNMET_COOLING_MAX, (
                    f"VRF unmet cooling {mv['unmet_hours_cooling']} hrs"
                )
                print("benchmark:", json.dumps({
                    "sys4": {k: m4.get(k) for k in
                             ("unmet_hours_heating", "unmet_hours_cooling",
                              "eui_kBtu_ft2")},
                    "vrf": {k: mv.get(k) for k in
                            ("unmet_hours_heating", "unmet_hours_cooling",
                             "eui_kBtu_ft2")},
                }))
    asyncio.run(_run())
