"""Tests for the Kiva foundation tools — requires OpenStudio (Docker).

Driven in-process, like tests/test_ground_contact.py and tests/test_ground_temperatures.py: the
assertions turn on SDK behaviour that no MCP response exposes, and building the geometry here makes
every asserted number exact.

**Model state only, never a simulation.** EnergyPlus creates one 2D finite-difference domain per
Kiva floor, so an annual run is far too slow for a CI shard. `ForwardTranslator` stands in as the
cheap proxy for "EnergyPlus would accept this"; the real run is done once by hand and recorded in
the PR.

SDK facts these tests pin (probed, OpenStudio 3.11.0 / EnergyPlus 25.2.0):
  - `Surface.exposedPerimeter()` SEGFAULTS on a surface with no parent Space. No exception, no
    error dict — the interpreter dies. `test_space_less_floor_is_reported_not_crashed` is the
    regression, and if it ever fails it takes the whole pytest process with it.
  - `Surface.setAdjacentFoundation()` sets the boundary condition to Foundation but leaves
    SunExposed/WindExposed intact, which would put solar gain on a buried slab.
  - `createSurfacePropertyExposedFoundationPerimeter()` returns an initialized optional even when
    it silently discarded the method or the value.
  - `model.getFoundationKivaSettings()` creates the unique object; the Optional getter does not.
  - `exampleModel()`'s floors use the massless "CP02 CARPET PAD" layer, so they are legitimately
    refused — a real instance of the constraint, not a contrived one.

Manual EnergyPlus verification (run once by hand, 2026-09-11, EnergyPlus 25.2.0, Boston TMY3,
one-week run period, two 10x10 slabs with slab_on_grade_perimeter_insulated):

    exit=0
    eplusout.end: EnergyPlus Completed Successfully -- 8 Warning; 0 Severe Errors
    eplusout.eio:
      ! <Kiva Foundation Name>, Horizontal Cells, Vertical Cells, Total Cells,
        Total Exposed Perimeter, Perimeter Fraction, Wall Height, ...
      KIVA SLAB_ON_GRADE_PERIMETER_INSULATED SURFACE 1,39,27,1053,30.00,1.00,0.00,...
      KIVA SLAB_ON_GRADE_PERIMETER_INSULATED SURFACE 7,39,27,1053,30.00,1.00,0.00,...

The 30.00 m matches what compute_exposed_perimeters reported, so the geometry path is right end to
end. Runtime was 0.76 s, but that is a trivial model — it says nothing useful about the cost on a
real one, which scales with the number of domains (one per floor).
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_OPENSTUDIO_INTEGRATION"),
        reason="requires OpenStudio (set RUN_OPENSTUDIO_INTEGRATION=1)",
    ),
]

BOSTON_EPW = "/repo/tests/assets/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"

# Four 10x10 quadrants of a 20x20 building: each floor has two outer edges, so 20.0 m exposed
# each and 80.0 m for the footprint.
QUADRANTS = {
    "SW": [[0, 0], [10, 0], [10, 10], [0, 10]],
    "SE": [[10, 0], [20, 0], [20, 10], [10, 10]],
    "NW": [[0, 10], [10, 10], [10, 20], [0, 20]],
    "NE": [[10, 10], [20, 10], [20, 20], [10, 20]],
}


@pytest.fixture(autouse=True)
def _clear_model():
    from mcp_server.model_manager import clear_model
    clear_model()
    yield
    clear_model()


def _allowed_dir():
    """A directory the path allowlist accepts — pytest's tmp_path (/tmp) is rejected."""
    from mcp_server.config import user_run_root

    d = user_run_root() / "pytest_kiva" / uuid4().hex[:10]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_empty_model() -> None:
    import openstudio

    from mcp_server.model_manager import load_model

    path = _allowed_dir() / "empty.osm"
    openstudio.model.Model().save(openstudio.toPath(str(path)), True)
    load_model(path)


def _slab_construction(name: str = "Kiva Test Slab") -> str:
    """A single-layer standard-opaque construction — Kiva refuses massless layers."""
    from mcp_server.skills.constructions.operations import (
        create_construction,
        create_standard_opaque_material,
    )

    material = create_standard_opaque_material(
        name=f"{name} Concrete", thickness_m=0.1, conductivity_w_m_k=1.9,
        density_kg_m3=2300.0, specific_heat_j_kg_k=900.0,
    )
    assert material["ok"] is True, material
    construction = create_construction(name=name, material_names=[f"{name} Concrete"])
    assert construction["ok"] is True, construction
    return name


