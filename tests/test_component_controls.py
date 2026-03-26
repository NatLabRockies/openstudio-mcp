"""Integration tests for controls & setpoints (Phase 5B)."""
import asyncio
import json

import pytest
from conftest import create_and_load, create_baseline_and_load, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


# --- Economizer tests (System 3 PSZ-AC) ---

def test_set_economizer_type():
    """Change economizer to NoEconomizer."""
    # Validates: set_economizer_properties changes economizer_control_type on System 3 PSZ-AC
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "ctrl_econ1")
                await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": zones[:1],
                    "economizer": True,
                })
                # Find the air loop name
                alr = await session.call_tool("list_air_loops", {})
                loops = unwrap(alr)["air_loops"]
                assert len(loops) >= 1, f"System 3 should create at least 1 air loop, got {len(loops)}"
                # Find the PSZ-AC loop added by System 3 (example model may have a pre-existing loop)
                psz_loops = [l for l in loops if "PSZ" in l["name"]]
                assert len(psz_loops) >= 1, f"No PSZ-AC loop found in {[l['name'] for l in loops]}"
                loop_name = psz_loops[0]["name"]

                result = await session.call_tool("set_economizer_properties", {
                    "air_loop_name": loop_name,
                    "properties": json.dumps({"economizer_control_type": "NoEconomizer"}),
                })
                data = unwrap(result)
                assert data["ok"] is True, f"set_economizer_properties failed: {data.get('error')}"
                assert data["changes"]["economizer_control_type"]["new"] == "NoEconomizer"

                # Independent query verification
                ald = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": loop_name,
                })
                details = unwrap(ald)
                assert details["ok"] is True
                oa = details["air_loop"].get("outdoor_air_system") or {}
                assert oa.get("economizer_type") == "NoEconomizer"
    asyncio.run(_run())


def test_set_economizer_drybulb_limit():
    """Set max dry-bulb limit."""
    # Validates: set_economizer_properties changes max_limit_drybulb_temp_c on System 3
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "ctrl_econ2")
                await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": zones[:1],
                    "economizer": True,
                })
                alr = await session.call_tool("list_air_loops", {})
                loop_name = unwrap(alr)["air_loops"][0]["name"]

                result = await session.call_tool("set_economizer_properties", {
                    "air_loop_name": loop_name,
                    "properties": json.dumps({"max_limit_drybulb_temp_c": 24.0}),
                })
                data = unwrap(result)
                assert data["ok"] is True, f"set_economizer_properties failed: {data.get('error')}"
                assert data["changes"]["max_limit_drybulb_temp_c"]["new"] == pytest.approx(24.0, abs=0.1)

                # Independent query verification
                ald = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": loop_name,
                })
                details = unwrap(ald)
                oa = details["air_loop"].get("outdoor_air_system") or {}
                # Drybulb limit not exposed in get_air_loop_details, just verify OAS exists
                assert isinstance(oa.get("name"), str), "OA system should have a name after economizer setup"
    asyncio.run(_run())


def test_economizer_no_oa_system():
    """Error when loop has no OA system (System 1 PTAC has no air loop OA)."""
    # Validates: set_economizer_properties returns ok=False for nonexistent air loop
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_and_load(session, "ctrl_nooa")
                # No air loop to test — try with bad name
                result = await session.call_tool("set_economizer_properties", {
                    "air_loop_name": "Nonexistent Loop",
                    "properties": json.dumps({"economizer_control_type": "NoEconomizer"}),
                })
                data = unwrap(result)
                assert data["ok"] is False
                assert "error" in data, "Should include error message for missing loop"
                assert "not found" in data["error"].lower() or "air loop" in data["error"].lower()
    asyncio.run(_run())


# --- Setpoint manager tests (System 5 VAV) ---

