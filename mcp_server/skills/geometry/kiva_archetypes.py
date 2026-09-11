"""Foundation archetypes for EnergyPlus Kiva, and the provenance of every value they supply.

Kiva needs foundation detail a gbXML export does not contain — insulation position, R-value and
extent. Asking a modeller ten dimensional questions gets nobody a model, so this module offers a
short menu of named foundation types, each expanding into a complete parameter set that the caller
can then override field by field.

**An archetype is an insulation strategy, not a geometry description.** Basement depth is not a
Kiva input: EnergyPlus reads the below-grade wall surfaces attached to the same Foundation object
and their height *is* the depth. `wallHeightAboveGrade` only says how much of that wall shows above
grade, and `wallDepthBelowSlab` is the footing stem below the slab underside. So an archetype can
never contradict the geometry the model already carries.

Kept free of `import openstudio` (CLAUDE.md rule 4) so the table and the provenance merge — the
part most likely to be wrong — are unit-testable with no container. Same trade as
weather/epw_ground_temperatures.py and gbxml_import/zone_checks.py.

## Where the numbers come from, honestly

There is **no vendored Kiva insulation geometry** in this image, and this module does not pretend
otherwise:

- `openstudio-standards-0.8.5` carries 90 `GroundContact*` rows in
  `ashrae_90_1_2019.construction_properties.json`, but they are **F-factor and C-factor only** —
  code performance per unit perimeter, with no insulation depth, width or position. Inverting an
  F-factor into Kiva geometry needs ASHRAE 90.1 Appendix A tables that are not vendored here.
- NECB's `apply_kiva_foundation` (openstudio-standards) applies no insulation at all.
- ComStock has no foundation insulation parameters.

**Sourced:** the XPS material properties and the 0.6 m interior-horizontal width come from the
`tbd-3.5.0` gem (`lib/tbd/geo.rb`), which is vendored and does exactly this job.

**Not sourced:** every R-value and insulation extent below is a *conventional starting point*. Each
archetype carries a `basis` string saying so, and it travels into the tool response. The caller is
separately shown the 90.1 F-factor/C-factor target for the model's climate zone, so the vendored
data is used for what it actually is — a cross-check — rather than as a fake derivation.

## IDD defaults and the provenance rule

Probed on OpenStudio 3.11.0: `wallHeightAboveGrade` 0.2, `wallDepthBelowSlab` 0.0, `footingDepth`
0.3, both horizontal insulation extents 0.0, soil 1.73 / 1842.0 / 419.0.

Several archetype values equal the IDD default. Claiming `archetype:<name>` for a field that was
never written would make provenance theatre, so `resolve_kiva_parameters` reports
`openstudio_default (archetype agrees)` in that case and the writer leaves the field defaulted.
"""
from __future__ import annotations

from dataclasses import dataclass

# XPS, from tbd-3.5.0/lib/tbd/geo.rb ("XPS 25mm"). The one vendored material basis available.
XPS_CONDUCTIVITY_W_MK = 0.029
XPS_DENSITY_KG_M3 = 28.0
XPS_SPECIFIC_HEAT_J_KGK = 1450.0
XPS_ROUGHNESS = "Rough"

# OpenStudio/EnergyPlus IDD defaults, probed on 3.11.0.
IDD_WALL_HEIGHT_ABOVE_GRADE_M = 0.2
IDD_WALL_DEPTH_BELOW_SLAB_M = 0.0
IDD_FOOTING_DEPTH_M = 0.3
IDD_SOIL_CONDUCTIVITY_W_MK = 1.73
IDD_SOIL_DENSITY_KG_M3 = 1842.0
IDD_SOIL_SPECIFIC_HEAT_J_KGK = 419.0

# TBD's clamp for a floor with no exposed edge — Kiva rejects a zero perimeter.
MIN_EXPOSED_PERIMETER_M = 0.001

# R-SI 1.76 m2K/W is R-10 IP, the conventional starting point for slab-edge and basement-wall
# insulation in this table. Not a code-derived value — see the module docstring.
CONVENTIONAL_R_SI = 1.76

CONVENTIONAL_BASIS = (
    "conventional starting point — not derived from a code table or a vendored dataset; "
    "check it against the reported 90.1 F-factor/C-factor target for this climate zone"
)
TBD_BASIS = "material properties and interior-horizontal width from the vendored tbd gem (geo.rb)"

