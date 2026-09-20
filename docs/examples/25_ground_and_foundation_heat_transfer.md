# Example 25: Ground and Foundation Heat Transfer (`/foundation-modeling`)

Two ways to model what happens under a building — a fast approximate one and a real 2D soil solver —
and how to tell which a model needs.

## Scenario

A gbXML translation arrives with no ground temperatures at all. EnergyPlus falls back to its own
defaults: 18 °C every month on every `Ground` surface, in Boston and in Austin alike. The project
EPW has carried measured ground temperatures the whole time and nothing read them.

The fix is not one tool but a choice. Ground-coupled heat transfer can be represented by a monthly
temperature under the slab, or by solving the soil as a two-dimensional domain. Those give different
answers and cost very different amounts of simulation time, and picking without knowing the
difference is how a model ends up confidently wrong.

## Concepts

### What EnergyPlus does with a ground-coupled surface

A surface whose outside boundary condition is `Ground` exchanges heat with a temperature you supply,
month by month. There are four objects, and they drive different things:

| Object | Drives | Default |
|--------|--------|---------|
| `Site:GroundTemperature:BuildingSurface` | **Every `Ground` surface's heat balance** — this is the slab | 18.0 °C |
| `Site:GroundTemperature:FCfactorMethod` | F/C-factor constructions only | 13.0 °C |
| `Site:GroundTemperature:Shallow` | Surface ground heat exchangers, `Site:GroundDomain` | 13.0 °C |
| `Site:GroundTemperature:Deep` | Deep ground heat exchangers | 16.0 °C |

On a typical gbXML model with no ground heat exchanger and no F/C-factor constructions, **only
`BuildingSurface` changes the answer.** The other three are inert. Four written objects are not four
improvements.

### Why the EPW's numbers cannot go straight into BuildingSurface

The EPW header carries a `GROUND TEMPERATURES` record — three depths, twelve monthly values each:

```
GROUND TEMPERATURES,3,.5,,,,-0.29,-1.36,0.53,3.49,11.23,17.20,21.23,22.45,20.36,15.73,9.53,3.79,
                      2,,,,3.63,...,  4,,,,6.88,...
```

Those are **undisturbed** soil temperatures — an open field with no building on it. The EPW's own
`.stat` file says so, at `tests/assets/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.stat:498-500`:

> `**These ground temperatures should NOT BE USED in the GroundTemperatures object to compute building floor losses.`
> `The temperatures for 0.5 m depth can be used for GroundTemperatures:Surface.`
> `The temperatures for 4.0 m depth can be used for GroundTemperatures:Deep.`

Boston's January value at 0.5 m is −0.29 °C. Writing that under a heated slab overstates the floor
loss badly — the soil under a building is warmed by the building.

### What Kiva does instead

Kiva solves a two-dimensional finite-difference slice through the slab edge and sweeps it around the
exposed perimeter, so slab-edge loss and insulation geometry fall out of the physics rather than
being averaged away:

```
                    │ ← interior
   grade            │
  ─────┬────────────┤  ← wall_height_above_grade (0.2 m default)
       │▓▓          │
       │▓▓ exterior │
       │▓▓ vertical │═══════════════  ← the slab (your Floor surface)
       │▓▓ insul.   │▒▒▒▒▒ interior horizontal insulation (↔ width)
       │  ↕ depth   │
       └────┬───────┘  ← wall_depth_below_slab (0.0 m default)
         ┌──┴──┐
         │footing│     ← footing_depth (0.3 m default)
         └──────┘
              ↓ soil solved to far-field 40 m, deep ground "Autoselect"
```

**Basement depth is not a Kiva input.** Kiva reads the below-grade wall surfaces attached to the same
Foundation object; their height *is* the depth. `wall_height_above_grade` only says how much of that
wall shows above grade, and `wall_depth_below_slab` is the footing stem below the slab underside.

A `Foundation` surface **ignores `Site:GroundTemperature:BuildingSurface` entirely.** The two methods
do not stack.

## Choosing a method

| | `set_ground_temperatures` | `set_kiva_foundation` |
|---|---|---|
| Cost | None | One 2D domain **per floor** |
| User input | None | Foundation type, ideally real insulation detail |
| Use when | Screening, compliance runs, no foundation information available | Slab-edge loss matters, basement-dominated building, the foundation is the subject |