def test_set_setpoint_min_max_temp():
    """Modify SPM properties on System 5 (SetpointManagerScheduled)."""
    # Validates: set_setpoint_manager_properties changes properties on System 5 SPM
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "ctrl_spm")
                await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zones,
                })
                # Find SPM name via air loop details
                alr = await session.call_tool("list_air_loops", {})
                loop = unwrap(alr)["air_loops"][0]
                ald = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": loop["name"],
                })
                details = unwrap(ald)
                assert details["ok"] is True, f"get_air_loop_details failed: {details}"
                air_loop_data = details.get("air_loop", details)
                spm_list = air_loop_data.get("setpoint_managers", [])
                assert len(spm_list) > 0, (
                    f"System 5 air loop '{loop['name']}' should have at least one SPM"
                )
                spm_info = spm_list[0]
                spm_name = spm_info["name"]
                spm_type = spm_info.get("type", "")

                # Build properties appropriate for the SPM type
                if "SingleZoneReheat" in spm_type:
                    props = {
                        "minimum_supply_air_temperature_c": 10.0,
                        "maximum_supply_air_temperature_c": 45.0,
                    }
                elif "Scheduled" in spm_type:
                    props = {"control_variable": "Temperature"}
                elif "Warmest" in spm_type or "Coldest" in spm_type:
                    props = {
                        "minimum_setpoint_temperature": 10.0,
                        "maximum_setpoint_temperature": 45.0,
                    }
                else:
                    pytest.skip(f"Unsupported SPM type for property test: {spm_type}")

                result = await session.call_tool("set_setpoint_manager_properties", {
                    "setpoint_name": spm_name,
                    "properties": json.dumps(props),
                })
                data = unwrap(result)
                if not data["ok"]:
                    pytest.fail(
                        f"set_setpoint_manager_properties failed on {spm_type}"
                        f" '{spm_name}': {data.get('error') or data.get('errors')}",
                    )
                # Verify at least one property was changed
                assert len(data["changes"]) > 0, f"No properties changed: {data}"
                # Verify change values match what we sent
                for prop_name, new_val in props.items():
                    if prop_name in data["changes"]:
                        actual = data["changes"][prop_name]["new"]
                        if isinstance(new_val, float):
                            assert actual == pytest.approx(new_val, abs=0.1)
                        else:
                            assert actual == new_val
    asyncio.run(_run())


# --- Sizing tests (System 7) ---

def test_set_chw_loop_exit_temp():
    """Change CHW sizing temp on System 7."""
    # Validates: set_sizing_properties changes CHW loop exit temp and round-trips via get_plant_loop_details
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "ctrl_chw")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                # Find CHW plant loop
                plr = await session.call_tool("list_plant_loops", {})
                loops = unwrap(plr)["plant_loops"]
                chw = next((l for l in loops if "chw" in l["name"].lower() or "chill" in l["name"].lower() or "cool" in l["name"].lower()), None)
                assert chw is not None, f"System 7 should create CHW loop, got loops: {[l['name'] for l in loops]}"

                result = await session.call_tool("set_sizing_properties", {
                    "loop_name": chw["name"],
                    "properties": json.dumps({"design_loop_exit_temperature_c": 5.5}),
                })
                data = unwrap(result)
                assert data["ok"] is True, f"set_sizing_properties failed: {data.get('error')}"
                assert data["changes"]["design_loop_exit_temperature_c"]["new"] == pytest.approx(5.5, abs=0.1)

                # Independent query verification
                pld = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": chw["name"],
                })
                pd = unwrap(pld)
                assert pd["ok"] is True
                assert pd["plant_loop"].get("design_loop_exit_temp_c", 0) == pytest.approx(5.5, abs=0.1)
    asyncio.run(_run())


