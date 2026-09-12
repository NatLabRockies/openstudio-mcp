"""Unit tests for mcp_server.skills.geometry.kiva_archetypes.

Pure Python — no openstudio, no Docker. The archetype table and the provenance merge carry all the
judgment in the Kiva feature, so they get covered without a container. Same tier as
tests/test_epw_ground_temperatures.py and tests/test_gbxml_zone_checks.py.

The soil-property tests duck-type GroundTemperatureSet rather than importing it, matching how
kiva_archetypes itself avoids the dependency.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from mcp_server.skills.geometry.kiva_archetypes import (
    ARCHETYPES,
    CONVENTIONAL_R_SI,
    IDD_FOOTING_DEPTH_M,
    IDD_SOIL_CONDUCTIVITY_W_MK,
    IDD_SOIL_DENSITY_KG_M3,
    IDD_SOIL_SPECIFIC_HEAT_J_KGK,
    IDD_WALL_HEIGHT_ABOVE_GRADE_M,
    MATCH_WALL_DEPTH,
    POSITION_EXTERIOR_VERTICAL,
    POSITION_INTERIOR_HORIZONTAL,
    PROVENANCE_DEFAULT,
    PROVENANCE_DEFAULT_AGREES,
    PROVENANCE_EPW,
    PROVENANCE_EXISTING,
    PROVENANCE_USER,
    XPS_CONDUCTIVITY_W_MK,
    UnknownArchetypeError,
    archetype_menu,
    get_archetype,
    resolve_insulation,
    resolve_kiva_parameters,
    resolve_soil_properties,
    xps_thickness_m,
)

pytestmark = pytest.mark.unit

ALL_NAMES = [
    "slab_on_grade_uninsulated",
    "slab_on_grade_perimeter_insulated",
    "heated_basement_insulated",
    "unheated_basement",
    "crawlspace_vented",
]


@dataclass(frozen=True)
class _FakeGroundTemperatureSet:
    """Duck-types epw_ground_temperatures.GroundTemperatureSet's soil fields."""

    conductivity_w_mk: float | None = None
    density_kg_m3: float | None = None
    specific_heat_j_kgk: float | None = None


# --------------------------------------------------------------------------- the table


def test_the_five_archetypes_are_present():
    # Validates: the menu the interview offers is exactly the five agreed types
    assert sorted(ARCHETYPES) == sorted(ALL_NAMES)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_archetype_is_complete(name):
    # Validates: no archetype can hand the writer a None it would dereference
    a = get_archetype(name)

    assert a.name == name
    assert len(a.label) > 3
    assert len(a.description) > 20
    assert len(a.basis) > 20
    assert isinstance(a.wall_height_above_grade_m, float)
    assert isinstance(a.wall_depth_below_slab_m, float)
    assert isinstance(a.footing_depth_m, float)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_archetype_states_its_basis(name):
    # Regression: the numbers below are conventional, not sourced. If a basis string ever goes
    # missing, a made-up R-value starts reading as authoritative in the tool response.
    basis = get_archetype(name).basis

    assert "conventional starting point" in basis or "no insulation to source" in basis


def test_uninsulated_archetypes_carry_no_insulation():
    # Validates: "uninsulated" is a deliberate modelling choice, not a gap in the table
    assert get_archetype("slab_on_grade_uninsulated").insulation == ()
    assert get_archetype("unheated_basement").insulation == ()


def test_insulated_archetypes_carry_the_expected_position():
    # Validates: slab-edge insulation goes on the outside face; crawlspace insulation lies
    # horizontally inward. Swapping them silently changes the physics.
    slab = get_archetype("slab_on_grade_perimeter_insulated").insulation
    assert [s.position for s in slab] == [POSITION_EXTERIOR_VERTICAL]
    assert slab[0].depth_m == 0.6

    crawl = get_archetype("crawlspace_vented").insulation
    assert [s.position for s in crawl] == [POSITION_INTERIOR_HORIZONTAL]
    assert crawl[0].width_m == 0.6


