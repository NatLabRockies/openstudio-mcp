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
    assert sr.get("ok") is True


@pytest.mark.integration
def test_list_surfaces():
    """Test listing all surfaces."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_result = unwrap(await session.call_tool("create_example_osm", {"name": name}))
                assert create_result.get("ok") is True

                load_result = unwrap(await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]}))
                assert load_result.get("ok") is True

                # List surfaces
                surfaces_result = unwrap(await session.call_tool("list_surfaces", {}))

                assert isinstance(surfaces_result, dict)
                assert surfaces_result.get("ok") is True
                assert surfaces_result["count"] > 0
                assert "name" in surfaces_result["surfaces"][0]
                assert "surface_type" in surfaces_result["surfaces"][0]
                assert "gross_area_m2" in surfaces_result["surfaces"][0]

    asyncio.run(_run())


@pytest.mark.integration
def test_list_subsurfaces():
    """Test listing all subsurfaces."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_result = unwrap(await session.call_tool("create_example_osm", {"name": name}))
                assert create_result.get("ok") is True

                load_result = unwrap(await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]}))
                assert load_result.get("ok") is True

                # List subsurfaces
                subsurfaces_result = unwrap(await session.call_tool("list_subsurfaces", {}))

                assert isinstance(subsurfaces_result, dict)
                assert subsurfaces_result.get("ok") is True
                # Example model may have 0 subsurfaces
                assert "count" in subsurfaces_result

    asyncio.run(_run())


@pytest.mark.integration
def test_surfaces_baseline():
    """Test surfaces in 10-zone baseline model."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_geo")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr).get("ok") is True

                sr = await session.call_tool("list_surfaces", {})
                sd = unwrap(sr)
                print("baseline surfaces:", sd)
                assert sd.get("ok") is True
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
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                # 10m wide x 3m tall wall
                surfs_before = unwrap(await s.call_tool("list_surfaces", {}))
                count_before = surfs_before["count"]

                res = unwrap(await s.call_tool("create_surface", {
                    "name": "TestWall",
                    "vertices": [[0, 0, 0], [10, 0, 0], [10, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                    "surface_type": "Wall",
                }))
                assert res.get("ok") is True
                surf = res["surface"]
                assert surf["surface_type"] == "Wall"
                assert surf["gross_area_m2"] > 29  # ~30 m²
                assert surf["num_vertices"] == 4

                # Independent query verification
                surfs_after = unwrap(await s.call_tool("list_surfaces", {}))
                assert surfs_after["count"] == count_before + 1
    asyncio.run(_run())


@pytest.mark.integration
def test_create_surface_floor():
    """Create a floor surface."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                surfs_before = unwrap(await s.call_tool("list_surfaces", {}))
                count_before = surfs_before["count"]

                res = unwrap(await s.call_tool("create_surface", {
                    "name": "TestFloor",
                    "vertices": [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]],
                    "space_name": sp_name,
                    "surface_type": "Floor",
                    "outside_boundary_condition": "Ground",
                }))
                assert res.get("ok") is True
                assert res["surface"]["surface_type"] == "Floor"

                surfs_after = unwrap(await s.call_tool("list_surfaces", {}))
                assert surfs_after["count"] == count_before + 1
    asyncio.run(_run())


