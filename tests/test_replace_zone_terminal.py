"""Integration tests for replace_zone_terminal."""
import asyncio
import json
import os
import shlex
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


INTEGRATION_ENV_VAR = "RUN_OPENSTUDIO_INTEGRATION"
SERVER_CMD_VAR = "MCP_SERVER_CMD"

pytestmark = pytest.mark.skipif(
    os.getenv(INTEGRATION_ENV_VAR) != "1",
    reason=f"{INTEGRATION_ENV_VAR} not set to 1"
)


def _unwrap(result) -> dict:
    if hasattr(result, 'content') and len(result.content) > 0:
        text_content = result.content[0]
        if hasattr(text_content, 'text'):
            return json.loads(text_content.text)
    return {}


def _get_server_params():
    server_cmd = os.environ.get(SERVER_CMD_VAR, "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    return StdioServerParameters(
        command=server_cmd,
        args=server_args,
        env=os.environ.copy()
    )


async def _create_and_load(session, name):
    """Helper: create example model, load it, return zone names."""
    cr = await session.call_tool("create_example_osm", {"name": name})
    cd = _unwrap(cr)
    assert cd.get("ok") is True, cd
    lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
    assert _unwrap(lr).get("ok") is True
    zr = await session.call_tool("list_thermal_zones", {})
    zd = _unwrap(zr)
    return [z["name"] for z in zd["thermal_zones"]]


async def _create_baseline_and_load(session, name):
    """Helper: create baseline 10-zone model, load it, return zone names."""
    cr = await session.call_tool("create_baseline_osm", {"name": name})
    cd = _unwrap(cr)
    assert cd.get("ok") is True, cd
    lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
    assert _unwrap(lr).get("ok") is True
    zr = await session.call_tool("list_thermal_zones", {})
    zd = _unwrap(zr)
    return [z["name"] for z in zd["thermal_zones"]]


# --- Example model tests (1 zone) ---

def test_replace_single_zone():
    """Replace terminal on single zone from System 5 to PFP_Electric."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _create_and_load(session, "rzt_single")

                # Add System 5 (VAV w/ Reheat)
                sr = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV System"
                })
                assert _unwrap(sr).get("ok") is True

                # Replace single zone terminal
                rr = await session.call_tool("replace_zone_terminal", {
                    "zone_name": zone_names[0],
                    "terminal_type": "PFP_Electric"
                })
                rd = _unwrap(rr)
                print("replace result:", rd)

                assert rd.get("ok") is True
                assert rd["zone"]["name"] == zone_names[0]
                assert rd["zone"]["air_loop"] == "VAV System"
                assert rd["zone"]["new_terminal_type"] == "PFP_Electric"
                assert "VAV" in rd["zone"]["old_terminal_type"]

                # Independent query verification
                ald = _unwrap(await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV System"
                }))
                assert ald.get("ok") is True

    asyncio.run(_run())


def test_zone_not_on_air_loop():
    """Zone with no air terminal should error."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Use baseline model and create a fresh space+zone not on any air loop
                zone_names = await _create_baseline_and_load(session, "rzt_no_loop")

                # Create new space and zone not connected to any HVAC
                await session.call_tool("create_space", {"name": "Unconnected Space"})
                await session.call_tool("create_thermal_zone", {
                    "name": "Unconnected Zone",
                    "space_names": ["Unconnected Space"]
                })

                rr = await session.call_tool("replace_zone_terminal", {
                    "zone_name": "Unconnected Zone",
                    "terminal_type": "PFP_Electric"
                })
                rd = _unwrap(rr)
                print("no-loop result:", rd)

                assert rd.get("ok") is False
                assert "not connected" in rd["error"].lower()

    asyncio.run(_run())


def test_zone_not_found():
    """Invalid zone name should error."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await _create_and_load(session, "rzt_not_found")

                rr = await session.call_tool("replace_zone_terminal", {
                    "zone_name": "Nonexistent Zone",
                    "terminal_type": "VAV_Reheat"
                })
                rd = _unwrap(rr)
                print("not-found result:", rd)

                assert rd.get("ok") is False
                assert "not found" in rd["error"].lower()

    asyncio.run(_run())


def test_invalid_terminal_type():
    """Bad terminal type should error."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _create_and_load(session, "rzt_bad_type")

                rr = await session.call_tool("replace_zone_terminal", {
                    "zone_name": zone_names[0],
                    "terminal_type": "InvalidType"
                })
                rd = _unwrap(rr)
                print("invalid-type result:", rd)

                assert rd.get("ok") is False
                assert "Invalid terminal_type" in rd["error"]

    asyncio.run(_run())


