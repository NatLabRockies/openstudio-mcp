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
                # covered separately on the constructionless 11 Jay gbXML fixture.
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
