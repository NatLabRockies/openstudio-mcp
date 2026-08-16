"""Every geometry repair tool must verify its setVertices writes — requires OpenStudio (Docker).

Surface.setVertices() returns a bool, does not raise when it rejects a polygon, leaves the
old vertices fully intact, and reports its complaint to an OpenStudio logger this server
pins at Fatal (see stdout_suppression.py). A discarded return is therefore invisible in
every direction: the tool reports a mutation that never happened, and — worse at two of
these sites — acts on the assumption that it did.

Driven in-process rather than through the MCP server because these tests fault-inject
setVertices, and tests/test_geometry.py (which owns the behavioral coverage for these same
three tools) drives them through the stdio server subprocess, which monkeypatch cannot
reach. The real repair behavior stays covered there; this file covers only the write guards.

A rejection is not reachable through any of these tools today — each screens its polygon
with getArea() against a MIN_* threshold, and setVertices only refuses a polygon with fewer
than 3 vertices or no computable plane, which is the same |Newell| ~ 0 condition getArea
reports as zero. Measured on OpenStudio 3.11, rejection starts around 1e-5 m2 regardless of
aspect ratio, so the 0.01 thresholds in weld/merge hold ~1000x margin and
trim_overlapping_surfaces' MIN_REMAINDER_AREA_M2 = 0.0001 holds ~10x. These tests exist so
that margin is not the only thing standing between a rejected write and a false report.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import patch_set_vertices

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_OPENSTUDIO_INTEGRATION"),
        reason="requires OpenStudio (set RUN_OPENSTUDIO_INTEGRATION=1)",
    ),
]

ALWAYS_REJECT = lambda _original: lambda *_args: False  # noqa: E731


def _refuse_only_call(n: int):
    """A setVertices fake that lets every write through except the nth, which it refuses.

    Lets a test place the rejection at a precise point in a multi-write sequence — e.g.
    after the first side of a trim pair has already been rewritten.
    """
    def _factory(original):
        calls = []

        def _fake(self, vertices):
            calls.append(1)
            return False if len(calls) == n else original(self, vertices)

        return _fake
    return _factory


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


def _space_named(name: str):
    from mcp_server.model_manager import get_model

    return next(s for s in get_model().getSpaces() if s.nameString() == name)


# --- merge_coplanar_sliver_surfaces ----------------------------------------------------

def _build_split_ceiling(tmp_path: Path):
    """One space whose ceiling is two coplanar fragments — merge's target defect."""
    from mcp_server.skills.geometry.operations import create_space_from_floor_print, create_surface

    _load_empty_model(tmp_path)
    created = create_space_from_floor_print(
        name="MergeSpace",
        floor_vertices=[[0, 0], [10, 0], [10, 10], [0, 10]],
        floor_to_ceiling_height=3.0,
    )
    assert created["ok"] is True, created

    space = _space_named("MergeSpace")
    ceilings = [s for s in space.surfaces() if s.surfaceType() == "RoofCeiling"]
    assert len(ceilings) == 1, [s.nameString() for s in ceilings]
    ceilings[0].remove()

    # A is the larger fragment (60 m2 vs 40 m2), so it becomes the survivor and B is
    # what the tool would remove.
    for frag_name, x0, x1 in (("CeilingFragA", 0, 6), ("CeilingFragB", 6, 10)):
        frag = create_surface(
            name=frag_name,
            vertices=[[x0, 0, 3], [x1, 0, 3], [x1, 10, 3], [x0, 10, 3]],
            space_name="MergeSpace",
            surface_type="RoofCeiling",
            outside_boundary_condition="Outdoors",
        )
        assert frag["ok"] is True, frag
    return space


