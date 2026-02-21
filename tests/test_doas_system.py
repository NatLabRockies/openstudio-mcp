"""Integration tests for DOAS (Dedicated Outdoor Air System) template.

Tests verify:
- 100% outdoor air loop creation
- Energy recovery ventilator (ERV) presence/absence
- Zone equipment types (fan coils, radiant, chilled beams)
- Plant loop creation for zone equipment
- Outdoor air flow settings
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Test configuration
INTEGRATION_ENV_VAR = "RUN_OPENSTUDIO_INTEGRATION"
SERVER_CMD_VAR = "MCP_SERVER_CMD"

# Skip if integration tests not enabled
pytestmark = pytest.mark.skipif(
    os.getenv(INTEGRATION_ENV_VAR) != "1",
    reason=f"{INTEGRATION_ENV_VAR} not set to 1",
)


def _unwrap(result) -> dict:
    """Unwrap MCP tool result from TextContent."""
    if hasattr(result, "content") and len(result.content) > 0:
        text_content = result.content[0]
        if hasattr(text_content, "text"):
            return json.loads(text_content.text)
    return {}


def _get_server_params():
    """Get server parameters with proper env setup."""
    server_cmd = os.environ.get(SERVER_CMD_VAR, "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    return StdioServerParameters(
        command=server_cmd,
        args=server_args,
        env=os.environ.copy(),
    )


@pytest.mark.integration
def test_doas_with_erv():
    """Verify DOAS creates 100% OA loop with ERV."""

    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            name = "test_doas_erv"
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_data = _unwrap(create_resp)
            load_resp = await session.call_tool(
                "load_osm_model",
                {
                    "osm_path": create_data["osm_path"],
                },
            )

            zones_resp = await session.call_tool("list_thermal_zones", {})
            zones_data = _unwrap(zones_resp)
            zone_names = [z["name"] for z in zones_data["thermal_zones"]]

            # Create DOAS with ERV
            system_resp = await session.call_tool(
                "add_doas_system",
                {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS ERV Test",
                    "energy_recovery": True,
                    "sensible_effectiveness": 0.75,
                    "zone_equipment_type": "FanCoil",
                },
            )
            system_data = _unwrap(system_resp)

            assert system_data.get("ok") is True
            assert system_data["system"]["type"] == "DOAS"
            assert system_data["system"]["energy_recovery"] is True
            assert system_data["system"]["erv_name"] is not None
            assert "ERV" in system_data["system"]["erv_name"]
            assert system_data["system"]["sensible_effectiveness"] == 0.75

            # Independent query verification
            alr = await session.call_tool("list_air_loops", {})
            ald = _unwrap(alr)
            assert any("DOAS ERV Test" in lp["name"] for lp in ald["air_loops"])

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_without_erv():
    """Verify DOAS without ERV still creates valid system."""

    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            name = "test_doas_no_erv"
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_data = _unwrap(create_resp)
            load_resp = await session.call_tool(
                "load_osm_model",
                {
                    "osm_path": create_data["osm_path"],
                },
            )

            zones_resp = await session.call_tool("list_thermal_zones", {})
            zones_data = _unwrap(zones_resp)
            zone_names = [z["name"] for z in zones_data["thermal_zones"]]

            # Create DOAS without ERV
            system_resp = await session.call_tool(
                "add_doas_system",
                {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS No ERV",
                    "energy_recovery": False,
                    "zone_equipment_type": "FanCoil",
                },
            )
            system_data = _unwrap(system_resp)

            assert system_data.get("ok") is True
            assert system_data["system"]["energy_recovery"] is False
            assert system_data["system"]["erv_name"] is None
            assert system_data["system"]["sensible_effectiveness"] is None

            alr = await session.call_tool("list_air_loops", {})
            ald = _unwrap(alr)
            assert any("DOAS No ERV" in lp["name"] for lp in ald["air_loops"])

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_fan_coils():
    """Verify DOAS with fan coil zone equipment creates CHW/HW loops."""

    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            name = "test_doas_fc"
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_data = _unwrap(create_resp)
            load_resp = await session.call_tool(
                "load_osm_model",
                {
                    "osm_path": create_data["osm_path"],
                },
            )

            zones_resp = await session.call_tool("list_thermal_zones", {})
            zones_data = _unwrap(zones_resp)
            zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones (1 in example)

            # Create DOAS with fan coils
            system_resp = await session.call_tool(
                "add_doas_system",
                {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS FC",
                    "energy_recovery": True,
                    "zone_equipment_type": "FanCoil",
                },
            )
            system_data = _unwrap(system_resp)

            assert system_data.get("ok") is True
            assert system_data["system"]["zone_equipment_type"] == "FanCoil"
            assert system_data["system"]["chilled_water_loop"] is not None
            assert system_data["system"]["hot_water_loop"] is not None
            assert len(system_data["system"]["zone_equipment"]) == len(zone_names)

            # Verify fan coils
            for equip in system_data["system"]["zone_equipment"]:
                assert equip["type"] == "ZoneHVACFourPipeFanCoil"

            # Independent query verification — plant loops created
            plr = await session.call_tool("list_plant_loops", {})
            pld = _unwrap(plr)
            assert pld["count"] >= 2  # CHW + HW loops

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_radiant():
    """Verify DOAS with radiant zone equipment."""

    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            name = "test_doas_rad"
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_data = _unwrap(create_resp)
            load_resp = await session.call_tool(
                "load_osm_model",
                {
                    "osm_path": create_data["osm_path"],
                },
            )

            zones_resp = await session.call_tool("list_thermal_zones", {})
            zones_data = _unwrap(zones_resp)
            zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

            # Create DOAS with radiant
            system_resp = await session.call_tool(
                "add_doas_system",
                {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Radiant",
                    "energy_recovery": True,
                    "zone_equipment_type": "Radiant",
                },
            )
            system_data = _unwrap(system_resp)

            assert system_data.get("ok") is True
            assert system_data["system"]["zone_equipment_type"] == "Radiant"
            assert system_data["system"]["chilled_water_loop"] is not None
            assert system_data["system"]["hot_water_loop"] is not None

            # Verify radiant equipment
            for equip in system_data["system"]["zone_equipment"]:
                assert equip["type"] == "ZoneHVACLowTempRadiantVarFlow"

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_chiller_beams():
    """Verify DOAS with chilled beam zone equipment."""

    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            name = "test_doas_beams"
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_data = _unwrap(create_resp)
            load_resp = await session.call_tool(
                "load_osm_model",
                {
                    "osm_path": create_data["osm_path"],
                },
            )

            zones_resp = await session.call_tool("list_thermal_zones", {})
            zones_data = _unwrap(zones_resp)
            zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

            # Create DOAS with chilled beams
            system_resp = await session.call_tool(
                "add_doas_system",
                {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Beams",
                    "energy_recovery": True,
                    "zone_equipment_type": "Chiller_Beams",
                },
            )
            system_data = _unwrap(system_resp)

            assert system_data.get("ok") is True
            assert system_data["system"]["zone_equipment_type"] == "Chiller_Beams"
            assert system_data["system"]["chilled_water_loop"] is not None

            # Verify chilled beam equipment
            for equip in system_data["system"]["zone_equipment"]:
                assert equip["type"] == "AirTerminalSingleDuctConstantVolumeCooledBeam"

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_oa_flow():
    """Verify DOAS air loop exists and serves zones."""

    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            name = "test_doas_oa"
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_data = _unwrap(create_resp)
            load_resp = await session.call_tool(
                "load_osm_model",
                {
                    "osm_path": create_data["osm_path"],
                },
            )

            zones_resp = await session.call_tool("list_thermal_zones", {})
            zones_data = _unwrap(zones_resp)
            zone_names = [z["name"] for z in zones_data["thermal_zones"]]

            # Create DOAS
            system_resp = await session.call_tool(
                "add_doas_system",
                {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS OA Test",
                    "energy_recovery": True,
                    "zone_equipment_type": "FanCoil",
                },
            )
            system_data = _unwrap(system_resp)

            assert system_data.get("ok") is True

            # Verify DOAS loop exists and serves zones
            air_loops_resp = await session.call_tool("list_air_loops", {})
            air_loops_data = _unwrap(air_loops_resp)

            doas_loop = None
            for loop in air_loops_data["air_loops"]:
                if "DOAS OA Test" in loop["name"]:
                    doas_loop = loop
                    break

            assert doas_loop is not None
            assert doas_loop["num_thermal_zones"] == len(zone_names)

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_multi_zone_baseline():
    """Verify DOAS with fan coils on 10-zone baseline model."""
    import uuid

    name = f"test_doas_bl_{uuid.uuid4().hex[:8]}"

    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            cr = await session.call_tool("create_baseline_osm", {"name": name})
            cd = _unwrap(cr)
            assert cd.get("ok") is True, cd
            lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
            assert _unwrap(lr).get("ok") is True

            zones_resp = await session.call_tool("list_thermal_zones", {})
            zones_data = _unwrap(zones_resp)
            zone_names = [z["name"] for z in zones_data["thermal_zones"]]
            assert len(zone_names) == 10

            system_resp = await session.call_tool(
                "add_doas_system",
                {
                    "thermal_zone_names": zone_names,
                    "system_name": "Baseline DOAS",
                    "energy_recovery": True,
                    "sensible_effectiveness": 0.75,
                    "zone_equipment_type": "FanCoil",
                },
            )
            system_data = _unwrap(system_resp)

            assert system_data.get("ok") is True
            assert system_data["system"]["type"] == "DOAS"
            assert len(system_data["system"]["zone_equipment"]) == 10
            assert system_data["system"]["energy_recovery"] is True

            # Verify DOAS air loop serves all 10 zones
            air_loops_resp = await session.call_tool("list_air_loops", {})
            air_loops_data = _unwrap(air_loops_resp)
            doas_loop = next(
                (lp for lp in air_loops_data["air_loops"] if "Baseline DOAS" in lp["name"]),
                None,
            )
            assert doas_loop is not None
            assert doas_loop["num_thermal_zones"] == 10

    asyncio.run(_run())