def _build_quadrants(names=("SW", "SE", "NW", "NE")) -> list[str]:
    """Build the quadrant spaces and give every floor a Kiva-acceptable construction."""
    import openstudio

    from mcp_server.model_manager import get_model
    from mcp_server.skills.constructions.operations import assign_construction_to_surface
    from mcp_server.skills.geometry.operations import create_space_from_floor_print

    _load_empty_model()
    construction = _slab_construction()
    for name in names:
        created = create_space_from_floor_print(
            name=f"Space {name}", floor_vertices=QUADRANTS[name], floor_to_ceiling_height=3.0,
        )
        assert created["ok"] is True, created

    # A space with no ThermalZone is dropped wholesale by the ForwardTranslator ("Space ... is not
    # associated with a ThermalZone, it will not be translated"), so its Kiva objects never reach
    # the IDF. Kiva surfaces need a zone.
    model = get_model()
    for space in model.getSpaces():
        if not space.thermalZone().is_initialized():
            zone = openstudio.model.ThermalZone(model)
            zone.setName(f"{space.nameString()} Zone")
            assert space.setThermalZone(zone)

    floors = []
    for surface in get_model().getSurfaces():
        if surface.surfaceType() != "Floor":
            continue
        assigned = assign_construction_to_surface(
            surface_name=surface.nameString(), construction_name=construction,
        )
        assert assigned["ok"] is True, assigned
        floors.append(surface.nameString())
    return sorted(floors)


def _surface(name):
    from mcp_server.model_manager import get_model

    return next(s for s in get_model().getSurfaces() if s.nameString() == name)


# --------------------------------------------------------------------------- the segfault


def test_space_less_floor_is_reported_not_crashed():
    # Regression: Surface.exposedPerimeter() SEGFAULTS on a surface with no parent Space — no
    # exception, the interpreter dies and the MCP session with it. gbXML imports produce
    # parentless surfaces routinely. If this test ever fails it will take pytest down with it,
    # which is exactly the signal we want.
    import openstudio

    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_eligibility import (
        classify_foundation_candidates,
        compute_exposed_perimeters,
    )

    floors = _build_quadrants()
    model = get_model()
    orphan = openstudio.model.Surface(
        openstudio.Point3dVector([
            openstudio.Point3d(0, 0, 0), openstudio.Point3d(0, 5, 0),
            openstudio.Point3d(5, 5, 0), openstudio.Point3d(5, 0, 0),
        ]),
        model,
    )
    orphan.setName("Orphan Floor")
    assert not orphan.space().is_initialized()

    candidates = classify_foundation_candidates(model)
    blocked = {b["surface"]: b["reasons"] for b in candidates["blocked"]}
    assert "Orphan Floor" in blocked
    assert blocked["Orphan Floor"] == ["surface has no parent space"]

    # And the perimeter pass must not call the method on it either.
    perimeters, warnings = compute_exposed_perimeters(model, [*floors, "Orphan Floor"])
    assert "Orphan Floor" not in perimeters
    assert any("no parent space" in w for w in warnings), warnings


# --------------------------------------------------------------------------- exposed perimeter


def test_exposed_perimeter_matches_the_joined_footprint():
    # Validates: the joinAllPolygons recipe. Each 10x10 quadrant of a 20x20 building has two
    # outer edges, so 20.0 m each and 80.0 m total — a hand-built Polygon3d returns 0.0 instead.
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_eligibility import compute_exposed_perimeters

    floors = _build_quadrants()
    perimeters, warnings = compute_exposed_perimeters(get_model(), floors)

    assert warnings == [], warnings
    assert len(perimeters) == 4
    for name, value in perimeters.items():
        assert value == pytest.approx(20.0, abs=0.01), (name, perimeters)
    assert sum(perimeters.values()) == pytest.approx(80.0, abs=0.01)


def test_interior_bay_has_no_exposed_edge_and_is_clamped():
    # Validates: a slab surrounded on all sides scores zero, and Kiva rejects a zero perimeter, so
    # it is clamped and warned about rather than written as 0.
    from mcp_server.model_manager import get_model
    from mcp_server.skills.constructions.operations import assign_construction_to_surface
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation
    from mcp_server.skills.geometry.operations import create_space_from_floor_print

    _build_quadrants()
    # A 3x3 grid needs a centre bay; build one ringed by the four quadrants plus fillers.
    created = create_space_from_floor_print(
        name="Space Centre", floor_vertices=[[5, 5], [15, 5], [15, 15], [5, 15]],
        floor_to_ceiling_height=3.0,
    )
    assert created["ok"] is True, created
    for surface in get_model().getSurfaces():
        if surface.surfaceType() == "Floor":
            assign_construction_to_surface(
                surface_name=surface.nameString(), construction_name="Kiva Test Slab",
            )

    result = set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                                 include_below_grade_walls=False, dry_run=True)
    assert result["ok"] is True, result
    methods = {v["provenance"] for v in result["plan"]["exposed_perimeter"].values()}
    assert "computed_geometry" in methods, result["plan"]["exposed_perimeter"]