def test_merge_does_not_delete_fragments_when_the_survivor_rewrite_is_rejected(
    tmp_path, monkeypatch,
):
    # Regression: the survivor's setVertices return was discarded, and plan["others"] were
    # removed unconditionally on the next loop. A rejected write is silent and leaves the
    # survivor on its old fragment, so the tool destroyed the rest of the group against a
    # merge that never happened — and reported it as merged, with fragments_before: 2 and
    # surfaces_after: 1. This is the only one of the three sibling sites where a discarded
    # return loses geometry rather than merely misreporting, which is why the assertion
    # that matters is on the model, not the payload.
    from mcp_server.skills.geometry.merge_coplanar_sliver_surfaces import (
        merge_coplanar_sliver_surfaces,
    )

    space = _build_split_ceiling(tmp_path)
    before = sorted(s.nameString() for s in space.surfaces())

    patch_set_vertices(monkeypatch, space.surfaces()[0], ALWAYS_REJECT)

    result = merge_coplanar_sliver_surfaces()

    # Asserted before the payload, deliberately: the guarantee that matters here is that
    # no geometry was destroyed, so an unguarded regression should fail on the missing
    # fragment rather than on a report field.
    assert sorted(s.nameString() for s in space.surfaces()) == before
    ceilings = [s for s in space.surfaces() if s.surfaceType() == "RoofCeiling"]
    assert len(ceilings) == 2, [s.nameString() for s in ceilings]
    assert sum(float(s.grossArea()) for s in ceilings) == pytest.approx(100.0, abs=0.01)

    assert result["ok"] is True, result
    assert result["merged_group_count"] == 0, result
    assert result["merged"] == [], result
    assert result["skipped_group_count"] == 1, result
    entry = result["skipped"][0]
    assert "setVertices returned false" in entry["reason"], entry
    assert entry["space"] == "MergeSpace", entry
    assert sorted(entry["surfaces"]) == ["CeilingFragA", "CeilingFragB"], entry


# --- trim_overlapping_surfaces ---------------------------------------------------------

def _build_overlapping_walls(tmp_path: Path):
    """A non-enclosed space with two coplanar walls that genuinely overlap in area."""
    from mcp_server.skills.geometry.operations import create_surface
    from mcp_server.skills.spaces.operations import create_space

    _load_empty_model(tmp_path)
    created = create_space(name="TrimSpace")
    assert created["ok"] is True, created

    for wall_name, x0, x1 in (("OverlapA", 0, 3), ("OverlapB", 1, 4)):
        wall = create_surface(
            name=wall_name,
            vertices=[[x0, 0, 0], [x1, 0, 0], [x1, 0, 3], [x0, 0, 3]],
            space_name="TrimSpace",
            surface_type="Wall",
            outside_boundary_condition="Outdoors",
        )
        assert wall["ok"] is True, wall

    space = _space_named("TrimSpace")
    assert space.isEnclosedVolume() is False, "two walls alone must be non-enclosed"
    return space


def test_trim_changes_neither_side_when_the_first_write_is_rejected(tmp_path, monkeypatch):
    # Regression: both writes discarded their return. _prepare_remainder validates each side
    # before either is written precisely so a pair is trimmed completely or not at all, but
    # that only covers a validation failure — a rejected write left the same half-applied
    # state the split exists to prevent, reported as a clean trim.
    from mcp_server.skills.geometry.trim_overlapping_surfaces import trim_overlapping_surfaces

    space = _build_overlapping_walls(tmp_path)
    areas_before = sorted(round(float(s.grossArea()), 6) for s in space.surfaces())

    patch_set_vertices(monkeypatch, space.surfaces()[0], ALWAYS_REJECT)

    result = trim_overlapping_surfaces()

    assert result["ok"] is True, result
    assert result["trimmed_count"] == 0, result
    assert result["skipped_count"] == 1, result
    entry = result["skipped"][0]
    assert "surface_1's trimmed remainder" in entry["reason"], entry
    assert "neither side was changed" in entry["reason"], entry

    assert sorted(round(float(s.grossArea()), 6) for s in space.surfaces()) == areas_before


def test_trim_rolls_back_the_first_side_when_the_second_write_is_rejected(
    tmp_path, monkeypatch,
):
    # Regression: the half-applied case the module's own docstrings promise cannot happen.
    # With the first write landing and the second rejected, surface_1 must be restored so
    # the pair really is all-or-nothing, rather than the space being left half-trimmed and
    # reported as a clean trim.
    from mcp_server.skills.geometry.trim_overlapping_surfaces import trim_overlapping_surfaces

    space = _build_overlapping_walls(tmp_path)
    areas_before = sorted(round(float(s.grossArea()), 6) for s in space.surfaces())

    # Refuse only the second write, so the rollback that follows it can land.
    patch_set_vertices(monkeypatch, space.surfaces()[0], _refuse_only_call(2))

    result = trim_overlapping_surfaces()

    assert result["ok"] is True, result
    assert result["trimmed_count"] == 0, result
    assert result["skipped_count"] == 1, result
    entry = result["skipped"][0]
    assert "surface_2's trimmed remainder" in entry["reason"], entry
    assert "rolled back" in entry["reason"], entry

    # Rolled back means restored, not merely "not obviously worse" — both walls keep their
    # full pre-trim area, so no fragment of the trim survived.
    assert sorted(round(float(s.grossArea()), 6) for s in space.surfaces()) == areas_before