# Provenance vocabulary. Every reported value carries exactly one of these.
PROVENANCE_USER = "user"
PROVENANCE_EPW = "epw_header"
PROVENANCE_DEFAULT = "openstudio_default"
PROVENANCE_DEFAULT_AGREES = "openstudio_default (archetype agrees)"
PROVENANCE_COMPUTED = "computed_geometry"
PROVENANCE_COMPUTED_CLAMPED = "computed_geometry_zero_clamped"
PROVENANCE_FALLBACK_FRACTION = "fallback_fraction"

# Insulation positions, matching the FoundationKiva setter families.
POSITION_INTERIOR_HORIZONTAL = "interior_horizontal"
POSITION_EXTERIOR_VERTICAL = "exterior_vertical"

# Sentinel for "run this insulation the full depth of the below-grade wall", which is only
# knowable from the model geometry at write time.
MATCH_WALL_DEPTH = "match_wall_depth"


@dataclass(frozen=True)
class InsulationSpec:
    """One insulation layer on the Kiva cross-section.

    `depth_m` may be the string MATCH_WALL_DEPTH, meaning "run to the bottom of the below-grade
    wall" — resolved from geometry by the writer, since the archetype cannot know it.
    """

    position: str
    r_si_m2k_w: float
    depth_m: float | str | None = None
    width_m: float | None = None


@dataclass(frozen=True)
class Archetype:
    name: str
    label: str
    description: str
    basis: str
    wall_height_above_grade_m: float
    wall_depth_below_slab_m: float
    footing_depth_m: float
    insulation: tuple[InsulationSpec, ...]


ARCHETYPES: dict[str, Archetype] = {
    "slab_on_grade_uninsulated": Archetype(
        name="slab_on_grade_uninsulated",
        label="Slab on grade, uninsulated",
        description=(
            "A slab poured at grade with no perimeter insulation. Common in older commercial "
            "construction and in mild climates."
        ),
        basis="no insulation to source — the absence is the modelling choice",
        wall_height_above_grade_m=IDD_WALL_HEIGHT_ABOVE_GRADE_M,
        wall_depth_below_slab_m=IDD_WALL_DEPTH_BELOW_SLAB_M,
        footing_depth_m=IDD_FOOTING_DEPTH_M,
        insulation=(),
    ),
    "slab_on_grade_perimeter_insulated": Archetype(
        name="slab_on_grade_perimeter_insulated",
        label="Slab on grade with perimeter insulation",
        description=(
            "A slab at grade with rigid insulation on the outside face of the perimeter foundation "
            "wall, running down from grade. The common code-compliant slab detail."
        ),
        basis=CONVENTIONAL_BASIS,
        wall_height_above_grade_m=IDD_WALL_HEIGHT_ABOVE_GRADE_M,
        wall_depth_below_slab_m=IDD_WALL_DEPTH_BELOW_SLAB_M,
        footing_depth_m=IDD_FOOTING_DEPTH_M,
        insulation=(
            InsulationSpec(POSITION_EXTERIOR_VERTICAL, CONVENTIONAL_R_SI, depth_m=0.6),
        ),
    ),
    "heated_basement_insulated": Archetype(
        name="heated_basement_insulated",
        label="Heated basement, insulated walls",
        description=(
            "A conditioned basement with rigid insulation on the outside face of the basement "
            "wall, running its full below-grade depth. Depth comes from your model's wall "
            "geometry, not from this archetype."
        ),
        basis=CONVENTIONAL_BASIS,
        wall_height_above_grade_m=IDD_WALL_HEIGHT_ABOVE_GRADE_M,
        wall_depth_below_slab_m=IDD_WALL_DEPTH_BELOW_SLAB_M,
        footing_depth_m=IDD_FOOTING_DEPTH_M,
        insulation=(
            InsulationSpec(POSITION_EXTERIOR_VERTICAL, CONVENTIONAL_R_SI, depth_m=MATCH_WALL_DEPTH),
        ),
    ),
    "unheated_basement": Archetype(
        name="unheated_basement",
        label="Unheated basement",
        description=(
            "An unconditioned basement with no added foundation insulation — whatever resistance "
            "exists is in the wall construction itself."
        ),
        basis="no insulation to source — the absence is the modelling choice",
        wall_height_above_grade_m=IDD_WALL_HEIGHT_ABOVE_GRADE_M,
        wall_depth_below_slab_m=IDD_WALL_DEPTH_BELOW_SLAB_M,
        footing_depth_m=IDD_FOOTING_DEPTH_M,
        insulation=(),
    ),
    "crawlspace_vented": Archetype(
        name="crawlspace_vented",
        label="Vented crawlspace",
        description=(
            "A shallow vented crawlspace with insulation laid horizontally inward from the "
            "foundation wall. More of the stem wall shows above grade than on a slab."
        ),
        basis=f"{CONVENTIONAL_BASIS}; width {TBD_BASIS}",
        wall_height_above_grade_m=0.6,
        wall_depth_below_slab_m=IDD_WALL_DEPTH_BELOW_SLAB_M,
        footing_depth_m=IDD_FOOTING_DEPTH_M,
        insulation=(
            InsulationSpec(POSITION_INTERIOR_HORIZONTAL, CONVENTIONAL_R_SI, width_m=0.6),
        ),
    ),
}

