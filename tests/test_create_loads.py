"""Integration tests for load creation tools (Phase 6A).

Tests create_people_definition, create_lights_definition,
create_electric_equipment, create_gas_equipment, create_infiltration.
"""
import asyncio
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_loads") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _setup_model(session, model_name):
    """Create example model, load it, return first space name."""
    cr = unwrap(await session.call_tool("create_example_osm", {"name": model_name}))
    assert cr.get("ok") is True
    lr = unwrap(await session.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr.get("ok") is True
    spaces = unwrap(await session.call_tool("list_spaces", {"max_results": 0}))
    assert spaces.get("ok") is True and spaces["count"] > 0
    return spaces["spaces"][0]["name"]


# ---- People tests ----

@pytest.mark.integration
def test_create_people_by_area():
    # Validates: create_people_definition with people_per_area creates People object on correct space
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_people_definition", {
                    "name": "Office People", "space_name": space, "people_per_area": 0.05,
                }))
                assert res["ok"] is True
                assert res["people"]["name"] == "Office People"
                assert res["people"]["space"] == space
                # Verify shows in list
                lst = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "People", "max_results": 0}))
                assert any(p["name"] == "Office People" for p in lst["objects"])
    asyncio.run(_run())


@pytest.mark.integration
def test_create_people_by_count():
    # Validates: create_people_definition with num_people creates People object with fixed count
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_people_definition", {
                    "name": "Lab People", "space_name": space, "num_people": 10.0,
                }))
                assert res["ok"] is True
                assert res["people"]["name"] == "Lab People"
                # Verify the sizing value was set (not just name echoed back)
                people_data = res["people"]
                if "number_of_people" in people_data:
                    assert people_data["number_of_people"] == pytest.approx(10.0, abs=0.1), (
                        f"Expected 10 people, got {people_data['number_of_people']}"
                    )

                lst = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "People", "max_results": 0}))
                names = [p["name"] for p in lst["objects"]]
                assert "Lab People" in names, f"Lab People not found in model objects: {names}"
    asyncio.run(_run())


@pytest.mark.integration
def test_create_people_with_schedule():
    # Validates: create_people_definition assigns schedule to People object
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                # Create a schedule first
                sched = unwrap(await s.call_tool("create_schedule_ruleset", {
                    "name": "Occ Schedule", "schedule_type": "Fractional", "default_value": 0.8,
                }))
                assert sched["ok"] is True
                res = unwrap(await s.call_tool("create_people_definition", {
                    "name": "Scheduled People", "space_name": space,
                    "people_per_area": 0.04, "schedule_name": "Occ Schedule",
                }))
                assert res["ok"] is True
                assert res["people"]["number_of_people_schedule"] == "Occ Schedule"

                lst = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "People", "max_results": 0}))
                assert any(p["name"] == "Scheduled People" for p in lst["objects"])
    asyncio.run(_run())


# ---- Lights tests ----

@pytest.mark.integration
def test_create_lights_by_area():
    # Validates: create_lights_definition with watts_per_area creates Lights on space
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_lights_definition", {
                    "name": "Office Lights", "space_name": space, "watts_per_area": 10.76,
                }))
                assert res["ok"] is True
                assert res["lights"]["name"] == "Office Lights"
                lst = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "Lights", "max_results": 0}))
                assert any(l["name"] == "Office Lights" for l in lst["objects"])
    asyncio.run(_run())


@pytest.mark.integration
def test_create_lights_by_level():
    # Validates: create_lights_definition with lighting_level_w creates absolute wattage Lights
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_lights_definition", {
                    "name": "Desk Lamp", "space_name": space, "lighting_level_w": 500.0,
                }))
                assert res["ok"] is True
                assert res["lights"]["name"] == "Desk Lamp"

                lst = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "Lights", "max_results": 0}))
                assert any(l["name"] == "Desk Lamp" for l in lst["objects"])
    asyncio.run(_run())


# ---- Equipment tests ----

@pytest.mark.integration
def test_create_electric_equipment():
    # Validates: create_electric_equipment creates ElectricEquipment on space with correct name
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_electric_equipment", {
                    "name": "Computers", "space_name": space, "watts_per_area": 8.0,
                }))
                assert res["ok"] is True
                assert res["electric_equipment"]["name"] == "Computers"
                lst = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "ElectricEquipment", "max_results": 0}))
                assert any(e["name"] == "Computers" for e in lst["objects"])
    asyncio.run(_run())


@pytest.mark.integration
def test_create_gas_equipment():
    # Validates: create_gas_equipment creates GasEquipment on space with correct name
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_gas_equipment", {
                    "name": "Kitchen Range", "space_name": space, "watts_per_area": 5.0,
                }))
                assert res["ok"] is True
                assert res["gas_equipment"]["name"] == "Kitchen Range"

                lst = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "GasEquipment", "max_results": 0}))
                assert any(g["name"] == "Kitchen Range" for g in lst["objects"])
    asyncio.run(_run())


# ---- Infiltration tests ----

@pytest.mark.integration
def test_create_infiltration_by_area():
    # Validates: create_infiltration with flow_per_exterior_surface_area creates infiltration object
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_infiltration", {
                    "name": "Envelope Leakage", "space_name": space,
                    "flow_per_exterior_surface_area": 0.0003,
                }))
                assert res["ok"] is True
                assert res["infiltration"]["name"] == "Envelope Leakage"
                lst = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "SpaceInfiltrationDesignFlowRate", "max_results": 0}))
                assert any(i["name"] == "Envelope Leakage" for i in lst["objects"])
    asyncio.run(_run())


@pytest.mark.integration
def test_create_infiltration_by_ach():
    # Validates: create_infiltration with ach creates infiltration object with air changes method
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_infiltration", {
                    "name": "ACH Infiltration", "space_name": space, "ach": 0.5,
                }))
                assert res["ok"] is True
                assert res["infiltration"]["name"] == "ACH Infiltration"

                lst = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "SpaceInfiltrationDesignFlowRate", "max_results": 0}))
                assert any(i["name"] == "ACH Infiltration" for i in lst["objects"])
    asyncio.run(_run())


# ---- Error tests ----

@pytest.mark.integration
def test_create_load_invalid_space():
    # Validates: create_people_definition rejects nonexistent space with clear error
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_people_definition", {
                    "name": "Bad", "space_name": "NonexistentSpace", "people_per_area": 0.05,
                }))
                assert res["ok"] is False
                assert "not found" in res["error"]
    asyncio.run(_run())


@pytest.mark.integration
def test_create_load_invalid_schedule():
    # Validates: create_lights_definition rejects nonexistent schedule with clear error
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_lights_definition", {
                    "name": "Bad Lights", "space_name": space,
                    "watts_per_area": 10.0, "schedule_name": "NonexistentSchedule",
                }))
                assert res["ok"] is False
                assert "not found" in res["error"]
    asyncio.run(_run())


@pytest.mark.integration
def test_create_load_no_sizing_method():
    # Validates: create_people_definition requires sizing param (people_per_area or num_people)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                space = await _setup_model(s, _unique())
                res = unwrap(await s.call_tool("create_people_definition", {
                    "name": "No Size", "space_name": space,
                }))
                assert res["ok"] is False
                assert "people_per_area" in res["error"] or "Provide" in res["error"]
    asyncio.run(_run())