Default to the simple method. Reach for Kiva when the foundation is what the question is about.

## Prompt

> The gbXML import has no ground temperatures. Set them from the project weather file — and if the
> basement matters, model it properly.

---

## Walkthrough A — the simple method

```
1. import_gbxml(gbxml_path="/inputs/project.xml", epw_path="/inputs/boston.epw")
2. repair_and_validate_gbxml_geometry()
   → ground_temperatures_missing: true
     ground_temperatures_missing_count: 4
     ground_temperatures_state: {building_surface: "absent", fcfactor_method: "absent",
                                 shallow: "absent", deep: "absent"}
     ground_temperatures_hint: "...apply the EPW's values with set_ground_temperatures(), or model
                                the foundation directly with set_kiva_foundation()..."
3. set_ground_temperatures()                    # resolves the EPW the import used
   → applied:
       Site:GroundTemperature:Shallow:        depth_m 0.5, monthly_c [-0.29, -1.36, ... 3.79]
       Site:GroundTemperature:Deep:           depth_m 4.0, monthly_c [6.88, 4.93, ... 9.84]
       Site:GroundTemperature:FCfactorMethod: depth_m 0.5, source "epw_raw"
       Site:GroundTemperature:BuildingSurface: monthly_c [19.1] x12,
                                               source "setpoint_offset",
                                               mean_heating_setpoint_c 21.1, offset_c 2.0
4. repair_and_validate_gbxml_geometry()
   → ground_temperatures_missing: false
```

`ground_temperatures_missing` is **report-only** — it never moves `ok`, exactly like
`ground_contact_missing_count`. Check the count yourself.

Note what step 3 did *not* do: it did not put −0.29 °C under the slab. `BuildingSurface` was derived
from the model's own heating setpoints — the occupied 21.1 °C, minus 2 °C. That offset is a
documented rule of thumb, not a calculation, which is the whole reason Kiva exists.

**If the model has no thermostats yet**, `BuildingSurface` is skipped with a reason and the other
three are still written. Run it again after HVAC, or state the value:

```
5. set_ground_temperatures(building_surface_method="constant", building_surface_constant_c=18.0)
```

To accept the undisturbed values anyway — against the `.stat`'s advice, and it will say so:

```
6. set_ground_temperatures(building_surface_method="epw_raw")
   → warnings: ["...writes UNDISTURBED soil temperatures... expect overstated slab heat loss."]
```

## Walkthrough B — Kiva, with the interview

**Always look before choosing.**

```
1. get_foundation_options()
   → eligible_floors: [{surface: "Surface 1", exposed_perimeter_m: 30.0}, ...]
     eligible_walls:  [...]
     blocked: [{surface: "Surface 12",
                reasons: ["construction layer 'CP02 CARPET PAD' is not a standard opaque
                           material — EnergyPlus refuses massless layers on a Foundation surface"]}]
     kiva_domains_if_applied: 2
     climate_zone: "5A"
     code_targets: {slab_max_f_factor: {Heated: 0.9, Unheated: 0.73}, ...}
     archetypes: [...five, each with its full parameter set and a `basis` string...]
```

### Put the choice to the user

Show the five archetypes **with their numbers**, and ask which describes the building:

| Archetype | Insulation |
|---|---|
| `slab_on_grade_uninsulated` | none |
| `slab_on_grade_perimeter_insulated` | exterior vertical R-SI 1.76, 0.6 m deep |
| `heated_basement_insulated` | exterior vertical R-SI 1.76, full below-grade wall depth |
| `unheated_basement` | none |
| `crawlspace_vented` | interior horizontal R-SI 1.76, 0.6 m wide |

**Say that the R-values are conventional starting points.** There is no vendored source for Kiva
insulation geometry — openstudio-standards carries ASHRAE 90.1 ground data, but as F-factor and
C-factor, which are code *performance* per unit perimeter and cannot be converted to insulation
geometry without Appendix A tables that are not available here. So the tool reports the 90.1 target
for the model's climate zone as a **cross-check**, never as the source. If the user knows their real
insulation, take it over the archetype.

### Apply