# Geometry fields an archetype supplies, paired with the IDD default they may coincide with.
_GEOMETRY_DEFAULTS = {
    "wall_height_above_grade_m": IDD_WALL_HEIGHT_ABOVE_GRADE_M,
    "wall_depth_below_slab_m": IDD_WALL_DEPTH_BELOW_SLAB_M,
    "footing_depth_m": IDD_FOOTING_DEPTH_M,
}

_SOIL_DEFAULTS = {
    "soil_conductivity_w_mk": IDD_SOIL_CONDUCTIVITY_W_MK,
    "soil_density_kg_m3": IDD_SOIL_DENSITY_KG_M3,
    "soil_specific_heat_j_kgk": IDD_SOIL_SPECIFIC_HEAT_J_KGK,
}

_EPW_SOIL_FIELDS = {
    "soil_conductivity_w_mk": "conductivity_w_mk",
    "soil_density_kg_m3": "density_kg_m3",
    "soil_specific_heat_j_kgk": "specific_heat_j_kgk",
}


class UnknownArchetypeError(ValueError):
    """The caller named a foundation archetype that does not exist."""


@dataclass(frozen=True)
class ResolvedValue:
    """One parameter, its origin, and whether the writer should actually write it.

    `write` is False when the resolved value equals the IDD default and no caller asked for it —
    leaving the field defaulted keeps the OSM honest about what was actually chosen.
    """

    value: float | str | None
    provenance: str
    write: bool = True
    note: str | None = None


def xps_thickness_m(r_si_m2k_w: float) -> float:
    """Thickness of XPS giving the requested thermal resistance.

    Modellers think in R, and FoundationKiva wants a Material with a thickness — this is the
    conversion between them, at the vendored XPS conductivity.
    """
    if r_si_m2k_w <= 0:
        raise ValueError(f"R-value must be positive, got {r_si_m2k_w}")
    return r_si_m2k_w * XPS_CONDUCTIVITY_W_MK


def get_archetype(name: str) -> Archetype:
    """The named archetype, or UnknownArchetypeError listing the valid names."""
    try:
        return ARCHETYPES[name]
    except KeyError:
        raise UnknownArchetypeError(
            f"Unknown foundation archetype '{name}'. Valid: {sorted(ARCHETYPES)}",
        ) from None


def resolve_kiva_parameters(
    archetype_name: str,
    overrides: dict[str, float | None] | None = None,
) -> tuple[dict[str, ResolvedValue], list[str]]:
    """Merge an archetype's geometry values with caller overrides.

    Returns (resolved, warnings). A caller value always wins and reports `user`. An archetype value
    that equals the IDD default reports `openstudio_default (archetype agrees)` with `write=False`,
    so the writer leaves the field alone rather than claiming credit for a default.
    """
    archetype = get_archetype(archetype_name)
    supplied = {k: v for k, v in (overrides or {}).items() if v is not None}
    warnings: list[str] = []
    resolved: dict[str, ResolvedValue] = {}

    for field, idd_default in _GEOMETRY_DEFAULTS.items():
        if field in supplied:
            resolved[field] = ResolvedValue(supplied[field], PROVENANCE_USER)
            continue
        archetype_value = getattr(archetype, field)
        if archetype_value == idd_default:
            resolved[field] = ResolvedValue(
                archetype_value, PROVENANCE_DEFAULT_AGREES, write=False,
            )
        else:
            resolved[field] = ResolvedValue(archetype_value, f"archetype:{archetype_name}")

    unknown = sorted(set(supplied) - set(_GEOMETRY_DEFAULTS))
    if unknown:
        warnings.append(
            f"Ignoring unrecognised geometry override(s): {', '.join(unknown)}",
        )
    return resolved, warnings


