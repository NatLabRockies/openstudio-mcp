"""Integration tests for create_plant_loop, add/remove_demand_component (W12, W13)."""
import asyncio
import json
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_loop") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.mark.integration
def test_create_plant_loop_cooling():
    """create_plant_loop creates a cooling plant loop with pump and SPM."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = _unique("chw_loop")
                cr = unwrap(await session.call_tool("create_example_osm", {"name": name}))
                assert cr.get("ok") is True, cr

                resp = unwrap(await session.call_tool("create_plant_loop", {
                    "name": "New CHW Loop",
                    "loop_type": "Cooling",
                }))
                result = json.loads(resp) if isinstance(resp, str) else resp
                print("create_plant_loop cooling:", result)
                assert result.get("ok") is True, result
                assert result["loop_type"] == "Cooling"
                assert result["design_exit_temp_c"] == 7.22

                # Verify loop shows up
                loops = unwrap(await session.call_tool("list_plant_loops", {}))
                loop_names = [lp["name"] for lp in loops["plant_loops"]]
                assert "New CHW Loop" in loop_names

    asyncio.run(_run())


@pytest.mark.integration
def test_create_plant_loop_heating():
    """create_plant_loop creates a heating plant loop."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = _unique("hw_loop")
                cr = unwrap(await session.call_tool("create_example_osm", {"name": name}))
                assert cr.get("ok") is True, cr

                resp = unwrap(await session.call_tool("create_plant_loop", {
                    "name": "New HW Loop",
                    "loop_type": "Heating",
                    "supply_pump_type": "constant",
                }))
                result = json.loads(resp) if isinstance(resp, str) else resp
                print("create_plant_loop heating:", result)
                assert result.get("ok") is True, result
                assert result["loop_type"] == "Heating"
                assert result["design_exit_temp_c"] == 82.0

    asyncio.run(_run())


@pytest.mark.integration
def test_add_remove_demand_component():
    """add_demand_component and remove_demand_component move coils between loops."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = _unique("demand")
                # Create baseline with HVAC system 7 (VAV with CHW/HW loops)
                cr = unwrap(await session.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "07",
                }))
                assert cr.get("ok") is True, cr

                # Create a new cooling loop
                resp = unwrap(await session.call_tool("create_plant_loop", {
                    "name": "Alt CHW Loop",
                    "loop_type": "Cooling",
                }))
                result = json.loads(resp) if isinstance(resp, str) else resp
                assert result.get("ok") is True, result

                # List cooling coils
                comps = unwrap(await session.call_tool("list_hvac_components", {
                    "category": "coil",
                }))
                cooling_coils = [c for c in comps["components"] if "Cooling" in c["type"] and "Water" in c["type"]]

                if cooling_coils:
                    coil_name = cooling_coils[0]["name"]

                    # Find which plant loop has it on demand side
                    loops = unwrap(await session.call_tool("list_plant_loops", {}))
                    orig_loop = None
                    for lp in loops["plant_loops"]:
                        details = unwrap(await session.call_tool("get_plant_loop_details", {
                            "plant_loop_name": lp["name"],
                        }))
                        for comp in details.get("demand_components", []):
                            if comp.get("name") == coil_name:
                                orig_loop = lp["name"]
                                break
                        if orig_loop:
                            break

                    if orig_loop:
                        # Remove from original loop
                        rem = unwrap(await session.call_tool("remove_demand_component", {
                            "component_name": coil_name,
                            "plant_loop_name": orig_loop,
                        }))
                        rem_result = json.loads(rem) if isinstance(rem, str) else rem
                        print("remove_demand:", rem_result)
                        assert rem_result.get("ok") is True, rem_result

                        # Add to new loop
                        add = unwrap(await session.call_tool("add_demand_component", {
                            "component_name": coil_name,
                            "plant_loop_name": "Alt CHW Loop",
                        }))
                        add_result = json.loads(add) if isinstance(add, str) else add
                        print("add_demand:", add_result)
                        assert add_result.get("ok") is True, add_result

    asyncio.run(_run())
