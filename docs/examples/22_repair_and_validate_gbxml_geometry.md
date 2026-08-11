# Example 22: Repairing & Validating gbXML-Imported Geometry

Catch overlapping surfaces and non-enclosed spaces from a gbXML import in one call, instead of a long manual diagnostic chain.

## Scenario

After `import_gbxml` (Example 21), a modeler wants to know whether the geometry Revit exported is
actually clean before doing anything else with it. The manual way to check this — `get_model_summary`,
`validate_model`, `list_surfaces`, `get_surface_details` per surface, `list_spaces(detailed=true)`,
`get_space_details` per space — is a long chain of separate tool calls, each a full round trip.
`repair_and_validate_gbxml_geometry` moves that whole diagnostic into one server-side call.

## Prompt

> I just imported a gbXML file. Check the geometry for overlapping surfaces and spaces that aren't
> fully enclosed before I do anything else with it.

## Tool Call Sequence

```
1. import_gbxml(gbxml_path="/inputs/25_SpacesOneZE.xml",
                 epw_path="/inputs/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
2. repair_and_validate_gbxml_geometry()
   → runs match_surfaces() internally first (fixes cross-space shared walls —
     156 surfaces matched on this model), then reports what that can't fix:
   { ok: false,
     cross_space_surfaces_matched: 156,
     space_count: 25, surface_count: 228,
     overlapping_surfaces_count: 0, overlapping_surfaces: [],
     non_enclosed_spaces_count: 14,
     non_enclosed_spaces: [
       {"space": "aim2860", "floor_area_m2": 7.46, "has_floor": true, "has_roofceiling": true},
       ... ] }
```

Two calls total, replacing what would otherwise be dozens.

On a messier real-world Revit export (`tests/assets/2026_11Ja_path1.xml`, a residential floor
plan — a second fixture, imported the same way as Example 21 but not covered there), the same call
also finds 9 same-space surface overlaps — a genuine source-geometry defect, not a false positive
(see `tests/test_gbxml_import.py::test_repair_and_validate_gbxml_geometry_detects_shared_wall_duplication_overlaps`).
Of that fixture's 14 non-enclosed spaces, 3 are missing a RoofCeiling surface entirely rather than
having a subtler non-manifold gap — see "Follow-up" below.

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `import_gbxml` | Translate gbXML -> OSM (Example 21) |
| `repair_and_validate_gbxml_geometry` | Fix cross-space shared walls (`match_surfaces()`, internal), then report same-space overlaps and non-enclosed spaces in one call |
| `repair_missing_roof_ceiling` | Follow-up fix for non-enclosed spaces that have a Floor but no RoofCeiling at all (see "Follow-up" below) |
| `merge_coplanar_sliver_surfaces` | Follow-up fix for non-enclosed spaces fragmented into many same-space coplanar pieces (see "Follow-up" below) |
| `weld_coincident_vertices` | Follow-up fix for non-enclosed spaces with sub-centimeter corner gaps between non-coplanar surfaces (see "Follow-up" below) |
| `patch_missing_surfaces` | Follow-up fix for non-enclosed spaces missing a surface (usually a partition wall) outright (see "Follow-up" below) |
| `trim_overlapping_surfaces` | Follow-up fix for non-enclosed spaces with a genuine same-space surface overlap (see "Follow-up" below) |
| `get_surface_details` | Only needed afterward, for a specific flagged surface pair, if the summary isn't enough to act on |

## Follow-up: `repair_missing_roof_ceiling`

