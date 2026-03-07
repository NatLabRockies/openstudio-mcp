"""Integration test for /new-building skill workflow.

Exercises: create model → geometry → zones → envelope → loads →
schedules → HVAC → weather → save → simulate → extract results.
"""
import asyncio
import uuid

import pytest
from conftest import EPW_PATH, integration_enabled, poll_until_done, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_skill_new_building_workflow():
    """/new-building: full model creation → simulate → results."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_newbldg_{uuid.uuid4().hex[:8]}"

                # 1. Create baseline model (has geometry, zones, HVAC)
                cr = unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "03",
                }))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # 2. Get existing zones and spaces
                zones = unwrap(await s.call_tool("list_thermal_zones", {}))
                assert zones.get("ok") is True
                assert zones["count"] > 0
                zone_names = [z["name"] for z in zones["thermal_zones"]]

                spaces = unwrap(await s.call_tool("list_spaces", {}))
                assert spaces.get("ok") is True
                space_name = spaces["spaces"][0]["name"]

                # 3. Add glazing to an exterior wall
                surfaces = unwrap(await s.call_tool("list_surfaces", {}))
                assert surfaces.get("ok") is True
                ext_walls = [sf for sf in surfaces["surfaces"]
                             if sf.get("surface_type") == "Wall"
                             and sf.get("outside_boundary_condition") == "Outdoors"]
                if ext_walls:
                    wwr = unwrap(await s.call_tool("set_window_to_wall_ratio", {
                        "surface_name": ext_walls[0]["name"],
                        "ratio": 0.4,
                    }))
                    assert wwr.get("ok") is True

                # 4. Create schedule
                sched = unwrap(await s.call_tool("create_schedule_ruleset", {
                    "name": "Occ Schedule",
                    "schedule_type": "Fractional",
                    "default_value": 0.5,
                }))
                assert sched.get("ok") is True

                # 5. Add loads to first space
                people = unwrap(await s.call_tool("create_people_definition", {
                    "name": "Office People",
                    "space_name": space_name,
                    "people_per_area": 0.059,
                    "schedule_name": "Occ Schedule",
                }))
                assert people.get("ok") is True

                lights = unwrap(await s.call_tool("create_lights_definition", {
                    "name": "Office Lights",
                    "space_name": space_name,
                    "watts_per_area": 10.76,
                }))
                assert lights.get("ok") is True

                equip = unwrap(await s.call_tool("create_electric_equipment", {
                    "name": "Office Plugs",
                    "space_name": space_name,
                    "watts_per_area": 1.076,
                }))
                assert equip.get("ok") is True

                # 6. Verify HVAC (already present from baseline)
                hvac = unwrap(await s.call_tool("list_air_loops", {}))
                assert hvac.get("ok") is True
                assert hvac["count"] > 0

                # 8. Weather + design days + climate zone
                wr = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW_PATH,
                }))
                assert wr.get("ok") is True

                # 9. Save and simulate
                save_path = f"/runs/{name}.osm"
                sr = unwrap(await s.call_tool("save_osm_model", {
                    "save_path": save_path,
                }))
                assert sr.get("ok") is True

                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": save_path, "epw_path": EPW_PATH,
                }))
                assert sim.get("ok") is True
                run_id = sim["run_id"]

                status = await poll_until_done(s, run_id)
                assert status["run"]["status"] == "success", status

                # 10. Extract results
                metrics = unwrap(await s.call_tool("extract_summary_metrics", {
                    "run_id": run_id,
                }))
                assert metrics.get("ok") is True

    asyncio.run(_run())