# --------------------------------------------------------------------------- the write path


def test_applying_creates_one_kiva_per_floor_with_foundation_boundary():
    # Validates: EnergyPlus allows exactly one floor per Foundation:Kiva object
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    floors = _build_quadrants()
    result = set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                                 include_below_grade_walls=False, epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    assert sorted(result["applied"]["floors"]) == floors
    model = get_model()
    assert len(model.getFoundationKivas()) == 4
    for kiva in model.getFoundationKivas():
        assert len(kiva.surfaces()) == 1, kiva.nameString()
    for name in floors:
        assert _surface(name).outsideBoundaryCondition() == "Foundation"


def test_converted_surface_is_nosun_and_nowind():
    # Regression: setAdjacentFoundation sets the boundary condition but LEAVES SunExposed and
    # WindExposed intact — a buried slab taking solar gain is the exact defect ground_contact.py
    # exists to prevent. The tool must set the boundary condition first.
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    floors = _build_quadrants()
    assert set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                               include_below_grade_walls=False, epw_path=BOSTON_EPW)["ok"]

    for name in floors:
        surface = _surface(name)
        assert surface.sunExposure() == "NoSun", name
        assert surface.windExposure() == "NoWind", name


def test_exposed_perimeter_object_is_written_and_reads_back():
    # Validates: the object EnergyPlus treats as mandatory exists, with the method and value that
    # were asked for — createSurfaceProperty... reports success even when it discarded them.
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    floors = _build_quadrants()
    assert set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                               include_below_grade_walls=False, epw_path=BOSTON_EPW)["ok"]

    for name in floors:
        prop = _surface(name).surfacePropertyExposedFoundationPerimeter()
        assert prop.is_initialized(), name
        assert prop.get().exposedPerimeterCalculationMethod() == "TotalExposedPerimeter"
        assert prop.get().totalExposedPerimeter().get() == pytest.approx(20.0, abs=0.01)


def test_insulated_archetype_creates_and_reuses_one_xps_material():
    # Validates: the material is named deterministically, so a second run reuses it rather than
    # accumulating a duplicate
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_quadrants()
    first = set_kiva_foundation(archetype="slab_on_grade_perimeter_insulated",
                                include_below_grade_walls=False, epw_path=BOSTON_EPW)
    assert first["ok"] is True, first

    materials = [m.nameString() for m in get_model().getStandardOpaqueMaterials()
                 if m.nameString().startswith("Kiva XPS")]
    assert len(materials) == 1, materials
    assert "R-SI 1.76" in materials[0]

    second = set_kiva_foundation(archetype="slab_on_grade_perimeter_insulated",
                                 include_below_grade_walls=False, epw_path=BOSTON_EPW,
                                 overwrite=True)
    assert second["ok"] is True, second
    after = [m.nameString() for m in get_model().getStandardOpaqueMaterials()
             if m.nameString().startswith("Kiva XPS")]
    assert after == materials


# --------------------------------------------------------------------------- refusals


def test_massless_construction_layer_is_refused():
    # Validates: EnergyPlus refuses a Foundation surface with no-mass layers. exampleModel's own
    # floors use "CP02 CARPET PAD", so this is the real case, not a contrived one.
    import openstudio

    from mcp_server.model_manager import load_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation
    from mcp_server.skills.geometry.kiva_eligibility import classify_foundation_candidates

    path = _allowed_dir() / "example.osm"
    openstudio.model.exampleModel().save(openstudio.toPath(str(path)), True)
    load_model(path)

    from mcp_server.model_manager import get_model
    blocked = {b["surface"]: b["reasons"] for b in classify_foundation_candidates(get_model())["blocked"]}
    assert blocked, "expected exampleModel's carpet-pad floors to be refused"
    assert any("not a standard opaque material" in r for reasons in blocked.values() for r in reasons)

    result = set_kiva_foundation(archetype="slab_on_grade_uninsulated", epw_path=BOSTON_EPW)
    assert result["ok"] is False
    assert "No eligible foundation floors" in result["error"]


def test_surface_with_a_window_is_refused():
    # Validates: "Foundation is not allowed with windows" — an EnergyPlus fatal
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_eligibility import kiva_surface_blockers
    from mcp_server.skills.geometry.operations import create_subsurface

    _build_quadrants()
    wall = next(s for s in get_model().getSurfaces()
                if s.surfaceType() == "Wall" and s.outsideBoundaryCondition() == "Outdoors")
    created = create_subsurface(
        name="Kiva Test Window", parent_surface_name=wall.nameString(),
        vertices=[[1, 0.5], [2, 0.5], [2, 2], [1, 2]], subsurface_type="FixedWindow",
    )
    if created.get("ok"):
        assert any("windows or doors" in b for b in kiva_surface_blockers(wall)), wall.nameString()


