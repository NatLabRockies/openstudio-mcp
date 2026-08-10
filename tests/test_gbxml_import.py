"""Integration tests for import_gbxml (gbXML -> OSM via gbxml-to-openstudio measures).

Fixture: tests/assets/gbxml/25_SpacesOneZE.xml — a scaled-down copy of the
same fixture the upstream gbxml_import_advanced/gbxml_import_hvac measures use
in their own test suites (200_SpacesOneZE.xml). The gbXML.org "Standard Test
Model 2016" (schema conformance fixture) was tried first but isn't compatible
with the full pipeline: gbxml_import_advanced's schedule-building code crashes
on it (it lacks populated Schedule data the advanced/hvac measures expect —
that fixture is meant for basic schema-structure testing, not a full building
import).
"""
import asyncio
import os
import shutil
import uuid
from pathlib import Path

import pytest
from conftest import EPW_PATH, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

GBXML_PATH = "/repo/tests/assets/gbxml/25_SpacesOneZE.xml"
GBXML_PATH_11JAY = "/repo/tests/assets/2026_11Ja_path1.xml"
GBXML_PATH_AUSTIN = "/repo/tests/assets/gbxml/austin_office.xml"
GBXML_PATH_AUSTIN_SLIVERS = "/repo/tests/assets/gbxml/austin_apartment_slivers.xml"
AUSTIN_EPW_PATH = "/repo/tests/assets/USA_TX_Austin-Camp.Mabry.ANGB.722544_TMYx.2009-2023.epw"
AUSTIN_STAT_PATH = Path("/repo/tests/assets/USA_TX_Austin-Camp.Mabry.ANGB.722544_TMYx.2009-2023.stat")
AUSTIN_DDY_PATH = Path("/repo/tests/assets/USA_TX_Austin-Camp.Mabry.ANGB.722544_TMYx.2009-2023.ddy")
RUN_ROOT = Path(os.environ.get("OPENSTUDIO_MCP_RUN_ROOT", os.environ.get("OSMCP_RUN_ROOT", "/runs")))


def _unique_name(prefix: str = "pytest_gbxml") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_import_gbxml_basic():
    """Test translating a 25-space gbXML fixture with a user-supplied EPW."""
    # Validates: import_gbxml runs all 6 gbxml-to-openstudio measures via
    # --measures_only with zero errors/warnings, embeds the EPW's location
    # (ChangeBuildingLocation as the first step), and produces an OSM with
    # exactly the fixture's 25 spaces/zones, 228 surfaces
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    run_name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH, "epw_path": EPW_PATH, "run_name": run_name},
                ))
                assert result["ok"] is True, result
                assert result["osm_path"].endswith(".osm")
                assert result["total_errors"] == 0, result
                assert result["total_warnings"] == 0, result
                step_names = [s["measure"] for s in result["step_messages"]["steps"]]
                assert step_names == [
                    "ChangeBuildingLocation", "gbxml_import", "gbxml_import_advanced",
                    "gbxml_import_hvac", "set_simulation_control", "gbxml_postprocess",
                ], step_names

                load_result = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": result["osm_path"]},
                ))
                assert load_result["ok"] is True, load_result

                spaces_result = unwrap(await session.call_tool("list_spaces", {"max_results": 0}))
                assert spaces_result["ok"] is True
                assert spaces_result["count"] == 25, spaces_result

                zones_result = unwrap(await session.call_tool("list_thermal_zones", {"max_results": 0}))
                assert zones_result["count"] == 25, zones_result

                surfaces_result = unwrap(await session.call_tool("list_surfaces", {"max_results": 0}))
                assert surfaces_result["count"] == 228, surfaces_result

    asyncio.run(_run())


@pytest.mark.integration
def test_import_gbxml_missing_gbxml_file():
    """Test that a nonexistent gbXML path fails cleanly instead of crashing."""
    # Validates: missing gbxml_path returns ok=False with a specific error, no exception
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": "/inputs/does_not_exist.xml", "epw_path": EPW_PATH},
                ))
                assert result["ok"] is False
                assert result["error"] == "gbXML file not found: /inputs/does_not_exist.xml", result

    asyncio.run(_run())


