"""Integration tests for the space_type_assignment skill.

Fixture strategy: create_baseline_osm gives 10 zones that are always
conditioned (thermostats are always added, regardless of HVAC — see
test_building.py). We delete the baseline's shared SpaceType (which also
removes its People/Lights/ElectricEquipment, since they're attached to the
SpaceType, not the spaces) so conditioned spaces start with zero loads and no
space type, matching the real post-gbXML-import scenario this feature targets.
An extra space+zone with no thermostat is added where an unconditioned
control case is needed.
"""
import asyncio
import os
import uuid

import pytest
from conftest import create_baseline_and_load, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_sta") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


async def _strip_baseline_space_type(session) -> None:
    """Delete the baseline model's shared SpaceType, wiping its loads and
    unassigning it from all 10 spaces (they stay in conditioned zones)."""
    listed = unwrap(await session.call_tool("list_model_objects", {"object_type": "SpaceType", "max_results": 0}))
    assert listed["ok"] is True, listed
    for st in listed["objects"]:
        deleted = unwrap(await session.call_tool(
            "delete_object", {"object_name": st["name"], "object_type": "SpaceType"},
        ))
        assert deleted["ok"] is True, deleted


async def _add_unconditioned_space(session, suffix: str) -> str:
    """Add one space in a zone with no thermostat — never conditioned."""
    space_name = f"Unconditioned {suffix}"
    sc = unwrap(await session.call_tool("create_space", {"name": space_name}))
    assert sc["ok"] is True, sc
    zc = unwrap(await session.call_tool(
        "create_thermal_zone", {"name": f"Unconditioned Zone {suffix}", "space_names": [space_name]},
    ))
    assert zc["ok"] is True, zc
    return space_name


def _parse_table(table_rows: str) -> dict[int, list[str]]:
    rows = {}
    for line in table_rows.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        rows[int(parts[0])] = parts[1:]
    return rows


@pytest.mark.integration
def test_conditioned_zone_filter_excludes_unconditioned():
    # Validates: start_space_type_wizard only counts spaces in conditioned
    # (dual-setpoint thermostat) zones — an added zone with no thermostat
    # never appears in the wizard's pending count or table.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_baseline_and_load(session, name)
                await _add_unconditioned_space(session, name)

                start = unwrap(await session.call_tool("start_space_type_wizard", {}))
                assert start["ok"] is True, start
                assert start["conditioned_space_count"] == 10, start

                status = unwrap(await session.call_tool("get_space_type_wizard_status", {"page_size": 100}))
                assert status["ok"] is True, status
                assert status["remaining_count"] == 10
                assert len(_parse_table(status["table_rows"])) == 10

    asyncio.run(_run())


@pytest.mark.integration
def test_simple_path_assigns_and_no_loads():
    # Validates: assign_space_type_simple creates a SpaceType with zero
    # loads and assigns it to exactly the 10 conditioned spaces, never the
    # unconditioned one.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_baseline_and_load(session, name)
                unconditioned_space = await _add_unconditioned_space(session, name)

                result = unwrap(await session.call_tool("assign_space_type_simple", {
                    "standards_template": "90.1-2019",
                    "standards_building_type": "Office",
                    "standards_space_type": "WholeBuilding - Sm Office",
                }))
                assert result["ok"] is True, result
                assert result["spaces_assigned"] == 10, result
                assert result["reused_existing"] is False

                details = unwrap(await session.call_tool(
                    "get_space_type_details", {"space_type_name": result["space_type"]},
                ))
                assert details["ok"] is True, details
                st = details["space_type"]
                assert st["num_people"] == 0, st
                assert st["num_lights"] == 0, st
                assert st["num_electric_equipment"] == 0, st
                assert len(st["spaces"]) == 10, st

                unconditioned = unwrap(await session.call_tool(
                    "get_space_details", {"space_name": unconditioned_space},
                ))
                assert unconditioned["ok"] is True, unconditioned
                assert unconditioned["space"]["space_type"] != result["space_type"], unconditioned

    asyncio.run(_run())