def resolve_insulation(
    archetype_name: str,
    overrides: dict[str, float | None] | None = None,
) -> tuple[list[InsulationSpec], list[str]]:
    """The insulation layers to apply, after caller overrides.

    Overrides are per position: `<position>_r_si`, `<position>_depth_m`, `<position>_width_m`.
    Supplying an R-value for a position the archetype does not use adds that layer; supplying one
    the archetype does use replaces its value.
    """
    archetype = get_archetype(archetype_name)
    supplied = {k: v for k, v in (overrides or {}).items() if v is not None}
    warnings: list[str] = []

    by_position = {spec.position: spec for spec in archetype.insulation}
    for position in (POSITION_INTERIOR_HORIZONTAL, POSITION_EXTERIOR_VERTICAL):
        r_si = supplied.get(f"{position}_r_si")
        depth = supplied.get(f"{position}_depth_m")
        width = supplied.get(f"{position}_width_m")
        if r_si is None and depth is None and width is None:
            continue
        existing = by_position.get(position)
        if existing is None and r_si is None:
            warnings.append(
                f"Ignoring {position} extent override: no R-value given and this archetype "
                f"applies no {position} insulation.",
            )
            continue
        by_position[position] = InsulationSpec(
            position=position,
            r_si_m2k_w=r_si if r_si is not None else existing.r_si_m2k_w,
            depth_m=depth if depth is not None else (existing.depth_m if existing else None),
            width_m=width if width is not None else (existing.width_m if existing else None),
        )

    ordered = [by_position[p] for p in
               (POSITION_INTERIOR_HORIZONTAL, POSITION_EXTERIOR_VERTICAL) if p in by_position]
    return ordered, warnings


def resolve_soil_properties(
    ground_temperature_set=None,
    overrides: dict[str, float | None] | None = None,
) -> tuple[dict[str, ResolvedValue], list[str]]:
    """Soil conductivity, density and specific heat for FoundationKivaSettings.

    Precedence: caller override, then the EPW header's GROUND TEMPERATURES soil fields, then the
    OpenStudio defaults. Those three EPW fields are blank in every EPW bundled with this repo, so
    the defaulted path is the normal one — and when nothing is chosen the writer should not create
    the settings object at all, which is why every value carries `write`.

    `ground_temperature_set` is an epw_ground_temperatures.GroundTemperatureSet or None; it is
    duck-typed so this module stays free of that import at runtime.
    """
    supplied = {k: v for k, v in (overrides or {}).items() if v is not None}
    warnings: list[str] = []
    resolved: dict[str, ResolvedValue] = {}

    for field, default in _SOIL_DEFAULTS.items():
        if field in supplied:
            resolved[field] = ResolvedValue(supplied[field], PROVENANCE_USER)
            continue
        epw_value = None
        if ground_temperature_set is not None:
            epw_value = getattr(ground_temperature_set, _EPW_SOIL_FIELDS[field], None)
        if epw_value is not None:
            resolved[field] = ResolvedValue(epw_value, PROVENANCE_EPW)
        else:
            resolved[field] = ResolvedValue(default, PROVENANCE_DEFAULT, write=False)

    if ground_temperature_set is not None and all(
        r.provenance == PROVENANCE_DEFAULT for r in resolved.values()
    ):
        warnings.append(
            "The EPW header carries no soil properties (blank in every TMY file shipped with "
            "this repo), so OpenStudio's defaults stand: 1.73 W/m-K, 1842 kg/m3, 419 J/kg-K.",
        )
    return resolved, warnings


def archetype_menu() -> list[dict[str, object]]:
    """The archetype list an agent shows the user, with each one's full parameter set.

    The point is that the user sees the numbers before committing to them, rather than picking an
    opaque name — which is the only honest way to offer defaults nobody sourced.
    """
    menu: list[dict[str, object]] = []
    for name, archetype in ARCHETYPES.items():
        menu.append({
            "name": name,
            "label": archetype.label,
            "description": archetype.description,
            "basis": archetype.basis,
            "wall_height_above_grade_m": archetype.wall_height_above_grade_m,
            "wall_depth_below_slab_m": archetype.wall_depth_below_slab_m,
            "footing_depth_m": archetype.footing_depth_m,
            "insulation": [
                {
                    "position": spec.position,
                    "r_si_m2k_w": spec.r_si_m2k_w,
                    "material": "XPS",
                    "thickness_m": round(xps_thickness_m(spec.r_si_m2k_w), 4),
                    "depth_m": spec.depth_m,
                    "width_m": spec.width_m,
                }
                for spec in archetype.insulation
            ],
        })
    return menu
