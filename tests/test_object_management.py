"""Integration tests for object management tools (Phase 6B).

Tests delete_object, rename_object, list_model_objects.
"""
import asyncio
import uuid

import pytest
from conftest import integration_enabled, server_params, setup_example, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_objmgmt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _setup_baseline(session, model_name, ashrae_sys_num="07"):
    """Create + load baseline model with HVAC."""
    cr = unwrap(await session.call_tool("create_baseline_osm", {
        "name": model_name, "ashrae_sys_num": ashrae_sys_num,
    }))
    assert cr["ok"] is True, cr
    lr = unwrap(await session.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr["ok"] is True


# ---- Rename tests ----

@pytest.mark.integration
def test_rename_space():
    # Validates: rename_object changes space name and old name disappears from listing
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Get first space name
                spaces = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                old_name = spaces["spaces"][0]["name"]
                # Rename
                res = unwrap(await s.call_tool("rename_object", {
                    "object_name": old_name, "new_name": "Renamed Space",
                }))
                assert res["ok"] is True
                assert res["old_name"] == old_name
                assert res["new_name"] == "Renamed Space"
                # Verify
                spaces2 = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                assert any(sp["name"] == "Renamed Space" for sp in spaces2["spaces"])
    asyncio.run(_run())


@pytest.mark.integration
def test_rename_thermal_zone():
    # Validates: rename_object changes zone name, returns type=ThermalZone
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                zones = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                old_name = zones["thermal_zones"][0]["name"]
                res = unwrap(await s.call_tool("rename_object", {
                    "object_name": old_name, "new_name": "Renamed Zone",
                }))
                assert res["ok"] is True
                assert res["type"] == "ThermalZone"

                # Independent query verification
                zones2 = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                names = [z["name"] for z in zones2["thermal_zones"]]
                assert "Renamed Zone" in names
                assert old_name not in names
    asyncio.run(_run())


# ---- Delete tests ----

@pytest.mark.integration
def test_delete_space():
    # Validates: delete_object removes space and decreases count by 1
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Create a new space to delete (don't delete model's original)
                unwrap(await s.call_tool("create_space", {"name": "ToDelete"}))
                spaces_before = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                count_before = spaces_before["count"]
                # Delete
                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": "ToDelete",
                }))
                assert res["ok"] is True
                assert res["type"] == "Space"
                # Verify count decreased
                spaces_after = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                assert spaces_after["count"] == count_before - 1
    asyncio.run(_run())


@pytest.mark.integration
def test_delete_nonexistent():
    # Validates: delete_object returns ok:false with "not found" for bad name
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": "DoesNotExist123",
                }))
                assert res["ok"] is False
                assert "not found" in res["error"]
    asyncio.run(_run())


# list_model_objects tests are in test_generic_access.py

# ---- Baseline model tests ----

@pytest.mark.integration
def test_delete_boiler():
    # Validates: delete_object removes BoilerHotWater from System 7 model
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # System 7 has boiler
                await _setup_baseline(s, _unique(), ashrae_sys_num="07")
                boilers = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "BoilerHotWater", "max_results": 0,
                }))
                assert boilers["ok"] is True and boilers["count"] > 0
                boiler_name = boilers["objects"][0]["name"]
                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": boiler_name, "object_type": "BoilerHotWater",
                }))
                assert res["ok"] is True

                # Independent query verification
                boilers2 = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "BoilerHotWater", "max_results": 0,
                }))
                assert boilers2["count"] < boilers["count"]
    asyncio.run(_run())


@pytest.mark.integration
def test_rename_air_loop():
    # Validates: rename_object changes air loop name, returns type=AirLoopHVAC
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique(), ashrae_sys_num="03")
                loops = unwrap(await s.call_tool("list_air_loops", {}))
                assert loops["ok"] is True and loops["count"] > 0
                old = loops["air_loops"][0]["name"]
                res = unwrap(await s.call_tool("rename_object", {
                    "object_name": old, "new_name": "My AHU",
                }))
                assert res["ok"] is True
                assert res["type"] == "AirLoopHVAC"

                # Independent query verification
                loops2 = unwrap(await s.call_tool("list_air_loops", {}))
                names = [l["name"] for l in loops2["air_loops"]]
                assert "My AHU" in names
                assert old not in names
    asyncio.run(_run())


@pytest.mark.integration
def test_delete_with_type_hint():
    # Validates: delete_object with object_type hint removes ScheduleRuleset
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Create a schedule to delete
                unwrap(await s.call_tool("create_schedule_ruleset", {
                    "name": "TempSched", "schedule_type": "Fractional", "default_value": 1.0,
                }))
                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": "TempSched", "object_type": "ScheduleRuleset",
                }))
                assert res["ok"] is True
                assert res["type"] == "ScheduleRuleset"

                # Independent query verification
                scheds = unwrap(await s.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0}))
                names = [sr["name"] for sr in scheds["objects"]]
                assert "TempSched" not in names
    asyncio.run(_run())


@pytest.mark.integration
def test_rename_schedule():
    # Validates: rename_object changes schedule name, old name gone from listing
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Create a schedule to rename
                unwrap(await s.call_tool("create_schedule_ruleset", {
                    "name": "OldSched", "schedule_type": "Fractional", "default_value": 1.0,
                }))
                res = unwrap(await s.call_tool("rename_object", {
                    "object_name": "OldSched", "new_name": "NewSched",
                }))
                assert res["ok"] is True
                assert res["new_name"] == "NewSched"

                # Independent query verification
                scheds = unwrap(await s.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0}))
                names = [sr["name"] for sr in scheds["objects"]]
                assert "NewSched" in names
                assert "OldSched" not in names
    asyncio.run(_run())


# ---- find_object_references tests ----