@pytest.mark.integration
def test_simple_path_dedupes_existing_combo():
    # Validates: calling assign_space_type_simple twice with the same combo
    # reuses the existing SpaceType instead of creating a duplicate.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_baseline_and_load(session, name)

                args = {
                    "standards_template": "90.1-2016",
                    "standards_building_type": "Retail",
                    "standards_space_type": "WholeBuilding - Retail",
                }
                first = unwrap(await session.call_tool("assign_space_type_simple", args))
                assert first["ok"] is True, first
                assert first["reused_existing"] is False

                count_after_first = unwrap(await session.call_tool(
                    "list_model_objects", {"object_type": "SpaceType", "max_results": 0},
                ))["count"]

                second = unwrap(await session.call_tool("assign_space_type_simple", args))
                assert second["ok"] is True, second
                assert second["reused_existing"] is True
                assert second["space_type"] == first["space_type"]

                count_after_second = unwrap(await session.call_tool(
                    "list_model_objects", {"object_type": "SpaceType", "max_results": 0},
                ))["count"]
                assert count_after_second == count_after_first, (
                    f"space type count grew from {count_after_first} to {count_after_second}"
                )

    asyncio.run(_run())


@pytest.mark.integration
def test_wizard_table_exact_values():
    # Validates: table rows carry the exact People/Lights/ElectricEquipment
    # values set on a space — proves real Space aggregation, not a stub.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_baseline_and_load(session, name)
                await _strip_baseline_space_type(session)

                spaces = unwrap(await session.call_tool("list_spaces", {"max_results": 0}))
                assert spaces["ok"] is True, spaces
                target_space = spaces["spaces"][0]["name"]  # alphabetically first -> index 0

                load_calls = [
                    ("create_people_definition", "num_people", 8.0),
                    ("create_lights_definition", "watts_per_area", 8.0),
                    ("create_electric_equipment", "watts_per_area", 5.0),
                ]
                for tool, value_key, value in load_calls:
                    args = {"name": f"{name}_{tool}", "space_name": target_space, value_key: value}
                    r = unwrap(await session.call_tool(tool, args))
                    assert r["ok"] is True, r

                start = unwrap(await session.call_tool("start_space_type_wizard", {}))
                assert start["ok"] is True, start

                status = unwrap(await session.call_tool("get_space_type_wizard_status", {"page_size": 100}))
                assert status["ok"] is True, status
                rows = _parse_table(status["table_rows"])
                assert 0 in rows, rows
                _floor_area, peak_people, lpd, epd, _elev, _ext_wall = rows[0]
                assert float(peak_people) == pytest.approx(8.0), rows[0]
                assert float(lpd) == pytest.approx(8.0), rows[0]
                assert float(epd) == pytest.approx(5.0), rows[0]

    asyncio.run(_run())


@pytest.mark.integration
def test_wizard_removes_assigned_rows():
    # Validates: assign_space_type_batch removes assigned indices from the
    # remaining table server-side — the core wizard state invariant.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_baseline_and_load(session, name)

                assert unwrap(await session.call_tool("start_space_type_wizard", {}))["ok"] is True
                tmpl = unwrap(await session.call_tool("choose_space_type_templates", {"templates": ["90.1-2019"]}))
                assert tmpl["ok"] is True, tmpl
                bld = unwrap(await session.call_tool(
                    "choose_space_type_building_types", {"building_types": ["Office"], "page_size": 100},
                ))
                assert bld["ok"] is True, bld
                assert bld["remaining_count"] == 10, bld

                batch = unwrap(await session.call_tool("assign_space_type_batch", {
                    "standards_template": "90.1-2019",
                    "standards_building_type": "Office",
                    "standards_space_type": "OpenOffice",
                    "space_indices": [0, 1, 2],
                }))
                assert batch["ok"] is True, batch
                assert batch["assigned_this_batch"] == 3
                assert batch["remaining_count"] == 7

                status = unwrap(await session.call_tool("get_space_type_wizard_status", {"page_size": 100}))
                assert status["ok"] is True, status
                assert status["remaining_count"] == 7
                remaining_idx = set(_parse_table(status["table_rows"]).keys())
                assert remaining_idx == {3, 4, 5, 6, 7, 8, 9}, remaining_idx

    asyncio.run(_run())


@pytest.mark.integration
def test_wizard_rejects_invalid_combo():
    # Validates: an out-of-scope space type is rejected with a targeted
    # did_you_mean suggestion, not silently accepted.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_baseline_and_load(session, name)

                assert unwrap(await session.call_tool("start_space_type_wizard", {}))["ok"] is True
                assert unwrap(await session.call_tool(
                    "choose_space_type_templates", {"templates": ["90.1-2019"]},
                ))["ok"] is True
                assert unwrap(await session.call_tool(
                    "choose_space_type_building_types", {"building_types": ["Office"]},
                ))["ok"] is True

                bad = unwrap(await session.call_tool("assign_space_type_batch", {
                    "standards_template": "90.1-2019",
                    "standards_building_type": "Office",
                    "standards_space_type": "OpenOfice",  # typo
                    "space_indices": [0],
                }))
                assert bad["ok"] is False, bad
                assert "OpenOffice" in bad["did_you_mean"], bad

    asyncio.run(_run())


