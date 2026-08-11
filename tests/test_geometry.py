import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, setup_example, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_geometry") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


async def _setup_with_space(session, model_name, space_name):
    """Create model, load it, and create a space for geometry tests."""
    await setup_example(session, model_name)
    sr = unwrap(await session.call_tool("create_space", {"name": space_name}))
    assert sr["ok"] is True


@pytest.mark.integration
def test_list_surfaces():
    """Test listing all surfaces."""
    # Validates: example model surfaces have name, surface_type, gross_area_m2 fields
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_result = unwrap(await session.call_tool("create_example_osm", {"name": name}))
                assert create_result["ok"] is True

                load_result = unwrap(await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]}))
                assert load_result["ok"] is True

                # List surfaces
                surfaces_result = unwrap(await session.call_tool("list_surfaces", {"max_results": 0}))
                assert surfaces_result["ok"] is True
                assert surfaces_result["count"] > 0
                first = surfaces_result["surfaces"][0]
                assert first["name"], "Surface should have a name"
                assert first["surface_type"], "Surface should have a type"
                assert first["gross_area_m2"] > 0, "Surface should have positive area"

    asyncio.run(_run())


@pytest.mark.integration
def test_list_subsurfaces():
    """Test listing all subsurfaces."""
    # Validates: list_subsurfaces returns ok with count field on example model
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_result = unwrap(await session.call_tool("create_example_osm", {"name": name}))
                assert create_result["ok"] is True

                load_result = unwrap(await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]}))
                assert load_result["ok"] is True

                # List subsurfaces
                subsurfaces_result = unwrap(await session.call_tool("list_subsurfaces", {"max_results": 0}))
                assert subsurfaces_result["ok"] is True
                # Example model may have 0 subsurfaces
                assert subsurfaces_result["count"] >= 0
                actual_len = len(subsurfaces_result.get("subsurfaces", []))
                assert actual_len == subsurfaces_result["count"], (
                    f"List length should match count: {actual_len} != {subsurfaces_result['count']}"
                )

    asyncio.run(_run())


@pytest.mark.integration
def test_surfaces_baseline():
    """Test surfaces in 10-zone baseline model."""
    # Validates: 10-zone baseline has >= 50 surfaces including Wall and Floor/RoofCeiling
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_geo")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                sr = await session.call_tool("list_surfaces", {"max_results": 0})
                sd = unwrap(sr)
                print("baseline surfaces:", sd)
                assert sd["ok"] is True
                # 10-zone 2-story building should have many surfaces
                assert sd["count"] >= 50
                # Check for interior walls (surface boundary)
                types = {s["surface_type"] for s in sd["surfaces"]}
                assert "Wall" in types
                assert "Floor" in types or "RoofCeiling" in types

    asyncio.run(_run())


# ---- Surface creation tests ----


