import asyncio
import math
import os
import uuid
from pathlib import Path

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_building") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_get_building_info():
    """Test getting detailed building information."""
    # Validates: example model building has name="Building 1", floor_area=400m2
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # Get building info
                building_resp = await session.call_tool("get_building_info", {})
                building_result = unwrap(building_resp)
                print("get_building_info:", building_result)
                assert building_result["ok"] is True, building_result

                building = building_result["building"]
                assert building["name"] == "Building 1"
                assert building["floor_area_m2"] == pytest.approx(400.0)
                assert building["conditioned_floor_area_m2"] >= 0, "Should have conditioned area"
                assert building["exterior_surface_area_m2"] > 0, "Should have exterior surfaces"
                assert building["number_of_people"] >= 0, "Should have people count"

    asyncio.run(_run())


@pytest.mark.integration
def test_get_model_summary():
    """Test getting model summary with object counts."""
    # Validates: example model summary has 4 spaces, 1 zone, 1 space type, all expected keys
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # Get model summary
                summary_resp = await session.call_tool("get_model_summary", {})
                summary_result = unwrap(summary_resp)
                print("get_model_summary:", summary_result)
                assert summary_result["ok"] is True, summary_result

                summary = summary_result["summary"]
                # Known values from OpenStudio example model
                assert summary["building_name"] == "Building 1"
                assert summary["floor_area_m2"] == pytest.approx(400.0)
                assert summary["spaces"] == 4
                assert summary["thermal_zones"] == 1
                assert summary["space_types"] == 1

                # Verify all expected keys are present
                expected_keys = [
                    "building_name", "floor_area_m2", "conditioned_floor_area_m2",
                    "spaces", "building_stories", "thermal_zones",
                    "surfaces", "sub_surfaces", "shading_surfaces",
                    "materials", "constructions", "construction_sets",
                    "space_types", "people", "lights", "electric_equipment", "gas_equipment",
                    "schedule_rulesets", "schedule_constants",
                    "air_loops", "plant_loops", "zone_hvac_equipment",
                ]
                for key in expected_keys:
                    assert key in summary, f"Missing key: {key}"

    asyncio.run(_run())


@pytest.mark.integration
def test_list_building_stories():
    """Test listing building stories via list_model_objects."""
    # Validates: example model has exactly 1 building story via list_model_objects
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # List building stories via generic object access
                stories_resp = await session.call_tool("list_model_objects", {"object_type": "BuildingStory"})
                stories_result = unwrap(stories_resp)
                print("list_model_objects BuildingStory:", stories_result)
                assert stories_result["ok"] is True, stories_result

                # Example model has 1 story
                assert stories_result["count"] == 1
                stories = stories_result["objects"]
                assert len(stories) == 1

                # Check story attributes
                story = stories[0]
                assert story["name"], "Story should have a name"
                assert story["handle"], "Story should have a handle"

    asyncio.run(_run())


@pytest.mark.integration
def test_building_info_baseline():
    """Test building info with 10-zone baseline model."""
    # Validates: 10-zone baseline building floor area > 1000 m2
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_building")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                br = await session.call_tool("get_building_info", {})
                bd = unwrap(br)
                print("baseline building_info:", bd)
                assert bd["ok"] is True, bd
                b = bd["building"]
                assert b["floor_area_m2"] > 1000  # 2 floors * 100m * 50m = 10000 m²

    asyncio.run(_run())