@pytest.mark.integration
def test_create_surface_auto_type():
    """Omit surface_type — OS auto-detects from vertex tilt."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                sp_name = _unique_name("sp")
                await _setup_with_space(s, _unique_name(), sp_name)
                surfs_before = unwrap(await s.call_tool("list_surfaces", {}))
                count_before = surfs_before["count"]

                # Vertical polygon → should auto-detect as Wall
                res = unwrap(await s.call_tool("create_surface", {
                    "name": "AutoWall",
                    "vertices": [[0, 0, 0], [5, 0, 0], [5, 0, 3], [0, 0, 3]],
                    "space_name": sp_name,
                }))
                assert res.get("ok") is True
                assert res["surface"]["surface_type"] == "Wall"

                surfs_after = unwrap(await s.call_tool("list_surfaces", {}))
                assert surfs_after["count"] == count_before + 1
    asyncio.run(_run())


@pytest.mark.integration
def test_create_surface_invalid_space():
    """Bad space name should return error."""
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
                assert res.get("ok") is False
                assert "not found" in res["error"]
    asyncio.run(_run())


# ---- Subsurface creation tests ----


@pytest.mark.integration
def test_create_subsurface_window():
    """Create a window on a wall, verify in subsurface list."""
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
                assert res.get("ok") is True
                sub = res["subsurface"]
                assert sub["subsurface_type"] == "FixedWindow"
                assert sub["surface"] == "WallForWindow"

                # Independent query verification
                subs = unwrap(await s.call_tool("list_subsurfaces", {}))
                assert any(ss["name"] == "TestWindow" for ss in subs.get("subsurfaces", []))
    asyncio.run(_run())


@pytest.mark.integration
def test_create_subsurface_door():
    """Create a door on a wall."""
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
                assert res.get("ok") is True
                assert res["subsurface"]["subsurface_type"] == "Door"

                subs = unwrap(await s.call_tool("list_subsurfaces", {}))
                assert any(ss["name"] == "TestDoor" for ss in subs.get("subsurfaces", []))
    asyncio.run(_run())


@pytest.mark.integration
def test_create_subsurface_invalid_parent():
    """Bad parent surface name should return error."""
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
                assert res.get("ok") is False
                assert "not found" in res["error"]
    asyncio.run(_run())


# ---- Space from floor print test ----


@pytest.mark.integration
def test_create_space_from_floor_print():
    """Extrude a rectangular floor polygon, verify surfaces created."""
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
                assert res.get("ok") is True
                assert res["space_name"] == "ExtrudedSpace"
                # Rectangle → 4 walls + floor + ceiling = 6 surfaces
                assert res["num_surfaces"] == 6
                assert "Wall" in res["surface_types"]
                assert res["surface_types"]["Wall"] == 4

                # Independent query verification
                surfs = unwrap(await s.call_tool("list_surfaces", {}))
                ext_surfs = [sf for sf in surfs["surfaces"] if sf["space"] == "ExtrudedSpace"]
                assert len(ext_surfs) == 6
    asyncio.run(_run())


# ---- Surface matching tests ----


@pytest.mark.integration
def test_match_surfaces_adjacent_spaces():
    """Two adjacent spaces — shared wall should become interior after matching."""
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
                surfs_before = unwrap(await s.call_tool("list_surfaces", {}))
                new_surfs = [sf for sf in surfs_before["surfaces"]
                             if sf["space"] in ("Left", "Right")]
                interior_before = [sf for sf in new_surfs
                                   if sf["outside_boundary_condition"] == "Surface"]
                assert len(interior_before) == 0

                # Match
                res = unwrap(await s.call_tool("match_surfaces", {}))
                assert res.get("ok") is True
                assert res["matched_surfaces"] >= 2  # at least the shared wall pair

                # After matching: shared wall should be "Surface"
                surfs_after = unwrap(await s.call_tool("list_surfaces", {}))
                new_surfs_after = [sf for sf in surfs_after["surfaces"]
                                   if sf["space"] in ("Left", "Right")]
                interior_after = [sf for sf in new_surfs_after
                                  if sf["outside_boundary_condition"] == "Surface"]
                assert len(interior_after) >= 2  # pair of matched walls
    asyncio.run(_run())


@pytest.mark.integration
def test_match_surfaces_no_adjacency():
    """Single space — match_surfaces should succeed with 0 matched."""
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
                assert res.get("ok") is True
    asyncio.run(_run())


# ---- Window-to-wall ratio tests ----


@pytest.mark.integration
def test_set_window_to_wall_ratio():
    """Set 40% glazing on a wall, verify subsurface created."""
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
                assert res.get("ok") is True
                assert res["num_subsurfaces"] >= 1
                assert res["ratio"] == 0.4
                # Window area should be ~40% of wall (30 m² → ~12 m²)
                win_area = sum(sub["gross_area_m2"] for sub in res["subsurfaces"])
                assert 10 < win_area < 14

                # Independent query verification
                subs = unwrap(await s.call_tool("list_subsurfaces", {}))
                assert subs["count"] >= 1
    asyncio.run(_run())


@pytest.mark.integration
def test_set_window_to_wall_ratio_custom_sill():
    """Set glazing with custom sill height."""
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
                assert res.get("ok") is True
                assert res["num_subsurfaces"] >= 1

                subs = unwrap(await s.call_tool("list_subsurfaces", {}))
                assert subs["count"] >= 1
    asyncio.run(_run())


@pytest.mark.integration
def test_set_window_to_wall_ratio_not_wall():
    """Floor surface should be rejected."""
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
                assert res.get("ok") is False
                assert "not Wall" in res["error"]
    asyncio.run(_run())


@pytest.mark.integration
def test_set_window_to_wall_ratio_invalid_ratio():
    """Ratio outside 0-1 should be rejected."""
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
                assert res.get("ok") is False
    asyncio.run(_run())