@pytest.mark.integration
def test_create_surface_wall():
    """Create a wall surface with 4 vertices, verify type and area."""
    # Validates: create_surface Wall adds 1 surface with correct type, ~30m2 area, 4 vertices
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                # 10m wide x 3m tall wall
                surfs_before = unwrap(await s.call_tool("list_surfaces", {"max_results": 0}))
                count_before = surfs_before["count"]

                res = unwrap(await s.call_tool("create_surface", {
                    "name": "TestWall",
                    "vertices": [[0, 0, 0], [10, 0, 0], [10, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                }))
                assert res["ok"] is True
                surf = res["surface"]
                assert surf["surface_type"] == "Wall"
                assert surf["gross_area_m2"] > 29  # ~30 m²
                assert surf["num_vertices"] == 4

                # Independent query verification
                surfs_after = unwrap(await s.call_tool("list_surfaces", {"max_results": 0}))
                assert surfs_after["count"] == count_before + 1
    asyncio.run(_run())


@pytest.mark.integration
def test_create_surface_floor():
    """Create a floor surface."""
    # Validates: create_surface Floor with Ground BC adds 1 surface to model
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                surfs_before = unwrap(await s.call_tool("list_surfaces", {"max_results": 0}))
                count_before = surfs_before["count"]

                res = unwrap(await s.call_tool("create_surface", {
                    "name": "TestFloor",
                    "vertices": [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]],
                    "space_name": sp_name,
                    "surface_type": "Floor",
                    "outside_boundary_condition": "Ground",
                }))
                assert res["ok"] is True
                assert res["surface"]["surface_type"] == "Floor"

                surfs_after = unwrap(await s.call_tool("list_surfaces", {"max_results": 0}))
                assert surfs_after["count"] == count_before + 1
    asyncio.run(_run())


@pytest.mark.integration
def test_create_surface_auto_type():
    """Omit surface_type — OS auto-detects from vertex tilt."""
    # Validates: create_surface auto-detects Wall from vertical polygon tilt
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                surfs_before = unwrap(await s.call_tool("list_surfaces", {"max_results": 0}))
                count_before = surfs_before["count"]

                # Vertical polygon → should auto-detect as Wall
                res = unwrap(await s.call_tool("create_surface", {
                    "name": "AutoWall",
                    "vertices": [[0, 0, 0], [5, 0, 0], [5, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                }))
                assert res["ok"] is True
                assert res["surface"]["surface_type"] == "Wall"

                surfs_after = unwrap(await s.call_tool("list_surfaces", {"max_results": 0}))
                assert surfs_after["count"] == count_before + 1
    asyncio.run(_run())


@pytest.mark.integration
def test_create_surface_invalid_space():
    """Bad space name should return error."""
    # Validates: create_surface returns ok:false for nonexistent space name
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                res = unwrap(await s.call_tool("create_surface", {
                    "name": "BadSurf",
                    "vertices": [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]],
                    "space_name": "nonexistent_space",
                }))
                assert res["ok"] is False
                assert "not found" in res["error"]
    asyncio.run(_run())


# ---- Subsurface creation tests ----


@pytest.mark.integration
def test_create_subsurface_window():
    """Create a window on a wall, verify in subsurface list."""
    # Validates: create_subsurface FixedWindow on wall appears in subsurface list
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                # Create wall first
                unwrap(await s.call_tool("create_surface", {
                    "name": "WallForWindow",
                    "vertices": [[0, 0, 0], [10, 0, 0], [10, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                }))
                # Create window on wall
                res = unwrap(await s.call_tool("create_subsurface", {
                    "name": "TestWindow",
                    "vertices": [[1, 0, 0.8], [4, 0, 0.8], [4, 0, 2.5], [1, 0, 2.5]],
                    "parent_surface_name": "WallForWindow",
                    "subsurface_type": "FixedWindow",
                }))
                assert res["ok"] is True
                sub = res["subsurface"]
                assert sub["subsurface_type"] == "FixedWindow"
                assert sub["surface"] == "WallForWindow"

                # Independent query verification
                subs = unwrap(await s.call_tool("list_subsurfaces", {"max_results": 0}))
                assert any(ss["name"] == "TestWindow" for ss in subs.get("subsurfaces", []))
    asyncio.run(_run())


@pytest.mark.integration
def test_create_subsurface_door():
    """Create a door on a wall."""
    # Validates: create_subsurface Door on wall appears in subsurface list
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                unwrap(await s.call_tool("create_surface", {
                    "name": "WallForDoor",
                    "vertices": [[0, 0, 0], [10, 0, 0], [10, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                }))
                res = unwrap(await s.call_tool("create_subsurface", {
                    "name": "TestDoor",
                    "vertices": [[5, 0, 0], [6, 0, 0], [6, 0, 2.1], [5, 0, 2.1]],
                    "parent_surface_name": "WallForDoor",
                    "subsurface_type": "Door",
                }))
                assert res["ok"] is True
                assert res["subsurface"]["subsurface_type"] == "Door"

                subs = unwrap(await s.call_tool("list_subsurfaces", {"max_results": 0}))
                assert any(ss["name"] == "TestDoor" for ss in subs.get("subsurfaces", []))
    asyncio.run(_run())


@pytest.mark.integration
def test_create_subsurface_invalid_parent():
    """Bad parent surface name should return error."""
    # Validates: create_subsurface returns ok:false for nonexistent parent surface
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                res = unwrap(await s.call_tool("create_subsurface", {
                    "name": "BadSub",
                    "vertices": [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]],
                    "parent_surface_name": "nonexistent_surface",
                }))
                assert res["ok"] is False
                assert "not found" in res["error"]
    asyncio.run(_run())


# ---- Space from floor print test ----


@pytest.mark.integration
def test_create_space_from_floor_print():
    """Extrude a rectangular floor polygon, verify surfaces created."""
    # Validates: floor print extrusion creates 6 surfaces (4 walls + floor + ceiling)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                # 10x10m rectangle, 3m height
                res = unwrap(await s.call_tool("create_space_from_floor_print", {
                    "name": "ExtrudedSpace",
                    "floor_vertices": [[0, 0], [10, 0], [10, 10], [0, 10]],
                    "floor_to_ceiling_height": 3.0,
                }))
                assert res["ok"] is True
                assert res["space_name"] == "ExtrudedSpace"
                # Rectangle → 4 walls + floor + ceiling = 6 surfaces
                assert res["num_surfaces"] == 6
                assert "Wall" in res["surface_types"]
                assert res["surface_types"]["Wall"] == 4

                # Independent query verification
                surfs = unwrap(await s.call_tool("list_surfaces", {"max_results": 0}))
                ext_surfs = [sf for sf in surfs["surfaces"] if sf["space"] == "ExtrudedSpace"]
                assert len(ext_surfs) == 6
    asyncio.run(_run())


# ---- Surface matching tests ----


@pytest.mark.integration
def test_match_surfaces_adjacent_spaces():
    """Two adjacent spaces — shared wall should become interior after matching."""
    # Validates: match_surfaces converts shared wall to Surface BC between adjacent spaces
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                # Create two side-by-side spaces sharing the wall at x=5
                unwrap(await s.call_tool("create_space_from_floor_print", {
                    "name": "Left", "floor_vertices": [[0, 0], [5, 0], [5, 5], [0, 5]],
                    "floor_to_ceiling_height": 3.0,
                }))
                unwrap(await s.call_tool("create_space_from_floor_print", {
                    "name": "Right", "floor_vertices": [[5, 0], [10, 0], [10, 5], [5, 5]],
                    "floor_to_ceiling_height": 3.0,
                }))
                # Before matching: all walls are Outdoors
                surfs_before = unwrap(await s.call_tool("list_surfaces", {"detailed": True, "max_results": 0}))
                new_surfs = [sf for sf in surfs_before["surfaces"]
                             if sf["space"] in ("Left", "Right")]
                interior_before = [sf for sf in new_surfs
                                   if sf["outside_boundary_condition"] == "Surface"]
                assert len(interior_before) == 0

                # Match
                res = unwrap(await s.call_tool("match_surfaces", {}))
                assert res["ok"] is True
                assert res["matched_surfaces"] >= 2  # at least the shared wall pair

                # After matching: shared wall should be "Surface"
                surfs_after = unwrap(await s.call_tool("list_surfaces", {"detailed": True, "max_results": 0}))
                new_surfs_after = [sf for sf in surfs_after["surfaces"]
                                   if sf["space"] in ("Left", "Right")]
                interior_after = [sf for sf in new_surfs_after
                                  if sf["outside_boundary_condition"] == "Surface"]
                assert len(interior_after) >= 2  # pair of matched walls
    asyncio.run(_run())


@pytest.mark.integration
def test_match_surfaces_no_adjacency():
    """Single space — match_surfaces should succeed with 0 matched."""
    # Validates: match_surfaces succeeds with 0 matches on isolated space
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                unwrap(await s.call_tool("create_space_from_floor_print", {
                    "name": "Solo", "floor_vertices": [[0, 0], [5, 0], [5, 5], [0, 5]],
                    "floor_to_ceiling_height": 3.0,
                }))
                res = unwrap(await s.call_tool("match_surfaces", {}))
                assert res["ok"] is True
    asyncio.run(_run())


# ---- Missing roof/ceiling repair tests ----


@pytest.mark.integration
def test_repair_missing_roof_ceiling_synthesizes_flat_ceiling():
    """Delete an extruded space's ceiling, confirm repair synthesizes a matching one."""
    # Regression: repair_missing_roof_ceiling derives a flat RoofCeiling from a level
    # floor + uniformly level wall tops, oriented correctly (tilt ~0 deg, facing up),
    # and falls back to "Adiabatic" boundary when match_surfaces() finds no adjacent
    # match (an isolated space here). A second call is a no-op (repaired_count == 0).
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                unwrap(await s.call_tool("create_space_from_floor_print", {
                    "name": "RepairSpace",
                    "floor_vertices": [[0, 0], [10, 0], [10, 10], [0, 10]],
                    "floor_to_ceiling_height": 3.0,
                }))

                ceilings = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": "RepairSpace", "surface_type": "RoofCeiling", "max_results": 0,
                }))
                assert ceilings["count"] == 1, ceilings
                ceiling_name = ceilings["surfaces"][0]["name"]
                delete_result = unwrap(await s.call_tool(
                    "delete_object", {"object_name": ceiling_name, "object_type": "Surface"},
                ))
                assert delete_result["ok"] is True, delete_result

                result = unwrap(await s.call_tool("repair_missing_roof_ceiling", {}))
                assert result["ok"] is True, result
                assert result["repaired_count"] == 1, result
                assert result["skipped"] == [], result
                repaired = result["repaired"][0]
                assert repaired["space"] == "RepairSpace", repaired
                assert repaired["area_m2"] == pytest.approx(100.0, abs=0.01), repaired
                assert repaired["ceiling_z"] == pytest.approx(3.0, abs=0.001), repaired
                assert repaired["final_boundary_condition"] == "Adiabatic", repaired
                # Regression: the built-in example model has a default construction
                # set, so the synthesized surface should resolve one through the
                # hierarchy with no warning — the no-construction fallback path is
                # covered separately on the constructionless residential shared-wall-duplication gbXML fixture.
                assert repaired["construction"] is not None, repaired
                assert repaired["construction_warning"] is None, repaired
                assert repaired["boundary_condition_warning"] is not None, repaired

                new_ceilings = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": "RepairSpace", "surface_type": "RoofCeiling", "max_results": 0,
                }))
                assert new_ceilings["count"] == 1, new_ceilings
                details = unwrap(await s.call_tool(
                    "get_surface_details", {"surface_name": new_ceilings["surfaces"][0]["name"]},
                ))
                assert details["surface"]["tilt_deg"] == pytest.approx(0.0, abs=1e-6), details
                assert details["surface"]["outside_boundary_condition"] == "Adiabatic", details

                again = unwrap(await s.call_tool("repair_missing_roof_ceiling", {}))
                assert again["ok"] is True, again
                assert again["repaired_count"] == 0, again
    asyncio.run(_run())