@pytest.mark.integration
def test_conditioned_floor_area_with_hvac():
    """Conditioned floor area should equal total floor area when all zones have thermostats.

    Baseline model with ashrae_sys_num adds thermostats to all zones.
    Pre-v0.5: conditioned_floor_area_m2 returned 0.0 (SDK needs SQL).
    Now: computed from model objects (zones with thermostats).
    """
    # Validates: conditioned floor area equals total when all zones have thermostats
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_cond_area")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                # Baseline with HVAC = thermostats on all zones
                cr = await session.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "03", "num_floors": 1,
                })
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                br = await session.call_tool("get_building_info", {})
                bd = unwrap(br)
                assert bd["ok"] is True, bd
                b = bd["building"]
                # All zones have thermostats → conditioned = total
                assert b["conditioned_floor_area_m2"] == pytest.approx(
                    b["floor_area_m2"], rel=0.01,
                ), f"conditioned={b['conditioned_floor_area_m2']}, total={b['floor_area_m2']}"

                # Also check via get_model_summary
                sr = await session.call_tool("get_model_summary", {})
                sd = unwrap(sr)
                assert sd["ok"] is True, sd
                s = sd["summary"]
                assert s["conditioned_floor_area_m2"] == pytest.approx(
                    s["floor_area_m2"], rel=0.01,
                ), f"summary conditioned={s['conditioned_floor_area_m2']}, total={s['floor_area_m2']}"

    asyncio.run(_run())


@pytest.mark.integration
def test_conditioned_floor_area_no_hvac():
    """Conditioned floor area with baseline model (no HVAC system).

    create_baseline_osm always adds thermostats for sizing readiness,
    even without ashrae_sys_num. So conditioned area should equal total
    floor area (thermostats present on all zones).
    """
    # Validates: baseline without HVAC still has conditioned=total (thermostats always added)
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_uncond")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {
                    "name": name, "num_floors": 1,
                })
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                br = await session.call_tool("get_building_info", {})
                bd = unwrap(br)
                assert bd["ok"] is True, bd
                b = bd["building"]
                assert b["floor_area_m2"] > 0
                # Baseline always adds thermostats → conditioned = total
                assert b["conditioned_floor_area_m2"] == pytest.approx(
                    b["floor_area_m2"], rel=0.01,
                ), f"conditioned={b['conditioned_floor_area_m2']}, total={b['floor_area_m2']}"

    asyncio.run(_run())


@pytest.mark.integration
def test_building_stories_baseline():
    """Test building stories with 2-story baseline model via list_model_objects."""
    # Validates: 2-story baseline model has exactly 2 BuildingStory objects
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_stories")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                sr = await session.call_tool("list_model_objects", {"object_type": "BuildingStory"})
                sd = unwrap(sr)
                print("baseline stories:", sd)
                assert sd["ok"] is True, sd
                assert sd["count"] == 2
                assert len(sd["objects"]) == 2

    asyncio.run(_run())


@pytest.mark.integration
def test_building_info_no_loads():
    """Regression: get_building_info must not crash with NaN/Inf when model has no loads.

    Bug: density fields (peoplePerFloorArea, etc.) return NaN/Inf from
    OpenStudio when the model has geometry but no people/lights/equipment.
    Pydantic rejects NaN in JSON, causing a hard crash.
    """
    # Regression: get_building_info crashed with NaN/Inf when model has no loads
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_noloads")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                # Baseline model has geometry but no loads
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                br = await session.call_tool("get_building_info", {})
                bd = unwrap(br)
                print("no-loads building_info:", bd)
                assert bd["ok"] is True, f"get_building_info crashed: {bd}"

                b = bd["building"]
                assert b["floor_area_m2"] > 0
                # Density fields should be None (not NaN/Inf) when no loads
                for key in ["people_per_floor_area", "lighting_power_per_floor_area_w_m2",
                            "electric_equipment_power_per_floor_area_w_m2",
                            "gas_equipment_power_per_floor_area_w_m2"]:
                    val = b[key]
                    if val is not None:
                        assert isinstance(val, (int, float)), (
                            f"{key} should be numeric, got {type(val).__name__}: {val!r}"
                        )
                        assert math.isfinite(val), f"{key} = {val!r} — NaN/Inf not allowed in building info"

    asyncio.run(_run())