@pytest.mark.integration
def test_import_gbxml_rejects_wrong_extension():
    """Test that a non-XML file extension is rejected before any measure runs."""
    # Validates: extension guard rejects e.g. a .osm passed as gbxml_path
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": "/repo/tests/assets/SystemD_baseline.osm", "epw_path": EPW_PATH},
                ))
                assert result["ok"] is False
                assert "Not a gbXML file" in result["error"], result

    asyncio.run(_run())


@pytest.mark.integration
def test_import_gbxml_missing_epw_companion():
    """Test that an EPW without a matching .stat file is rejected before any measure runs."""
    # Validates: an EPW copied without its .stat/.ddy siblings fails with a
    # clear "Missing companion .stat file" error instead of crashing inside
    # the ChangeBuildingLocation measure
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    orphan_dir = RUN_ROOT / _unique_name("orphan_epw")
    orphan_dir.mkdir(parents=True, exist_ok=True)
    orphan_epw = orphan_dir / "orphan.epw"
    shutil.copy2(EPW_PATH, orphan_epw)

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH, "epw_path": str(orphan_epw)},
                ))
                assert result["ok"] is False
                assert "Missing companion .stat file" in result["error"], result

    asyncio.run(_run())


@pytest.mark.integration
def test_repair_and_validate_gbxml_geometry_on_real_import():
    """Test repair_and_validate_gbxml_geometry's exact, reproducible output on the real fixture."""
    # Validates: repair_and_validate_gbxml_geometry runs match_surfaces() (156 cross-space
    # surfaces matched), finds zero same-space overlaps (confirming the
    # openstudio.intersects()-alone approach's false positives on edge-touching
    # coplanar surfaces, e.g. adjacent wall segments split at a window, are
    # correctly filtered by the true-overlap-area check), and finds 14 spaces
    # that fail Space.isEnclosedVolume() despite having both a Floor and a
    # RoofCeiling surface (small non-manifold gaps between wall surfaces — a
    # real, known limitation of this gbXML fixture's geometry, and exactly why
    # isEnclosedVolume() is a more robust check than a Floor/RoofCeiling
    # presence test alone)
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    run_name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                import_result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH, "epw_path": EPW_PATH, "run_name": run_name},
                ))
                assert import_result["ok"] is True, import_result

                result = unwrap(await session.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert result["ok"] is False, result
                assert result["space_count"] == 25, result
                assert result["surface_count"] == 228, result
                assert result["cross_space_surfaces_matched"] == 156, result
                assert result["overlapping_surfaces_count"] == 0, result
                assert result["overlapping_surfaces"] == [], result
                assert result["non_enclosed_spaces_count"] == 14, result
                flagged = {s["space"]: s for s in result["non_enclosed_spaces"]}
                assert set(flagged) == {
                    "aim2860", "aim4506", "aim2208", "aim1808", "aim2104", "aim1721",
                    "aim2156", "aim0426", "aim1583", "aim1895", "aim0513", "aim1634",
                    "aim0635", "aim0845",
                }, flagged
                assert flagged["aim2860"]["floor_area_m2"] == pytest.approx(7.456443749999997, rel=1e-9), flagged
                assert flagged["aim2860"]["has_floor"] is True, flagged
                assert flagged["aim2860"]["has_roofceiling"] is True, flagged

    asyncio.run(_run())


@pytest.mark.integration
def test_repair_and_validate_gbxml_geometry_detects_same_space_overlap():
    """Test that a deliberately injected duplicate Floor surface is flagged."""
    # Validates: a second Floor surface covering the same footprint in the same
    # space is detected as a same-space overlap (match_surfaces() cannot fix
    # this — it explicitly skips surface pairs within the same space)
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name("pytest_overlap")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_result = unwrap(await session.call_tool("create_example_osm", {"name": name}))
                assert create_result["ok"] is True, create_result
                load_result = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": create_result["osm_path"]},
                ))
                assert load_result["ok"] is True, load_result

                space_result = unwrap(await session.call_tool(
                    "create_space_from_floor_print",
                    {
                        "name": "OverlapTestSpace",
                        "floor_vertices": [[0, 0], [10, 0], [10, 10], [0, 10]],
                        "floor_to_ceiling_height": 3.0,
                    },
                ))
                assert space_result["ok"] is True, space_result

                dup_result = unwrap(await session.call_tool(
                    "create_surface",
                    {
                        "name": "DuplicateFloor",
                        "vertices": [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]],
                        "space_name": "OverlapTestSpace",
                        "surface_type": "Floor",
                    },
                ))
                assert dup_result["ok"] is True, dup_result

                result = unwrap(await session.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert result["ok"] is False, result
                assert result["overlapping_surfaces_count"] == 1, result
                issue = result["overlapping_surfaces"][0]
                assert issue["space"] == "OverlapTestSpace", issue
                assert "DuplicateFloor" in (issue["surface_1"], issue["surface_2"]), issue
                assert issue["same_orientation"] is False, issue  # floor faces down, duplicate faces up
                assert issue["overlap_area_m2"] == pytest.approx(100.0, abs=0.01), issue

    asyncio.run(_run())


@pytest.mark.integration
def test_repair_and_validate_gbxml_geometry_detects_non_enclosed_space():
    """Test that removing a space's Floor surface is detected as a non-enclosed volume."""
    # Validates: a space missing its Floor surface fails Space.isEnclosedVolume()
    # and is reported with has_floor=False
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name("pytest_nonenclosed")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_result = unwrap(await session.call_tool("create_example_osm", {"name": name}))
                assert create_result["ok"] is True, create_result
                load_result = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": create_result["osm_path"]},
                ))
                assert load_result["ok"] is True, load_result

                space_result = unwrap(await session.call_tool(
                    "create_space_from_floor_print",
                    {
                        "name": "NonEnclosedTestSpace",
                        "floor_vertices": [[0, 0], [8, 0], [8, 8], [0, 8]],
                        "floor_to_ceiling_height": 3.0,
                    },
                ))
                assert space_result["ok"] is True, space_result

                floors = unwrap(await session.call_tool(
                    "list_surfaces",
                    {"space_name": "NonEnclosedTestSpace", "surface_type": "Floor", "max_results": 0},
                ))
                assert floors["count"] == 1, floors
                floor_name = floors["surfaces"][0]["name"]

                delete_result = unwrap(await session.call_tool(
                    "delete_object", {"object_name": floor_name, "object_type": "Surface"},
                ))
                assert delete_result["ok"] is True, delete_result

                result = unwrap(await session.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert result["ok"] is False, result
                assert result["non_enclosed_spaces_count"] >= 1, result
                flagged = [s for s in result["non_enclosed_spaces"] if s["space"] == "NonEnclosedTestSpace"]
                assert len(flagged) == 1, result
                assert flagged[0]["has_floor"] is False, flagged[0]
                assert flagged[0]["has_roofceiling"] is True, flagged[0]

    asyncio.run(_run())


@pytest.mark.integration
def test_repair_and_validate_gbxml_geometry_detects_11jay_overlaps():
    """Test repair_and_validate_gbxml_geometry's exact output on the 11 Jay St residential fixture."""
    # Regression: 2026_11Ja_path1.xml (a Revit-exported residential floor plan)
    # produces 9 real same-space surface overlaps that match_surfaces() cannot
    # fix — walls that border more than one neighboring room along their run
    # (e.g. a closet wall bordering both the second-floor envelope and the
    # backstairwell) are exported as one full-length surface per neighbor
    # instead of being split at the point where the neighbor changes, so the
    # shared segment is duplicated (fully or partially) inside whichever space
    # is common to both copies. Confirmed via get_surface_details: e.g.
    # su-e-2-11-i-w-99 (gross area 1.2936 m^2) sits entirely inside the
    # larger, coplanar su-w-11-13-i-w-209 (6.7005 m^2), both in
    # sp-11mastercloset. This is upstream/source-geometry behavior the
    # detector correctly flags, not a bug in _surface_overlaps() itself.
    #
    # Regression: this fixture's wall-duplication defect also leaves 2 of its
    # 18 conditioned zones (WSHP-9, WSHP-17) with near-zero computed volume —
    # the same enclosure-corruption family as the 14 non-enclosed spaces
    # below, just caught at the ThermalZone level instead of the Space level.
    # That's a real extra warning on top of the climate zone (already valid
    # via the Boston .stat file, so climate_zone_source stays "gbxml_measure").
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    run_name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                import_result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH_11JAY, "epw_path": EPW_PATH, "run_name": run_name},
                ))
                assert import_result["ok"] is True, import_result
                assert import_result["total_errors"] == 0, import_result
                assert import_result["climate_zone"] == "5A", import_result
                assert import_result["climate_zone_source"] == "gbxml_measure", import_result
                assert import_result["conditioned_zone_count"] == 18, import_result
                assert import_result["zero_volume_zone_count"] == 2, import_result
                assert {z["zone"] for z in import_result["zero_volume_zones"]} == {"WSHP-9", "WSHP-17"}, import_result
                assert import_result["zero_volume_warning"] is not None, import_result
                assert import_result["total_warnings"] == 1, import_result

                load_result = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": import_result["osm_path"]},
                ))
                assert load_result["ok"] is True, load_result
                assert load_result["building_name"] == "Test Residence 1", load_result
                assert load_result["spaces"] == 18, load_result
                assert load_result["thermal_zones"] == 18, load_result

                result = unwrap(await session.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert result["ok"] is False, result
                assert result["space_count"] == 18, result
                assert result["surface_count"] == 292, result
                assert result["cross_space_surfaces_matched"] == 128, result

                overlaps = {(o["surface_1"], o["surface_2"]): o for o in result["overlapping_surfaces"]}
                assert result["overlapping_surfaces_count"] == 9, result
                assert len(overlaps) == 9, result
                expected = {
                    ("su-n-2-5-i-w-94 Reversed", "su-s-5-13-i-w-155"):
                        ("sp-5kitchen", 1.6548, True),
                    ("su-e-11-12-i-w-208", "su-w-2-11-i-w-100 Reversed"):
                        ("sp-11mastercloset", 0.3019, True),
                    ("su-e-2-11-i-w-99 Reversed", "su-w-11-13-i-w-209"):
                        ("sp-11mastercloset", 1.2936, True),
                    ("su-e-11-12-i-w-208 Reversed", "su-w-2-12-i-w-104 Reversed"):
                        ("sp-12mastercabinet", 0.3019, False),
                    ("su-e-2-13-i-w-105 Reversed", "su-w-11-13-i-w-209 Reversed"):
                        ("sp-13backstairwell", 1.2936, False),
                    ("su-n-2-13-i-w-107 Reversed", "su-s-5-13-i-w-155 Reversed"):
                        ("sp-13backstairwell", 1.6725, False),
                    ("su-e-2-11-i-w-99", "su-e-2-13-i-w-105"):
                        ("sp-2secondfloor", 1.2936, True),
                    ("su-n-2-13-i-w-107", "su-n-2-5-i-w-94"):
                        ("sp-2secondfloor", 1.6725, True),
                    ("su-w-2-11-i-w-100", "su-w-2-12-i-w-104"):
                        ("sp-2secondfloor", 0.2942, True),
                }
                assert set(overlaps) == set(expected), overlaps
                for key, (space, area, same_orientation) in expected.items():
                    issue = overlaps[key]
                    assert issue["space"] == space, issue
                    assert issue["overlap_area_m2"] == pytest.approx(area, abs=1e-4), issue
                    assert issue["same_orientation"] is same_orientation, issue

                assert result["non_enclosed_spaces_count"] == 14, result
                flagged = {s["space"]: s for s in result["non_enclosed_spaces"]}
                assert set(flagged) == {
                    "sp-9diningroomcloset", "sp-8hallway", "sp-6bathroom", "sp-5kitchen",
                    "sp-0basement", "sp-1firstfloor", "sp-11mastercloset", "sp-12mastercabinet",
                    "sp-4masterbedroom", "sp-13backstairwell", "sp-16bedroom", "sp-14livingroom",
                    "sp-2secondfloor", "sp-3diningroom",
                }, flagged
                assert flagged["sp-9diningroomcloset"]["floor_area_m2"] == pytest.approx(
                    0.6067729799999994, rel=1e-9), flagged
                assert flagged["sp-9diningroomcloset"]["has_floor"] is True, flagged
                assert flagged["sp-9diningroomcloset"]["has_roofceiling"] is False, flagged
                assert flagged["sp-0basement"]["floor_area_m2"] == pytest.approx(
                    90.72543765430825, rel=1e-9), flagged
                assert flagged["sp-0basement"]["has_roofceiling"] is True, flagged

    asyncio.run(_run())


@pytest.mark.integration
def test_repair_missing_roof_ceiling_on_11jay_fixture():
    """Test repair_missing_roof_ceiling's exact output on the 11 Jay St residential fixture."""
    # Regression: of the 3 spaces flagged has_floor=True/has_roofceiling=False on this
    # fixture, only sp-9diningroomcloset actually gets an auto-repaired flat ceiling.
    # sp-11mastercloset is correctly skipped for uneven wall heights and
    # sp-4masterbedroom for having 3 Floor surfaces instead of 1 — both symptomatic of
    # the same wall-duplication defect documented in
    # test_repair_and_validate_gbxml_geometry_detects_11jay_overlaps, not something this
    # targeted repair should guess its way through. The repaired ceiling gets
    # "Adiabatic" (no adjacent-space match found), and non_enclosed_spaces_count drops
    # from 14 to 13 — the overlap count (9) and cross_space_surfaces_matched (128) are
    # unaffected, confirming this repair is orthogonal to the overlap defect.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    run_name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                import_result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH_11JAY, "epw_path": EPW_PATH, "run_name": run_name},
                ))
                assert import_result["ok"] is True, import_result

                load_result = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": import_result["osm_path"]},
                ))
                assert load_result["ok"] is True, load_result

                result = unwrap(await session.call_tool("repair_missing_roof_ceiling", {}))
                assert result["ok"] is True, result
                assert result["repaired_count"] == 1, result
                repaired = result["repaired"][0]
                assert repaired["space"] == "sp-9diningroomcloset", repaired
                assert repaired["area_m2"] == pytest.approx(0.6068, abs=1e-4), repaired
                assert repaired["ceiling_z"] == pytest.approx(9.4488, abs=1e-4), repaired
                assert repaired["final_boundary_condition"] == "Adiabatic", repaired

                # Regression: a real Revit gbXML export carries per-surface
                # constructions and no default construction set, so a
                # synthesized surface with nothing assigned would otherwise
                # hit an EnergyPlus missing-construction fatal at simulation
                # time. The fixture has other real RoofCeiling surfaces with
                # constructions to borrow from, so this should resolve
                # cleanly with no warning.
                assert repaired["construction"] is not None, repaired
                assert repaired["construction_warning"] is None, repaired
                # Regression: the closet has no space above it, so Adiabatic
                # is the physically-correct default here — but the response
                # still flags it, since Adiabatic silently drops roof heat
                # transfer for a genuinely top-floor space in the general case.
                assert repaired["boundary_condition_warning"] is not None, repaired

                validate = unwrap(await session.call_tool("validate_model", {}))
                missing_construction_warnings = [
                    w for w in validate["warnings"] if "missing construction" in w
                ]
                assert not any(repaired["new_surface_name"] in w for w in missing_construction_warnings), validate

                skipped = {s["space"]: s["reason"] for s in result["skipped"]}
                assert skipped == {
                    "sp-11mastercloset": "uneven wall heights, cannot auto-repair a flat ceiling",
                    "sp-4masterbedroom": "expected exactly 1 Floor surface, found 3",
                }, skipped

                revalidate = unwrap(await session.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert revalidate["ok"] is False, revalidate
                assert revalidate["surface_count"] == 293, revalidate
                assert revalidate["cross_space_surfaces_matched"] == 128, revalidate
                assert revalidate["overlapping_surfaces_count"] == 9, revalidate
                assert revalidate["non_enclosed_spaces_count"] == 13, revalidate
                remaining = {s["space"] for s in revalidate["non_enclosed_spaces"]}
                assert "sp-9diningroomcloset" not in remaining, remaining
                assert remaining == {
                    "sp-8hallway", "sp-6bathroom", "sp-5kitchen", "sp-0basement",
                    "sp-1firstfloor", "sp-11mastercloset", "sp-12mastercabinet",
                    "sp-4masterbedroom", "sp-13backstairwell", "sp-16bedroom",
                    "sp-14livingroom", "sp-2secondfloor", "sp-3diningroom",
                }, remaining

    asyncio.run(_run())


@pytest.mark.integration
def test_import_gbxml_climate_zone_already_valid_from_measure():
    """Test that a .stat file the vendored measure's own regex already handles is left untouched."""
    # Validates: the Boston EPW's .stat file uses the older "Climate type ...**"
    # phrasing, so ChangeBuildingLocation's own regex resolves it — import_gbxml's
    # ensure_climate_zone() sees an already-valid ASHRAE value and reports
    # climate_zone_source="gbxml_measure" without touching the model or falling
    # through to the .stat re-parse / WMO lookup tiers.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    run_name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH, "epw_path": EPW_PATH, "run_name": run_name},
                ))
                assert result["ok"] is True, result
                assert result["climate_zone"] == "5A", result
                assert result["climate_zone_source"] == "gbxml_measure", result
                assert result["climate_zone_resolved"] is True, result
                assert "climate_zone_prior_invalid_value" not in result, result
                assert result["total_warnings"] == 0, result

    asyncio.run(_run())