@pytest.mark.integration
def test_repair_missing_roof_ceiling_skips_uneven_walls():
    """A space with one short extra wall should be skipped, not given a wrong flat ceiling."""
    # Regression: repair_missing_roof_ceiling requires every wall's own top vertices to
    # reach the space's overall max Z within tolerance; an extra lower wall (a knee wall /
    # partial-height partition) must not be silently capped over.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                unwrap(await s.call_tool("create_space_from_floor_print", {
                    "name": "UnevenSpace",
                    "floor_vertices": [[0, 0], [10, 0], [10, 10], [0, 10]],
                    "floor_to_ceiling_height": 3.0,
                }))
                ceilings = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": "UnevenSpace", "surface_type": "RoofCeiling", "max_results": 0,
                }))
                delete_result = unwrap(await s.call_tool(
                    "delete_object",
                    {"object_name": ceilings["surfaces"][0]["name"], "object_type": "Surface"},
                ))
                assert delete_result["ok"] is True, delete_result

                # Extra short wall (top at 1.5m, well under the 3m full-height walls)
                short_wall = unwrap(await s.call_tool("create_surface", {
                    "name": "ShortKneeWall",
                    "vertices": [[0, 0, 0], [1, 0, 0], [1, 0, 1.5], [0, 0, 1.5]],
                    "space_name": "UnevenSpace",
                    "surface_type": "Wall",
                }))
                assert short_wall["ok"] is True, short_wall

                result = unwrap(await s.call_tool("repair_missing_roof_ceiling", {}))
                assert result["ok"] is True, result
                assert result["repaired_count"] == 0, result
                assert len(result["skipped"]) == 1, result
                skip = result["skipped"][0]
                assert skip["space"] == "UnevenSpace", skip
                assert "uneven wall heights" in skip["reason"], skip
    asyncio.run(_run())


# ---- Coplanar sliver surface merge tests ----


@pytest.mark.integration
def test_merge_coplanar_sliver_surfaces_merges_split_ceiling():
    """Replace a space's ceiling with two coplanar fragments sharing an edge; confirm merge."""
    # Regression: gbXML/Revit exports commonly split one physical ceiling into several
    # same-space coplanar fragments along adjacent-room boundaries. merge_coplanar_sliver_surfaces
    # must collapse touching, same-type, same-boundary-condition fragments back into one
    # surface with the combined area, and leave the space enclosed afterward.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                unwrap(await s.call_tool("create_space_from_floor_print", {
                    "name": "SliverSpace",
                    "floor_vertices": [[0, 0], [10, 0], [10, 10], [0, 10]],
                    "floor_to_ceiling_height": 3.0,
                }))

                ceilings = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": "SliverSpace", "surface_type": "RoofCeiling", "max_results": 0,
                }))
                assert ceilings["count"] == 1, ceilings
                delete_result = unwrap(await s.call_tool(
                    "delete_object",
                    {"object_name": ceilings["surfaces"][0]["name"], "object_type": "Surface"},
                ))
                assert delete_result["ok"] is True, delete_result

                for frag_name, x0, x1 in (("CeilingFragA", 0, 6), ("CeilingFragB", 6, 10)):
                    frag = unwrap(await s.call_tool("create_surface", {
                        "name": frag_name,
                        "vertices": [[x0, 0, 3], [x1, 0, 3], [x1, 10, 3], [x0, 10, 3]],
                        "space_name": "SliverSpace",
                        "surface_type": "RoofCeiling",
                        "outside_boundary_condition": "Outdoors",
                    }))
                    assert frag["ok"] is True, frag

                result = unwrap(await s.call_tool("merge_coplanar_sliver_surfaces", {}))
                assert result["ok"] is True, result
                assert result["merged_group_count"] == 1, result
                assert result["skipped"] == [], result
                group = result["merged"][0]
                assert group["space"] == "SliverSpace", group
                assert group["surface_type"] == "RoofCeiling", group
                assert group["fragments_before"] == 2, group
                assert group["surfaces_after"] == 1, group
                assert group["survivor"] == "CeilingFragA", group  # larger fragment (60 m2 vs 40 m2)

                ceilings_after = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": "SliverSpace", "surface_type": "RoofCeiling", "max_results": 0,
                }))
                assert ceilings_after["count"] == 1, ceilings_after
                assert ceilings_after["surfaces"][0]["gross_area_m2"] == pytest.approx(100.0, abs=0.01), ceilings_after
    asyncio.run(_run())