def test_requested_surface_that_is_not_eligible_aborts_with_nothing_written():
    # Validates: resolve-everything-before-writing — a typo must not leave a partial batch
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    floors = _build_quadrants()
    result = set_kiva_foundation(
        archetype="slab_on_grade_uninsulated",
        floor_surface_names=[floors[0], "No Such Surface"],
        epw_path=BOSTON_EPW,
    )

    assert result["ok"] is False
    assert "No Such Surface" in result["refused_surfaces"]
    assert len(get_model().getFoundationKivas()) == 0


def test_unknown_archetype_is_refused_with_the_valid_names():
    # Validates: a mistyped archetype is refused with the full valid list in the response, so an
    # agent can self-correct in one step instead of guessing names
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_quadrants()
    result = set_kiva_foundation(archetype="walkout_basement")

    assert result["ok"] is False
    assert "heated_basement_insulated" in result["valid_values"]


def test_out_of_range_perimeter_fraction_is_refused_before_the_sdk_sees_it():
    # Regression: OpenStudio silently discards a fraction outside 0..1 while still returning an
    # object that looks created
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_quadrants()
    result = set_kiva_foundation(
        archetype="slab_on_grade_uninsulated", exposed_perimeter_method="fraction",
        exposed_perimeter_fraction=12.0, epw_path=BOSTON_EPW,
    )

    assert result["ok"] is False
    assert "between 0 and 1" in result["error"]


def test_total_perimeter_across_several_floors_is_refused():
    # Validates: one number cannot describe four slabs
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_quadrants()
    result = set_kiva_foundation(
        archetype="slab_on_grade_uninsulated", exposed_perimeter_method="total",
        exposed_perimeter_m=40.0, epw_path=BOSTON_EPW,
    )

    assert result["ok"] is False
    assert "one perimeter cannot describe several slabs" in result["error"]


def test_reapplying_without_overwrite_is_refused():
    # Validates: idempotence guard — a floor that already carries a Foundation object is not
    # silently re-pointed; the error names the overwrite flag that allows it
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_quadrants()
    assert set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                               include_below_grade_walls=False, epw_path=BOSTON_EPW)["ok"]
    second = set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                                 include_below_grade_walls=False, epw_path=BOSTON_EPW)

    assert second["ok"] is False
    assert "overwrite=True" in second["error"]


def test_overwrite_does_not_accumulate_foundation_objects():
    # Regression: overwrite=True reset the floor's reference but never removed the previous
    # FoundationKiva, so every re-run added four orphan Foundation:Kiva objects to the OSM/IDF
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    floors = _build_quadrants()
    first = set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                                include_below_grade_walls=False, epw_path=BOSTON_EPW)
    assert first["ok"] is True, first
    second = set_kiva_foundation(archetype="slab_on_grade_perimeter_insulated",
                                 include_below_grade_walls=False, epw_path=BOSTON_EPW,
                                 overwrite=True)

    assert second["ok"] is True, second
    kivas = get_model().getFoundationKivas()
    assert len(kivas) == len(floors), sorted(k.nameString() for k in kivas)
    assert all("slab_on_grade_perimeter_insulated" in k.nameString() for k in kivas)
    for name in floors:
        assert _surface(name).adjacentFoundation().get().nameString().startswith(
            "Kiva slab_on_grade_perimeter_insulated")


def test_overwrite_keeps_a_previous_foundation_that_walls_still_use_and_warns():
    # Validates: when the re-run does not re-pair the walls, the old Foundation object is the only
    # thing keeping their reference valid — it is kept and the response says which walls and why
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    floor, walls = _build_basement()
    first = set_kiva_foundation(archetype="unheated_basement", include_below_grade_walls=True,
                                epw_path=BOSTON_EPW)
    assert first["ok"] is True, first
    second = set_kiva_foundation(archetype="unheated_basement", include_below_grade_walls=False,
                                 epw_path=BOSTON_EPW, overwrite=True)

    assert second["ok"] is True, second
    assert len(get_model().getFoundationKivas()) == 2
    kept = [w for w in second["warnings"] if "was kept because" in w]
    assert len(kept) == 1, second["warnings"]
    for name in walls:
        assert name in kept[0]
    floor_kiva = _surface(floor).adjacentFoundation().get().nameString()
    wall_kiva = _surface(walls[0]).adjacentFoundation().get().nameString()
    assert floor_kiva != wall_kiva


