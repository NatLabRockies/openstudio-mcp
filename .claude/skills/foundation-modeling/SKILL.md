---
name: foundation-modeling
description: Choose and apply a ground heat transfer method — EPW ground temperatures for a fast approximate answer, or EnergyPlus Kiva for real slab-edge heat transfer. Use when a model has no ground temperatures, when slab or basement heat loss matters, or when the user asks about foundations, slabs, basements or crawlspaces.
---

# Foundation and ground heat transfer

Two methods, and they are not interchangeable. Pick deliberately.

| | `set_ground_temperatures` | `set_kiva_foundation` |
|---|---|---|
| What it does | Writes the four `Site:GroundTemperature:*` objects from the EPW header | Solves a 2D finite-difference soil domain per floor |
| Needs from the user | Nothing | The foundation type, and ideally real insulation detail |
| Simulation cost | None | Substantial — one domain per floor |
| Good for | Screening runs, compliance work, models with no foundation information | Slab-edge loss, basement-dominated buildings, studying the foundation itself |

**Default to the simple method.** Reach for Kiva when the foundation is what the question is about,
or when the user asks for it. A Kiva surface ignores `Site:GroundTemperature:BuildingSurface`
entirely, so the two do not stack.

## The simple method

```
1. set_ground_temperatures()
```

Resolves the EPW itself — the one `import_gbxml` used, or the model's own weather file. Writes
`Shallow`, `Deep` and `FCfactorMethod` from the EPW's measured values, and derives
`BuildingSurface` from the model's heating setpoints.

**Why `BuildingSurface` is not written from the EPW:** those are *undisturbed* soil temperatures, an
open field with no building on it. The EPW's own `.stat` file says they "should NOT BE USED in the
GroundTemperatures object to compute building floor losses". Boston's January figure is −0.29 °C;
writing that under a heated slab overstates the loss badly.

If the model has no thermostats yet, `BuildingSurface` is skipped with a reason — run it again after
HVAC, or state the value:

```
2. set_ground_temperatures(building_surface_method="constant", building_surface_constant_c=18.0)
```

## The detailed method: Kiva

**Always call `get_foundation_options()` first, then ask the user.** Do not pick an archetype for
them.

```
1. get_foundation_options()
```

It reports which floors and below-grade walls EnergyPlus would accept, why each rejected surface was
rejected, the exposed perimeter computed from the building footprint, how many Kiva domains would be
created, and the five archetypes **with their full parameter sets**.

### Put the choice to the user

Show them the archetype list with its actual numbers — not just the names. Ask which describes the
building's foundation:

- **Slab on grade, uninsulated**
- **Slab on grade with perimeter insulation**
- **Heated basement, insulated walls**
- **Unheated basement**
- **Vented crawlspace**

**Say plainly that the R-values are conventional starting points, not code-derived.** There is no
vendored source for Kiva insulation geometry, so the archetype numbers are a way to skip a
ten-question interrogation, not a substitute for knowing the building. Each archetype carries a
`basis` string saying so, and the response reports the ASHRAE 90.1 F-factor / C-factor target for
the model's climate zone as a cross-check. If the user knows their real insulation, take it.

### Apply it

```
2. set_kiva_foundation(archetype="heated_basement_insulated")
```

Overriding anything the user does know:

```
3. set_kiva_foundation(archetype="slab_on_grade_perimeter_insulated",
     exterior_vertical_insulation_r_si=3.52,
     exterior_vertical_insulation_depth_m=1.2)
```

Use `dry_run=True` to show the user exactly what would be written before committing:

```
4. set_kiva_foundation(archetype="unheated_basement", dry_run=True)
```

## What to check in the result

- **`provenance` on every value** — `user`, `archetype:<name>`, `epw_header`,
  `openstudio_default`, or `computed_geometry`. Anything marked `archetype:*` is a number nobody
  sourced; report that to the user rather than presenting the result as measured.
- **`ground_temperature_interaction`** — if `set_ground_temperatures` ran earlier, this says which
  surfaces Kiva now governs and whether `BuildingSurface` still applies to anything.
- **`warnings`** — unpaired below-grade walls, clamped interior bays, missing soil properties.

## Expect refusals, and do not treat them as failures

EnergyPlus is strict about Kiva surfaces, and the tool refuses rather than writing a model that
fails at run time:

- **Massless construction layers are the most common blocker on a real Revit model.** gbXML slabs
  routinely carry no-mass layers and EnergyPlus refuses them outright. Fix with
  `create_standard_opaque_material`, `create_construction` and `assign_construction_to_surface`,
  then retry. This is normal, not an edge case.
- Windows or doors on the surface — not allowed with a Foundation boundary condition.
- Walls with more than four vertices.
- Surfaces with no parent space.
- More than 20 eligible floors requires `confirm_many_domains=True`, because that is 20 separate 2D
  domains and a much slower simulation.

Never set `Foundation` with `set_surface_boundary_conditions` — EnergyPlus also needs a
`Foundation:Kiva` object and an exposed-perimeter object, and fails fatally without them.
`set_kiva_foundation` writes all three together, and the other tool refuses the condition for that
reason.

## After either method

Kiva needs a weather file at simulation time — EnergyPlus will not run it design-day-only. Neither
tool saves; call `save_osm_model` to persist.