@pytest.mark.integration
def test_merge_coplanar_sliver_surfaces_skips_mixed_boundary_conditions():
    """Two coplanar wall fragments with different boundary conditions must not be blended."""
    # Regression: merging fragments with different outsideBoundaryCondition values would
    # silently misrepresent one side of the merged surface (e.g. Ground blended into
    # Outdoors); the tool must report this as skipped, not guess which condition wins.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)

                frag_c = unwrap(await s.call_tool("create_surface", {
                    "name": "MixedFragC",
                    "vertices": [[0, 0, 0], [5, 0, 0], [5, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))
                assert frag_c["ok"] is True, frag_c
                frag_d = unwrap(await s.call_tool("create_surface", {
                    "name": "MixedFragD",
                    "vertices": [[5, 0, 0], [10, 0, 0], [10, 0, 3], [5, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Ground",
                }))
                assert frag_d["ok"] is True, frag_d

                result = unwrap(await s.call_tool("merge_coplanar_sliver_surfaces", {}))
                assert result["ok"] is True, result
                assert result["merged_group_count"] == 0, result
                assert result["skipped_group_count"] == 1, result
                skip = result["skipped"][0]
                assert sorted(skip["surfaces"]) == ["MixedFragC", "MixedFragD"], skip
                assert "mixed boundary conditions" in skip["reason"], skip

                walls_after = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": sp_name, "surface_type": "Wall", "max_results": 0,
                }))
                assert {"MixedFragC", "MixedFragD"} <= {su["name"] for su in walls_after["surfaces"]}, walls_after
    asyncio.run(_run())


@pytest.mark.integration
def test_merge_coplanar_sliver_surfaces_skips_fragments_with_subsurfaces():
    """A coplanar fragment carrying a window must not be merged away."""
    # Regression: merging a fragment with a subsurface would need to reparent that
    # window/door onto the merged survivor; this tool doesn't attempt that containment
    # check yet, so any group containing a subsurface must be skipped and reported, not
    # silently dropped along with the fragment that owned it.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)

                frag_e = unwrap(await s.call_tool("create_surface", {
                    "name": "WindowedFragE",
                    "vertices": [[0, 0, 0], [5, 0, 0], [5, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))
                assert frag_e["ok"] is True, frag_e
                frag_f = unwrap(await s.call_tool("create_surface", {
                    "name": "PlainFragF",
                    "vertices": [[5, 0, 0], [10, 0, 0], [10, 0, 3], [5, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))
                assert frag_f["ok"] is True, frag_f
                window = unwrap(await s.call_tool("create_subsurface", {
                    "name": "FragEWindow",
                    "vertices": [[1, 0, 1], [4, 0, 1], [4, 0, 2], [1, 0, 2]],
                    "parent_surface_name": "WindowedFragE",
                }))
                assert window["ok"] is True, window

                result = unwrap(await s.call_tool("merge_coplanar_sliver_surfaces", {}))
                assert result["ok"] is True, result
                assert result["merged_group_count"] == 0, result
                assert result["skipped_group_count"] == 1, result
                skip = result["skipped"][0]
                assert sorted(skip["surfaces"]) == ["PlainFragF", "WindowedFragE"], skip
                assert "subsurfaces" in skip["reason"], skip
    asyncio.run(_run())


@pytest.mark.integration
def test_merge_coplanar_sliver_surfaces_no_op_on_clean_model():
    """A model with no coplanar fragmentation should merge nothing."""
    # Regression: guards against the grouping/merge logic false-positiving on a normal,
    # already-clean model (one surface per side) and mutating geometry that never needed it.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())

                result = unwrap(await s.call_tool("merge_coplanar_sliver_surfaces", {}))
                assert result["ok"] is True, result
                assert result["merged_group_count"] == 0, result
                assert result["skipped_group_count"] == 0, result
    asyncio.run(_run())


# ---- Coincident vertex welding tests ----


def _box_vertices(east_x_offset=0.0):
    """A 4x4x3 box's 6 surfaces, with the east wall optionally shifted in x."""
    east_x = 4.0 + east_x_offset
    return {
        "Floor": [[0, 0, 0], [0, 4, 0], [4, 4, 0], [4, 0, 0]],
        "Ceiling": [[0, 0, 3], [4, 0, 3], [4, 4, 3], [0, 4, 3]],
        "WallSouth": [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]],
        "WallNorth": [[4, 4, 0], [0, 4, 0], [0, 4, 3], [4, 4, 3]],
        "WallWest": [[0, 4, 0], [0, 0, 0], [0, 0, 3], [0, 4, 3]],
        "WallEast": [[east_x, 0, 0], [east_x, 4, 0], [east_x, 4, 3], [east_x, 0, 3]],
    }


async def _build_box(session, space_name, east_x_offset=0.0):
    surface_types = {
        "Floor": "Floor", "Ceiling": "RoofCeiling", "WallSouth": "Wall",
        "WallNorth": "Wall", "WallWest": "Wall", "WallEast": "Wall",
    }
    for surface_name, vertices in _box_vertices(east_x_offset).items():
        res = unwrap(await session.call_tool("create_surface", {
            "name": f"{space_name}_{surface_name}",
            "vertices": vertices,
            "space_name": space_name,
            "surface_type": surface_types[surface_name],
            "outside_boundary_condition": "Outdoors",
        }))
        assert res["ok"] is True, res


@pytest.mark.integration
def test_weld_coincident_vertices_closes_corner_gap():
    """A wall shifted 1.5cm off its true corner should snap back and close the space."""
    # Regression: gbXML/Revit exports commonly leave sub-centimeter float noise between
    # vertices that are supposed to coincide (non-coplanar surfaces meeting at a corner —
    # a different defect from merge_coplanar_sliver_surfaces' same-plane fragmentation).
    # weld_coincident_vertices must close the resulting manifold gap. Which surface ends
    # up moved is arbitrary — getCombinedPoint()'s pool snaps whichever point it sees
    # second onto whichever it saw first for that corner, and space.surfaces() iteration
    # order isn't guaranteed, so this asserts the outcome that actually matters (the space
    # becomes enclosed) rather than which specific surface was rewritten.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                await _build_box(s, sp_name, east_x_offset=0.015)

                before = unwrap(await s.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert sp_name in [ns["space"] for ns in before["non_enclosed_spaces"]], before

                result = unwrap(await s.call_tool("weld_coincident_vertices", {}))
                assert result["ok"] is True, result
                assert result["skipped"] == [], result
                welded_names = [w["space"] for w in result["welded"]]
                assert sp_name in welded_names, result
                entry = next(w for w in result["welded"] if w["space"] == sp_name)
                assert len(entry["surfaces_modified"]) >= 1, entry
                assert entry["vertices_snapped"] >= 4, entry

                after = unwrap(await s.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert sp_name not in [ns["space"] for ns in after["non_enclosed_spaces"]], after
    asyncio.run(_run())


@pytest.mark.integration
def test_weld_coincident_vertices_leaves_large_offset_alone():
    """A wall shifted 5cm off (past WELD_TOLERANCE_M) must not get silently snapped."""
    # Regression: a gap larger than the weld tolerance is a real, distinct geometry
    # problem — snapping it anyway would misrepresent the model's actual (broken) shape
    # rather than report a false "fixed."
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                await _build_box(s, sp_name, east_x_offset=0.05)

                result = unwrap(await s.call_tool("weld_coincident_vertices", {}))
                assert result["ok"] is True, result
                welded_names = [w["space"] for w in result["welded"]]
                assert sp_name not in welded_names, result
    asyncio.run(_run())


@pytest.mark.integration
def test_weld_coincident_vertices_skips_degenerate_same_surface_collapse():
    """A surface whose own vertices are naturally within tolerance must not be corrupted."""
    # Regression: welding must not silently collapse two of a single surface's own
    # vertices onto the same point (a zero-length edge / degenerate polygon) — that's a
    # bug in the input surface (e.g. a hairline sliver), not something to paper over.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                thin = unwrap(await s.call_tool("create_surface", {
                    "name": "HairlineWall",
                    "vertices": [[0, 0, 0], [0.005, 0, 0], [0.005, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))
                assert thin["ok"] is True, thin

                result = unwrap(await s.call_tool("weld_coincident_vertices", {}))
                assert result["ok"] is True, result
                assert result["welded"] == [], result
                assert result["skipped_surface_count"] == 1, result
                skip = result["skipped"][0]
                assert skip["space"] == sp_name, skip
                assert skip["surface"] == "HairlineWall", skip
                assert "degenerate" in skip["reason"], skip
    asyncio.run(_run())


@pytest.mark.integration
def test_weld_coincident_vertices_no_op_on_clean_model():
    """A model with no vertex-level gaps should weld nothing."""
    # Regression: guards against the welding logic false-positiving on a normal,
    # already-clean model and mutating geometry that never needed it.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())

                result = unwrap(await s.call_tool("weld_coincident_vertices", {}))
                assert result["ok"] is True, result
                assert result["welded_space_count"] == 0, result
                assert result["skipped_surface_count"] == 0, result
    asyncio.run(_run())


# ---- Missing wall surface patching tests ----


@pytest.mark.integration
def test_patch_missing_surfaces_reconstructs_deleted_wall():
    """Delete one wall from an otherwise-clean box; confirm the tool rebuilds it."""
    # Regression: Space.polyhedron().edgesNotTwo() finds the deleted wall's 4 unpaired
    # edges tracing a single planar rectangle; patch_missing_surfaces must
    # reconstruct exactly that surface and leave the space enclosed afterward.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                unwrap(await s.call_tool("create_space_from_floor_print", {
                    "name": "PatchSpace",
                    "floor_vertices": [[0, 0], [10, 0], [10, 10], [0, 10]],
                    "floor_to_ceiling_height": 3.0,
                }))
                walls = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": "PatchSpace", "surface_type": "Wall", "max_results": 0,
                }))
                assert walls["count"] == 4, walls
                target_wall = walls["surfaces"][0]["name"]
                delete_result = unwrap(await s.call_tool(
                    "delete_object", {"object_name": target_wall, "object_type": "Surface"},
                ))
                assert delete_result["ok"] is True, delete_result

                baseline = unwrap(await s.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert "PatchSpace" in [ns["space"] for ns in baseline["non_enclosed_spaces"]], baseline

                result = unwrap(await s.call_tool("patch_missing_surfaces", {}))
                assert result["ok"] is True, result
                assert result["patched_count"] == 1, result
                assert result["skipped"] == [], result
                entry = result["patched"][0]
                assert entry["space"] == "PatchSpace", entry
                assert entry["surface_type"] == "Wall", entry
                assert entry["area_m2"] == pytest.approx(30.0, abs=0.01), entry
                # Regression: an unmatched patch is assumed Adiabatic, and the assumption
                # is now reported (boundary_condition_ambiguous) instead of being silent —
                # that silence was the actual review finding. Exposure must follow the
                # boundary condition: a Surface defaults to SunExposed/WindExposed and
                # nothing used to change it, which is incoherent against an adiabatic
                # outside face and becomes a live error (fictitious solar + wind on 100+
                # surfaces of a real fixture) if the surface is instead left Outdoors.
                #
                # Also guards the scope of the fallback pairing pass: PatchSpace is built
                # on top of the example model, so this patched wall IS coincident with
                # pre-existing example-model geometry. An earlier version of that pass
                # searched every surface in the model and paired them, silently converting
                # someone else's exterior wall into an interior boundary. It only ever
                # considers surfaces from the same patch run now, so this stays Adiabatic.
                assert entry["final_boundary_condition"] == "Adiabatic", entry
                assert entry["boundary_condition_ambiguous"] is True, entry
                assert result["ambiguous_boundary_condition_count"] == 1, result
                patched_surface = unwrap(await s.call_tool("get_surface_details", {
                    "surface_name": entry["new_surface_name"],
                }))
                assert patched_surface["surface"]["sun_exposure"] == "NoSun", patched_surface
                assert patched_surface["surface"]["wind_exposure"] == "NoWind", patched_surface

                after = unwrap(await s.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert "PatchSpace" not in [ns["space"] for ns in after["non_enclosed_spaces"]], after
    asyncio.run(_run())


@pytest.mark.integration
def test_patch_missing_surfaces_splits_non_planar_hole_into_two_facets():
    """Two adjacent walls deleted together trace one loop, but it isn't planar — split it."""
    # Regression: removing two walls that share a vertical edge (WallEast + WallNorth,
    # meeting at the box's far corner) leaves a single connected 6-edge loop of unpaired
    # edges (non-branching, consumes cleanly) — but the loop bends around the missing
    # corner and isn't flat. patch_missing_surfaces must recognize the bend and
    # split the loop into two planar facets via a chord (the shared vertical corner
    # edge), reconstructing both walls, rather than forcing one wrong flat patch or
    # giving up entirely.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                await _build_box(s, sp_name)
                for wall in ("WallEast", "WallNorth"):
                    delete_result = unwrap(await s.call_tool(
                        "delete_object",
                        {"object_name": f"{sp_name}_{wall}", "object_type": "Surface"},
                    ))
                    assert delete_result["ok"] is True, delete_result

                result = unwrap(await s.call_tool("patch_missing_surfaces", {}))
                assert result["ok"] is True, result
                assert result["skipped"] == [], result
                assert result["patched_count"] == 2, result
                total_area = sum(p["area_m2"] for p in result["patched"])
                # WallEast (4x3=12) + WallNorth (4x3=12): total reconstructed area should
                # match the two missing walls, not something distorted by a bad split.
                assert total_area == pytest.approx(24.0, abs=0.1), result

                after = unwrap(await s.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert sp_name not in [ns["space"] for ns in after["non_enclosed_spaces"]], after
    asyncio.run(_run())


@pytest.mark.integration
def test_patch_missing_surfaces_patches_multiple_disjoint_holes_independently():
    """Two opposite walls deleted leave two separate holes — patch each on its own."""
    # Regression: removing non-adjacent walls (WallEast + WallWest) leaves two disjoint
    # 4-edge rectangles among the unpaired edges — two independent connected components,
    # not one combined loop. patch_missing_surfaces must not require the whole
    # space's unpaired edges to form a single loop; each component is resolved on its
    # own, so both get reconstructed.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                await _build_box(s, sp_name)
                for wall in ("WallEast", "WallWest"):
                    delete_result = unwrap(await s.call_tool(
                        "delete_object",
                        {"object_name": f"{sp_name}_{wall}", "object_type": "Surface"},
                    ))
                    assert delete_result["ok"] is True, delete_result

                result = unwrap(await s.call_tool("patch_missing_surfaces", {}))
                assert result["ok"] is True, result
                assert result["skipped"] == [], result
                assert result["patched_count"] == 2, result
                components = {p["component"] for p in result["patched"]}
                assert components == {0, 1}, result

                after = unwrap(await s.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert sp_name not in [ns["space"] for ns in after["non_enclosed_spaces"]], after
    asyncio.run(_run())


@pytest.mark.integration
def test_patch_missing_surfaces_skips_same_space_overlap():
    """An edge shared by three surfaces is a same-space overlap, not a missing surface."""
    # Regression: patch_missing_surfaces must not mistake a duplicate/overlapping
    # edge (used 3+ times) for a missing-surface boundary (used exactly once) — that's a
    # different defect (see repair_and_validate_gbxml_geometry's overlapping_surfaces),
    # not something this tool attempts to fix.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                for i, (dx, dy) in enumerate([(1, 0), (0, 1), (-1, -1)]):
                    res = unwrap(await s.call_tool("create_surface", {
                        "name": f"Wing{i}",
                        "vertices": [[0, 0, 0], [dx, dy, 0], [dx, dy, 3], [0, 0, 3]],
                        "space_name": sp_name,
                        "surface_type": "Wall",
                        "outside_boundary_condition": "Outdoors",
                    }))
                    assert res["ok"] is True, res

                result = unwrap(await s.call_tool("patch_missing_surfaces", {}))
                assert result["ok"] is True, result
                assert result["patched_count"] == 0, result
                # Two independent reasons, not guessed away: the shared edge itself (used
                # 3+ times) is excluded from consideration as its own space-level finding,
                # and excluding it leaves the origin vertex at degree 3 (odd) among the
                # three wings' remaining edges — an unresolvable branch point, reported
                # separately rather than silently folded into the overlap finding.
                assert result["skipped_count"] == 2, result
                reasons = [sk["reason"] for sk in result["skipped"]]
                assert any(sk["space"] == sp_name for sk in result["skipped"]), result
                assert any("3+ times" in r for r in reasons), result
                assert any("branch point" in r for r in reasons), result
    asyncio.run(_run())


@pytest.mark.integration
def test_patch_missing_surfaces_no_op_on_clean_model():
    """A model with no missing surfaces should patch nothing."""
    # Regression: guards against the loop-tracing/reconstruction logic false-positiving
    # on a normal, already-enclosed model and mutating geometry that never needed it.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())

                result = unwrap(await s.call_tool("patch_missing_surfaces", {}))
                assert result["ok"] is True, result
                assert result["patched_count"] == 0, result
                assert result["skipped_count"] == 0, result
    asyncio.run(_run())


# ---- Overlapping surface trimming tests ----


@pytest.mark.integration
def test_trim_overlapping_surfaces_trims_partial_overlap():
    """Two coplanar walls with a genuine 2D overlap get trimmed to their non-overlap remainder."""
    # Regression: a wall exported once per neighboring room instead of split at the
    # boundary between them (shared-wall duplication) leaves two same-space
    # surfaces genuinely overlapping in area, not just touching along an edge.
    # trim_overlapping_surfaces must replace each with its own non-overlapping
    # remainder, not guess which one is "right." The space (just two overlapping walls,
    # nothing else) is trivially non-enclosed, satisfying the tool's scoping.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                wall_a = unwrap(await s.call_tool("create_surface", {
                    "name": "OverlapA",
                    "vertices": [[0, 0, 0], [3, 0, 0], [3, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))
                assert wall_a["ok"] is True, wall_a
                wall_b = unwrap(await s.call_tool("create_surface", {
                    "name": "OverlapB",
                    "vertices": [[1, 0, 0], [4, 0, 0], [4, 0, 3], [1, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))
                assert wall_b["ok"] is True, wall_b

                result = unwrap(await s.call_tool("trim_overlapping_surfaces", {}))
                assert result["ok"] is True, result
                assert result["skipped"] == [], result
                assert result["trimmed_count"] == 1, result
                entry = result["trimmed"][0]
                assert entry["space"] == sp_name, entry
                areas = sorted([entry["surface_1_remaining_area_m2"], entry["surface_2_remaining_area_m2"]])
                assert areas == [pytest.approx(3.0, abs=0.01), pytest.approx(3.0, abs=0.01)], entry
    asyncio.run(_run())


@pytest.mark.integration
def test_trim_overlapping_surfaces_removes_fully_contained_duplicate():
    """A small surface fully inside a bigger one is a pure duplicate — remove it, not the container."""
    # Regression: full containment is asymmetric, not a case for symmetric trimming —
    # the small surface is entirely redundant; the big one was never wrong and must come
    # out of this untouched, not carved a hole into.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                big = unwrap(await s.call_tool("create_surface", {
                    "name": "BigWall",
                    "vertices": [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))
                assert big["ok"] is True, big
                # Touches Big's own left edge (x=0) rather than floating fully in its
                # interior — keeps Big's own would-be remainder a simple notched polygon,
                # not an untested donut/hole topology (moot here since the container is
                # left untouched either way, but avoids relying on that at all).
                small = unwrap(await s.call_tool("create_surface", {
                    "name": "SmallDuplicateWall",
                    "vertices": [[0, 0, 1], [2, 0, 1], [2, 0, 2], [0, 0, 2]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))
                assert small["ok"] is True, small

                result = unwrap(await s.call_tool("trim_overlapping_surfaces", {}))
                assert result["ok"] is True, result
                assert result["skipped"] == [], result
                assert result["trimmed_count"] == 1, result
                entry = result["trimmed"][0]
                assert entry["space"] == sp_name, entry
                assert entry["removed"] == "SmallDuplicateWall", entry
                assert entry["kept_unchanged"] == "BigWall", entry

                remaining = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": sp_name, "surface_type": "Wall", "max_results": 0,
                }))
                assert remaining["count"] == 1, remaining
                assert remaining["surfaces"][0]["name"] == "BigWall", remaining
                assert remaining["surfaces"][0]["gross_area_m2"] == pytest.approx(12.0, abs=0.01), remaining
    asyncio.run(_run())


@pytest.mark.integration
def test_trim_overlapping_surfaces_no_op_when_no_non_enclosed_spaces_have_overlaps():
    """A clean, enclosed model should be left alone even if it isn't perfectly optimized."""
    # Regression: trim_overlapping_surfaces is scoped to spaces failing
    # isEnclosedVolume() — a coplanar sliver elsewhere existing peacefully alongside an
    # already-enclosed space must not be touched just because it exists.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())

                result = unwrap(await s.call_tool("trim_overlapping_surfaces", {}))
                assert result["ok"] is True, result
                assert result["trimmed_count"] == 0, result
                assert result["skipped_count"] == 0, result
    asyncio.run(_run())


@pytest.mark.integration
def test_trim_overlapping_surfaces_skips_mismatched_boundary_conditions():
    """Two overlapping walls with different boundary conditions must not be blended."""
    # Regression: overlapping in space does not make two surfaces interchangeable. The
    # tool used to trim any coincident-plane pair with no compatibility check at all, so
    # a shared-wall duplicate whose copy was still "Outdoors" could be blended against a
    # "Ground"-facing surface, silently misrepresenting one side. Must be reported as
    # skipped with a reason, and both surfaces must survive untouched.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                for surface_name, bc in (("BcWallOutdoors", "Outdoors"), ("BcWallGround", "Ground")):
                    x_offset = 0 if bc == "Outdoors" else 1
                    res = unwrap(await s.call_tool("create_surface", {
                        "name": surface_name,
                        "vertices": [
                            [x_offset, 0, 0], [x_offset + 3, 0, 0],
                            [x_offset + 3, 0, 3], [x_offset, 0, 3],
                        ],
                        "space_name": sp_name,
                        "surface_type": "Wall",
                        "outside_boundary_condition": bc,
                    }))
                    assert res["ok"] is True, res

                result = unwrap(await s.call_tool("trim_overlapping_surfaces", {}))
                assert result["ok"] is True, result
                assert result["trimmed_count"] == 0, result
                assert result["skipped_count"] == 1, result
                assert "mixed boundary conditions" in result["skipped"][0]["reason"], result

                after = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": sp_name, "surface_type": "Wall", "max_results": 0,
                }))
                assert after["count"] == 2, after
                assert all(
                    srf["gross_area_m2"] == pytest.approx(9.0, abs=0.01) for srf in after["surfaces"]
                ), after
    asyncio.run(_run())


@pytest.mark.integration
def test_trim_overlapping_surfaces_skips_surface_carrying_a_window():
    """A surface with a subsurface must not be trimmed or removed — its window would be lost."""
    # Regression: Surface is an OpenStudio ParentObject, so remove() cascades and deletes
    # child subsurfaces outright, and setVertices() on a shrinking parent leaves its
    # window stranded outside it. The tool previously did neither check, so a duplicate
    # fully containing a windowed wall silently destroyed the window. Both surfaces and
    # the window must survive, with the pair reported as skipped.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                host = unwrap(await s.call_tool("create_surface", {
                    "name": "WindowedWall",
                    "vertices": [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))
                assert host["ok"] is True, host
                win = unwrap(await s.call_tool("create_subsurface", {
                    "name": "TrimGuardWindow",
                    "vertices": [[1, 0, 1], [3, 0, 1], [3, 0, 2], [1, 0, 2]],
                    "parent_surface_name": "WindowedWall",
                    "subsurface_type": "FixedWindow",
                }))
                assert win["ok"] is True, win
                dupe = unwrap(await s.call_tool("create_surface", {
                    "name": "DuplicateOfWindowedWall",
                    "vertices": [[2, 0, 0], [5, 0, 0], [5, 0, 3], [2, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))
                assert dupe["ok"] is True, dupe

                result = unwrap(await s.call_tool("trim_overlapping_surfaces", {}))
                assert result["ok"] is True, result
                assert result["trimmed_count"] == 0, result
                assert result["skipped_count"] == 1, result
                assert "subsurfaces" in result["skipped"][0]["reason"], result

                walls_after = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": sp_name, "surface_type": "Wall", "max_results": 0,
                }))
                assert walls_after["count"] == 2, walls_after
                # Scoped to this wall — the example model this is built on has windows of
                # its own, so a model-wide listing would say nothing about whether THIS
                # window survived.
                subs_after = unwrap(await s.call_tool("list_subsurfaces", {
                    "surface_name": "WindowedWall", "max_results": 0,
                }))
                assert [sub["name"] for sub in subs_after["subsurfaces"]] == ["TrimGuardWindow"], subs_after
    asyncio.run(_run())


@pytest.mark.integration
def test_patch_missing_surfaces_skips_high_degree_branch_point():
    """A high-degree branch vertex is rejected immediately, not searched factorially."""
    # Regression: _try_branch_decomposition enumerated every perfect matching of a branch
    # vertex's incident edges — (deg-1)!! candidates, i.e. 654,729,075 at degree 20, each
    # costing O(edges) to trace. Nothing capped the degree, tool calls have no timeout,
    # and they run in a thread that cannot be cancelled, so one malformed imported model
    # could occupy a worker indefinitely. Exercised directly against the topology module
    # rather than through a model: building a degree-20 vertex out of real Surfaces would
    # obscure exactly the property under test, which is that the cap is enforced before
    # any enumeration starts.
    if not integration_enabled():
        pytest.skip("integration disabled")

    import math
    import time

    import openstudio

    from mcp_server.skills.geometry.edge_topology import MAX_BRANCH_DEGREE, resolve_component

    hub = openstudio.Point3d(0, 0, 0)
    degree = 20
    spokes = [
        (hub, openstudio.Point3d(math.cos(2 * math.pi * k / degree), math.sin(2 * math.pi * k / degree), 0))
        for k in range(degree)
    ]

    started = time.perf_counter()
    facets, reason, valid_count = resolve_component(spokes)
    elapsed = time.perf_counter() - started

    assert facets is None, facets
    assert valid_count == 0, valid_count
    assert f"degree {degree}" in reason, reason
    assert str(MAX_BRANCH_DEGREE) in reason, reason
    # The unbounded version would not have returned within the life of this test run;
    # a second is many orders of magnitude of headroom over the ~0.1ms the cap costs.
    assert elapsed < 1.0, f"took {elapsed:.3f}s — the degree cap is not being enforced"


@pytest.mark.integration
def test_merge_coplanar_sliver_surfaces_preserves_roof_normal():
    """A merged RoofCeiling must keep facing upward, not be flipped by the join."""
    # Regression: the winding helper reversed any polygon whose normal had z > 0, which is
    # the correct test only in an alignFace local frame. It was also applied to the joined
    # loops AFTER transforming them back to global coordinates, where both branches leave
    # a horizontal surface facing downward — silently inverting every merged ceiling and
    # roof. tilt_deg is the observable: 0 is upward-facing, 180 is inverted.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                fragments = {
                    "RoofNormalFragA": [[0, 0, 3], [10, 0, 3], [10, 6, 3], [0, 6, 3]],
                    "RoofNormalFragB": [[0, 6, 3], [10, 6, 3], [10, 10, 3], [0, 10, 3]],
                }
                for surface_name, vertices in fragments.items():
                    frag = unwrap(await s.call_tool("create_surface", {
                        "name": surface_name,
                        "vertices": vertices,
                        "space_name": sp_name,
                        "surface_type": "RoofCeiling",
                        "outside_boundary_condition": "Outdoors",
                    }))
                    assert frag["ok"] is True, frag

                before = unwrap(await s.call_tool("get_surface_details", {
                    "surface_name": "RoofNormalFragA",
                }))
                assert before["surface"]["tilt_deg"] == pytest.approx(0.0, abs=0.5), before

                result = unwrap(await s.call_tool("merge_coplanar_sliver_surfaces", {}))
                assert result["ok"] is True, result
                assert result["merged_group_count"] == 1, result

                merged = unwrap(await s.call_tool("list_surfaces", {
                    "space_name": sp_name, "surface_type": "RoofCeiling", "max_results": 0,
                }))
                assert merged["count"] == 1, merged
                assert merged["surfaces"][0]["gross_area_m2"] == pytest.approx(100.0, abs=0.01), merged
                after = unwrap(await s.call_tool("get_surface_details", {
                    "surface_name": merged["surfaces"][0]["name"],
                }))
                assert after["surface"]["tilt_deg"] == pytest.approx(0.0, abs=0.5), after
    asyncio.run(_run())


async def _build_open_box(session, space_name, x0, y0, width, depth, omit, height=3.0):
    """A box at an arbitrary origin/size with one face left out, so the space is open.

    The shared _build_box helper is fixed at 0..4 and always complete; these tests need
    two boxes at different origins, each missing the face they would share.
    """
    x1, y1 = x0 + width, y0 + depth
    faces = {
        "Floor": ([[x0, y0, 0], [x0, y1, 0], [x1, y1, 0], [x1, y0, 0]], "Floor"),
        "Ceiling": ([[x0, y0, height], [x1, y0, height], [x1, y1, height], [x0, y1, height]], "RoofCeiling"),
        "WallSouth": ([[x0, y0, 0], [x1, y0, 0], [x1, y0, height], [x0, y0, height]], "Wall"),
        "WallNorth": ([[x1, y1, 0], [x0, y1, 0], [x0, y1, height], [x1, y1, height]], "Wall"),
        "WallWest": ([[x0, y1, 0], [x0, y0, 0], [x0, y0, height], [x0, y1, height]], "Wall"),
        "WallEast": ([[x1, y0, 0], [x1, y1, 0], [x1, y1, height], [x1, y0, height]], "Wall"),
    }
    for face_name, (vertices, surface_type) in faces.items():
        if face_name == omit:
            continue
        res = unwrap(await session.call_tool("create_surface", {
            "name": f"{space_name}_{face_name}",
            "vertices": vertices,
            "space_name": space_name,
            "surface_type": surface_type,
            "outside_boundary_condition": "Outdoors",
        }))
        assert res["ok"] is True, res


@pytest.mark.integration
def test_patch_missing_surfaces_pairs_near_coincident_patches():
    """Two patches 5cm apart — too far for the SDK — get paired by the fallback."""
    # Regression: openstudio.model.matchSurfaces() compares vertices against an
    # internal, non-configurable tolerance of roughly 0.0125m, so two reconstructed
    # surfaces that are plainly the same partition but land a few centimetres apart
    # come back unmatched and were then assumed Adiabatic. Measured on the Austin
    # fixture, 6 of 107 "ambiguous" patches actually had a coincident counterpart in
    # another space. Here two adjacent boxes are offset by 0.05m and each is missing
    # the wall they share: both get patched, the SDK misses the pair, and the fallback
    # must join them so both report "Surface".
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                left, right = _unique_name("left"), _unique_name("right")
                for space_name in (left, right):
                    assert unwrap(await s.call_tool("create_space", {"name": space_name}))["ok"] is True
                await _build_open_box(s, left, 0.0, 0.0, 4.0, 4.0, omit="WallEast")
                await _build_open_box(s, right, 4.05, 0.0, 4.0, 4.0, omit="WallWest")

                result = unwrap(await s.call_tool("patch_missing_surfaces", {}))
                assert result["ok"] is True, result
                assert result["paired_by_fallback_count"] == 1, result
                pair = result["paired_by_fallback"][0]
                assert pair["overlap_fraction"] == pytest.approx(1.0, abs=0.01), pair
                assert {pair["space"], pair["paired_with_space"]} == {left, right}, pair

                patched_here = [e for e in result["patched"] if e["space"] in (left, right)]
                assert len(patched_here) == 2, patched_here
                for entry in patched_here:
                    assert entry["final_boundary_condition"] == "Surface", entry
                    assert entry["boundary_condition_ambiguous"] is False, entry
                    assert entry["paired_by_fallback"] is True, entry
    asyncio.run(_run())


@pytest.mark.integration
def test_patch_missing_surfaces_refuses_to_pair_mismatched_areas():
    """Two patches that merely overlap are left unpaired, not forced together."""
    # Regression: the fallback above must not become a blanket "pair anything coplanar."
    # On the Austin fixture a 1474 m2 floor plate overlaps a 1059 m2 one by 72% — two
    # genuinely different surfaces that matchSurfaces() was right to decline, where
    # forcing adjacency would invent an interzone pair with a 415 m2 area mismatch.
    # Same shape in miniature: a 12 m2 hole against a 6 m2 one, 50% of the larger, must
    # stay unpaired and fall through to the Adiabatic assumption.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique_name())
                big, small = _unique_name("big"), _unique_name("small")
                for space_name in (big, small):
                    assert unwrap(await s.call_tool("create_space", {"name": space_name}))["ok"] is True
                await _build_open_box(s, big, 0.0, 0.0, 4.0, 4.0, omit="WallEast")
                # Half the depth, so its missing west wall is 6 m2 against the other's 12.
                await _build_open_box(s, small, 4.05, 0.0, 4.0, 2.0, omit="WallWest")

                result = unwrap(await s.call_tool("patch_missing_surfaces", {}))
                assert result["ok"] is True, result
                assert result["paired_by_fallback_count"] == 0, result
                patched_here = [e for e in result["patched"] if e["space"] in (big, small)]
                assert len(patched_here) == 2, patched_here
                for entry in patched_here:
                    assert entry["final_boundary_condition"] == "Adiabatic", entry
                    assert entry["boundary_condition_ambiguous"] is True, entry
                    assert entry["paired_by_fallback"] is False, entry
    asyncio.run(_run())


# ---- set_surface_boundary_conditions ----


@pytest.mark.integration
def test_set_surface_boundary_conditions_derives_coherent_exposure():
    """Setting Adiabatic in bulk also forces NoSun/NoWind; Outdoors restores exposure."""
    # Regression: exposure has to follow the boundary condition. A Surface defaults to
    # SunExposed/WindExposed, so a bulk tool that changed only the boundary condition
    # would reproduce the exact defect this PR fixed in patch_missing_surfaces —
    # fictitious solar gain on surfaces that have no outdoor face.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                names = ["BcBatchWallA", "BcBatchWallB"]
                for idx, surface_name in enumerate(names):
                    y = idx * 2.0
                    assert unwrap(await s.call_tool("create_surface", {
                        "name": surface_name,
                        "vertices": [[0, y, 0], [4, y, 0], [4, y, 3], [0, y, 3]],
                        "space_name": sp_name,
                        "surface_type": "Wall",
                        "outside_boundary_condition": "Outdoors",
                    }))["ok"] is True

                result = unwrap(await s.call_tool("set_surface_boundary_conditions", {
                    "surface_names": names, "outside_boundary_condition": "Adiabatic",
                }))
                assert result["ok"] is True, result
                assert result["updated_count"] == 2, result
                assert result["exposure_derived"] is True, result
                assert result["sun_exposure"] == "NoSun", result
                for surface_name in names:
                    details = unwrap(await s.call_tool("get_surface_details", {
                        "surface_name": surface_name,
                    }))["surface"]
                    assert details["outside_boundary_condition"] == "Adiabatic", details
                    assert details["sun_exposure"] == "NoSun", details
                    assert details["wind_exposure"] == "NoWind", details

                back = unwrap(await s.call_tool("set_surface_boundary_conditions", {
                    "surface_names": names, "outside_boundary_condition": "Outdoors",
                }))
                assert back["ok"] is True, back
                restored = unwrap(await s.call_tool("get_surface_details", {
                    "surface_name": names[0],
                }))["surface"]
                assert restored["sun_exposure"] == "SunExposed", restored
                assert restored["wind_exposure"] == "WindExposed", restored
    asyncio.run(_run())


@pytest.mark.integration
def test_set_surface_boundary_conditions_explicit_exposure_wins():
    """An explicit exposure argument overrides the value derived from the condition."""
    # Validates: a shaded or sheltered exterior surface is a legitimate model, so the
    # derived default must be a default, not a rule.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                assert unwrap(await s.call_tool("create_surface", {
                    "name": "BcShadedWall",
                    "vertices": [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))["ok"] is True

                result = unwrap(await s.call_tool("set_surface_boundary_conditions", {
                    "surface_names": ["BcShadedWall"],
                    "outside_boundary_condition": "Outdoors",
                    "sun_exposure": "NoSun",
                }))
                assert result["ok"] is True, result
                assert result["exposure_derived"] is False, result
                details = unwrap(await s.call_tool("get_surface_details", {
                    "surface_name": "BcShadedWall",
                }))["surface"]
                assert details["outside_boundary_condition"] == "Outdoors", details
                assert details["sun_exposure"] == "NoSun", details
                # wind was not specified, so it follows the boundary condition
                assert details["wind_exposure"] == "WindExposed", details
    asyncio.run(_run())


@pytest.mark.integration
def test_set_surface_boundary_conditions_rejects_bad_input_without_mutating():
    """An unknown surface or invalid condition fails the whole batch, changing nothing."""
    # Regression: a partially-applied batch is worse than a rejected one — the caller
    # cannot tell which surfaces changed. Every name is resolved before anything is
    # written, so the real surface here must come out untouched.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                assert unwrap(await s.call_tool("create_surface", {
                    "name": "BcUntouchedWall",
                    "vertices": [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                    "outside_boundary_condition": "Outdoors",
                }))["ok"] is True

                missing = unwrap(await s.call_tool("set_surface_boundary_conditions", {
                    "surface_names": ["BcUntouchedWall", "NoSuchSurfaceAtAll"],
                    "outside_boundary_condition": "Adiabatic",
                }))
                assert missing["ok"] is False, missing
                assert missing["missing_surfaces"] == ["NoSuchSurfaceAtAll"], missing

                bad_value = unwrap(await s.call_tool("set_surface_boundary_conditions", {
                    "surface_names": ["BcUntouchedWall"],
                    "outside_boundary_condition": "Adiabatik",
                }))
                assert bad_value["ok"] is False, bad_value
                assert "Adiabatic" in bad_value["did_you_mean"], bad_value

                paired = unwrap(await s.call_tool("set_surface_boundary_conditions", {
                    "surface_names": ["BcUntouchedWall"],
                    "outside_boundary_condition": "Surface",
                }))
                assert paired["ok"] is False, paired
                assert "match_surfaces" in paired["error"], paired

                details = unwrap(await s.call_tool("get_surface_details", {
                    "surface_name": "BcUntouchedWall",
                }))["surface"]
                assert details["outside_boundary_condition"] == "Outdoors", details
                assert details["sun_exposure"] == "SunExposed", details
    asyncio.run(_run())