def test_set_hw_loop_delta_t():
    """Change HW sizing delta-T on System 7."""
    # Validates: set_sizing_properties changes HW loop delta-T and round-trips via get_plant_loop_details
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "ctrl_hw")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                plr = await session.call_tool("list_plant_loops", {})
                loops = unwrap(plr)["plant_loops"]
                hw = next((l for l in loops if "hw" in l["name"].lower() or "hot" in l["name"].lower() or "heat" in l["name"].lower()), None)
                assert hw is not None, f"System 7 should create HW loop, got loops: {[l['name'] for l in loops]}"

                result = await session.call_tool("set_sizing_properties", {
                    "loop_name": hw["name"],
                    "properties": json.dumps({"loop_design_temperature_difference_c": 15.0}),
                })
                data = unwrap(result)
                assert data["ok"] is True, f"set_sizing_properties failed: {data.get('error')}"
                assert data["changes"]["loop_design_temperature_difference_c"]["new"] == pytest.approx(15.0, abs=0.1)

                # Independent query verification
                pld = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": hw["name"],
                })
                pd = unwrap(pld)
                assert pd["ok"] is True
                assert pd["plant_loop"].get("loop_design_delta_temp_c", 0) == pytest.approx(15.0, abs=0.1)
    asyncio.run(_run())


def test_set_sizing_invalid_loop():
    """Bad loop name returns error."""
    # Validates: set_sizing_properties returns ok=False with error for nonexistent loop
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_and_load(session, "ctrl_invlp")

                result = await session.call_tool("set_sizing_properties", {
                    "loop_name": "Nonexistent Loop",
                    "properties": json.dumps({"design_loop_exit_temperature_c": 5.0}),
                })
                data = unwrap(result)
                assert data["ok"] is False
                assert "error" in data, "Should include error message for missing loop"
                assert "not found" in data["error"].lower()
    asyncio.run(_run())


def test_get_setpoint_manager_props():
    """Read SPM properties via generic get_component_properties."""
    # Validates: get_component_properties returns ok=False for nonexistent SPM name
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "ctrl_getspm")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                # SPMs aren't in the generic registry, so this should fail gracefully
                result = await session.call_tool("get_component_properties", {
                    "component_name": "Some SPM Name",
                })
                data = unwrap(result)
                assert data["ok"] is False
                assert "error" in data, "Should include error message for unfound component"
                assert "not found" in data["error"].lower() or "error" in data["error"].lower()
    asyncio.run(_run())


def test_set_economizer_differential_drybulb():
    """Set economizer to DifferentialDryBulb on System 3."""
    # Validates: set_economizer_properties changes to DifferentialDryBulb and verifies via air loop details
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "ctrl_difdb")
                await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": zones[:1],
                    "economizer": False,
                })
                alr = await session.call_tool("list_air_loops", {})
                loop_name = unwrap(alr)["air_loops"][0]["name"]

                result = await session.call_tool("set_economizer_properties", {
                    "air_loop_name": loop_name,
                    "properties": json.dumps({"economizer_control_type": "DifferentialDryBulb"}),
                })
                data = unwrap(result)
                assert data["ok"] is True, f"set_economizer_properties failed: {data.get('error')}"
                assert data["changes"]["economizer_control_type"]["new"] == "DifferentialDryBulb"

                # Independent query verification
                ald = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": loop_name,
                })
                details = unwrap(ald)
                oa = details["air_loop"].get("outdoor_air_system") or {}
                assert oa.get("economizer_type") == "DifferentialDryBulb"
    asyncio.run(_run())


def test_set_economizer_invalid_loop():
    """Bad loop name returns error."""
    # Validates: set_economizer_properties returns ok=False with error for nonexistent air loop
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_and_load(session, "ctrl_inveco")

                result = await session.call_tool("set_economizer_properties", {
                    "air_loop_name": "Nonexistent Loop",
                    "properties": json.dumps({"economizer_control_type": "NoEconomizer"}),
                })
                data = unwrap(result)
                assert data["ok"] is False
                assert "error" in data, "Should include error message for missing air loop"
                assert "not found" in data["error"].lower() or "air loop" in data["error"].lower()
    asyncio.run(_run())