```
2. set_kiva_foundation(archetype="heated_basement_insulated")
   → applied: {floors: ["Surface 1"], walls: ["Surface 2", "Surface 3", ...],
               foundations: [{name: "Kiva heated_basement_insulated Surface 1",
                              exposed_perimeter: {method: "TotalExposedPerimeter",
                                                  value: 30.0,
                                                  provenance: "computed_geometry"}}]}
     plan.geometry: {wall_height_above_grade_m: {value: 0.2,
                                                 provenance: "openstudio_default (archetype agrees)",
                                                 written: false}, ...}
     ground_temperature_interaction: {surfaces_now_kiva: 5, ground_surfaces_remaining: 0,
                                      warning: "...the 5 surface(s) just converted to Kiva ignore
                                                it. It now applies to no surfaces at all."}
```

Overriding what the user actually knows:

```
3. set_kiva_foundation(archetype="slab_on_grade_perimeter_insulated",
     exterior_vertical_insulation_r_si=3.52,
     exterior_vertical_insulation_depth_m=1.2)
```

Showing the user the plan first:

```
4. set_kiva_foundation(archetype="unheated_basement", dry_run=True)
   → dry_run: true, plan: {...}, note: "Nothing was changed."
```

### Reading the provenance

Every value says where it came from, because several were never sourced:

| provenance | means |
|---|---|
| `user` | the caller supplied it |
| `archetype:<name>` | a conventional starting point — report this to the user |
| `openstudio_default (archetype agrees)` | left defaulted; the archetype did not override it |
| `epw_header` | the EPW's soil properties (blank in every bundled TMY file) |
| `computed_geometry` | exposed perimeter from the joined building footprint |
| `computed_geometry_zero_clamped` | an interior bay with no exposed edge |

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `set_ground_temperatures` | Write the four `Site:GroundTemperature:*` objects from the EPW header |
| `get_weather_info` | Read back which ground-temperature objects are set |
| `get_foundation_options` | Eligible surfaces, blockers, exposed perimeter, archetype menu, code targets |
| `set_kiva_foundation` | Apply a Kiva 2D foundation model |
| `repair_and_validate_gbxml_geometry` | Reports `ground_temperatures_missing` (report-only) |

## Common Pitfalls

- **Massless construction layers are the most common Kiva blocker on a real Revit model.** gbXML
  slabs routinely carry no-mass layers and EnergyPlus refuses them outright — `exampleModel()`'s own
  floors fail this on `CP02 CARPET PAD`. Fix with `create_standard_opaque_material`,
  `create_construction` and `assign_construction_to_surface`, then retry. Normal, not an edge case.
- **A Kiva surface may not carry windows or doors**, and a Kiva wall may not exceed four vertices.
- **Never set `Foundation` with `set_surface_boundary_conditions`.** EnergyPlus also needs a
  `Foundation:Kiva` object and a `SurfaceProperty:ExposedFoundationPerimeter`, and fails fatally
  without them. That tool now refuses the condition and points here.
- **Kiva needs a weather file at simulation time** — it cannot run design-day-only.
- **One 2D domain per floor** is an EnergyPlus rule, not a choice. Forty slabs is forty domains;
  past twenty the tool requires `confirm_many_domains=True`.
- **`Shallow` and `Deep` are inert** without a ground heat exchanger, and `FCfactorMethod` only
  affects F/C-factor constructions. Do not read four applied objects as four improvements.
- Neither tool saves. Call `save_osm_model`.

## Integration Test

- `tests/test_epw_ground_temperatures.py` — the EPW header parser (unit tier, no Docker)
- `tests/test_zone_heating_setpoints.py` — the setpoint derivation (unit tier)
- `tests/test_ground_temperatures.py` — the simple method end to end
- `tests/test_kiva_archetypes.py` — the archetype table and provenance (unit tier)
- `tests/test_kiva_foundation.py` — Kiva model state, including
  `test_forward_translation_emits_the_kiva_objects_without_errors`

The forward-translation test is a proxy: a missing exposed-perimeter object is a *runtime* fatal, so
it was also verified once by hand. EnergyPlus 25.2.0, Boston TMY3, one-week run, two slabs with
`slab_on_grade_perimeter_insulated`: `EnergyPlus Completed Successfully -- 8 Warning; 0 Severe
Errors`, with `eplusout.eio` reporting two Kiva foundations of 1053 cells each and a total exposed
perimeter of 30.00 m — the same number the tool computed. Details in the
`tests/test_kiva_foundation.py` module docstring.