@pytest.mark.integration
def test_import_gbxml_resolves_climate_zone_from_stat_file_on_austin_fixture():
    """Test the real-world garbage-climate-zone bug this feature guards against, plus the
    conditioned-zone volume fields on the same import (one large-fixture import, not two —
    the Austin fixture is 74 spaces vs. the 25-space Boston fixture used elsewhere in this
    file, so its cost is worth amortizing across both assertions)."""
    # Regression: the Austin fixture's .stat file (Climate.OneBuilding.org
    # format) uses "Climate Zone "2A" (ASHRAE Standard 169-2021)" — no
    # "type" label, no trailing "**". The vendored ChangeBuildingLocation
    # measure's own regex misses this entirely and silently leaves the
    # literal string "Lookup From Stat File" as the model's ASHRAE climate
    # zone (confirmed via its own registered warning, "Can't find ASHRAE
    # climate zone in stat file."). ensure_climate_zone() catches this
    # invalid placeholder and re-resolves "2A" directly from the same .stat
    # file with the broadened regex, rather than falling through to the
    # WMO/geographic lookup tier unnecessarily.
    #
    # Validates: the same import also reports conditioned_zone_count and
    # zero_volume_zone_count/zero_volume_zones/zero_volume_warning. On this
    # fixture the 74 conditioned zones all have real volume — the positive
    # "flag it" branch (zero/missing volume) is covered separately with
    # lightweight fakes in tests/test_gbxml_zone_checks.py, since this real
    # fixture happens not to reproduce that defect.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    run_name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH_AUSTIN, "epw_path": AUSTIN_EPW_PATH, "run_name": run_name},
                ))
                assert result["ok"] is True, result
                assert result["climate_zone"] == "2A", result
                assert result["climate_zone_source"] == "stat_file", result
                assert result["climate_zone_resolved"] is True, result
                assert result["climate_zone_prior_invalid_value"] == "Lookup From Stat File", result
                assert result["conditioned_zone_count"] == 74, result
                assert result["zero_volume_zone_count"] == 0, result
                assert result["zero_volume_zones"] == [], result
                assert result["zero_volume_warning"] is None, result
                assert result["total_errors"] == 0, result
                assert result["total_warnings"] == 1, result  # the measure's own "Can't find ASHRAE..." warning

                # Regression: ensure_climate_zone() used to mutate a Model
                # instance orphaned by an earlier model.save()/load_model()
                # reorder — the response said "2A" while both the saved OSM
                # and the session model still held the invalid placeholder.
                # Reload the saved file fresh and read the zone back off the
                # model itself, not the response, to catch that class of bug.
                reload_result = unwrap(await session.call_tool("load_osm_model", {"osm_path": result["osm_path"]}))
                assert reload_result["ok"] is True, reload_result
                weather_info = unwrap(await session.call_tool("get_weather_info", {}))
                assert weather_info["ashrae_climate_zone"] == "2A", weather_info

    asyncio.run(_run())