@pytest.mark.integration
def test_wizard_finish_requires_full_assignment():
    # Validates: finish_space_type_wizard blocks on unassigned spaces unless
    # force=True, and force=True saves + reports the unassigned count.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_baseline_and_load(session, name)

                assert unwrap(await session.call_tool("start_space_type_wizard", {}))["ok"] is True
                assert unwrap(await session.call_tool(
                    "choose_space_type_templates", {"templates": ["90.1-2019"]},
                ))["ok"] is True
                assert unwrap(await session.call_tool(
                    "choose_space_type_building_types", {"building_types": ["Office"]},
                ))["ok"] is True
                assert unwrap(await session.call_tool("assign_space_type_batch", {
                    "standards_template": "90.1-2019",
                    "standards_building_type": "Office",
                    "standards_space_type": "OpenOffice",
                    "space_indices": [0, 1, 2],
                }))["ok"] is True

                blocked = unwrap(await session.call_tool("finish_space_type_wizard", {}))
                assert blocked["ok"] is False, blocked
                assert blocked["remaining_count"] == 7, blocked

                forced = unwrap(await session.call_tool("finish_space_type_wizard", {"force": True}))
                assert forced["ok"] is True, forced
                assert forced["spaces_assigned"] == 3, forced
                assert forced["spaces_left_unassigned"] == 7, forced

    asyncio.run(_run())


@pytest.mark.integration
def test_wizard_end_to_end_save():
    # Validates: full wizard flow saves a model where every originally
    # conditioned space has a non-null space type on reload.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_baseline_and_load(session, name)

                assert unwrap(await session.call_tool("start_space_type_wizard", {}))["ok"] is True
                assert unwrap(await session.call_tool(
                    "choose_space_type_templates", {"templates": ["90.1-2019"]},
                ))["ok"] is True
                assert unwrap(await session.call_tool(
                    "choose_space_type_building_types", {"building_types": ["Office"]},
                ))["ok"] is True
                batch = unwrap(await session.call_tool("assign_space_type_batch", {
                    "standards_template": "90.1-2019",
                    "standards_building_type": "Office",
                    "standards_space_type": "OpenOffice",
                    "space_indices": list(range(10)),
                }))
                assert batch["ok"] is True, batch
                assert batch["remaining_count"] == 0, batch

                finish = unwrap(await session.call_tool("finish_space_type_wizard", {}))
                assert finish["ok"] is True, finish
                assert finish["spaces_assigned"] == 10, finish
                assert finish["spaces_left_unassigned"] == 0, finish

                reload_result = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": finish["osm_path"]},
                ))
                assert reload_result["ok"] is True, reload_result

                spaces = unwrap(await session.call_tool("list_spaces", {"detailed": True, "max_results": 0}))
                assert spaces["ok"] is True, spaces
                assert len(spaces["spaces"]) == 10
                for space in spaces["spaces"]:
                    assert space["space_type"] is not None, space

    asyncio.run(_run())


@pytest.mark.integration
def test_wizard_cancel_clears_state_not_model():
    # Validates: cancel_space_type_wizard clears tracking only — prior
    # assign_space_type_batch mutations stay in the model.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_baseline_and_load(session, name)

                assert unwrap(await session.call_tool("start_space_type_wizard", {}))["ok"] is True
                assert unwrap(await session.call_tool(
                    "choose_space_type_templates", {"templates": ["90.1-2019"]},
                ))["ok"] is True
                assert unwrap(await session.call_tool(
                    "choose_space_type_building_types", {"building_types": ["Office"]},
                ))["ok"] is True
                batch = unwrap(await session.call_tool("assign_space_type_batch", {
                    "standards_template": "90.1-2019",
                    "standards_building_type": "Office",
                    "standards_space_type": "OpenOffice",
                    "space_indices": [0],
                }))
                assert batch["ok"] is True, batch
                assigned_space_type = batch["space_type"]

                cancelled = unwrap(await session.call_tool("cancel_space_type_wizard", {}))
                assert cancelled["ok"] is True, cancelled

                after = unwrap(await session.call_tool("get_space_type_wizard_status", {}))
                assert after["ok"] is False, after

                details = unwrap(await session.call_tool(
                    "get_space_type_details", {"space_type_name": assigned_space_type},
                ))
                assert details["ok"] is True, details
                assert len(details["space_type"]["spaces"]) == 1, details

    asyncio.run(_run())
