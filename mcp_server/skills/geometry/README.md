# geometry skill — internal notes

Most of this package is gbXML repair (see `mcp_server/skills/gbxml_import/README.md` for the defect
catalogue those tools address). This note covers only the Kiva foundation work, because its
constraints were expensive to establish and are not discoverable from the OpenStudio API.

## Kiva: what EnergyPlus actually enforces

Read out of the EnergyPlus 25.2.0 binary's own error strings, not from documentation:

| Rule | Consequence |
|---|---|
| only one floor per `Foundation:Kiva` | one Kiva object **per floor surface**, always |
| floor and wall surfaces only | anything else is refused |
| a `Foundation` surface with no `SurfaceProperty:ExposedFoundationPerimeter` | **fatal** |
| Kiva walls must have ≤ 4 vertices | refused |
| `"Foundation" ... must use only regular material objects` | no massless / no-mass / air-gap layers |
| `Exterior boundary condition = Foundation is not allowed with windows` | no subsurfaces |
| requires a weather file | Kiva cannot run design-day-only |
| paired wall lengths ≤ the floor's exposed perimeter | validated before writing |

`kiva_surface_blockers()` in `kiva_eligibility.py` checks every one that is cheap, and refuses the
surface with a reason rather than writing a model that dies at run time. On a real Revit model the
massless-layer rule is the most common outcome — `openstudio.model.exampleModel()`'s own floors fail
it on `CP02 CARPET PAD`.

## Three SDK traps, all verified by probe

**1. `Surface.exposedPerimeter()` segfaults on a surface with no parent Space.** No Python
exception, no error dict — the interpreter dies and takes the MCP session with it. gbXML imports
produce parentless surfaces routinely (that is why `patch_missing_surfaces` exists). `_has_space()`
guards every call and `test_space_less_floor_is_reported_not_crashed` is the regression.

**2. `createSurfacePropertyExposedFoundationPerimeter(method, value)` reports success when it
silently discarded the input.** It returns an initialized Optional either way:

| call | initialized | method reads back |
|---|---|---|
| `("TotalExposedPerimeter", 12.0)` | True | `'TotalExposedPerimeter'` |
| `("ExposedPerimeterFraction", 1.0)` | True | `'ExposedPerimeterFraction'` |
| `("Calculate", 12.0)` | **True** | `''` |
| `("Bogus", 12.0)` | **True** | `''` |

An out-of-range fraction (a fraction must be 0..1) gets the same treatment — method set, value
unset. So the method is whitelisted here, the value is range-checked against it, and
`_write_exposed_perimeter()` reads both back and compares. `is_initialized()` is never treated as
success. `BySegment` is legal in the IDD but not offered: EnergyPlus cannot auto-correct a clockwise
floor polygon under it, OpenStudio exposes no segment API, and gbXML winding is exactly what
`weld_coincident_vertices` exists to clean up.

**3. `Surface.setAdjacentFoundation()` leaves `SunExposed`/`WindExposed` intact.** It sets the
boundary condition but not the exposure, so a buried slab would keep taking solar gain — the same
defect `ground_contact.py`'s docstring is about. `setOutsideBoundaryCondition("Foundation")` is
called **first** because that one derives NoSun/NoWind.

Also: `model.getFoundationKivaSettings()` creates the unique object;
`getOptionalFoundationKivaSettings()` does not. Same hazard as the `Site:GroundTemperature:*`
objects in `weather/ground_temperatures.py`, and the read paths use the Optional form throughout.

## Exposed perimeter

The only recipe that works:

```python
polys = openstudio.Point3dVectorVector()
for f in every_at_or_below_grade_floor:      # ALL of them, not just the selected ones
    polys.append(f.space().get().transformation() * f.vertices())
joined = openstudio.joinAllPolygons(polys, 0.01)
exposed = sum(f.exposedPerimeter(j) for j in joined)
```

A hand-built `Polygon3d` returns 0.0 — the winding does not match. Neighbouring floors must be in the
join or an interior bay will not correctly score zero. Disjoint wings produce several polygons and
each floor scores against exactly one, so summing across them is required. A computed zero is clamped
to `MIN_EXPOSED_PERIMETER_M` (Kiva rejects a zero perimeter), matching the vendored `tbd` gem.

## The archetype numbers, and what they are not

`kiva_archetypes.py` carries five foundation types. **There is no vendored basis for Kiva insulation
geometry in this image, and the module says so rather than implying one:**

- openstudio-standards has 90 `GroundContact*` rows, but as F-factor and C-factor — code performance
  per unit perimeter, with no insulation depth, width or position. Inverting them needs ASHRAE 90.1
  Appendix A tables that are not vendored.
- NECB's `apply_kiva_foundation` applies no insulation at all; ComStock has none.
- The `tbd-3.5.0` gem supplies the XPS properties and the 0.6 m interior-horizontal width. Those are
  cited; everything else is a conventional starting point carrying a `basis` string that says so.

The 90.1 F/C-factor target for the model's climate zone is reported alongside as a cross-check, which
is what that data legitimately is.

Provenance is not decoration. `wall_height_above_grade = 0.2` is both the archetype value and the IDD
default, so where they agree the field is left defaulted and reported as
`openstudio_default (archetype agrees)` — claiming `archetype:*` for a field never written would make
the whole mechanism theatre.

## File layout

| File | Role |
|---|---|
| `kiva_archetypes.py` | The table, R→thickness, provenance merge. **No `openstudio` import** — unit-testable. |
| `kiva_eligibility.py` | Blockers, candidate classification, wall pairing, exposed perimeter. |
| `kiva_foundation.py` | Read side: `get_foundation_options`, code targets, object helpers. |
| `kiva_apply.py` | Write side: `set_kiva_foundation`. |
| `tools_kiva.py` | MCP registration, split out because `tools.py` was already at ~389/400 lines. |

## Interaction with `Site:GroundTemperature:*`

A `Foundation` surface ignores `Site:GroundTemperature:BuildingSurface` entirely, and Kiva is
incompatible with the F/C-factor constructions that `FCfactorMethod` affects. `set_kiva_foundation`
reports this in `ground_temperature_interaction`, and
`weather/ground_temperatures.find_missing_ground_temperatures()` goes quiet about BuildingSurface once
every ground-coupled surface is Kiva — otherwise `repair_and_validate_gbxml_geometry` nags forever at
the user who did the higher-fidelity thing.