Not every non-enclosed space has the same defect. Some have both a Floor and a RoofCeiling but
still fail `isEnclosedVolume()` (small non-manifold gaps between walls — see "Why Two Separate
Checks" below); others are missing a RoofCeiling entirely — common for small closets/cabinets
nested under a bigger room's ceiling in the source Revit model. `repair_missing_roof_ceiling()`
targets only the second case: it synthesizes a flat ceiling from the space's Floor + wall-top
geometry, but only when the floor is level and every wall reaches the same height — anything
sloped, stepped, or ambiguous (e.g. more than one Floor surface in a space) is reported as skipped,
not guessed at.

```
3. repair_missing_roof_ceiling()
   → { ok: true, repaired_count: 1,
       repaired: [{"space": "sp-9diningroomcloset", "area_m2": 0.6068,
                   "final_boundary_condition": "Adiabatic"}],
       skipped: [
         {"space": "sp-11mastercloset", "reason": "uneven wall heights, cannot auto-repair a flat ceiling"},
         {"space": "sp-4masterbedroom", "reason": "expected exactly 1 Floor surface, found 3"}] }
4. repair_and_validate_gbxml_geometry()   # confirm: non_enclosed_spaces_count 14 -> 13
```

On this residential fixture, only 1 of the 3 has-Floor/no-RoofCeiling spaces was actually safe to
auto-repair — the other 2 are symptoms of the same wall-duplication defect that causes the 9
surface overlaps above, not something a flat-ceiling repair should paper over.

## Follow-up: `merge_coplanar_sliver_surfaces`

The most common real-world cause of non-enclosed spaces isn't a missing surface at all — it's
`tests/assets/gbxml/austin_apartment_slivers.xml` (a 74-space Austin apartment/retail/office
building) that shows this: Revit's gbXML export splits one physical wall, floor, or ceiling into
many tiny same-space coplanar fragments, one per adjacent-room boundary segment. Fragment areas
still sum correctly (`zero_volume_zone_count` stays 0 on `import_gbxml`), but the seams between
fragments don't align to tight tolerance — 69 of that fixture's 74 spaces fail
`isEnclosedVolume()` even though every one of them already has both a Floor and a RoofCeiling.

```
3. merge_coplanar_sliver_surfaces()
   → groups same-space, coplanar, same-type fragments sharing a boundary condition and
     construction, joins their footprints with openstudio.joinAll(), and rebuilds fewer,
     larger Surface objects in their place. Re-runs match_surfaces() once, batched, if
     anything changed.
   { ok: true, merged_group_count: 28, merged: [...], skipped_group_count: 3, skipped: [...] }
4. repair_and_validate_gbxml_geometry()   # confirm: non_enclosed_spaces_count 69 -> 67
```

Mixed boundary conditions/constructions across a group, and any fragment carrying a subsurface
(window or door), are reported as skipped rather than guessed at — reparenting a subsurface onto a
newly-merged surface safely needs a containment check this tool doesn't attempt. This means it
isn't guaranteed to fully close every space in one pass; re-check with
`repair_and_validate_gbxml_geometry()` and treat the improvement, not a promise of `ok: true`, as
the signal.

## Follow-up: `weld_coincident_vertices`

A different, more common defect than either of the above: surfaces that are *not* coplanar (two
perpendicular walls, or a wall and the floor) whose shared corner is off by sub-centimeter float
noise. `Space.isEnclosedVolume()` (via `openstudio.model.Polyhedron` internally) has its own
undocumented, non-configurable internal vertex-merge tolerance — a synthetic box test found it
silently collapses a 0.012m corner offset (still reports enclosed) but not a 0.013m one — so this
snaps vertices *before* that check ever runs rather than relying on it being forgiving.

```
3. weld_coincident_vertices()
   → per space, runs every vertex of every surface through openstudio.getCombinedPoint()
     against a running per-space point pool, snapping each to an existing pool point
     within tolerance or adding it as a new one. Only rewrites a surface if welding
     actually moved one of its points. Re-runs match_surfaces() once, batched, if
     anything changed.
   { ok: true, welded_space_count: 22, welded: [...], skipped_surface_count: 8, skipped: [...] }
4. repair_and_validate_gbxml_geometry()   # confirm the effect on non_enclosed_spaces_count
```

Two of a surface's own vertices snapping onto the same point (a degenerate edge — happens on
naturally hairline-thin fragments) and near-zero resulting area are reported as skipped rather than
corrupted.