def test_heated_basement_insulation_depth_defers_to_geometry():
    # Regression: basement depth is NOT a Kiva input — it comes from the below-grade wall
    # surfaces. The archetype must not invent a depth that contradicts the model.
    spec = get_archetype("heated_basement_insulated").insulation[0]

    assert spec.depth_m == MATCH_WALL_DEPTH


def test_unknown_archetype_lists_the_valid_names():
    # Validates: a mistyped archetype name gets the full menu in the error so the agent can self-correct in one step
    with pytest.raises(UnknownArchetypeError) as excinfo:
        get_archetype("walkout_basement")

    for name in ALL_NAMES:
        assert name in str(excinfo.value)


# --------------------------------------------------------------------------- R to thickness


def test_r_si_converts_to_xps_thickness():
    # Validates: the vendored XPS conductivity is what turns an R-value into a Material thickness
    assert xps_thickness_m(CONVENTIONAL_R_SI) == pytest.approx(0.05104, abs=1e-5)
    assert xps_thickness_m(1.0) == pytest.approx(XPS_CONDUCTIVITY_W_MK)


def test_non_positive_r_value_is_rejected():
    # Validates: R <= 0 is rejected before it becomes a zero or negative XPS Material thickness
    with pytest.raises(ValueError, match="must be positive"):
        xps_thickness_m(0.0)


# --------------------------------------------------------------------------- geometry provenance


def test_archetype_value_equal_to_the_idd_default_is_not_claimed_as_the_archetypes():
    # Regression: wall_height_above_grade 0.2 is BOTH the archetype value and the IDD default.
    # Reporting "archetype:..." for a field nobody writes makes provenance theatre.
    resolved, warnings = resolve_kiva_parameters("slab_on_grade_uninsulated")

    height = resolved["wall_height_above_grade_m"]
    assert height.value == IDD_WALL_HEIGHT_ABOVE_GRADE_M
    assert height.provenance == PROVENANCE_DEFAULT_AGREES
    assert height.write is False
    assert warnings == []


def test_archetype_value_differing_from_the_default_is_written_and_attributed():
    # Validates: the crawlspace raises the stem wall above the 0.2 default, so it must be written
    resolved, _ = resolve_kiva_parameters("crawlspace_vented")

    height = resolved["wall_height_above_grade_m"]
    assert height.value == 0.6
    assert height.provenance == "archetype:crawlspace_vented"
    assert height.write is True


def test_user_override_beats_the_archetype():
    # Validates: an explicit geometry override wins over the archetype value and is attributed to the user
    resolved, _ = resolve_kiva_parameters(
        "crawlspace_vented", {"wall_height_above_grade_m": 0.45},
    )

    height = resolved["wall_height_above_grade_m"]
    assert height.value == 0.45
    assert height.provenance == PROVENANCE_USER
    assert height.write is True


def test_user_override_equal_to_the_default_is_still_written_as_user():
    # Validates: an explicit request is honoured and attributed, even when it matches the default
    resolved, _ = resolve_kiva_parameters(
        "crawlspace_vented", {"footing_depth_m": IDD_FOOTING_DEPTH_M},
    )

    footing = resolved["footing_depth_m"]
    assert footing.provenance == PROVENANCE_USER
    assert footing.write is True


def test_overriding_one_field_leaves_the_others_at_their_archetype_provenance():
    # Validates: provenance is per-field — overriding one value must not relabel the untouched ones
    resolved, _ = resolve_kiva_parameters(
        "crawlspace_vented", {"wall_depth_below_slab_m": 0.9},
    )

    assert resolved["wall_depth_below_slab_m"].provenance == PROVENANCE_USER
    assert resolved["wall_height_above_grade_m"].provenance == "archetype:crawlspace_vented"


def test_none_overrides_are_ignored_rather_than_written_as_null():
    # Validates: the tool signature is all-optional kwargs, so None means "not supplied"
    resolved, _ = resolve_kiva_parameters(
        "crawlspace_vented", {"wall_height_above_grade_m": None},
    )

    assert resolved["wall_height_above_grade_m"].provenance == "archetype:crawlspace_vented"