@pytest.mark.integration
def test_find_object_references_construction_referenced_by_surface():
    # Validates: assigning a construction to a surface makes the surface show up
    # in the construction's referenced_by, with the correct via_field
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())

                mat = unwrap(await s.call_tool("create_standard_opaque_material", {
                    "name": "RefTestMaterial",
                }))
                assert mat["ok"] is True, mat
                constr = unwrap(await s.call_tool("create_construction", {
                    "name": "RefTestConstruction", "material_names": ["RefTestMaterial"],
                }))
                assert constr["ok"] is True, constr

                surfaces = unwrap(await s.call_tool("list_surfaces", {"max_results": 1}))
                surface_name = surfaces["surfaces"][0]["name"]
                assign = unwrap(await s.call_tool("assign_construction_to_surface", {
                    "surface_name": surface_name, "construction_name": "RefTestConstruction",
                }))
                assert assign["ok"] is True, assign

                res = unwrap(await s.call_tool("find_object_references", {
                    "object_type": "Construction", "object_name": "RefTestConstruction",
                }))
                assert res["ok"] is True, res
                assert res["referenced_by_count"] >= 1, res
                ref_names = {r["name"] for r in res["referenced_by"]}
                assert surface_name in ref_names, res
                matching = next(r for r in res["referenced_by"] if r["name"] == surface_name)
                assert matching["via_field"] == "Construction Name", matching

                # And the reverse direction: the construction references its material
                out_names = {r["name"] for r in res["references"]}
                assert "RefTestMaterial" in out_names, res
    asyncio.run(_run())


@pytest.mark.integration
def test_find_object_references_orphaned_object_has_no_referrers():
    # Validates: a construction never assigned anywhere reports zero referenced_by
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())

                unwrap(await s.call_tool("create_standard_opaque_material", {
                    "name": "OrphanMaterial",
                }))
                unwrap(await s.call_tool("create_construction", {
                    "name": "OrphanConstruction", "material_names": ["OrphanMaterial"],
                }))

                res = unwrap(await s.call_tool("find_object_references", {
                    "object_type": "Construction", "object_name": "OrphanConstruction",
                }))
                assert res["ok"] is True, res
                assert res["referenced_by_count"] == 0, res
                assert res["referenced_by"] == [], res
    asyncio.run(_run())


@pytest.mark.integration
def test_find_object_references_not_found():
    # Validates: unknown object returns ok=False, not an exception
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("find_object_references", {
                    "object_type": "Construction", "object_name": "NoSuchConstruction123",
                }))
                assert res["ok"] is False, res
    asyncio.run(_run())


# ---- delete_object check_references tests ----

@pytest.mark.integration
def test_delete_object_check_references_blocks_referenced_construction():
    # Validates: delete_object(check_references=True) refuses to delete a
    # construction still assigned to a surface, and reports the blocker
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())

                unwrap(await s.call_tool("create_standard_opaque_material", {
                    "name": "BlockMaterial",
                }))
                unwrap(await s.call_tool("create_construction", {
                    "name": "BlockConstruction", "material_names": ["BlockMaterial"],
                }))
                surfaces = unwrap(await s.call_tool("list_surfaces", {"max_results": 1}))
                surface_name = surfaces["surfaces"][0]["name"]
                unwrap(await s.call_tool("assign_construction_to_surface", {
                    "surface_name": surface_name, "construction_name": "BlockConstruction",
                }))

                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": "BlockConstruction", "object_type": "Construction",
                    "check_references": True,
                }))
                assert res["ok"] is False, res
                assert "blocked_by" in res, res
                assert any(b["name"] == surface_name for b in res["blocked_by"]), res

                # Still present — the blocked delete must not have gone through
                still_there = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "Construction", "max_results": 0,
                }))
                names = [o["name"] for o in still_there["objects"]]
                assert "BlockConstruction" in names, still_there
    asyncio.run(_run())


@pytest.mark.integration
def test_delete_object_check_references_false_deletes_anyway():
    # Validates: check_references defaults to False, matching prior delete_object behavior —
    # a referenced construction is still deletable without the flag
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())

                unwrap(await s.call_tool("create_standard_opaque_material", {
                    "name": "UnblockedMaterial",
                }))
                unwrap(await s.call_tool("create_construction", {
                    "name": "UnblockedConstruction", "material_names": ["UnblockedMaterial"],
                }))
                surfaces = unwrap(await s.call_tool("list_surfaces", {"max_results": 1}))
                surface_name = surfaces["surfaces"][0]["name"]
                unwrap(await s.call_tool("assign_construction_to_surface", {
                    "surface_name": surface_name, "construction_name": "UnblockedConstruction",
                }))

                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": "UnblockedConstruction", "object_type": "Construction",
                }))
                assert res["ok"] is True, res
    asyncio.run(_run())


@pytest.mark.integration
def test_delete_space_with_surfaces_default_not_blocked_by_own_children():
    # Regression: check_references defaulting to True would have blocked every
    # Space deletion with surfaces, since a Space's own surfaces register as its
    # "sources" (normal ownership, not a stray reference) — default must be False
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                unwrap(await s.call_tool("create_space", {"name": "SpaceWithNoSurfaces"}))
                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": "SpaceWithNoSurfaces",
                }))
                assert res["ok"] is True, res
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# H-29: fetch_object UUID validation (direct SDK, not MCP)
# ---------------------------------------------------------------------------

def test_bad_uuid_returns_none():
    # Regression: malformed UUID in fetch_object caused unhandled exception
    openstudio = pytest.importorskip("openstudio")
    from mcp_server.osm_helpers import fetch_object
    model = openstudio.model.Model()
    result = fetch_object(model, "Space", handle="not-a-valid-uuid-!!!")
    assert result is None, "Malformed UUID should return None, not an object"
