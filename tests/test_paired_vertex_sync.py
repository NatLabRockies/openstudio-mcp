"""Tests for sync_paired_surface_vertices — requires OpenStudio (Docker).

Driven in-process rather than through the MCP server because the defect under test —
the two sides of an interior surface pair carrying different vertex counts — cannot be
created through any MCP tool. No tool sets vertices on an existing surface; the repair
tools that produce the defect in the field (weld_coincident_vertices,
merge_coplanar_sliver_surfaces) only do so incidentally, on geometry broken in specific
ways. Building the pair directly is what makes these assertions exact rather than
fixture-dependent. The end-to-end path through repair_and_validate_gbxml_geometry is
covered on the real Austin fixture in test_gbxml_import.py.
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

# Space A occupies x 0..10, space B x 10..20, both y 0..10 and 3 m tall, so the
# shared wall at x=10 is a single 10 x 3 = 30 m2 rectangle on each side.
SHARED_WALL_AREA_M2 = 30.0
# The polygon each test substitutes for the B side: same plane, 2 m tall instead of 3.
SHRUNK_WALL_AREA_M2 = 20.0


@pytest.fixture(autouse=True)
def _clear_model():
    from mcp_server.model_manager import clear_model
    clear_model()
    yield
    clear_model()


def _load_empty_model(tmp_path: Path) -> None:
    """Load a model with no geometry, so every count below comes from this test alone."""
    import openstudio

    from mcp_server.model_manager import load_model

    osm_path = tmp_path / "empty.osm"
    openstudio.model.Model().save(openstudio.toPath(str(osm_path)), True)
    load_model(osm_path)


def _build_adjacent_pair(tmp_path: Path):
    """Two adjacent spaces with their shared wall matched; returns (a_side, b_side)."""
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.operations import create_space_from_floor_print, match_surfaces

    _load_empty_model(tmp_path)

    for name, x0, x1 in (("SyncA", 0, 10), ("SyncB", 10, 20)):
        created = create_space_from_floor_print(
            name=name,
            floor_vertices=[[x0, 0], [x1, 0], [x1, 10], [x0, 10]],
            floor_to_ceiling_height=3.0,
        )
        assert created["ok"] is True, created

    matched = match_surfaces()
    assert matched["ok"] is True, matched

    model = get_model()
    paired = [
        s for s in model.getSurfaces()
        if s.outsideBoundaryCondition() == "Surface" and s.adjacentSurface().is_initialized()
    ]
    # Exactly one interior boundary exists, so anything the tests count afterward is
    # attributable to the pair they deliberately break.
    assert len(paired) == 2, [s.nameString() for s in paired]

    by_space = {s.space().get().nameString(): s for s in paired}
    assert set(by_space) == {"SyncA", "SyncB"}, sorted(by_space)
    assert by_space["SyncA"].grossArea() == pytest.approx(SHARED_WALL_AREA_M2, abs=1e-6)
    assert by_space["SyncB"].grossArea() == pytest.approx(SHARED_WALL_AREA_M2, abs=1e-6)
    return by_space["SyncA"], by_space["SyncB"]


def _shrink(surface, extra_vertex: bool) -> None:
    """Replace a side with a 20 m2 polygon in the same plane, optionally 5-sided.

    The extra point is collinear, so the vertex count changes without the area changing
    with it — that separates the two signals the code treats differently.
    """
    import openstudio

    points = [
        openstudio.Point3d(10, 0, 0),
        openstudio.Point3d(10, 10, 0),
        openstudio.Point3d(10, 10, 2),
    ]
    if extra_vertex:
        points.append(openstudio.Point3d(10, 5, 2))
    points.append(openstudio.Point3d(10, 0, 2))
    assert surface.setVertices(points) is True, "setVertices rejected the substitute polygon"


def _fragment_partner_side(b_side) -> None:
    """Leave B's side of the shared wall as a fragment of a wall A still spans whole.

    Reproduces the merged-vs-tiled case: B's wall becomes two stacked surfaces, only the
    lower of which stays paired with A's full-height wall, plus a collinear midpoint so the
    pair disagrees on vertex count without disagreeing on anything else. B stays enclosed,
    so any later break is attributable to the sync alone.
    """
    import openstudio

    b_space = b_side.space().get()

    def _at_height(vertices, low: float, high: float):
        return openstudio.Point3dVector(
            [openstudio.Point3d(v.x(), v.y(), low if v.z() == 0 else high) for v in vertices],
        )

    full = list(b_side.vertices())
    upper = openstudio.model.Surface(_at_height(full, 1.5, 3.0), b_space.model())
    upper.setName("SyncBUpperHalf")
    assert upper.setSpace(b_space) is True
    assert upper.surfaceType() == "Wall", upper.surfaceType()

    # A's side keeps the full 30 m2, so it wins on area and B's fragment is what gets rewritten.
    lower = list(_at_height(full, 0.0, 1.5))
    lower.insert(1, openstudio.Point3d(
        (lower[0].x() + lower[1].x()) / 2, (lower[0].y() + lower[1].y()) / 2,
        (lower[0].z() + lower[1].z()) / 2,
    ))
    assert b_side.setVertices(openstudio.Point3dVector(lower)) is True
    assert len(b_side.vertices()) == 5
    assert b_space.isEnclosedVolume() is True, "B must start closed for the guard to be meaningful"


def _patch_set_vertices(monkeypatch, surface, make_replacement) -> None:
    """Swap setVertices on whichever class in the SWIG MRO actually defines it.

    Patching the class rather than the instance is what makes this bite: the code under test
    walks model.getSurfaces() and gets fresh proxy objects, not the ones a test holds.
    `make_replacement` receives the original unbound function so a fake can delegate to it.
    """
    target = next(c for c in type(surface).__mro__ if "setVertices" in c.__dict__)
    monkeypatch.setattr(target, "setVertices", make_replacement(target.setVertices))


def test_choose_authoritative_index_prefers_larger_area():
    # Validates: area is the leading criterion, ahead of vertex count — the drifted side
    # is typically the one a weld shrank, so the larger polygon is the one to keep
    from mcp_server.skills.geometry.paired_vertex_sync import choose_authoritative_index

    # The smaller side has MORE vertices, so a vertex-count-first rule would pick it.
    assert choose_authoritative_index([("a", 4, 30.0), ("b", 5, 20.0)]) == 0
    assert choose_authoritative_index([("a", 5, 20.0), ("b", 4, 30.0)]) == 1


def test_choose_authoritative_index_tiebreaks_on_vertex_count_then_name():
    # Validates: equal areas fall through to the higher vertex count, and a full tie
    # falls through to the lexicographically smaller name, so the choice is total and
    # never depends on iteration order
    from mcp_server.skills.geometry.paired_vertex_sync import choose_authoritative_index

    assert choose_authoritative_index([("a", 4, 30.0), ("b", 5, 30.0)]) == 1
    assert choose_authoritative_index([("b", 4, 30.0), ("a", 4, 30.0)]) == 1
    assert choose_authoritative_index([("a", 4, 30.0), ("b", 4, 30.0)]) == 0


def test_sync_repairs_vertex_count_mismatch(tmp_path):
    # Validates: a pair whose sides carry 4 and 5 vertices is repaired by mirroring the
    # larger-area side onto the smaller, leaving both sides with the same vertex count
    # and the same area — the exact condition E+ GetSurfaceData checks before simulating
    from mcp_server.skills.geometry.paired_vertex_sync import sync_paired_surface_vertices

    a_side, b_side = _build_adjacent_pair(tmp_path)
    a_name, b_name = a_side.nameString(), b_side.nameString()
    _shrink(b_side, extra_vertex=True)
    assert len(b_side.vertices()) == 5

    result = sync_paired_surface_vertices()

    assert result["ok"] is True, result
    assert result["paired_vertex_mismatches_repaired_count"] == 1, result
    assert result["paired_vertex_mismatches_skipped_count"] == 0, result
    assert result["paired_area_mismatches_count"] == 0, result

    entry = result["paired_vertex_mismatches_repaired"][0]
    assert entry["surface"] == b_name, entry
    assert entry["space"] == "SyncB", entry
    assert entry["partner"] == a_name, entry
    assert entry["partner_space"] == "SyncA", entry
    assert entry["kept"] == a_name, entry
    assert entry["vertices_before"] == 5, entry
    assert entry["vertices_after"] == 4, entry
    assert entry["area_before_m2"] == pytest.approx(SHRUNK_WALL_AREA_M2, abs=1e-4), entry
    assert entry["area_after_m2"] == pytest.approx(SHARED_WALL_AREA_M2, abs=1e-4), entry

    # Assert the model itself, not just the report: both sides now describe one polygon.
    assert len(a_side.vertices()) == 4
    assert len(b_side.vertices()) == 4
    assert b_side.grossArea() == pytest.approx(SHARED_WALL_AREA_M2, abs=1e-6)
    # The rewritten side must still point back at its partner — a repair that silently
    # dropped the pairing would satisfy every count above while breaking the model.
    assert b_side.outsideBoundaryCondition() == "Surface"
    assert b_side.adjacentSurface().is_initialized()
    assert b_side.adjacentSurface().get().nameString() == a_name


def test_sync_skips_rewriting_a_side_that_carries_subsurfaces(tmp_path):
    # Validates: the side that would be rewritten is left alone when it holds windows or
    # doors, since they are positioned against the polygon it has and replacing that
    # polygon could strand them outside it — reported as skipped, and skipped pairs are
    # what keep repair_and_validate_gbxml_geometry's ok False
    from mcp_server.skills.geometry.operations import create_subsurface
    from mcp_server.skills.geometry.paired_vertex_sync import sync_paired_surface_vertices

    a_side, b_side = _build_adjacent_pair(tmp_path)
    b_name = b_side.nameString()

    window = create_subsurface(
        name="SyncBWindow",
        vertices=[[10, 2, 1], [10, 8, 1], [10, 8, 2], [10, 2, 2]],
        parent_surface_name=b_name,
    )
    assert window["ok"] is True, window

    # B is the smaller side, so B is the one the repair would rewrite.
    _shrink(b_side, extra_vertex=True)

    result = sync_paired_surface_vertices()

    assert result["ok"] is True, result
    assert result["paired_vertex_mismatches_repaired_count"] == 0, result
    assert result["paired_vertex_mismatches_skipped_count"] == 1, result
    assert result["paired_area_mismatches_count"] == 0, result

    entry = result["paired_vertex_mismatches_skipped"][0]
    assert entry["partner"] == b_name, entry
    assert entry["surface"] == a_side.nameString(), entry
    assert "subsurfaces" in entry["reason"], entry

    # Untouched: still mismatched, and the window is still on it.
    assert len(b_side.vertices()) == 5
    assert [s.nameString() for s in b_side.subSurfaces()] == ["SyncBWindow"]


def test_sync_reports_area_mismatch_without_reshaping(tmp_path):
    # Validates: sides that agree on vertex count but not on area are reported only.
    # E+ accepts them and matchSurfaces() has its own ~0.0125 m tolerance, so reshaping
    # on that weaker signal would be a guess — the geometry must come back unchanged
    from mcp_server.skills.geometry.paired_vertex_sync import sync_paired_surface_vertices

    a_side, b_side = _build_adjacent_pair(tmp_path)
    a_name, b_name = a_side.nameString(), b_side.nameString()
    _shrink(b_side, extra_vertex=False)
    assert len(b_side.vertices()) == 4

    result = sync_paired_surface_vertices()

    assert result["ok"] is True, result
    assert result["paired_vertex_mismatches_repaired_count"] == 0, result
    assert result["paired_vertex_mismatches_skipped_count"] == 0, result
    assert result["paired_area_mismatches_count"] == 1, result

    entry = result["paired_area_mismatches"][0]
    # Which side is reported as "surface" follows model iteration order, so pin the pair
    # rather than the roles.
    assert {entry["surface"], entry["partner"]} == {a_name, b_name}, entry
    assert sorted((entry["area_m2"], entry["partner_area_m2"])) == [
        pytest.approx(SHRUNK_WALL_AREA_M2, abs=1e-4),
        pytest.approx(SHARED_WALL_AREA_M2, abs=1e-4),
    ], entry

    assert b_side.grossArea() == pytest.approx(SHRUNK_WALL_AREA_M2, abs=1e-6)
    assert a_side.grossArea() == pytest.approx(SHARED_WALL_AREA_M2, abs=1e-6)


def test_sync_is_a_no_op_on_a_consistent_model(tmp_path):
    # Validates: a model whose pairs already agree reports nothing and rewrites nothing.
    # This runs on every repair_and_validate_gbxml_geometry call, so a false positive
    # here would reshape correct geometry on healthy models
    from mcp_server.skills.geometry.paired_vertex_sync import sync_paired_surface_vertices

    a_side, b_side = _build_adjacent_pair(tmp_path)
    a_before = [(v.x(), v.y(), v.z()) for v in a_side.vertices()]
    b_before = [(v.x(), v.y(), v.z()) for v in b_side.vertices()]

    result = sync_paired_surface_vertices()

    assert result["ok"] is True, result
    assert result["paired_vertex_mismatches_repaired"] == [], result
    assert result["paired_vertex_mismatches_skipped"] == [], result
    assert result["paired_area_mismatches"] == [], result

    assert [(v.x(), v.y(), v.z()) for v in a_side.vertices()] == a_before
    assert [(v.x(), v.y(), v.z()) for v in b_side.vertices()] == b_before


def test_sync_repair_is_idempotent(tmp_path):
    # Validates: running the repair twice reports one fix then none. The second call is
    # what proves the mirrored polygon actually satisfies the check that triggered the
    # first — a repair that left the pair inconsistent would report it again forever
    from mcp_server.skills.geometry.paired_vertex_sync import sync_paired_surface_vertices

    _a_side, b_side = _build_adjacent_pair(tmp_path)
    _shrink(b_side, extra_vertex=True)

    first = sync_paired_surface_vertices()
    assert first["paired_vertex_mismatches_repaired_count"] == 1, first

    second = sync_paired_surface_vertices()
    assert second["ok"] is True, second
    assert second["paired_vertex_mismatches_repaired_count"] == 0, second
    assert second["paired_vertex_mismatches_skipped_count"] == 0, second
    assert second["paired_area_mismatches_count"] == 0, second


def test_sync_repairs_across_spaces_with_different_origins(tmp_path):
    # Regression: Surface.vertices() are relative to the owning Space's origin, so copying
    # them verbatim across spaces displaces the polygon by the difference between the two
    # origins. gbXML imports happen to land identity transforms (their OS:Space origin
    # fields come through empty), which hid this — a model whose spaces carry origins
    # would have had the rewritten surface teleported instead of repaired. Space B is
    # given origin x=10 with its own vertices shifted to match, so it occupies exactly the
    # same world position as before: a verbatim copy puts the repaired wall at world x=20,
    # the correct conversion leaves it at x=10.
    import openstudio

    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.paired_vertex_sync import sync_paired_surface_vertices

    _load_empty_model(tmp_path)

    from mcp_server.skills.geometry.operations import create_space_from_floor_print, match_surfaces

    for name, x0, x1 in (("SyncA", 0, 10), ("SyncB", 10, 20)):
        assert create_space_from_floor_print(
            name=name,
            floor_vertices=[[x0, 0], [x1, 0], [x1, 10], [x0, 10]],
            floor_to_ceiling_height=3.0,
        )["ok"] is True

    model = get_model()
    b_space = next(s for s in model.getSpaces() if s.nameString() == "SyncB")
    # Re-express B in a frame whose origin is x=10, leaving it where it already is.
    for surface in b_space.surfaces():
        shifted = openstudio.Point3dVector(
            [openstudio.Point3d(v.x() - 10.0, v.y(), v.z()) for v in surface.vertices()],
        )
        assert surface.setVertices(shifted) is True
    assert b_space.setXOrigin(10.0) is True

    assert match_surfaces()["ok"] is True
    b_side = next(
        s for s in b_space.surfaces()
        if s.outsideBoundaryCondition() == "Surface" and s.adjacentSurface().is_initialized()
    )
    # In B's own frame the shared wall sits at local x=0 even though it is at world x=10.
    assert all(v.x() == pytest.approx(0.0, abs=1e-9) for v in b_side.vertices()), b_side.vertices()

    # Shrink B in ITS frame: same plane (local x=0), 2 m tall, with a collinear 5th point.
    shrunk = openstudio.Point3dVector([
        openstudio.Point3d(0, 0, 0), openstudio.Point3d(0, 10, 0), openstudio.Point3d(0, 10, 2),
        openstudio.Point3d(0, 5, 2), openstudio.Point3d(0, 0, 2),
    ])
    assert b_side.setVertices(shrunk) is True

    result = sync_paired_surface_vertices()
    assert result["ok"] is True, result
    assert result["paired_vertex_mismatches_repaired_count"] == 1, result

    world = b_space.transformation() * b_side.vertices()
    assert [v.x() for v in world] == [pytest.approx(10.0, abs=1e-9)] * len(world), [
        (v.x(), v.y(), v.z()) for v in world
    ]
    assert b_side.grossArea() == pytest.approx(SHARED_WALL_AREA_M2, abs=1e-6)


def test_sync_rolls_back_a_mirror_that_worsens_the_partner_space(tmp_path):
    # Regression: a vertex-count mismatch is not always a desync to mirror. When
    # merge_coplanar_sliver_surfaces has collapsed one space's wall into a single surface while
    # the neighbour's side is still tiled into fragments, the two sides legitimately differ, and
    # overwriting the fragment with the merged polygon leaves the neighbour overlapping itself.
    # Measured on the Austin fixture, mirroring unguarded cost three spaces (4 non-enclosed
    # became 7) and pushed patch_missing_surfaces off its known-good result (117/5/2/103 ->
    # 119/8/2/106). isEnclosedVolume() is too coarse to catch it — 67 of those 74 spaces are
    # already non-enclosed when the sync runs, so closed->open never fires — hence the guard
    # measures polyhedron().edgesNotTwo(True), the same metric patch_missing_surfaces works from.
    from mcp_server.skills.geometry.paired_vertex_sync import sync_paired_surface_vertices

    a_side, b_side = _build_adjacent_pair(tmp_path)
    b_space = b_side.space().get()
    _fragment_partner_side(b_side)

    result = sync_paired_surface_vertices()

    assert result["ok"] is True, result
    assert result["paired_vertex_mismatches_repaired_count"] == 0, result
    assert result["paired_vertex_mismatches_skipped_count"] == 1, result
    entry = result["paired_vertex_mismatches_skipped"][0]
    assert "unpaired edges" in entry["reason"], entry
    assert "rolled back" in entry["reason"], entry

    # Rolled back means byte-for-byte restored, not merely "not obviously worse".
    assert len(b_side.vertices()) == 5, b_side.vertices()
    assert b_side.grossArea() == pytest.approx(15.0, abs=1e-6)
    assert a_side.grossArea() == pytest.approx(SHARED_WALL_AREA_M2, abs=1e-6)
    assert b_space.isEnclosedVolume() is True


def test_rejected_write_is_reported_as_skipped_not_as_a_repair(tmp_path, monkeypatch):
    # Regression: setVertices() returns a bool and leaves the surface's old vertices in place
    # when it rejects a polygon — without raising, and with its only complaint going to an
    # OpenStudio logger this server pins at Fatal. An unchecked call therefore looks exactly
    # like a harmless mirror to the manifold guard (edge counts unchanged either way), so the
    # pair would be counted as repaired while the vertex-count mismatch that aborts E+ at
    # GetSurfaceData survives untouched, under ok True. Fault-injected because the guards
    # above the write make a real rejection unreachable today: MIN_VERTICES bounds the count
    # and the MIN_SYNCED_SURFACE_AREA_M2 check implies a computable plane. That coupling is
    # what this asserts the code no longer depends on.
    from mcp_server.skills.geometry.paired_vertex_sync import sync_paired_surface_vertices

    a_side, b_side = _build_adjacent_pair(tmp_path)
    _shrink(b_side, extra_vertex=True)
    assert len(b_side.vertices()) == 5

    _patch_set_vertices(monkeypatch, b_side, lambda _original: lambda *_args: False)

    result = sync_paired_surface_vertices()

    assert result["ok"] is True, result
    assert result["paired_vertex_mismatches_repaired_count"] == 0, result
    assert result["paired_vertex_mismatches_repaired"] == [], result
    assert result["paired_vertex_mismatches_skipped_count"] == 1, result
    entry = result["paired_vertex_mismatches_skipped"][0]
    assert "setVertices returned false" in entry["reason"], entry
    assert entry["partner"] == b_side.nameString(), entry

    # No repair means no rematch was needed, and the defect is still on the model for a
    # later pass to find rather than silently written off as fixed.
    assert result["rematched_surfaces"] is None, result
    assert len(a_side.vertices()) == 4, a_side.vertices()
    assert len(b_side.vertices()) == 5, b_side.vertices()


def test_rejected_rollback_fails_the_run_instead_of_reporting_a_clean_skip(tmp_path, monkeypatch):
    # Regression: the rollback in the manifold guard was also unchecked, and it is the more
    # dangerous of the two writes. A refused restore leaves the model holding the mirror this
    # function just decided was harmful, so reporting the pair as "rolled back and left
    # unchanged" would be a false statement about damaged geometry. It must end the run with
    # ok False and say the model needs reloading.
    from mcp_server.skills.geometry.paired_vertex_sync import sync_paired_surface_vertices

    a_side, b_side = _build_adjacent_pair(tmp_path)
    b_name = b_side.nameString()
    _fragment_partner_side(b_side)

    def _let_the_mirror_land_then_refuse_the_restore(original):
        calls = []

        def _fake(self, vertices):
            calls.append(1)
            return original(self, vertices) if len(calls) == 1 else False

        return _fake

    _patch_set_vertices(monkeypatch, b_side, _let_the_mirror_land_then_refuse_the_restore)

    result = sync_paired_surface_vertices()

    assert result["ok"] is False, result
    assert b_name in result["error"], result
    assert "must be reloaded" in result["error"], result
    assert result["paired_vertex_mismatches_repaired_count"] == 0, result
    # Terminal, not a skip — a caller must not read this as a survivable outcome.
    assert "paired_vertex_mismatches_skipped" not in result, result

    # The error is telling the truth: the harmful mirror really is still applied.
    assert b_side.grossArea() == pytest.approx(SHARED_WALL_AREA_M2, abs=1e-6), b_side.grossArea()
    assert len(b_side.vertices()) == len(a_side.vertices()), b_side.vertices()


def test_setvertices_rejection_modes_stay_inside_the_area_guard(tmp_path):
    # Validates: the two conditions under which OpenStudio rejects a polygon — fewer than
    # three vertices, and no computable plane — are both screened by the guards that run
    # before the write, and a rejection leaves the surface untouched rather than half-written.
    # getArea() is |Newell| / 2 and Plane construction fails only when |Newell| is ~0, so an
    # area above MIN_SYNCED_SURFACE_AREA_M2 implies a plane. Pinned here so an OpenStudio
    # upgrade that changes either behavior fails loudly instead of quietly invalidating the
    # reasoning behind the guard order.
    import openstudio

    from mcp_server.skills.geometry.paired_vertex_sync import MIN_SYNCED_SURFACE_AREA_M2

    a_side, _ = _build_adjacent_pair(tmp_path)
    original = list(a_side.vertices())

    too_few = openstudio.Point3dVector(original[:2])
    collinear = openstudio.Point3dVector([
        openstudio.Point3d(10, 0, 0), openstudio.Point3d(10, 5, 0), openstudio.Point3d(10, 10, 0),
    ])

    for name, polygon in (("too_few", too_few), ("collinear", collinear)):
        assert a_side.setVertices(polygon) is False, name
        # Rejected means untouched, which is exactly why an unchecked call is invisible.
        assert len(a_side.vertices()) == len(original), name
        assert a_side.grossArea() == pytest.approx(SHARED_WALL_AREA_M2, abs=1e-6), name

        area = openstudio.getArea(polygon)
        assert not area.is_initialized() or area.get() <= MIN_SYNCED_SURFACE_AREA_M2, name


def test_sync_reports_no_model_loaded_instead_of_raising():
    # Validates: the operation returns ok False rather than raising through MCP when no
    # model is loaded (operations contract — nothing raises through the tool layer)
    from mcp_server.skills.geometry.paired_vertex_sync import sync_paired_surface_vertices

    result = sync_paired_surface_vertices()
    assert result["ok"] is False, result
    assert "model" in result["error"].lower(), result
