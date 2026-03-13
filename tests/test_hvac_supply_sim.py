"""Simulation-level smoke tests for HVAC supply wiring (H-25/H-26/H-27).

Unlike test_hvac_supply_wiring.py which only checks the object graph,
these tests actually run EnergyPlus and verify models simulate without
fatal/severe errors.  Catches missing setpoint managers, unconnected
nodes, sizing failures, and other issues invisible to wiring-only tests.

Configurations tested:
1. DOAS + FanCoil (default fuels) — air + CHW + HW + condenser loops
2. Radiant + DOAS (default fuels) — radiant HW/CHW + boiler/chiller/tower + DOAS
3. DOAS + FanCoil (both district)  — DistrictHeating + DistrictCooling objects
4. DOAS + Chilled Beams            — CHW-only, no HW loop
5. DOAS + Radiant zone equip       — radiant via DOAS template branch
"""
from __future__ import annotations

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

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _setup_baseline(s, name):
    """Create baseline 10-zone model, load, set weather + design days + sim control."""
    cr = unwrap(await s.call_tool("create_baseline_osm", {"name": name}))
    assert cr.get("ok") is True, cr
    lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr.get("ok") is True, lr

    zr = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
    zone_names = [z["name"] for z in zr["thermal_zones"]]
    assert len(zone_names) == 10

    wr = unwrap(await s.call_tool("change_building_location", {"weather_file": EPW_PATH}))
    assert wr.get("ok") is True, wr

    sc = unwrap(await s.call_tool("set_simulation_control", {
        "do_zone_sizing": True, "do_system_sizing": True,
        "do_plant_sizing": True, "run_for_sizing_periods": True,
        "run_for_weather_file": True,
    }))
    assert sc.get("ok") is True

    rp = unwrap(await s.call_tool("set_run_period", {
        "begin_month": 1, "begin_day": 1,
        "end_month": 1, "end_day": 31, "name": "January Only",
    }))
    assert rp.get("ok") is True

    return zone_names


async def _save_run_and_check(s, name):
    """Save model, run simulation, assert success + no fatal/severe errors."""
    save_path = f"/runs/{name}.osm"
    sr = unwrap(await s.call_tool("save_osm_model", {"osm_path": save_path}))
    assert sr.get("ok") is True

    sim = unwrap(await s.call_tool("run_simulation", {
        "osm_path": save_path, "epw_path": EPW_PATH,
    }))
    assert sim.get("ok") is True, sim
    run_id = sim["run_id"]

    status = await poll_until_done(s, run_id)
    state = status["run"]["status"]
    assert state == "success", (
        f"Simulation {state} — expected success.\n"
        f"Check: get_run_logs(run_id='{run_id}', stream='energyplus')"
    )

    # Check eplusout.err for fatal/severe
    err_resp = unwrap(await s.call_tool("read_file", {
        "file_path": f"/runs/{run_id}/run/eplusout.err", "max_bytes": 100000,
    }))
    if err_resp.get("ok"):
        err_text = err_resp.get("content", "")
        assert "** Fatal **" not in err_text, (
            f"EnergyPlus fatal error:\n{err_text[-2000:]}"
        )
        severe_lines = [
            line for line in err_text.splitlines()
            if "** Severe  **" in line
        ]
        assert len(severe_lines) == 0, (
            f"{len(severe_lines)} severe errors:\n" + "\n".join(severe_lines[:20])
        )

    # Verify metrics extraction works
    metrics = unwrap(await s.call_tool("extract_summary_metrics", {
        "run_id": run_id,
    }))
    assert metrics.get("ok") is True, metrics
    assert "metrics" in metrics


# ---------------------------------------------------------------------------
# 1. DOAS + FanCoil — default fuels (boiler + chiller + tower)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_doas_fancoil_simulates():
    """10-zone DOAS FanCoil → EnergyPlus completes, no fatal/severe errors."""
    name = f"sim_doas_fc_{uuid.uuid4().hex[:8]}"

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                zone_names = await _setup_baseline(s, name)

                sys_resp = unwrap(await s.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS FC Sim",
                    "energy_recovery": True,
                    "sensible_effectiveness": 0.75,
                    "zone_equipment_type": "FanCoil",
                }))
                assert sys_resp.get("ok") is True, sys_resp
                sys = sys_resp["system"]
                assert sys["hot_water_loop"] is not None
                assert sys["chilled_water_loop"] is not None
                assert sys["condenser_water_loop"] is not None

                await _save_run_and_check(s, name)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 2. Radiant + DOAS — default fuels (radiant HW/CHW + boiler/chiller/tower)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_radiant_doas_simulates():
    """10-zone radiant floor + DOAS → EnergyPlus completes, no fatal/severe."""
    name = f"sim_rad_doas_{uuid.uuid4().hex[:8]}"

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                zone_names = await _setup_baseline(s, name)

                sys_resp = unwrap(await s.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Rad Sim",
                    "radiant_type": "Floor",
                    "ventilation_system": "DOAS",
                }))
                assert sys_resp.get("ok") is True, sys_resp
                sys = sys_resp["system"]
                assert sys["hot_water_loop"] is not None
                assert sys["chilled_water_loop"] is not None
                assert sys["condenser_water_loop"] is not None
                assert sys["doas_loop"] is not None

                await _save_run_and_check(s, name)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 3. DOAS + FanCoil — both district (DistrictHeating + DistrictCooling)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_doas_district_simulates():
    """10-zone DOAS FanCoil w/ district H+C → EnergyPlus completes."""
    name = f"sim_doas_dist_{uuid.uuid4().hex[:8]}"

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                zone_names = await _setup_baseline(s, name)

                sys_resp = unwrap(await s.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Dist Sim",
                    "energy_recovery": True,
                    "zone_equipment_type": "FanCoil",
                    "heating_fuel": "DistrictHeating",
                    "cooling_fuel": "DistrictCooling",
                }))
                assert sys_resp.get("ok") is True, sys_resp
                sys = sys_resp["system"]
                assert sys["condenser_water_loop"] is None  # district = no condenser

                await _save_run_and_check(s, name)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 4. DOAS + Chilled Beams — CHW-only (chiller + condenser, no HW loop)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_doas_chilled_beams_simulates():
    """10-zone DOAS chilled beams → EnergyPlus completes, no fatal/severe."""
    name = f"sim_doas_beam_{uuid.uuid4().hex[:8]}"

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                zone_names = await _setup_baseline(s, name)

                sys_resp = unwrap(await s.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Beam Sim",
                    "energy_recovery": True,
                    "zone_equipment_type": "ChilledBeams",
                }))
                assert sys_resp.get("ok") is True, sys_resp
                sys = sys_resp["system"]
                assert sys["chilled_water_loop"] is not None
                assert sys["hot_water_loop"] is None  # beams = CHW only

                await _save_run_and_check(s, name)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 5. DOAS + Radiant zone equipment — exercises DOAS template Radiant branch
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_doas_radiant_equip_simulates():
    """10-zone DOAS w/ radiant zone equip → EnergyPlus completes, no fatal/severe."""
    name = f"sim_doas_rad_{uuid.uuid4().hex[:8]}"

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                zone_names = await _setup_baseline(s, name)

                sys_resp = unwrap(await s.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Rad Sim",
                    "energy_recovery": True,
                    "zone_equipment_type": "Radiant",
                }))
                assert sys_resp.get("ok") is True, sys_resp
                sys = sys_resp["system"]
                assert sys["chilled_water_loop"] is not None
                assert sys["hot_water_loop"] is not None
                assert sys["condenser_water_loop"] is not None

                await _save_run_and_check(s, name)

    asyncio.run(_run())