def test_unrecognised_geometry_override_warns_rather_than_silently_vanishing():
    # Validates: a misspelled override key is warned about by name rather than dropped silently
    _, warnings = resolve_kiva_parameters(
        "crawlspace_vented", {"wall_thickness_m": 0.3},
    )

    assert any("wall_thickness_m" in w for w in warnings), warnings


# --------------------------------------------------------------------------- insulation merge


def test_insulation_defaults_to_the_archetypes_layers():
    # Validates: with no overrides the archetype's own layers come back at CONVENTIONAL_R_SI with no warnings
    specs, warnings = resolve_insulation("slab_on_grade_perimeter_insulated")

    assert [s.position for s in specs] == [POSITION_EXTERIOR_VERTICAL]
    assert specs[0].r_si_m2k_w == CONVENTIONAL_R_SI
    assert warnings == []


def test_r_value_override_replaces_the_archetype_value_and_keeps_the_extent():
    # Validates: an R override changes only the R-value; the archetype's 0.6 m extent survives the merge
    specs, _ = resolve_insulation(
        "slab_on_grade_perimeter_insulated", {"exterior_vertical_r_si": 3.52},
    )

    assert specs[0].r_si_m2k_w == 3.52
    assert specs[0].depth_m == 0.6


def test_adding_a_position_the_archetype_does_not_use():
    # Validates: a user can insulate under the slab of an otherwise-bare archetype
    specs, warnings = resolve_insulation(
        "slab_on_grade_uninsulated",
        {"interior_horizontal_r_si": 1.76, "interior_horizontal_width_m": 1.2},
    )

    assert [s.position for s in specs] == [POSITION_INTERIOR_HORIZONTAL]
    assert specs[0].width_m == 1.2
    assert warnings == []


def test_extent_without_an_r_value_on_an_uninsulated_archetype_warns():
    # Validates: a width with no insulation to apply it to is a mistake, not a silent no-op
    specs, warnings = resolve_insulation(
        "slab_on_grade_uninsulated", {"interior_horizontal_width_m": 1.2},
    )

    assert specs == []
    assert any("no R-value given" in w for w in warnings), warnings


# --------------------------------------------------------------------------- soil properties


def test_soil_falls_back_to_openstudio_defaults_when_the_epw_is_blank():
    # Regression: every EPW bundled with this repo leaves the soil fields blank, so this is the
    # normal path — and nothing should be written, or we create a settings object nobody asked for
    resolved, warnings = resolve_soil_properties(_FakeGroundTemperatureSet())

    assert resolved["soil_conductivity_w_mk"].value == IDD_SOIL_CONDUCTIVITY_W_MK
    assert resolved["soil_density_kg_m3"].value == IDD_SOIL_DENSITY_KG_M3
    assert resolved["soil_specific_heat_j_kgk"].value == IDD_SOIL_SPECIFIC_HEAT_J_KGK
    assert all(r.provenance == PROVENANCE_DEFAULT for r in resolved.values())
    assert all(r.write is False for r in resolved.values())
    assert any("no soil properties" in w for w in warnings), warnings


def test_soil_seeds_from_a_populated_epw_header():
    # Validates: populated EPW soil fields are written and attributed to the EPW, not left at the IDD defaults
    resolved, _ = resolve_soil_properties(
        _FakeGroundTemperatureSet(conductivity_w_mk=1.95, density_kg_m3=1900.0,
                                  specific_heat_j_kgk=430.0),
    )

    assert resolved["soil_conductivity_w_mk"].value == 1.95
    assert resolved["soil_conductivity_w_mk"].provenance == PROVENANCE_EPW
    assert resolved["soil_conductivity_w_mk"].write is True
    assert resolved["soil_density_kg_m3"].provenance == PROVENANCE_EPW


def test_a_partially_populated_epw_header_mixes_provenance():
    # Validates: one supplied field must not drag the other two into claiming an EPW origin
    resolved, _ = resolve_soil_properties(
        _FakeGroundTemperatureSet(conductivity_w_mk=1.95),
    )

    assert resolved["soil_conductivity_w_mk"].provenance == PROVENANCE_EPW
    assert resolved["soil_density_kg_m3"].provenance == PROVENANCE_DEFAULT