def test_trim_fails_the_run_when_the_rollback_itself_is_rejected(tmp_path, monkeypatch):
    # Regression: with the second write rejected AND its rollback refused, the space really
    # is left half-trimmed and nothing can undo it. That must not be reported as a skip
    # alongside ok True — a caller would read it as a survivable outcome and keep building
    # on damaged geometry. Same ruling as _restore_or_fail in paired_vertex_sync.py.
    from mcp_server.skills.geometry.trim_overlapping_surfaces import trim_overlapping_surfaces

    space = _build_overlapping_walls(tmp_path)

    # Only the first write lands; both the second and the rollback after it are refused.
    def _land_only_the_first(original):
        calls = []

        def _fake(self, vertices):
            calls.append(1)
            return original(self, vertices) if len(calls) == 1 else False

        return _fake

    patch_set_vertices(monkeypatch, space.surfaces()[0], _land_only_the_first)

    result = trim_overlapping_surfaces()

    assert result["ok"] is False, result
    assert "must be reloaded" in result["error"], result
    assert "half-trimmed" in result["error"], result
    assert result["trimmed_count"] == 0, result
    # Terminal, not a skip — no skipped list to read this off as recoverable.
    assert "skipped" not in result, result

    # The error is telling the truth: one side really did keep its trimmed remainder.
    areas = sorted(round(float(s.grossArea()), 6) for s in space.surfaces())
    assert areas != sorted([9.0, 9.0]), areas


# --- weld_coincident_vertices ----------------------------------------------------------

# A 4x4x3 box whose east wall is shifted 1.5cm out, inside WELD_TOLERANCE_M (0.02), so the
# weld has real work to do. Ported from test_geometry.py's _box_vertices.
_BOX = {
    "Floor": ("Floor", [[0, 0, 0], [0, 4, 0], [4, 4, 0], [4, 0, 0]]),
    "Ceiling": ("RoofCeiling", [[0, 0, 3], [4, 0, 3], [4, 4, 3], [0, 4, 3]]),
    "WallSouth": ("Wall", [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]]),
    "WallNorth": ("Wall", [[4, 4, 0], [0, 4, 0], [0, 4, 3], [4, 4, 3]]),
    "WallWest": ("Wall", [[0, 4, 0], [0, 0, 0], [0, 0, 3], [0, 4, 3]]),
    "WallEast": ("Wall", [[4.015, 0, 0], [4.015, 4, 0], [4.015, 4, 3], [4.015, 0, 3]]),
}


def _build_offset_box(tmp_path: Path):
    from mcp_server.skills.geometry.operations import create_surface
    from mcp_server.skills.spaces.operations import create_space

    _load_empty_model(tmp_path)
    created = create_space(name="WeldSpace")
    assert created["ok"] is True, created

    for surface_name, (surface_type, vertices) in _BOX.items():
        res = create_surface(
            name=f"Weld{surface_name}",
            vertices=vertices,
            space_name="WeldSpace",
            surface_type=surface_type,
            outside_boundary_condition="Outdoors",
        )
        assert res["ok"] is True, res

    space = _space_named("WeldSpace")
    assert space.isEnclosedVolume() is False, "the 1.5cm offset must leave the space open"
    return space


def test_weld_does_not_count_a_rejected_write_as_a_snapped_surface(tmp_path, monkeypatch):
    # Regression: the setVertices return was discarded, so a rejected write still appended
    # the surface to surfaces_modified and added its points to vertices_snapped — reporting
    # a weld that never happened while the corner gap it was closing survived, under ok
    # True. Unlike the merge and trim sites nothing is destroyed here; the damage is purely
    # a false report, which is exactly what makes it hard to notice.
    from mcp_server.skills.geometry.weld_coincident_vertices import weld_coincident_vertices

    space = _build_offset_box(tmp_path)
    vertices_before = {
        s.nameString(): [(v.x(), v.y(), v.z()) for v in s.vertices()] for s in space.surfaces()
    }

    patch_set_vertices(monkeypatch, space.surfaces()[0], ALWAYS_REJECT)

    result = weld_coincident_vertices()

    assert result["ok"] is True, result
    assert result["welded_space_count"] == 0, result
    assert result["welded"] == [], result
    assert result["skipped_surface_count"] >= 1, result
    assert all(
        "setVertices returned false" in entry["reason"] for entry in result["skipped"]
    ), result["skipped"]
    assert {entry["space"] for entry in result["skipped"]} == {"WeldSpace"}, result["skipped"]

    # No surface moved, so the gap the weld was closing is still there to be found.
    after = {
        s.nameString(): [(v.x(), v.y(), v.z()) for v in s.vertices()] for s in space.surfaces()
    }
    assert after == vertices_before
    assert space.isEnclosedVolume() is False
