"""Integration test for /add-hvac skill workflow.

Exercises: create model → load → list zones → add_baseline_system →
verify with list_air_loops + list_zone_hvac_equipment.
"""
import asyncio
import uuid

import pytest

from conftest import unwrap, integration_enabled, server_params
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_skill_add_hvac_workflow():
    """/add-hvac skill: inspect model → add system → verify equipment."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_hvac_{uuid.uuid4().hex[:8]}"

                # 1. Create baseline (gives us zones, no HVAC yet via example)
                cr = unwrap(await s.call_tool("create_example_osm", {
                    "name": name,
                }))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # 2. Understand current model
                info = unwrap(await s.call_tool("get_building_info", {}))
                assert info.get("ok") is True

                zones = unwrap(await s.call_tool("list_thermal_zones", {}))
                assert zones.get("ok") is True
                assert zones["count"] > 0
                zone_names = [z["name"] for z in zones["thermal_zones"]]

                # 3. Add HVAC system (System 3 = PSZ-AC for small building)
                hvac = unwrap(await s.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": zone_names,
                    "heating_fuel": "NaturalGas",
                }))
                assert hvac.get("ok") is True, hvac

                # 4. Verify air loops created
                loops = unwrap(await s.call_tool("list_air_loops", {}))
                assert loops.get("ok") is True
                assert loops["count"] > 0

                # 5. Verify zone equipment
                equip = unwrap(await s.call_tool("list_zone_hvac_equipment", {}))
                assert equip.get("ok") is True

    asyncio.run(_run())