def test_user_soil_override_beats_the_epw():
    # Validates: a user soil value outranks an EPW-supplied one and is attributed to the user
    resolved, _ = resolve_soil_properties(
        _FakeGroundTemperatureSet(conductivity_w_mk=1.95),
        {"soil_conductivity_w_mk": 2.2},
    )

    assert resolved["soil_conductivity_w_mk"].value == 2.2
    assert resolved["soil_conductivity_w_mk"].provenance == PROVENANCE_USER


def test_existing_model_soil_value_is_reported_and_not_overwritten():
    # Regression: a FoundationKivaSettings object already carrying custom soil values was reported
    # as `openstudio_default` with written=False, so the plan misstated what the simulation uses
    resolved, _ = resolve_soil_properties(
        _FakeGroundTemperatureSet(conductivity_w_mk=1.95),
        {"soil_density_kg_m3": 1900.0},
        existing={"soil_conductivity_w_mk": 2.4, "soil_density_kg_m3": 1700.0,
                  "soil_specific_heat_j_kgk": None},
    )

    assert resolved["soil_conductivity_w_mk"].value == 2.4
    assert resolved["soil_conductivity_w_mk"].provenance == PROVENANCE_EXISTING
    assert resolved["soil_conductivity_w_mk"].write is False
    # A caller value still beats the model's own.
    assert resolved["soil_density_kg_m3"].value == 1900.0
    assert resolved["soil_density_kg_m3"].provenance == PROVENANCE_USER
    # Still defaulted on the model, blank in the EPW: IDD default, not written.
    assert resolved["soil_specific_heat_j_kgk"].provenance == PROVENANCE_DEFAULT


def test_insulation_layers_carry_per_field_provenance():
    # Regression: resolve_insulation dropped whether each value came from the user or the
    # archetype, so dry_run could not show provenance for the insulation at all
    specs, _ = resolve_insulation(
        "slab_on_grade_perimeter_insulated", {"exterior_vertical_depth_m": 1.2},
    )

    assert len(specs) == 1
    layer = specs[0].as_plan()
    assert layer["r_si_m2k_w"] == {"value": CONVENTIONAL_R_SI,
                                   "provenance": "archetype:slab_on_grade_perimeter_insulated"}
    assert layer["depth_m"] == {"value": 1.2, "provenance": PROVENANCE_USER}
    assert layer["width_m"] == {"value": None,
                                "provenance": "archetype:slab_on_grade_perimeter_insulated"}


def test_soil_with_no_epw_at_all_defaults_quietly():
    # Validates: None (no EPW) yields IDD defaults without the 'no soil properties' warning a blank header gets
    resolved, warnings = resolve_soil_properties(None)

    assert all(r.provenance == PROVENANCE_DEFAULT for r in resolved.values())
    assert warnings == []


# --------------------------------------------------------------------------- the menu


def test_menu_shows_every_archetype_with_its_numbers_and_basis():
    # Validates: the user sees the actual parameter set before choosing — the only honest way to
    # offer defaults nobody sourced
    menu = archetype_menu()

    assert len(menu) == len(ALL_NAMES)
    entry = next(e for e in menu if e["name"] == "slab_on_grade_perimeter_insulated")
    assert entry["wall_height_above_grade_m"] == IDD_WALL_HEIGHT_ABOVE_GRADE_M
    assert "conventional starting point" in entry["basis"]
    assert entry["insulation"][0]["position"] == POSITION_EXTERIOR_VERTICAL
    assert entry["insulation"][0]["thickness_m"] == pytest.approx(0.051, abs=1e-3)
    assert entry["insulation"][0]["material"] == "XPS"


def test_menu_reports_the_geometry_deferred_depth_verbatim():
    # Validates: the MATCH_WALL_DEPTH sentinel passes through the menu unchanged rather than rendered as a number
    menu = archetype_menu()
    entry = next(e for e in menu if e["name"] == "heated_basement_insulated")

    assert entry["insulation"][0]["depth_m"] == MATCH_WALL_DEPTH