**On the Austin apartment fixture, this tool alone doesn't reduce `non_enclosed_spaces_count`
(69 -> 69)** even though it does real, verified work (22 spaces, real vertex snaps — see
`test_geometry.py`'s synthetic tests for proof the mechanism works in isolation): the spaces it
touches here have *other* simultaneous non-manifold edges beyond what a 2cm weld closes. Combined
with `merge_coplanar_sliver_surfaces()`, in either order, the fixture lands at the same 67 as
`merge_coplanar_sliver_surfaces()` alone — weld adds no *additional* closures on this specific
fixture, but causes zero regressions either (confirmed space-by-space, not just by count). Don't
assume running every available repair tool is strictly additive; measure the actual before/after on
your own model.

## Follow-up: `patch_missing_surfaces`

After the two tools above, 67 of the Austin fixture's 74 spaces were still non-enclosed. A direct
investigation into why — `Space.polyhedron().edgesNotTwo(True)`, the same manifold check
`isEnclosedVolume()` runs internally (note the `True` — `edgesNotTwo(False)` hides edges
Polyhedron's own internal colinear-point auto-heal step creates, understating the real defect on
some spaces) — found that 394 of 397 "bad" edges across those 67 spaces are used by exactly **one**
surface, not the two a closed volume requires: a genuinely missing surface, not a tolerance gap
(there's nothing to weld or join when the surface doesn't exist at all).

```
3. patch_missing_surfaces()
   → per space, finds every connected component of unpaired (count==1) edges
     independently (a space can have more than one separate hole), traces each into a
     loop, recursively splits a non-planar loop into planar facets via chords, and
     resolves a branch point (more than one missing surface meeting at a vertex) via a
     bounded search over ways to pair up its edges. Surface type is inferred from each
     facet's own geometry, not assumed to be a wall. Edges used 3+ times (a same-space
     overlap — a different defect) are excluded and reported separately, not allowed to
     block the rest of the space. Re-runs match_surfaces() once, batched; anything still
     unmatched afterward is set Adiabatic; every space is re-checked afterward rather
     than trusted, in case a new internal chord edge happens to coincide with an
     already-ambiguous pre-existing one.
   { ok: true, patched_count: 119, patched: [...], skipped_count: 5, skipped: [...] }
4. repair_and_validate_gbxml_geometry()   # confirm: non_enclosed_spaces_count 67 -> ~4
```

On the Austin fixture this reconstructs the large majority of the 67 remaining spaces' holes —
mostly missing partition walls, but one (`sp-1stair`) turned out to be a missing RoofCeiling,
confirming the surface type really is inferred, not hardcoded. Only a handful of components are
honestly skipped now (down from 32 in the tool's first version, before multi-component/chord-
splitting/branch-decomposition support): a same-space overlap (a different defect, see
"Follow-up: `trim_overlapping_surfaces`" below), a component whose edges don't form one simple
loop, and rarely a space where every component reported success but the post-patch re-check still
found it non-enclosed. Interestingly, many of the reconstructed walls' footprints recur identically
across several spaces (e.g. the same missing wall in four different apartments) — the same unit
type repeated across floors, all missing the same wall *type* in the source export, not several
unrelated one-off defects.

**A measured, honest caveat**: the exact `patched_count`/`skipped_count` on this fixture shift by
exactly 1 in either direction on a small fraction of runs (119/5 most often, occasionally 118/6) —
genuine run-to-run non-determinism, most likely in `Polyhedron`'s own internal edge ordering (C++,
not something this tool controls), tipping one borderline chord/pairing search to a different but
still-valid choice. The final `non_enclosed_spaces_count` and which specific spaces remain has been
stable across repeated runs regardless.

## Follow-up: `trim_overlapping_surfaces`

The flip side of a missing surface: a genuine same-space 2D overlap. Either a wall exported once
per neighboring room instead of split at the boundary between them (shared-wall duplication), or,
occasionally, a byproduct of `patch_missing_surfaces()` reconstructing a surface that
happens to coincide with something already there. Scoped to spaces currently failing
`isEnclosedVolume()` — a coplanar sliver artifact coexisting peacefully with an already-enclosed
space is not this tool's concern.

```
5. trim_overlapping_surfaces()
   → detects coincident-plane pairs with true 2D overlap area (the same
     openstudio.intersect() approach repair_and_validate_gbxml_geometry already uses for
     overlapping_surfaces), then replaces each surface's vertices with its own
     non-overlapping remainder, or removes it outright if fully contained within the
     other (full containment is asymmetric — the container is left untouched, not
     carved a hole into). A remainder splitting into multiple disjoint pieces is
     reported as skipped rather than guessed at.
   { ok: true, trimmed_count: 12, trimmed: [...], skipped_count: 16, skipped: [...] }
6. repair_and_validate_gbxml_geometry()   # confirm: non_enclosed_spaces_count ~4
```

On the Austin fixture, most trims are pure duplicates fully contained within another surface. A
same-run safety guard skips (rather than risks compounding) a second overlap touching a surface
already handled earlier in the same call — call it again to pick up the next one; it converges to
zero further trims.

**Combined total on this fixture: 69 -> 67 (weld + merge) -> 4 (patch + trim)** — all but 4 of the
original non-enclosed spaces closed by four automated, verified repair tools. The honest remainder
— `sp-14retail`, `sp-21restuarant`, `sp-35apartment`, `sp-6retail` — was checked directly, not
assumed: running `patch_missing_surfaces()` and `trim_overlapping_surfaces()` repeatedly
against each other reaches a **stable oscillation**, each pass's fix creating exactly the input the
other pass "fixes" right back, rather than converging further. These 4 spaces have a structurally
ambiguous mix of missing and duplicate geometry that neither tool can resolve alone — that's a
genuinely different, harder problem than anything the four tools above address, not a case to keep
looping against.

## Why Two Separate Checks

