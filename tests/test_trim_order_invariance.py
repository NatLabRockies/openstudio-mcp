"""Order-invariance guard for trim_overlapping_surfaces — requires OpenStudio (Docker).

Issue #134 reported this tool flaking between 1 trimmed / 18 skipped and 0/19 on the Austin
fixture, hypothesising that handle-ordered enumeration and an asymmetric compatibility check made
borderline pairs flip. Investigation found the canonicalization already present — name-sorted
spaces and surfaces, `already_handled` keyed by name — introduced by the very commit that created
the module (542591f, PR #124), so the module has never existed on develop without it. Four probes
against the real fixture (duplicate-name audit, auto-numbering sweep, whole-model clone with fresh
handles, and reading the compatibility check for symmetry) all came back deterministic.

What was missing was a test. The canonicalization could be removed and every existing test would
still pass, because the pinned fixture assertions only exercise one enumeration order. These tests
pin the property directly, and cheaply — the real fixture costs a ~20 minute import, so the
geometry here is synthetic and built so that name order and handle order DISAGREE.
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

# Three coplanar walls on x=0, each overlapping the next. Created in reverse-alphabetical order so
# handle order (creation order) is the exact reverse of name order — any code that enumerates by
# handle picks a different first pair than code that enumerates by name.
WALL_SPANS = (("C_wall", 8.0, 18.0), ("B_wall", 5.0, 15.0), ("A_wall", 0.0, 10.0))


@pytest.fixture(autouse=True)
def _clear_model():
    from mcp_server.model_manager import clear_model
    clear_model()
    yield
    clear_model()


def _build_overlapping_model(tmp_path: Path) -> Path:
    """A non-enclosed space holding three mutually overlapping coplanar walls.

    Non-enclosed on purpose: trim_overlapping_surfaces is scoped to spaces failing
    isEnclosedVolume(), so a closed space would be skipped entirely and the test would pass
    without exercising anything. A floor with no ceiling guarantees it.
    """
    import openstudio

    model = openstudio.model.Model()
    space = openstudio.model.Space(model)
    space.setName("TrimOrderSpace")

    floor = openstudio.model.Surface(
        openstudio.Point3dVector([
            openstudio.Point3d(0, 20, 0), openstudio.Point3d(20, 20, 0),
            openstudio.Point3d(20, 0, 0), openstudio.Point3d(0, 0, 0),
        ]),
        model,
    )
    floor.setName("TheFloor")
    assert floor.setSpace(space) is True

    for name, y0, y1 in WALL_SPANS:
        wall = openstudio.model.Surface(
            openstudio.Point3dVector([
                openstudio.Point3d(0, y0, 3), openstudio.Point3d(0, y0, 0),
                openstudio.Point3d(0, y1, 0), openstudio.Point3d(0, y1, 3),
            ]),
            model,
        )
        wall.setName(name)
        assert wall.setSpace(space) is True
        assert wall.surfaceType() == "Wall", (name, wall.surfaceType())

    assert space.isEnclosedVolume() is False, "space must be non-enclosed for trim to consider it"

    osm_path = tmp_path / "overlaps.osm"
    model.save(openstudio.toPath(str(osm_path)), True)
    return osm_path


def _trim_result(osm_path: Path) -> dict:
    from mcp_server.model_manager import load_model
    from mcp_server.skills.geometry.trim_overlapping_surfaces import trim_overlapping_surfaces

    load_model(osm_path)
    return trim_overlapping_surfaces()


def test_trim_picks_the_pair_by_name_order_not_creation_order(tmp_path):
    # Regression (#134): with three mutually overlapping surfaces, `already_handled` makes this
    # first-come-first-served — whichever pair is seen first is trimmed and the rest are skipped.
    # Which pair that is therefore reveals the enumeration order outright. Names sort
    # A_wall < B_wall < C_wall while creation (handle) order is the reverse, so handle-ordered
    # enumeration would trim C_wall/B_wall instead.
    result = _trim_result(_build_overlapping_model(tmp_path))

    assert result["ok"] is True, result
    assert result["trimmed_count"] == 1, result
    assert result["skipped_count"] == 2, result

    entry = result["trimmed"][0]
    assert (entry["surface_1"], entry["surface_2"]) == ("A_wall", "B_wall"), entry
    assert entry["space"] == "TrimOrderSpace", entry

    # The other two pairs are declined for being downstream of the handled one, not for some
    # unrelated incompatibility that would make this test pass for the wrong reason.
    for skipped in result["skipped"]:
        assert "already involved in another overlap" in skipped["reason"], skipped


def test_trim_is_unchanged_by_a_fresh_handle_assignment(tmp_path):
    # Regression (#134): the reported trigger was OpenStudio minting fresh UUIDs on every import,
    # changing getSurfaces() order. Cloning a model mints a whole new handle set while leaving the
    # geometry byte-identical, which reproduces that condition without a ~20 minute re-import.
    # Every stage of the result must be identical, not merely the counts.
    import openstudio

    osm_path = _build_overlapping_model(tmp_path)
    baseline = _trim_result(osm_path)

    source = openstudio.model.Model.load(openstudio.toPath(str(osm_path))).get()
    # clone(False) is newHandles; clone(True) is keepHandles and would perturb nothing. The
    # assertion below is what catches that mistake — it was made once already while investigating
    # this issue, and produced a false "deterministic" result.
    clone = source.clone(False).to_Model()
    original_handles = {str(s.handle()) for s in source.getSurfaces()}
    clone_handles = {str(s.handle()) for s in clone.getSurfaces()}
    assert clone_handles.isdisjoint(original_handles), "clone must not reuse the source's handles"

    clone_path = tmp_path / "overlaps_clone.osm"
    clone.save(openstudio.toPath(str(clone_path)), True)
    reordered = _trim_result(clone_path)

    assert reordered["trimmed_count"] == baseline["trimmed_count"], (baseline, reordered)
    assert reordered["skipped_count"] == baseline["skipped_count"], (baseline, reordered)
    assert [(e["surface_1"], e["surface_2"]) for e in reordered["trimmed"]] == \
           [(e["surface_1"], e["surface_2"]) for e in baseline["trimmed"]], (baseline, reordered)
    assert [e["surface_1_remaining_area_m2"] for e in reordered["trimmed"]] == \
           [e["surface_1_remaining_area_m2"] for e in baseline["trimmed"]], (baseline, reordered)


def test_incompatibility_reason_decides_the_same_way_in_either_operand_order(tmp_path):
    # Regression (#134): the issue hypothesised the compatibility check was asymmetric, so a
    # borderline pair would flip between trim and skip depending on which surface arrived first.
    # It is symmetric — set comparisons, and a subsurface check that fires if EITHER side has one
    # — and that must stay true, since the pair order is otherwise free to change.
    import openstudio

    from mcp_server.model_manager import get_model, load_model
    from mcp_server.skills.geometry.trim_overlapping_surfaces import _incompatibility_reason

    load_model(_build_overlapping_model(tmp_path))
    model = get_model()
    a = next(s for s in model.getSurfaces() if s.nameString() == "A_wall")
    b = next(s for s in model.getSurfaces() if s.nameString() == "B_wall")

    # Compatible both ways to start with.
    assert _incompatibility_reason(a, b) is None
    assert _incompatibility_reason(b, a) is None

    # Each guard must fire regardless of operand order. Only the decision is asserted, not the
    # message text, which legitimately names the surfaces in the order it was given them.
    assert a.setOutsideBoundaryCondition("Adiabatic") is True
    assert (_incompatibility_reason(a, b) is None) == (_incompatibility_reason(b, a) is None)
    assert _incompatibility_reason(a, b) is not None
    assert a.setOutsideBoundaryCondition("Outdoors") is True

    window = openstudio.model.SubSurface(
        openstudio.Point3dVector([
            openstudio.Point3d(0, 2, 2), openstudio.Point3d(0, 2, 1),
            openstudio.Point3d(0, 4, 1), openstudio.Point3d(0, 4, 2),
        ]),
        model,
    )
    assert window.setSurface(a) is True
    assert (_incompatibility_reason(a, b) is None) == (_incompatibility_reason(b, a) is None)
    assert _incompatibility_reason(a, b) is not None