def test_no_model_loaded_reports_instead_of_raising():
    # Validates: the operations contract (CLAUDE.md rule 5) — both Kiva tools return ok=False
    # with no model loaded rather than raising RuntimeError through MCP
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation
    from mcp_server.skills.geometry.kiva_foundation import get_foundation_options

    assert set_kiva_foundation(archetype="slab_on_grade_uninsulated")["ok"] is False
    assert get_foundation_options()["ok"] is False


# --------------------------------------------------------------------------- options / state


def test_get_foundation_options_does_not_create_the_settings_object():
    # Regression: the plain getFoundationKivaSettings() creates the unique object. A read tool that
    # used it would make every model look configured, and the next save would persist it.
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_foundation import get_foundation_options

    _build_quadrants()
    assert get_model().getOptionalFoundationKivaSettings().is_initialized() is False

    for _ in range(3):
        options = get_foundation_options()
        assert options["ok"] is True, options
        assert options["existing_kiva"]["settings_present"] is False

    assert get_model().getOptionalFoundationKivaSettings().is_initialized() is False


def test_options_reports_the_archetype_menu_with_its_basis():
    # Validates: the user is shown the numbers and their provenance before choosing, which is the
    # only honest way to offer values nobody sourced
    from mcp_server.skills.geometry.kiva_foundation import get_foundation_options

    _build_quadrants()
    options = get_foundation_options()

    assert options["ok"] is True, options
    assert options["eligible_floor_count"] == 4
    assert len(options["archetypes"]) == 5
    slab = next(a for a in options["archetypes"] if a["name"] == "slab_on_grade_perimeter_insulated")
    assert "conventional starting point" in slab["basis"]
    assert slab["insulation"][0]["r_si_m2k_w"] == 1.76


def test_blank_epw_soil_leaves_settings_uncreated():
    # Validates: every bundled EPW leaves the soil fields blank, so nothing is chosen and no
    # FoundationKivaSettings object should appear
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_quadrants()
    result = set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                                 include_below_grade_walls=False, epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    assert result["applied"]["settings_written"] == []
    assert get_model().getOptionalFoundationKivaSettings().is_initialized() is False


def test_user_soil_override_creates_settings_and_reports_provenance():
    # Validates: a caller-supplied soil property is the one case that must create the unique
    # FoundationKivaSettings object, land on it, and be attributed to the user
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_quadrants()
    result = set_kiva_foundation(
        archetype="slab_on_grade_uninsulated", include_below_grade_walls=False,
        epw_path=BOSTON_EPW, soil_conductivity_w_mk=2.2,
    )

    assert result["ok"] is True, result
    assert result["plan"]["soil"]["soil_conductivity_w_mk"]["provenance"] == "user"
    settings = get_model().getOptionalFoundationKivaSettings()
    assert settings.is_initialized()
    assert settings.get().soilConductivity() == pytest.approx(2.2)


def test_dry_run_changes_nothing():
    # Validates: dry_run returns the full plan for the user to inspect while creating no
    # FoundationKiva objects — the preview must not be a partial apply
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_quadrants()
    result = set_kiva_foundation(archetype="slab_on_grade_perimeter_insulated",
                                 include_below_grade_walls=False, epw_path=BOSTON_EPW,
                                 dry_run=True)

    assert result["ok"] is True, result
    assert result["dry_run"] is True
    assert result["plan"]["floors"]
    assert len(get_model().getFoundationKivas()) == 0


# --------------------------------------------------------------------------- Phase 1 interaction


def test_kiva_reports_that_it_supersedes_the_building_surface_temperatures():
    # Validates: a Foundation surface ignores Site:GroundTemperature:BuildingSurface entirely, so
    # a user who ran both must be told rather than left to discover it
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _build_quadrants()
    assert set_ground_temperatures(epw_path=BOSTON_EPW,
                                   building_surface_method="constant",
                                   building_surface_constant_c=18.0)["ok"]

    result = set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                                 include_below_grade_walls=False, epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    interaction = result["ground_temperature_interaction"]
    assert interaction["surfaces_now_kiva"] == 4
    assert interaction["building_surface_state"] == "set"
    assert "ignore it" in interaction["warning"]


# --------------------------------------------------------------------------- translation proxy