@pytest.mark.integration
def test_import_gbxml_falls_back_to_wmo_lookup_when_stat_file_unusable():
    """Test the WMO-hash fallback tier when the .stat file has no usable climate-zone line at all."""
    # Validates: with a .stat file that has its ASHRAE climate-zone line
    # replaced entirely (so neither the vendored measure's regex nor our own
    # broadened re-parse can match), ensure_climate_zone() falls through to
    # the WMO-station hash lookup and resolves the correct zone from the
    # EPW's own WMO number (722544 -> "2A" in the bundled reference table),
    # never fabricating a value it can't support with real data.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    run_dir = RUN_ROOT / _unique_name("austin_no_stat_zone")
    run_dir.mkdir(parents=True, exist_ok=True)
    mutated_epw = run_dir / "austin.epw"
    mutated_stat = run_dir / "austin.stat"
    mutated_ddy = run_dir / "austin.ddy"
    shutil.copy2("/repo/tests/assets/USA_TX_Austin-Camp.Mabry.ANGB.722544_TMYx.2009-2023.epw", mutated_epw)
    shutil.copy2(AUSTIN_DDY_PATH, mutated_ddy)
    stat_text = AUSTIN_STAT_PATH.read_text(encoding="utf-8", errors="replace")
    assert ' - Climate Zone "2A" (ASHRAE Standard 169-2021)' in stat_text
    mutated_text = stat_text.replace(
        ' - Climate Zone "2A" (ASHRAE Standard 169-2021)',
        " - Local Climate Descriptor 2A (no longer a recognizable ASHRAE zone line)",
    )
    mutated_stat.write_text(mutated_text, encoding="utf-8")

    run_name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH_AUSTIN, "epw_path": str(mutated_epw), "run_name": run_name},
                ))
                assert result["ok"] is True, result
                assert result["climate_zone"] == "2A", result
                assert result["climate_zone_source"] == "wmo_or_geographic_lookup", result
                assert result["climate_zone_resolved"] is True, result
                assert result["climate_zone_prior_invalid_value"] == "Lookup From Stat File", result

                # Regression: same persistence check as the stat-file test
                # above — the WMO/geographic fallback tier mutates the model
                # too, so it's equally exposed to the save/load-model reorder
                # bug if that ever regresses.
                reload_result = unwrap(await session.call_tool("load_osm_model", {"osm_path": result["osm_path"]}))
                assert reload_result["ok"] is True, reload_result
                weather_info = unwrap(await session.call_tool("get_weather_info", {}))
                assert weather_info["ashrae_climate_zone"] == "2A", weather_info

    asyncio.run(_run())


