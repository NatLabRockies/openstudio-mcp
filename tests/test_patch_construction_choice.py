"""Construction assignment for reconstructed surfaces — requires OpenStudio (Docker).

Follow-up to #134. patch_missing_surfaces used to take the first surface of a matching *type* in
handle order, from the whole model, as its construction donor. Two defects in one line: handles
are UUIDs minted afresh on every import, so the choice was random; and filtering on type alone
meant a patched interior ceiling could draw from an exterior roof. On the Austin fixture the
RoofCeiling pool holds 92 interior ceilings and 13 exterior roofs, and the donor is shared by
every patch in a run, so roughly one run in eight put an R-20 cool-roof assembly on ~117 interior
surfaces — while also flipping trim_overlapping_surfaces between 1/18 and 0/19.

Synthetic and in-process: the real fixture costs a ~20 minute import, and every property here is
expressible in a two-space model.
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


def _named_construction(model, name: str):
    import openstudio

    construction = openstudio.model.Construction(model)
    construction.setName(name)
    return construction


def _space(model, name: str, x0: float, x1: float):
    """A 10 m deep, 3 m tall box spanning x0..x1, built from explicit surfaces."""
    import openstudio

    space = openstudio.model.Space(model)
    space.setName(name)
    faces = {
        "floor": [(x0, 0, 0), (x1, 0, 0), (x1, 10, 0), (x0, 10, 0)],
        "ceiling": [(x0, 10, 3), (x1, 10, 3), (x1, 0, 3), (x0, 0, 3)],
        "south": [(x0, 0, 3), (x1, 0, 3), (x1, 0, 0), (x0, 0, 0)],
        "north": [(x1, 10, 3), (x0, 10, 3), (x0, 10, 0), (x1, 10, 0)],
        "west": [(x0, 10, 3), (x0, 0, 3), (x0, 0, 0), (x0, 10, 0)],
        "east": [(x1, 0, 3), (x1, 10, 3), (x1, 10, 0), (x1, 0, 0)],
    }
    made = {}
    for face, points in faces.items():
        surface = openstudio.model.Surface(
            openstudio.Point3dVector([openstudio.Point3d(*p) for p in points]), model,
        )
        surface.setName(f"{name}_{face}")
        assert surface.setSpace(space) is True
        made[face] = surface
    return space, made


def _load(model, tmp_path: Path, stem: str = "m") -> None:
    import openstudio

    from mcp_server.model_manager import load_model

    path = tmp_path / f"{stem}.osm"
    model.save(openstudio.toPath(str(path)), True)
    load_model(path)


def _new_model():
    import openstudio
    return openstudio.model.Model()


def test_a_paired_patch_takes_its_partners_construction(tmp_path):
    # Validates: when the reconstructed surface ends up matched to a real partner, the two sides
    # are the same physical assembly, so the partner's construction is used outright rather than
    # any heuristic. A decoy of the same surface type carrying a different construction sits in
    # the model to prove the choice is not just "first wall we found".
    from mcp_server.skills.geometry.patch_missing_surfaces import patch_missing_surfaces

    model = _new_model()
    _left, left_faces = _space(model, "Left", 0, 10)
    _right, right_faces = _space(model, "Right", 10, 20)

    partner_construction = _named_construction(model, "PartnerAssembly")
    decoy = _named_construction(model, "DecoyAssembly")
    for surface in list(left_faces.values()) + list(right_faces.values()):
        surface.setConstruction(decoy)
    # The surviving side of the shared partition carries the construction the patch should copy.
    right_faces["west"].setConstruction(partner_construction)
    # Punch the hole: Left loses its side of the shared partition.
    left_faces["east"].remove()

    _load(model, tmp_path)
    result = patch_missing_surfaces()

    assert result["ok"] is True, result
    assert result["patched_count"] == 1, result
    entry = result["patched"][0]
    assert entry["space"] == "Left", entry
    assert entry["construction_source"] == "partner", entry
    assert entry["construction"] == "PartnerAssembly", entry


def test_an_unpaired_patch_prefers_its_own_boundary_condition_over_another(tmp_path):
    # Regression (#134): the donor pool was filtered by surface type alone, so an interior
    # surface could inherit an exterior assembly. An unpaired patch is set Adiabatic, so it must
    # prefer an existing Adiabatic wall over an Outdoors one even though both are Walls.
    from mcp_server.skills.geometry.patch_missing_surfaces import patch_missing_surfaces

    model = _new_model()
    _space_obj, faces = _space(model, "Solo", 0, 10)

    exterior = _named_construction(model, "ExteriorAssembly")
    interior = _named_construction(model, "InteriorAssembly")
    for surface in faces.values():
        surface.setOutsideBoundaryCondition("Outdoors")
        surface.setConstruction(exterior)
    # One adiabatic wall, the only surface sharing the patch's eventual boundary condition.
    # Deliberately the LAST wall in name order (north < south < west once east is removed), so a
    # type-only donor would reach Solo_north/ExteriorAssembly first and this test would catch it.
    # Picking an alphabetically-early donor here would let the old behaviour pass by luck.
    faces["west"].setOutsideBoundaryCondition("Adiabatic")
    faces["west"].setConstruction(interior)
    faces["east"].remove()

    _load(model, tmp_path)
    result = patch_missing_surfaces()

    assert result["ok"] is True, result
    assert result["patched_count"] == 1, result
    entry = result["patched"][0]
    # Unpaired, so Adiabatic — and the Adiabatic donor must win over the 4 Outdoors ones.
    assert entry["final_boundary_condition"] == "Adiabatic", entry
    assert entry["construction"] == "InteriorAssembly", entry
    assert entry["construction_source"] in ("same_space_same_boundary", "same_boundary"), entry
    assert result["construction_fallback_count"] == 0, result
    assert "construction_warnings" not in result, result


def test_construction_choice_survives_a_fresh_handle_assignment(tmp_path):
    # Regression (#134): the donor was the first matching surface in handle order, so the choice
    # was redrawn on every import. clone(False) is newHandles (clone(True) keeps them and would
    # perturb nothing), which reproduces a fresh import's enumeration in milliseconds.
    from mcp_server.skills.geometry.patch_missing_surfaces import patch_missing_surfaces

    def _assignments(model, stem):
        _load(model, tmp_path, stem)
        result = patch_missing_surfaces()
        assert result["ok"] is True, result
        assert result["patched_count"] >= 1, result
        return sorted((e["construction"], e["construction_source"]) for e in result["patched"])

    def _fixture():
        model = _new_model()
        _space(model, "Solo", 0, 10)
        space_faces = {s.nameString(): s for s in model.getSurfaces()}
        # A deliberately mixed pool: several Wall constructions, so an arbitrary pick has
        # something to be arbitrary about.
        for index, (name, surface) in enumerate(sorted(space_faces.items())):
            surface.setOutsideBoundaryCondition("Outdoors")
            surface.setConstruction(_named_construction(model, f"Assembly{index}"))
        space_faces["Solo_east"].remove()
        return model

    baseline_model = _fixture()
    baseline = _assignments(baseline_model, "base")

    source = _fixture()
    clone = source.clone(False).to_Model()
    original = {str(s.handle()) for s in source.getSurfaces()}
    assert {str(s.handle()) for s in clone.getSurfaces()}.isdisjoint(original)
    assert _assignments(clone, "clone") == baseline, baseline


def test_no_available_construction_is_reported_once_not_per_surface(tmp_path):
    # Validates: a model with no construction anywhere still patches, and says so — in a single
    # top-level warning plus a per-surface slug, not a paragraph repeated on every entry. On the
    # Austin fixture the equivalent case covers 103 of 117 patches, so per-entry prose would add
    # tens of kilobytes to a response an agent has to read.
    from mcp_server.skills.geometry.patch_missing_surfaces import patch_missing_surfaces

    model = _new_model()
    _space(model, "Solo", 0, 10)
    {s.nameString(): s for s in model.getSurfaces()}["Solo_east"].remove()

    _load(model, tmp_path)
    result = patch_missing_surfaces()

    assert result["ok"] is True, result
    assert result["patched_count"] == 1, result
    entry = result["patched"][0]
    assert entry["construction"] is None, entry
    assert entry["construction_source"] == "none_available", entry
    assert "construction_warning" not in entry, entry  # aggregated, not repeated

    assert result["construction_missing_count"] == 1, result
    assert len(result["construction_warnings"]) == 1, result
    assert "missing-construction error" in result["construction_warnings"][0], result