def test_forward_translation_emits_the_kiva_objects_without_errors():
    # Validates: the cheap proxy for "EnergyPlus would accept this". The missing-perimeter failure
    # is a runtime fatal, so the real check is the one manual simulation recorded in the PR — but
    # a clean forward translation catches everything structural in about two seconds.
    import openstudio

    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_quadrants()
    assert set_kiva_foundation(archetype="slab_on_grade_perimeter_insulated",
                               include_below_grade_walls=False, epw_path=BOSTON_EPW)["ok"]

    translator = openstudio.energyplus.ForwardTranslator()
    workspace = translator.translateModel(get_model())

    assert list(translator.errors()) == [], [e.logMessage() for e in translator.errors()]
    idf = workspace.toIdfFile().__str__()
    assert "Foundation:Kiva" in idf
    assert "SurfaceProperty:ExposedFoundationPerimeter" in idf


# --------------------------------------------------------------------------- below-grade walls


def _build_basement() -> tuple[str, list[str]]:
    """One 10x10 space with its floor 2.5 m below grade, so its walls are fully buried."""
    import openstudio

    from mcp_server.model_manager import get_model
    from mcp_server.skills.constructions.operations import assign_construction_to_surface
    from mcp_server.skills.geometry.operations import create_space_from_floor_print

    _load_empty_model()
    construction = _slab_construction()
    created = create_space_from_floor_print(
        name="Basement", floor_vertices=QUADRANTS["SW"], floor_to_ceiling_height=2.5,
    )
    assert created["ok"] is True, created

    model = get_model()
    space = next(s for s in model.getSpaces() if s.nameString() == "Basement")
    zone = openstudio.model.ThermalZone(model)
    zone.setName("Basement Zone")
    space.setThermalZone(zone)

    # create_space_from_floor_print always extrudes upward from z=0, so drop the whole space to
    # put the floor at -2.5 m and the walls entirely below grade.
    for surface in space.surfaces():
        moved = openstudio.Point3dVector([
            openstudio.Point3d(v.x(), v.y(), v.z() - 2.5) for v in surface.vertices()
        ])
        assert surface.setVertices(moved)
        assign_construction_to_surface(
            surface_name=surface.nameString(), construction_name=construction,
        )

    floor = next(s.nameString() for s in space.surfaces() if s.surfaceType() == "Floor")
    walls = sorted(s.nameString() for s in space.surfaces() if s.surfaceType() == "Wall")
    return floor, walls


