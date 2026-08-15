"""Tests for find_missing_ground_contact — requires OpenStudio (Docker).

Driven in-process, like tests/test_paired_vertex_sync.py, because no MCP tool places a space at
a chosen elevation or sets a space origin, and both are exactly what the grade rule turns on.
Building the geometry directly is what makes every asserted count exact rather than
fixture-dependent. The end-to-end path through repair_and_validate_gbxml_geometry is covered on
the real basement fixture in test_gbxml_import.py.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_OPENSTUDIO_INTEGRATION"),
        reason="requires OpenStudio (set RUN_OPENSTUDIO_INTEGRATION=1)",
    ),
]


@pytest.fixture(autouse=True)
def _clear_model():
    from mcp_server.model_manager import clear_model
    clear_model()
    yield
    clear_model()


def _load_empty_model(tmp_path: Path) -> None:
    """A model with no geometry, so every count comes from the test alone."""
    import openstudio

    from mcp_server.model_manager import load_model

    osm_path = tmp_path / "empty.osm"
    openstudio.model.Model().save(openstudio.toPath(str(osm_path)), True)
    load_model(osm_path)


def _space_at(name: str, floor_z: float, height: float = 3.0):
    """A 10x10 space whose floor sits at world z=floor_z, built from explicit surfaces.

    create_space_from_floor_print() always extrudes upward from z=0, so it cannot place a floor
    below grade — the case this module exists for. Surfaces are created directly instead.
    """
    import openstudio

    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.operations import create_space_from_floor_print

    # Make the space at z=0, then move its surfaces bodily to the intended elevation. Surface
    # type is fixed at creation and survives the move, so the floor stays a Floor.
    created = create_space_from_floor_print(
        name=name, floor_vertices=[[0, 0], [10, 0], [10, 10], [0, 10]], floor_to_ceiling_height=height,
    )
    assert created["ok"] is True, created

    space = next(s for s in get_model().getSpaces() if s.nameString() == name)
    for surface in space.surfaces():
        moved = openstudio.Point3dVector(
            [openstudio.Point3d(v.x(), v.y(), v.z() + floor_z) for v in surface.vertices()],
        )
        assert surface.setVertices(moved) is True
    return space


def _surfaces_of(space, surface_type: str):
    return [s for s in space.surfaces() if s.surfaceType() == surface_type]


def test_ground_family_covers_every_sdk_ground_condition():
    # Validates: the "already connected" set is derived from the SDK and covers all ten
    # ground-coupled conditions, not just the literal "Ground". A `== "Ground"` check would
    # report every F/C-factor and Kiva Foundation surface as defective — the exact constructions
    # ASHRAE 90.1 baseline work uses
    import openstudio

    from mcp_server.skills.geometry.ground_contact import ground_boundary_conditions

    family = ground_boundary_conditions()
    assert "Ground" in family
    assert "Foundation" in family
    assert "GroundFCfactorMethod" in family
    assert "GroundBasementPreprocessorLowerWall" in family
    assert len(family) == 10, sorted(family)
    # Nothing outdoor-facing or interior may leak in.
    assert family.isdisjoint({"Outdoors", "Surface", "Adiabatic", "OtherSideCoefficients"})
    valid = set(openstudio.model.Surface.validOutsideBoundaryConditionValues())
    assert family <= valid, family - valid


def test_slab_at_grade_left_outdoors_is_reported(tmp_path):
    # Validates: a floor at z=0 still set Outdoors is the unambiguous case — it is reported by
    # name, and the name is what set_surface_boundary_conditions() takes
    from mcp_server.skills.geometry.ground_contact import find_missing_ground_contact

    _load_empty_model(tmp_path)
    space = _space_at("AtGrade", floor_z=0.0)
    floor = _surfaces_of(space, "Floor")[0]
    assert floor.outsideBoundaryCondition() == "Ground", floor.outsideBoundaryCondition()
    # fromFloorPrint() sets a z=0 floor to Ground already; force the defect under test.
    assert floor.setOutsideBoundaryCondition("Outdoors") is True

    result = find_missing_ground_contact()

    assert result["ok"] is True, result
    assert result["ground_contact_missing_count"] == 1, result
    assert result["ground_contact_missing"] == [floor.nameString()], result
    assert result["ground_surfaces_existing_count"] == 0, result
    assert result["partially_below_grade_count"] == 0, result
    assert result["adiabatic_below_grade_count"] == 0, result
    assert "ground_contact_missing_truncated" not in result, result


def test_slab_already_ground_is_not_reported(tmp_path):
    # Validates: the same slab, correctly set, produces no finding and is counted as existing
    # ground contact — the number that makes an implausible result visible next to the finding
    from mcp_server.skills.geometry.ground_contact import find_missing_ground_contact

    _load_empty_model(tmp_path)
    space = _space_at("AtGrade", floor_z=0.0)
    assert _surfaces_of(space, "Floor")[0].outsideBoundaryCondition() == "Ground"

    result = find_missing_ground_contact()

    assert result["ground_contact_missing_count"] == 0, result
    assert result["ground_surfaces_existing_count"] == 1, result
    # Clean models stay cheap: no name lists at all.
    assert "ground_contact_missing" not in result, result
    assert "partially_below_grade" not in result, result


def test_every_ground_family_condition_suppresses_the_finding(tmp_path):
    # Regression: a check written against the literal "Ground" would report a slab set to
    # GroundFCfactorMethod or Foundation as missing ground contact. Driven from the SDK's own
    # value list so a new condition in a future OpenStudio cannot silently start false-positiving
    from mcp_server.skills.geometry.ground_contact import (
        find_missing_ground_contact,
        ground_boundary_conditions,
    )

    _load_empty_model(tmp_path)
    space = _space_at("AtGrade", floor_z=0.0)
    floor = _surfaces_of(space, "Floor")[0]

    for condition in sorted(ground_boundary_conditions()):
        assert floor.setOutsideBoundaryCondition(condition) is True, condition
        result = find_missing_ground_contact()
        assert result["ground_contact_missing_count"] == 0, (condition, result)
        assert result["ground_surfaces_existing_count"] == 1, (condition, result)


def test_fully_buried_surfaces_are_actionable(tmp_path):
    # Validates: a space entirely below grade contributes its floor and all four walls to the
    # actionable list, while its ceiling — sitting exactly at grade but a RoofCeiling — is left
    # alone, since a ceiling below grade is not a ground connection
    from mcp_server.skills.geometry.ground_contact import find_missing_ground_contact

    _load_empty_model(tmp_path)
    buried = _space_at("Basement", floor_z=-3.0)  # floor at -3, walls -3..0, ceiling at 0
    for surface in buried.surfaces():
        assert surface.setOutsideBoundaryCondition("Outdoors") is True

    result = find_missing_ground_contact()

    buried_names = {s.nameString() for s in buried.surfaces() if s.surfaceType() in ("Floor", "Wall")}
    assert len(buried_names) == 5, buried_names
    assert result["ground_contact_missing_count"] == 5, result
    assert set(result["ground_contact_missing"]) == buried_names, result
    assert result["partially_below_grade_count"] == 0, result


def test_wall_crossing_grade_is_split_by_how_much_of_it_is_buried(tmp_path):
    # Regression: an "entirely below grade" rule finds nothing on a real basement model. Every
    # one of the 17 basement walls in tests/assets/2026_11Ja_path1.xml runs z=-3.05 to z=+0.91 —
    # 77% buried, and 0 of them fully buried — so the whole ground-connection defect in that
    # model would be reported as non-actionable. A wall mostly below grade is a basement wall;
    # one that merely dips below is not
    from mcp_server.skills.geometry.ground_contact import find_missing_ground_contact

    _load_empty_model(tmp_path)
    # 3 m tall walls: floor at -2 puts 2/3 below grade; floor at -1 puts 1/3 below.
    mostly = _space_at("MostlyBuried", floor_z=-2.0)
    barely = _space_at("BarelyBuried", floor_z=-1.0)
    for surface in list(mostly.surfaces()) + list(barely.surfaces()):
        assert surface.setOutsideBoundaryCondition("Outdoors") is True

    result = find_missing_ground_contact()

    mostly_walls = {s.nameString() for s in mostly.surfaces() if s.surfaceType() == "Wall"}
    barely_walls = {s.nameString() for s in barely.surfaces() if s.surfaceType() == "Wall"}
    # Both floors are fully below grade and actionable regardless; only the walls differ.
    floors = {
        s.nameString() for s in list(mostly.surfaces()) + list(barely.surfaces())
        if s.surfaceType() == "Floor"
    }
    assert len(floors) == 2, floors

    assert result["ground_contact_missing_count"] == 6, result
    assert set(result["ground_contact_missing"]) == mostly_walls | floors, result
    assert result["partially_below_grade_count"] == 4, result
    assert set(result["partially_below_grade"]) == barely_walls, result
    assert barely_walls.isdisjoint(set(result["ground_contact_missing"])), result


def test_elevated_space_reports_nothing(tmp_path):
    # Validates: a space entirely above grade produces no finding — the check must not sweep
    # every Outdoors wall in the model into a "fix me" list
    from mcp_server.skills.geometry.ground_contact import find_missing_ground_contact

    _load_empty_model(tmp_path)
    space = _space_at("Upper", floor_z=3.0)
    for surface in space.surfaces():
        assert surface.setOutsideBoundaryCondition("Outdoors") is True

    result = find_missing_ground_contact()

    assert result["ground_contact_missing_count"] == 0, result
    assert result["partially_below_grade_count"] == 0, result


def test_space_origin_is_applied_before_the_grade_test(tmp_path):
    # Regression: Surface.vertices() are relative to the owning Space's origin, so reading z off
    # them directly misplaces every surface in a space that carries one. Here the floor sits at
    # local z=0 in a space whose origin is z=3 — it is 3 m ABOVE grade in world coordinates and
    # must not be reported. A vertices()-only implementation reports it as a buried slab
    from mcp_server.skills.geometry.ground_contact import find_missing_ground_contact

    _load_empty_model(tmp_path)
    space = _space_at("Lifted", floor_z=0.0)
    assert space.setZOrigin(3.0) is True
    for surface in space.surfaces():
        assert surface.setOutsideBoundaryCondition("Outdoors") is True

    result = find_missing_ground_contact()

    assert result["ground_contact_missing_count"] == 0, result
    assert result["partially_below_grade_count"] == 0, result


def test_adiabatic_below_grade_is_counted_not_named(tmp_path):
    # Validates: a below-grade surface already set Adiabatic is a deliberate assumption
    # patch_missing_surfaces may have recorded, so it is counted but never listed — naming a
    # hundred of them would be noise in a response an agent has to read
    from mcp_server.skills.geometry.ground_contact import find_missing_ground_contact

    _load_empty_model(tmp_path)
    space = _space_at("Basement", floor_z=-3.0)
    for surface in space.surfaces():
        if surface.surfaceType() in ("Floor", "Wall"):
            assert surface.setOutsideBoundaryCondition("Adiabatic") is True

    result = find_missing_ground_contact()

    assert result["adiabatic_below_grade_count"] == 5, result
    assert result["ground_contact_missing_count"] == 0, result
    assert "ground_contact_missing" not in result, result


def test_actionable_list_caps_but_keeps_the_count_exact(tmp_path):
    # Validates: past GROUND_NAME_CAP the list is truncated and flagged, while the count stays
    # exact. The cap is deliberately far above the sibling 20-issue cap — these names are replayed
    # into one batched set_surface_boundary_conditions() call, and a short list would force
    # repeated diagnose-and-fix rounds
    import openstudio

    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.ground_contact import GROUND_NAME_CAP, find_missing_ground_contact

    _load_empty_model(tmp_path)
    space = _space_at("Basement", floor_z=-3.0)
    model = get_model()

    extra = GROUND_NAME_CAP + 5
    for i in range(extra):
        # Wound clockwise seen from above so the normal points down and OpenStudio types these
        # as Floor. The counterclockwise order makes them RoofCeiling, which this check ignores
        # by design — a ceiling below grade is not a ground connection.
        surface = openstudio.model.Surface(
            openstudio.Point3dVector([
                openstudio.Point3d(0, 1, -3), openstudio.Point3d(1, 1, -3),
                openstudio.Point3d(1, 0, -3), openstudio.Point3d(0, 0, -3),
            ]),
            model,
        )
        surface.setName(f"BuriedFloor{i}")
        assert surface.setSpace(space) is True
        assert surface.surfaceType() == "Floor", surface.surfaceType()
        assert surface.setOutsideBoundaryCondition("Outdoors") is True

    result = find_missing_ground_contact()

    # The basement's own floor is left Ground by fromFloorPrint, so only its 4 Outdoors walls
    # join the extras.
    assert result["ground_surfaces_existing_count"] == 1, result
    assert result["ground_contact_missing_count"] == extra + 4, result
    assert len(result["ground_contact_missing"]) == GROUND_NAME_CAP, result
    assert result["ground_contact_missing_truncated"] is True, result


def test_reports_no_model_loaded_instead_of_raising():
    # Validates: returns ok False rather than raising through MCP when no model is loaded
    # (operations contract — nothing raises through the tool layer)
    from mcp_server.skills.geometry.ground_contact import find_missing_ground_contact

    result = find_missing_ground_contact()
    assert result["ok"] is False, result
    assert "model" in result["error"].lower(), result