# ---- Window-to-wall ratio tests ----


@pytest.mark.integration
def test_set_window_to_wall_ratio():
    """Set 40% glazing on a wall, verify subsurface created."""
    # Validates: 40% WWR creates ~12m2 window on 30m2 wall
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                # Create a wall
                unwrap(await s.call_tool("create_surface", {
                    "name": "WWR_Wall",
                    "vertices": [[0, 0, 0], [10, 0, 0], [10, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                }))
                # Set 40% window-to-wall ratio
                res = unwrap(await s.call_tool("set_window_to_wall_ratio", {
                    "surface_name": "WWR_Wall",
                    "ratio": 0.4,
                }))
                assert res["ok"] is True
                assert res["num_subsurfaces"] >= 1
                assert res["ratio"] == pytest.approx(0.4)
                # Window area should be ~40% of wall (30 m² → ~12 m²)
                win_area = sum(sub["gross_area_m2"] for sub in res["subsurfaces"])
                assert 10 < win_area < 14

                # Independent query verification
                subs = unwrap(await s.call_tool("list_subsurfaces", {"max_results": 0}))
                assert subs["count"] >= 1
    asyncio.run(_run())


@pytest.mark.integration
def test_set_window_to_wall_ratio_custom_sill():
    """Set glazing with custom sill height."""
    # Validates: custom sill height parameter creates valid subsurface
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                unwrap(await s.call_tool("create_surface", {
                    "name": "Sill_Wall",
                    "vertices": [[0, 0, 0], [8, 0, 0], [8, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                }))
                res = unwrap(await s.call_tool("set_window_to_wall_ratio", {
                    "surface_name": "Sill_Wall",
                    "ratio": 0.3,
                    "sill_height_m": 1.2,
                }))
                assert res["ok"] is True
                assert res["num_subsurfaces"] >= 1

                subs = unwrap(await s.call_tool("list_subsurfaces", {"max_results": 0}))
                assert subs["count"] >= 1
    asyncio.run(_run())


@pytest.mark.integration
def test_set_window_to_wall_ratio_not_wall():
    """Floor surface should be rejected."""
    # Validates: WWR rejects Floor surface with "not Wall" error
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                unwrap(await s.call_tool("create_surface", {
                    "name": "MyFloor",
                    "vertices": [[0, 0, 0], [5, 0, 0], [5, 5, 0], [0, 5, 0]],
                    "space_name": sp_name,
                    "surface_type": "Floor",
                    "outside_boundary_condition": "Ground",
                }))
                res = unwrap(await s.call_tool("set_window_to_wall_ratio", {
                    "surface_name": "MyFloor",
                    "ratio": 0.3,
                }))
                assert res["ok"] is False
                assert "not Wall" in res["error"]
    asyncio.run(_run())


@pytest.mark.integration
def test_set_window_to_wall_ratio_invalid_ratio():
    """Ratio outside 0-1 should be rejected."""
    # Validates: WWR rejects ratio > 1.0 with ok:false
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                unwrap(await s.call_tool("create_surface", {
                    "name": "Ratio_Wall",
                    "vertices": [[0, 0, 0], [5, 0, 0], [5, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                }))
                res = unwrap(await s.call_tool("set_window_to_wall_ratio", {
                    "surface_name": "Ratio_Wall",
                    "ratio": 1.5,
                }))
                assert res["ok"] is False
    asyncio.run(_run())
