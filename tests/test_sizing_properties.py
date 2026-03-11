"""Integration tests for sizing system and sizing zone tools (W4, W5)."""
import asyncio
import json
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_sizing") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def run_session():
    """Yield a helper that creates model + air loop + zones for sizing tests."""
    async def _setup(session):
        # Create baseline model (has air loop + zones)
        name = _unique()
        cr = await session.call_tool("create_baseline_osm", {
            "name": name, "ashrae_sys_num": "07",
        })
        cd = unwrap(cr)
        assert cd.get("ok") is True, cd
        return cd

    return _setup


@pytest.mark.integration
def test_set_sizing_system_properties():
    """set_sizing_system_properties sets DOAS config on an air loop."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = _unique()
                cr = unwrap(await session.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "07",
                }))
                assert cr.get("ok") is True, cr

                # Get air loop name
                loops = unwrap(await session.call_tool("list_air_loops", {}))
                assert loops.get("ok") is True
                loop_name = loops["air_loops"][0]["name"]

                # Set DOAS-style sizing
                props = {
                    "type_of_load_to_size_on": "VentilationRequirement",
                    "central_cooling_design_supply_air_temperature": 16.0,
                    "all_outdoor_air_in_cooling": True,
                }
                resp = unwrap(await session.call_tool("set_sizing_system_properties", {
                    "air_loop_name": loop_name,
                    "properties": json.dumps(props),
                }))
                print("set_sizing_system:", resp)
                assert resp.get("ok") is True, resp
                assert "type_of_load_to_size_on" in resp["changes"]

                # Verify via getter
                get_resp = unwrap(await session.call_tool("get_sizing_system_properties", {
                    "air_loop_name": loop_name,
                }))
                assert get_resp.get("ok") is True
                assert get_resp["properties"]["type_of_load_to_size_on"] == "VentilationRequirement"
                assert get_resp["properties"]["central_cooling_design_supply_air_temperature"] == 16.0

    asyncio.run(_run())


@pytest.mark.integration
def test_set_sizing_zone_properties_bulk():
    """set_sizing_zone_properties updates DOAS settings on multiple zones."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = _unique()
                cr = unwrap(await session.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "07",
                }))
                assert cr.get("ok") is True, cr

                # Get first 2 zone names
                zones = unwrap(await session.call_tool("list_thermal_zones", {}))
                assert zones.get("ok") is True
                zone_names = [z["name"] for z in zones["thermal_zones"][:2]]

                # Bulk update
                props = {
                    "zone_cooling_sizing_factor": 1.15,
                    "account_for_dedicated_outdoor_air_system": True,
                    "dedicated_outdoor_air_system_control_strategy": "NeutralSupplyAir",
                }
                resp = unwrap(await session.call_tool("set_sizing_zone_properties", {
                    "zone_names": json.dumps(zone_names),
                    "properties": json.dumps(props),
                }))
                print("set_sizing_zone bulk:", resp)
                assert resp.get("ok") is True, resp
                assert resp["zones_processed"] == 2

                # Verify one zone
                get_resp = unwrap(await session.call_tool("get_sizing_zone_properties", {
                    "zone_name": zone_names[0],
                }))
                assert get_resp.get("ok") is True
                assert abs(get_resp["properties"]["zone_cooling_sizing_factor"] - 1.15) < 0.001
                assert get_resp["properties"]["account_for_dedicated_outdoor_air_system"] is True

    asyncio.run(_run())
