---
name: gbxml-import
description: Translate a Revit-exported gbXML file into an OpenStudio model, then repair common export geometry defects (non-enclosed spaces, duplicate/missing surfaces). Use when importing gbXML, or when a gbXML-derived model has non-enclosed spaces or surface overlaps.
---

# gbXML Import

## Workflow

1. `import_gbxml(gbxml_path=..., epw_path=..., ...)` (optional `osm_path`, `run_name`) — needs four files under
   `/inputs`: the gbXML file, its project EPW, and the EPW's companion `.stat`/`.ddy` files
   (same directory, same filename stem as the EPW). Result auto-loads the model and always
   returns a `climate_zone` (+ `climate_zone_source`) unless truly unresolvable — if
   `climate_zone_resolved` is `false`, call `change_building_location` explicitly before any
   ASHRAE 90.1 baseline work.
2. `repair_and_validate_gbxml_geometry()` — always run next. Fixes shared walls left as
   "Outdoors" internally and re-synchronizes desynchronized interior surface pairs, then reports
   `overlapping_surfaces_count`, `non_enclosed_spaces_count`, and
   `paired_vertex_mismatches_skipped_count` for what it can't fix on its own.
3. If all three counts are `0`, done. Otherwise diagnose and repair — see below.

## Fixing non-enclosed spaces

Five distinct causes, each needing a different tool — none are fixed automatically by
`repair_and_validate_gbxml_geometry()`'s internal `match_surfaces()` call. Work through them in
this order, re-checking with `repair_and_validate_gbxml_geometry()` after each:

1. **Missing RoofCeiling entirely** (`has_floor: true`, `has_roofceiling: false` in the report)
   → `repair_missing_roof_ceiling()`. Only synthesizes a flat ceiling when the floor is level and
   walls are a uniform height; sloped or ambiguous spaces are skipped with a reason.
2. **Fragmented surfaces** (has both Floor and RoofCeiling, but Revit split one physical
   wall/floor/ceiling into many tiny same-space coplanar pieces) → `merge_coplanar_sliver_surfaces()`.
3. **Sub-centimeter corner gaps** (non-coplanar surfaces meeting at a corner off by float noise)
   → `weld_coincident_vertices()`.
4. **A surface missing outright** (usually an interior partition wall dropped from the export,
   often the same wall missing from every stacked instance of a repeated unit type) →
   `patch_missing_surfaces()`.
5. **Same-space overlap** — shared-wall duplication: a wall exported once per neighboring room
   instead of split at the shared boundary, leaving a duplicate; or a byproduct of
   `patch_missing_surfaces()` reconstructing a surface that happens to coincide with existing
   geometry → `trim_overlapping_surfaces()`.

Run the merge/weld pair before the patch/trim pair — patch and trim work off whatever gap is
left once merge and weld have closed what they can.

## Notes

- None of the five repair tools guarantee full closure in one pass, and they aren't strictly
  additive — a space can carry more than one defect at once, and `patch_missing_surfaces()` /
  `trim_overlapping_surfaces()` can oscillate against each other on structurally ambiguous
  geometry (each pass recreates the other's input). Re-run
  `repair_and_validate_gbxml_geometry()` to confirm actual progress rather than assuming success.
- Ambiguous cases are always reported as skipped with a specific reason, never guessed at.
  That includes geometry too tangled to resolve affordably — a hole converging on a very
  high-degree vertex is reported rather than searched, so these tools stay bounded on
  arbitrarily malformed input.
- **Check `ambiguous_boundary_condition_count` after `patch_missing_surfaces()`.** A
  reconstructed surface that `match_surfaces()` couldn't pair is set `Adiabatic` with
  `NoSun`/`NoWind` and flagged `boundary_condition_ambiguous`. That is an assumption, not a
  determination: these facets are topological closures traced from a hole's outline, so zero
  heat flux keeps a surface the tool can't physically identify from inventing or destroying
  load. It is wrong for a genuinely exterior wall or roof the export dropped — override those
  with `set_surface_boundary_conditions(surface_names=[...],
  outside_boundary_condition="Outdoors")`, which takes the whole flagged list in one call and
  keeps sun/wind exposure coherent with the condition automatically. Expect this count to be
  large on a badly broken export; on the project's own test fixture it is 103 of 117 patches.
- **Also check `construction_fallback_count` after `patch_missing_surfaces()`.** Each patch gets a
  construction copied from existing geometry (these models rarely have a default construction set,
  and E+ fails without one). `construction_source` says where it came from per surface — `partner`
  and `same_boundary` are safe; `type_only_fallback` means the only donor available had a
  *different* boundary condition, so an exterior assembly may now sit on an interior surface.
  `construction_warnings` explains it once rather than per surface. Review those before trusting
  results, and correct any that are wrong with `assign_construction_to_surface`.
- `trim_overlapping_surfaces()` only trims a pair that is genuinely the same thing twice
  (matching type, boundary condition, and construction, neither carrying a window or door).
  Anything else is reported as skipped — resolve those by hand rather than expecting the
  tool to pick a winner.
- **Check `ground_contact_missing_count`.** gbXML exports under-declare ground contact and the
  translator reproduces the omission — the repo's own basement fixture ends up with 1 Ground
  surface out of 292. A buried slab or basement wall left `Outdoors` takes fictitious solar gain
  and wind convection. `repair_and_validate_gbxml_geometry()` reports it (z = 0 is grade) but
  never fixes it. Fix in one batched call:
  `set_surface_boundary_conditions(surface_names=[<the reported names>],
  outside_boundary_condition="Ground")` — it sets `NoSun`/`NoWind` automatically. **Review the
  list first**: a slab over a crawlspace or open parking is not ground contact, and a wall only
  partly below grade gets its above-grade portion buried too. `partially_below_grade` holds walls
  crossing grade with less than half buried — reported, not proposed for a batch fix. `ok` is
  unaffected by any of this, so it will not stop you; check the count yourself.
- **The repair tools above can desynchronize interior surface pairs**, since each rewrites one
  side of a pair in isolation. Two sides with different vertex counts make EnergyPlus abort at
  `GetSurfaceData` before simulating — nothing else in this server catches it, `validate_model`
  included, and `match_surfaces()` counts surfaces rather than consistent pairs so a broken pair
  looks healthy there. `repair_and_validate_gbxml_geometry()` re-synchronizes automatically on
  every call, so running it after each repair (as instructed above) is what keeps the model
  simulable. Check `paired_vertex_mismatches_skipped` — those are pairs it would not guess at (a
  side carrying windows/doors, a mirrored polygon that collapses, or a mirror that would have left
  a space with more unpaired edges than it had, which is rolled back), and they still block
  simulation. `paired_area_mismatches` is informational: E+ accepts those.
- `repair_and_validate_gbxml_geometry()` mutates the model (via `match_surfaces()` and the pair
  sync) before reporting — if you need to inspect pre-match state, save a copy of the model first.
- After geometry is clean, spaces still need standards space types — see the
  `attribute-space-types` skill.