- **Same-space overlaps** (e.g. an accidental duplicate Floor surface): OpenStudio's own
  `intersectSurfaces()`/`matchSurfaces()` — what `match_surfaces()` calls — explicitly refuse to
  touch two surfaces within the *same* space; they only reconcile shared walls *between* adjacent
  spaces. There's no SDK method for same-space duplicate detection, so this is computed directly:
  coincident-plane surfaces (`Plane.equal`/`Plane.reverseEqual`) are checked for true 2D overlap
  area via `openstudio.intersect()` — not just `openstudio.intersects()`, which returns `True` even
  for two surfaces that merely *touch* along a shared edge (e.g. adjacent wall segments split at a
  window), which would otherwise flood the report with false positives.
- **Non-enclosed spaces**: `Space.volume()` never signals failure — on non-manifold geometry it
  silently falls back to `ceilingHeight() * floorArea()` and only logs a C++ warning. The robust
  check is the boolean `Space.isEnclosedVolume()`. On the fixture above, all 14 flagged spaces
  *do* have both a Floor and a RoofCeiling surface (`has_floor`/`has_roofceiling` both `true`) —
  the actual defect is small non-manifold gaps between wall surfaces, which a naive
  "does a Floor/RoofCeiling exist" check would have missed entirely.

## Common Pitfalls

- **`overlapping_surfaces_count == 0` doesn't mean the geometry is perfect** — it means no *same-space*
  duplicate overlaps were found. `non_enclosed_spaces_count` is a separate, independent signal.
- **The response has a side effect**: `repair_and_validate_gbxml_geometry()` mutates the model via
  `match_surfaces()` before reporting (by design — the majority "shared wall left as Outdoors" case
  gets fixed for free). If you need to inspect the model *before* any matching runs, call
  `match_surfaces()` yourself only after checking, or save a copy of the model first.
- **A large `non_enclosed_spaces_count` isn't necessarily a bug in the tool** — it's often a genuine
  property of the source gbXML/Revit export. Real CAD-to-gbXML translations frequently produce
  small sub-centimeter gaps between adjacent surfaces that a Floor/RoofCeiling presence check alone
  would never catch.

## Integration Test

See `tests/test_gbxml_import.py::test_repair_and_validate_gbxml_geometry_on_real_import`,
`::test_repair_and_validate_gbxml_geometry_detects_same_space_overlap`,
`::test_repair_and_validate_gbxml_geometry_detects_non_enclosed_space`,
`::test_repair_and_validate_gbxml_geometry_detects_shared_wall_duplication_overlaps`,
`::test_repair_missing_roof_ceiling_on_shared_wall_duplication_fixture`, and
`::test_geometry_repair_pipeline_on_austin_apartment_fixture` (covers
`merge_coplanar_sliver_surfaces`, `weld_coincident_vertices`, `patch_missing_surfaces`, and
`trim_overlapping_surfaces` together on the same real fixture — the 69/67/4 numbers above come from
this test). `repair_missing_roof_ceiling`, `merge_coplanar_sliver_surfaces`,
`weld_coincident_vertices`, `patch_missing_surfaces`, and `trim_overlapping_surfaces`
themselves also have synthetic-geometry tests in `tests/test_geometry.py`
(`test_repair_missing_roof_ceiling_synthesizes_flat_ceiling`,
`test_repair_missing_roof_ceiling_skips_uneven_walls`,
`test_merge_coplanar_sliver_surfaces_merges_split_ceiling`,
`test_merge_coplanar_sliver_surfaces_skips_mixed_boundary_conditions`,
`test_merge_coplanar_sliver_surfaces_skips_fragments_with_subsurfaces`,
`test_merge_coplanar_sliver_surfaces_no_op_on_clean_model`,
`test_weld_coincident_vertices_closes_corner_gap`,
`test_weld_coincident_vertices_leaves_large_offset_alone`,
`test_weld_coincident_vertices_skips_degenerate_same_surface_collapse`,
`test_weld_coincident_vertices_no_op_on_clean_model`,
`test_patch_missing_surfaces_reconstructs_deleted_wall`,
`test_patch_missing_surfaces_splits_non_planar_hole_into_two_facets`,
`test_patch_missing_surfaces_patches_multiple_disjoint_holes_independently`,
`test_patch_missing_surfaces_skips_same_space_overlap`,
`test_patch_missing_surfaces_no_op_on_clean_model`,
`test_trim_overlapping_surfaces_trims_partial_overlap`,
`test_trim_overlapping_surfaces_removes_fully_contained_duplicate`,
`test_trim_overlapping_surfaces_no_op_when_no_non_enclosed_spaces_have_overlaps`).