def test_below_grade_walls_join_their_floors_foundation_object():
    # Validates: EnergyPlus requires a Kiva wall to reference the SAME Foundation object as its
    # floor, so pairing is adjacency rather than selection
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    floor, walls = _build_basement()
    result = set_kiva_foundation(archetype="heated_basement_insulated",
                                 include_below_grade_walls=True, epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    assert result["applied"]["floors"] == [floor]
    assert sorted(result["applied"]["walls"]) == walls

    kivas = get_model().getFoundationKivas()
    assert len(kivas) == 1, [k.nameString() for k in kivas]
    attached = sorted(s.nameString() for s in kivas[0].surfaces())
    assert attached == sorted([floor, *walls])
    for name in walls:
        assert _surface(name).outsideBoundaryCondition() == "Foundation"
        assert _surface(name).sunExposure() == "NoSun"


def test_excluding_walls_leaves_them_alone():
    # Validates: the escape hatch produces a floors-only model, which is still valid Kiva
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    floor, walls = _build_basement()
    result = set_kiva_foundation(archetype="heated_basement_insulated",
                                 include_below_grade_walls=False, epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    assert result["applied"]["walls"] == []
    assert _surface(floor).outsideBoundaryCondition() == "Foundation"
    for name in walls:
        assert _surface(name).outsideBoundaryCondition() != "Foundation"


def test_below_grade_floor_gets_its_real_exposed_perimeter():
    # Regression: joinAllPolygons and Surface.exposedPerimeter assert |z| <= tolerance, so a
    # basement floor at -2.5 m scored 0.0 and was clamped to 1 mm as an "interior bay" — every
    # basement got a foundation with no exposed edge. The footprint is now scored at z = 0.
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation
    from mcp_server.skills.geometry.kiva_eligibility import compute_exposed_perimeters

    floor, _walls = _build_basement()
    perimeters, warnings = compute_exposed_perimeters(get_model(), [floor])
    assert perimeters == {floor: pytest.approx(40.0, abs=0.001)}, (perimeters, warnings)

    result = set_kiva_foundation(archetype="unheated_basement", epw_path=BOSTON_EPW)
    assert result["ok"] is True, result
    exposed = result["applied"]["foundations"][0]["exposed_perimeter"]
    assert exposed["method"] == "TotalExposedPerimeter"
    assert exposed["value"] == pytest.approx(40.0, abs=0.001)
    assert exposed["provenance"] == "computed_geometry"
    assert not any("interior bay" in w for w in result["warnings"]), result["warnings"]


def test_paired_walls_longer_than_the_exposed_perimeter_are_refused():
    # Validates: EnergyPlus refuses a Foundation:Kiva whose wall surfaces have "a combined length
    # greater than the exposed perimeter of the foundation" (severe, at run time). Four 10 m walls
    # against a stated 10 m perimeter must be refused here, with nothing written.
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    floor, walls = _build_basement()
    result = set_kiva_foundation(
        archetype="unheated_basement", include_below_grade_walls=True,
        exposed_perimeter_method="total", exposed_perimeter_m=10.0, epw_path=BOSTON_EPW,
    )

    assert result["ok"] is False, result
    assert "exposed perimeter" in result["error"]
    detail = result["wall_length_exceeds_perimeter"][floor]
    assert detail["paired_wall_length_m"] == pytest.approx(40.0, abs=0.01)
    assert detail["exposed_perimeter_m"] == pytest.approx(10.0, abs=0.001)
    assert sorted(detail["walls"]) == walls
    assert _surface(floor).outsideBoundaryCondition() != "Foundation"
    for name in walls:
        assert _surface(name).outsideBoundaryCondition() != "Foundation"


def test_basement_insulation_depth_comes_from_the_wall_geometry():
    # Regression: basement depth is NOT a Kiva input. The archetype defers with MATCH_WALL_DEPTH
    # and the writer must resolve it from the paired walls, not invent a number.
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_basement()
    result = set_kiva_foundation(archetype="heated_basement_insulated",
                                 include_below_grade_walls=True, epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    kiva = get_model().getFoundationKivas()[0]
    assert kiva.exteriorVerticalInsulationDepth().get() == pytest.approx(2.5, abs=0.01)
    assert kiva.exteriorVerticalInsulationMaterial().is_initialized()


def test_user_stem_wall_depth_on_a_slab_model_is_honoured():
    # Regression: a "suspicious depth" guard refused any wall_depth_below_slab_m above 0.5 m on a
    # model with no below-grade walls, while telling the user to "pass the value explicitly" —
    # which was the only way to reach it, since every archetype's own value is 0.0. A frost-depth
    # stem wall on a slab is a real detail and must be writable.
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    _build_quadrants()
    result = set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                                 wall_depth_below_slab_m=1.2, epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    depth = result["plan"]["geometry"]["wall_depth_below_slab_m"]
    assert depth == {"value": 1.2, "provenance": "user", "written": True}
    for kiva in get_model().getFoundationKivas():
        assert kiva.wallDepthBelowSlab() == pytest.approx(1.2, abs=1e-6)


def test_basement_archetype_on_a_slab_model_applies_without_wall_insulation():
    # Validates: an archetype is an insulation strategy, not a geometry claim — with no below-grade
    # wall to pair, the full-depth exterior insulation is skipped with a warning naming why, and the
    # floors still get their Foundation objects
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation

    floors = _build_quadrants()
    result = set_kiva_foundation(archetype="heated_basement_insulated", epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    assert sorted(result["applied"]["floors"]) == floors
    assert result["applied"]["walls"] == []
    assert result["applied"]["insulation"] == {}
    assert any("no below-grade wall was paired" in w for w in result["warnings"]), result["warnings"]
    for kiva in get_model().getFoundationKivas():
        assert not kiva.exteriorVerticalInsulationMaterial().is_initialized()
    # A skipped layer must not leave an unused XPS material behind either.
    xps = [m.nameString() for m in get_model().getStandardOpaqueMaterials()
           if m.nameString().startswith("Kiva XPS")]
    assert xps == [], xps


def _build_stacked_basement() -> dict[str, object]:
    """Two basement levels plus a neighbour, matched, so interior floors and partitions exist.

    Lower (z -5..-2.5) and Lower2 beside it share a partition wall; Upper (z -2.5..0) sits on
    Lower, so Upper's floor is matched to Lower's ceiling. Only the two bottom floors and the
    exterior below-grade walls touch soil.
    """
    import openstudio

    from mcp_server.model_manager import get_model
    from mcp_server.skills.constructions.operations import assign_construction_to_surface
    from mcp_server.skills.geometry.operations import create_space_from_floor_print, match_surfaces

    _load_empty_model()
    construction = _slab_construction()
    model = get_model()

    def build(name, footprint, dz):
        created = create_space_from_floor_print(
            name=name, floor_vertices=footprint, floor_to_ceiling_height=2.5,
        )
        assert created["ok"] is True, created
        space = next(s for s in model.getSpaces() if s.nameString() == name)
        zone = openstudio.model.ThermalZone(model)
        zone.setName(f"{name} Zone")
        space.setThermalZone(zone)
        for surface in space.surfaces():
            moved = openstudio.Point3dVector([
                openstudio.Point3d(v.x(), v.y(), v.z() + dz) for v in surface.vertices()
            ])
            assert surface.setVertices(moved)
            assign_construction_to_surface(
                surface_name=surface.nameString(), construction_name=construction,
            )
        return space

    lower = build("Lower", QUADRANTS["SW"], -5.0)
    lower2 = build("Lower2", QUADRANTS["SE"], -5.0)
    upper = build("Upper", QUADRANTS["SW"], -2.5)
    matched = match_surfaces()
    assert matched["ok"] is True, matched
    # Upper floor <-> Lower ceiling, and the Lower <-> Lower2 partition: two pairs, four surfaces.
    assert matched["matched_surfaces"] == 4, matched

    def one(space, kind):
        return next(s.nameString() for s in space.surfaces() if s.surfaceType() == kind)

    partition = sorted(
        s.nameString() for s in [*lower.surfaces(), *lower2.surfaces()]
        if s.surfaceType() == "Wall" and s.outsideBoundaryCondition() == "Surface"
    )
    assert len(partition) == 2, partition
    return {
        "lower_floor": one(lower, "Floor"),
        "lower2_floor": one(lower2, "Floor"),
        "upper_floor": one(upper, "Floor"),
        "lower_ceiling": one(lower, "RoofCeiling"),
        "partition_walls": partition,
    }


def test_matched_interior_surfaces_are_not_kiva_candidates():
    # Regression: eligibility filtered only Adiabatic, so a matched interior floor (a two-storey
    # basement, a crawlspace modelled as a zone) and buried partition walls were converted to
    # Foundation, and setOutsideBoundaryCondition dropped their partners to Outdoors/SunExposed
    # 2.5 m underground. ground_contact.py already excludes "Surface"; this path must too.
    from mcp_server.model_manager import get_model
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation
    from mcp_server.skills.geometry.kiva_eligibility import classify_foundation_candidates

    names = _build_stacked_basement()
    candidates = classify_foundation_candidates(get_model())
    floors = sorted(f["surface"] for f in candidates["eligible_floors"])
    walls = sorted(w["surface"] for w in candidates["eligible_walls"])

    assert floors == sorted([names["lower_floor"], names["lower2_floor"]]), floors
    assert names["upper_floor"] not in floors
    assert not set(names["partition_walls"]) & set(walls), walls
    # 3 exterior walls on each lower space plus Upper's 4, all fully buried; no partitions.
    assert len(walls) == 10, walls

    result = set_kiva_foundation(archetype="unheated_basement", epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    assert sorted(result["applied"]["floors"]) == floors
    assert _surface(names["upper_floor"]).outsideBoundaryCondition() == "Surface"
    ceiling = _surface(names["lower_ceiling"])
    assert ceiling.outsideBoundaryCondition() == "Surface"
    assert ceiling.adjacentSurface().get().nameString() == names["upper_floor"]
    for name in names["partition_walls"]:
        assert _surface(name).outsideBoundaryCondition() == "Surface"


# --------------------------------------------------------------------------- guards elsewhere


def test_set_surface_boundary_conditions_refuses_a_dangling_foundation():
    # Regression: "Foundation" is in the SDK's valid list, so this tool accepted it and produced a
    # model that fails fatally in EnergyPlus for want of the two companion objects.
    from mcp_server.skills.geometry.boundary_conditions import set_surface_boundary_conditions

    floors = _build_quadrants()
    result = set_surface_boundary_conditions(
        surface_names=[floors[0]], outside_boundary_condition="Foundation",
    )

    assert result["ok"] is False
    assert "set_kiva_foundation" in result["error"]
    assert _surface(floors[0]).outsideBoundaryCondition() != "Foundation"


def test_ground_temperature_report_goes_quiet_once_every_surface_uses_kiva():
    # Validates: a user who did the higher-fidelity thing should not be nagged forever about
    # Site:GroundTemperature:BuildingSurface, which Kiva ignores
    from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation
    from mcp_server.skills.weather.ground_temperatures import find_missing_ground_temperatures

    _build_quadrants()
    before = find_missing_ground_temperatures()
    assert before["kiva_foundation_surface_count"] == 0
    assert "set_ground_temperatures()" in before["ground_temperatures_hint"]
    assert "set_kiva_foundation()" in before["ground_temperatures_hint"]

    assert set_kiva_foundation(archetype="slab_on_grade_uninsulated",
                               include_below_grade_walls=False, epw_path=BOSTON_EPW)["ok"]

    after = find_missing_ground_temperatures()
    assert after["kiva_foundation_surface_count"] == 4
    assert "would be inert here" in after["ground_temperatures_hint"]
    assert after["ok"] is True