def test_hw_terminal_no_loop():
    """VAV_Reheat on System 6 (no HW loop) should error."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _create_and_load(session, "rzt_no_hw")

                # Add System 6 (Packaged VAV w/ PFP — no HW loop)
                sr = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "PFP System"
                })
                assert _unwrap(sr).get("ok") is True

                # Try VAV_Reheat — needs HW loop which System 6 doesn't have
                rr = await session.call_tool("replace_zone_terminal", {
                    "zone_name": zone_names[0],
                    "terminal_type": "VAV_Reheat"
                })
                rd = _unwrap(rr)
                print("no-hw result:", rd)

                assert rd.get("ok") is False
                assert "hot water" in rd["error"].lower()

    asyncio.run(_run())


# --- Baseline model tests (10 zones) ---

def test_replace_single_zone_baseline():
    """Replace 1 of 10 zones on System 7."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _create_baseline_and_load(session, "rzt_baseline_single")

                # Add System 7 (VAV w/ Reheat, chiller/boiler/tower)
                sr = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                assert _unwrap(sr).get("ok") is True

                # Replace first zone to PFP_Electric
                rr = await session.call_tool("replace_zone_terminal", {
                    "zone_name": zone_names[0],
                    "terminal_type": "PFP_Electric"
                })
                rd = _unwrap(rr)
                print("baseline single replace:", rd)

                assert rd.get("ok") is True
                assert rd["zone"]["name"] == zone_names[0]
                assert rd["zone"]["new_terminal_type"] == "PFP_Electric"

                ald = _unwrap(await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV"
                }))
                assert ald.get("ok") is True
                assert ald["air_loop"]["num_thermal_zones"] == 10

    asyncio.run(_run())


def test_mixed_terminals_baseline():
    """Core zones -> VAV_NoReheat, perimeter keeps VAV_Reheat."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _create_baseline_and_load(session, "rzt_mixed")

                # Add System 7
                sr = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                assert _unwrap(sr).get("ok") is True

                # Find core zones (contain "Core")
                core_zones = [z for z in zone_names if "Core" in z]
                assert len(core_zones) > 0, f"No core zones found in {zone_names}"

                # Replace core zones to VAV_NoReheat
                for cz in core_zones:
                    rr = await session.call_tool("replace_zone_terminal", {
                        "zone_name": cz,
                        "terminal_type": "VAV_NoReheat"
                    })
                    rd = _unwrap(rr)
                    print(f"mixed replace {cz}:", rd)
                    assert rd.get("ok") is True
                    assert rd["zone"]["new_terminal_type"] == "VAV_NoReheat"

                # Verify all zones still connected
                ald = _unwrap(await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV"
                }))
                assert set(ald["air_loop"]["thermal_zones"]) == set(zone_names)

    asyncio.run(_run())


def test_replace_preserves_other_zones_baseline():
    """Verify 9 zones unchanged after replacing 1."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _create_baseline_and_load(session, "rzt_preserve")

                # Add System 7
                sr = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                assert _unwrap(sr).get("ok") is True

                # Replace only the first zone
                rr = await session.call_tool("replace_zone_terminal", {
                    "zone_name": zone_names[0],
                    "terminal_type": "PFP_Electric"
                })
                assert _unwrap(rr).get("ok") is True

                # Check air loop still has all zones
                alr = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV"
                })
                ald = _unwrap(alr)
                print("air loop after replace:", ald)
                assert ald.get("ok") is True

                loop_zones = set(ald["air_loop"]["thermal_zones"])
                original_zones = set(zone_names)
                assert loop_zones == original_zones, f"Zone mismatch: {loop_zones} != {original_zones}"

    asyncio.run(_run())


def test_gradual_retrofit_baseline():
    """Replace 3 zones one-by-one sequentially."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _create_baseline_and_load(session, "rzt_retrofit")

                # Add System 7
                sr = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                assert _unwrap(sr).get("ok") is True

                # Replace 3 zones sequentially with different types
                replacements = [
                    (zone_names[0], "PFP_Electric"),
                    (zone_names[1], "VAV_NoReheat"),
                    (zone_names[2], "CAV"),
                ]
                for zn, tt in replacements:
                    rr = await session.call_tool("replace_zone_terminal", {
                        "zone_name": zn,
                        "terminal_type": tt
                    })
                    rd = _unwrap(rr)
                    print(f"retrofit {zn} -> {tt}:", rd)
                    assert rd.get("ok") is True
                    assert rd["zone"]["new_terminal_type"] == tt

    asyncio.run(_run())


def test_replace_to_pfp_baseline():
    """Replace perimeter zone to PFP_Electric on System 7."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _create_baseline_and_load(session, "rzt_pfp")

                # Add System 7
                sr = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                assert _unwrap(sr).get("ok") is True

                # Find a perimeter zone
                perim_zones = [z for z in zone_names if "Perimeter" in z or "perim" in z.lower()]
                # If no "Perimeter" naming, just use last zone
                target = perim_zones[0] if perim_zones else zone_names[-1]

                rr = await session.call_tool("replace_zone_terminal", {
                    "zone_name": target,
                    "terminal_type": "PFP_Electric"
                })
                rd = _unwrap(rr)
                print(f"pfp replace {target}:", rd)

                assert rd.get("ok") is True
                assert rd["zone"]["new_terminal_type"] == "PFP_Electric"
                assert "PFP" in rd["zone"]["new_terminal_name"]

                ald = _unwrap(await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV"
                }))
                assert ald.get("ok") is True

    asyncio.run(_run())