@pytest.mark.integration
def test_building_tools_without_loaded_model():
    """Test that building tools fail gracefully when no model is loaded."""
    # Validates: building tools return ok:false with "no model loaded" when no model
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to get building info without loading a model
                building_resp = await session.call_tool("get_building_info", {})
                building_result = unwrap(building_resp)
                print("get_building_info (no model):", building_result)
                assert building_result["ok"] is False
                assert "no model loaded" in building_result["error"].lower()

    asyncio.run(_run())


_RATIO_FIELDS = (
    "people_per_floor_area", "floor_area_per_person_m2",
    "lighting_power_per_floor_area_w_m2",
    "electric_equipment_power_per_floor_area_w_m2",
    "gas_equipment_power_per_floor_area_w_m2",
    "infiltration_design_flow_per_exterior_surface_area",
    "infiltration_design_flow_per_exterior_wall_area",
)


def _save_model(model, name: str) -> str:
    """Write a model under /runs so the MCP server can load it."""
    import openstudio

    run_root = Path(os.environ.get("OPENSTUDIO_MCP_RUN_ROOT", os.environ.get("OSMCP_RUN_ROOT", "/runs")))
    path = run_root / "examples" / name / "model.osm"
    path.parent.mkdir(parents=True, exist_ok=True)
    model.save(openstudio.path(str(path)), True)
    return str(path)


@pytest.mark.integration
def test_get_building_info_with_zero_people():
    # Regression: #233 — Building.floorAreaPerPerson() throws "division by 0" when the
    # building has no people, and the SWIG wrapper leaves the Python error pending, so
    # the tool returned ok:false, then ok:true with a garbage 6.9e-310 value, then raised
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")
    import openstudio

    model = openstudio.model.exampleModel()
    for people in model.getPeoples():
        people.remove()
    assert model.getBuilding().numberOfPeople() == 0.0
    osm_path = _save_model(model, _unique_name("pytest_zero_people"))

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert unwrap(await session.call_tool("load_osm_model", {"osm_path": osm_path}))["ok"] is True

                # Three calls: before the fix each outcome differed (ok:false, garbage, raise)
                for attempt in range(3):
                    result = unwrap(await session.call_tool("get_building_info", {}))
                    assert result["ok"] is True, f"call {attempt}: {result}"
                    b = result["building"]
                    assert b["number_of_people"] == 0.0
                    assert b["floor_area_per_person_m2"] is None, (
                        f"call {attempt}: no people means no area per person, got {b['floor_area_per_person_m2']}")
                    # Floor area is non-zero, so per-floor-area ratios are real numbers
                    assert b["floor_area_m2"] == pytest.approx(400.0)
                    assert b["people_per_floor_area"] == 0.0
                    assert b["lighting_power_per_floor_area_w_m2"] == pytest.approx(10.0, rel=0.01)

    asyncio.run(_run())


@pytest.mark.integration
def test_get_building_info_on_empty_model():
    # Regression: #233 — with no people floorAreaPerPerson throws (the per-floor-area
    # getters return 0.0 for 0/0); every undefined ratio must come back null, and the
    # tool must not fail or raise, on repeated calls too
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")
    import openstudio

    osm_path = _save_model(openstudio.model.Model(), _unique_name("pytest_empty_building"))

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert unwrap(await session.call_tool("load_osm_model", {"osm_path": osm_path}))["ok"] is True

                for attempt in range(2):
                    result = unwrap(await session.call_tool("get_building_info", {}))
                    assert result["ok"] is True, f"call {attempt}: {result}"
                    b = result["building"]
                    assert b["floor_area_m2"] == 0.0
                    assert b["exterior_surface_area_m2"] == 0.0
                    assert b["number_of_people"] == 0.0
                    for field in _RATIO_FIELDS:
                        assert b[field] is None, (
                            f"call {attempt}: {field} should be null with a zero denominator, got {b[field]}")

    asyncio.run(_run())
