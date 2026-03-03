"""Integration tests for replace_air_terminals."""
import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_replace_vav_to_pfp():
    """Test replacing VAV reheat terminals with PFP electric terminals."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_replace_vav_to_pfp"

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                assert create_data.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })
                load_data = unwrap(load_resp)
                assert load_data.get("ok") is True

                # Get zones
                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Add System 5 (VAV with reheat)
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV System",
                })
                system_data = unwrap(system_resp)
                assert system_data.get("ok") is True

                # Replace terminals with PFP electric
                replace_resp = await session.call_tool("replace_air_terminals", {
                    "air_loop_name": "VAV System",
                    "terminal_type": "PFP_Electric",
                })
                replace_data = unwrap(replace_resp)

                assert replace_data.get("ok") is True
                assert replace_data["air_loop"]["name"] == "VAV System"
                assert replace_data["air_loop"]["terminals_replaced"] == len(zone_names)
                assert "VAV" in replace_data["air_loop"]["old_terminal_type"]
                assert replace_data["air_loop"]["new_terminal_type"] == "PFP_Electric"
                assert len(replace_data["air_loop"]["zones"]) == len(zone_names)

                # Independent query verification
                ald = unwrap(await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV System",
                }))
                for t in ald["air_loop"].get("terminals", []):
                    assert "PIU" in t["type"] or "PFP" in t.get("name", "")

    asyncio.run(_run())


@pytest.mark.integration
def test_replace_pfp_to_vav():
    """Test replacing PFP terminals with VAV reheat terminals."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_replace_pfp_to_vav"

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                # Get zones
                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Add System 7 (VAV with reheat - has HW loop)
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat System",
                })
                system_data = unwrap(system_resp)
                assert system_data.get("ok") is True

                # Replace VAV reheat with PFP electric (going from reheat to PFP)
                replace_resp = await session.call_tool("replace_air_terminals", {
                    "air_loop_name": "VAV Reheat System",
                    "terminal_type": "PFP_Electric",
                })
                replace_data = unwrap(replace_resp)

                assert replace_data.get("ok") is True
                assert replace_data["air_loop"]["terminals_replaced"] == len(zone_names)
                assert "VAV" in replace_data["air_loop"]["old_terminal_type"]
                assert replace_data["air_loop"]["new_terminal_type"] == "PFP_Electric"

                ald = unwrap(await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Reheat System",
                }))
                for t in ald["air_loop"].get("terminals", []):
                    assert "PIU" in t["type"] or "PFP" in t.get("name", "")

    asyncio.run(_run())


@pytest.mark.integration
def test_replace_with_options():
    """Test replacing terminals with custom min_airflow_fraction."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_replace_with_options"

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                # Get zones
                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Add System 5
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV System",
                })
                system_data = unwrap(system_resp)
                assert system_data.get("ok") is True

                # Replace with custom min airflow fraction
                replace_resp = await session.call_tool("replace_air_terminals", {
                    "air_loop_name": "VAV System",
                    "terminal_type": "VAV_NoReheat",
                    "terminal_options": {"min_airflow_fraction": 0.2},
                })
                replace_data = unwrap(replace_resp)

                assert replace_data.get("ok") is True
                assert replace_data["air_loop"]["terminals_replaced"] == len(zone_names)

                ald = unwrap(await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV System",
                }))
                for t in ald["air_loop"].get("terminals", []):
                    assert "NoReheat" in t["type"]

    asyncio.run(_run())


@pytest.mark.integration
def test_replace_invalid_air_loop():
    """Test error when air loop not found."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_replace_invalid_air_loop"

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                # Try to replace terminals on non-existent air loop
                replace_resp = await session.call_tool("replace_air_terminals", {
                    "air_loop_name": "Nonexistent Loop",
                    "terminal_type": "VAV_Reheat",
                })
                replace_data = unwrap(replace_resp)

                assert replace_data.get("ok") is False
                assert "not found" in replace_data["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_replace_invalid_terminal_type():
    """Test error when invalid terminal type specified."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_replace_invalid_terminal_type"

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                # Get zones
                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Add System 5
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV System",
                })

                # Try to replace with invalid terminal type
                replace_resp = await session.call_tool("replace_air_terminals", {
                    "air_loop_name": "VAV System",
                    "terminal_type": "InvalidType",
                })
                replace_data = unwrap(replace_resp)

                assert replace_data.get("ok") is False
                assert "Invalid terminal_type" in replace_data["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_replace_hw_terminal_no_loop():
    """Test error when VAV_Reheat requested but no HW loop exists."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_replace_hw_terminal_no_loop"

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                # Get zones
                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Add System 3 (no HW loop, just packaged rooftop)
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": zone_names[:1],  # Single zone only
                    "system_name": "PSZ System",
                })
                system_data = unwrap(system_resp)
                assert system_data.get("ok") is True

                # Try to replace with VAV_Reheat (needs HW loop)
                replace_resp = await session.call_tool("replace_air_terminals", {
                    "air_loop_name": "PSZ System",
                    "terminal_type": "VAV_Reheat",
                })
                replace_data = unwrap(replace_resp)

                assert replace_data.get("ok") is False
                assert "hot water" in replace_data["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_replace_preserves_zones():
    """Test that all zones remain connected after terminal replacement."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_replace_preserves_zones"

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                # Get zones
                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Add System 5
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV System",
                })
                system_data = unwrap(system_resp)
                assert system_data.get("ok") is True

                # Replace terminals
                replace_resp = await session.call_tool("replace_air_terminals", {
                    "air_loop_name": "VAV System",
                    "terminal_type": "PFP_Electric",
                })
                replace_data = unwrap(replace_resp)
                assert replace_data.get("ok") is True

                # Verify all original zones still in list
                replaced_zones = set(replace_data["air_loop"]["zones"])
                original_zones = set(zone_names)
                assert replaced_zones == original_zones

    asyncio.run(_run())


@pytest.mark.integration
def test_replace_multiple_times():
    """Test replacing terminals twice on same loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_replace_multiple_times"

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                # Get zones
                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Add System 5
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV System",
                })

                # First replacement
                replace1_resp = await session.call_tool("replace_air_terminals", {
                    "air_loop_name": "VAV System",
                    "terminal_type": "PFP_Electric",
                })
                replace1_data = unwrap(replace1_resp)
                assert replace1_data.get("ok") is True

                # Second replacement
                replace2_resp = await session.call_tool("replace_air_terminals", {
                    "air_loop_name": "VAV System",
                    "terminal_type": "VAV_NoReheat",
                })
                replace2_data = unwrap(replace2_resp)
                assert replace2_data.get("ok") is True
                assert replace2_data["air_loop"]["terminals_replaced"] == len(zone_names)
                assert "PFP" in replace2_data["air_loop"]["old_terminal_type"] or "PIU" in replace2_data["air_loop"]["old_terminal_type"]

                ald = unwrap(await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV System",
                }))
                for t in ald["air_loop"].get("terminals", []):
                    assert "NoReheat" in t["type"]

    asyncio.run(_run())