@pytest.mark.integration
def test_geometry_repair_pipeline_on_austin_apartment_fixture():
    """Real-world reproduction of both the sliver-fragmentation and corner-gap defects."""
    # Regression: tests/assets/gbxml/austin_apartment_slivers.xml is a 74-space Austin
    # apartment/retail/office building whose Revit gbXML export both (a) splits walls/
    # floors/ceilings into many same-space coplanar fragments per adjacent-room boundary
    # segment (confirmed by inspection: sp-4stair's ceiling alone is split into a 25.21 m2
    # piece plus a 0.084 m2 sliver), and (b) leaves sub-centimeter gaps between non-coplanar
    # surfaces meeting at corners. Every fragment area still sums correctly —
    # zero_volume_zone_count stays 0 — but the seams don't align to tight tolerance, so 69
    # of the 74 spaces fail isEnclosedVolume() even though each one already has both a
    # Floor and a RoofCeiling. match_surfaces() alone (run inside
    # repair_and_validate_gbxml_geometry) cannot fix either defect, since it only
    # reconciles surfaces between spaces, never within one.
    #
    # Honest result on this fixture, confirmed both ways (see tmp diagnostic run, not
    # committed): weld_coincident_vertices() alone does real, verified work (22 spaces,
    # real vertex snaps — see the synthetic tests in test_geometry.py) but doesn't flip
    # any space to enclosed by itself here (69 -> 69), because the spaces it touches have
    # *other* simultaneous non-manifold edges beyond what a 2cm weld closes.
    # merge_coplanar_sliver_surfaces() alone fixes 2 (69 -> 67: sp-4stair, sp-7stair —
    # the exact ceiling-fragmentation case this feature was built to diagnose). Running
    # both, in either order, lands at the same 67 with zero regressions — weld doesn't add
    # closures beyond what merge already achieves on this specific fixture, but it isn't
    # harmful either.
    #
    # A follow-up investigation into that remaining 67 (Space.polyhedron().edgesNotTwo(),
    # the same manifold check isEnclosedVolume() uses) found 394 of 397 bad edges are used
    # by exactly one surface — a genuinely missing surface, not a tolerance gap. 58 of the
    # 67 spaces have those unpaired edges chain into exactly one simple, planar loop (55 of
    # them vertical — missing partition walls), which patch_missing_wall_surfaces()
    # reconstructs directly from the loop. The remaining spaces (mostly the large open-plan
    # retail/restaurant rooms) have multiple or branching loops this tool doesn't attempt.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    run_name = _unique_name("austin_slivers")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                import_result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH_AUSTIN_SLIVERS, "epw_path": AUSTIN_EPW_PATH, "run_name": run_name},
                ))
                assert import_result["ok"] is True, import_result
                assert import_result["conditioned_zone_count"] == 74, import_result
                assert import_result["zero_volume_zone_count"] == 0, import_result

                reload_result = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": import_result["osm_path"]},
                ))
                assert reload_result["ok"] is True, reload_result

                baseline = unwrap(await session.call_tool("repair_and_validate_gbxml_geometry", {}))
                assert baseline["ok"] is False, baseline
                assert baseline["space_count"] == 74, baseline
                assert baseline["overlapping_surfaces_count"] == 0, baseline
                assert baseline["non_enclosed_spaces_count"] == 69, baseline

                weld_result = unwrap(await session.call_tool("weld_coincident_vertices", {}))
                assert weld_result["ok"] is True, weld_result
                assert weld_result["welded_space_count"] == 22, weld_result
                assert weld_result["skipped_surface_count"] == 8, weld_result

                merge_result = unwrap(await session.call_tool("merge_coplanar_sliver_surfaces", {}))
                assert merge_result["ok"] is True, merge_result
                # Regression: 28 groups collapse (up to 8 same-plane fragments down to 1
                # surface, e.g. sp-14retail's ceiling), only 3 genuinely skipped (real
                # mixed-boundary-condition/subsurface cases, not iteration-order artifacts
                # — see the two-phase plan/apply split in merge_coplanar_sliver_surfaces).
                assert merge_result["merged_group_count"] == 28, merge_result
                assert merge_result["skipped_group_count"] == 3, merge_result

                mid = unwrap(await session.call_tool("repair_and_validate_gbxml_geometry", {}))
                # 67, not fewer — see the honest accounting above. Weld contributes zero
                # *additional* closures beyond merge on this fixture, but causes zero
                # regressions either (verified space-by-space, not just by count, in the
                # diagnostic that produced these numbers).
                assert mid["non_enclosed_spaces_count"] == 67, mid

                patch_result = unwrap(await session.call_tool("patch_missing_wall_surfaces", {}))
                assert patch_result["ok"] is True, patch_result
                # Regression: 35 of the 67 still-broken spaces have their unpaired edges
                # form exactly one simple, planar loop and get reconstructed (mostly Wall,
                # but sp-1stair's missing surface is correctly auto-detected as
                # RoofCeiling — this isn't hardcoded to walls). The other 32 are honestly
                # skipped: 23 for a non-planar loop (a real 6+ vertex hole that a flat
                # patch would misrepresent), 7 for edges that don't form one simple loop
                # (branch points / multiple separate holes, e.g. sp-6retail, sp-3restuarant),
                # and 2 for a genuine same-space overlap (edges used 3+ times, a different
                # defect entirely). 35 + 32 == 67 — every originally-broken space gets a
                # definitive patch-or-skip decision, none fall through uncounted.
                assert patch_result["patched_count"] == 35, patch_result
                assert patch_result["skipped_count"] == 32, patch_result

                after = unwrap(await session.call_tool("repair_and_validate_gbxml_geometry", {}))
                # 69 -> 67 (weld+merge) -> 32 (patch): more than half of the original
                # non-enclosed spaces closed by purely automated, verified repair tools,
                # with the honest remainder (branching/multi-loop/overlap cases) reported
                # rather than guessed at.
                assert after["non_enclosed_spaces_count"] == 32, after

    asyncio.run(_run())
