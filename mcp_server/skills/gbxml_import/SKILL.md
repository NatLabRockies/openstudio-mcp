# gbxml_import

Translate a gbXML file (typically exported from Revit 2022+) into an OpenStudio `.osm` model.

## Why

gbXML carries geometry, space, and HVAC-system data authored in Revit. Rather than parsing it
directly, this skill runs it through the same measures Revit's own OpenStudio CLI workflow uses
(NatLabRockies/gbxml-to-openstudio), via `openstudio run --measures_only`, so the model comes out
exactly as that pipeline would build it — without ever invoking EnergyPlus.

## Flow

1. The user places **four files** under `/inputs`: the gbXML file, its project EPW, and the
   EPW's companion `.stat` and `.ddy` files (same directory, same filename stem as the EPW).
2. `import_gbxml(gbxml_path, epw_path[, osm_path, run_name])`
3. Steps run: `ChangeBuildingLocation` → `gbxml_import` → `gbxml_import_advanced` →
   `gbxml_import_hvac` → `set_simulation_control` → `gbxml_postprocess`. These are vendored
   measure names from `NatLabRockies/gbxml-to-openstudio`, not this skill or its
   `import_gbxml`/`repair_and_validate_gbxml_geometry` tools — the `gbxml_import` measure step
   is a coincidentally-identical name, not a self-reference.
   `ChangeBuildingLocation` always runs, even though no simulation ever does —
   `gbxml_import_advanced` reads the model's WeatherFile timezone while building
   schedules and errors out without one. This is also what embeds the project's
   real location in the resulting `.osm`, rather than a placeholder.
4. Result includes `osm_path` (auto-loaded as the current session model), plus per-step
   `error`/`warning` messages and `total_errors`/`total_warnings` counts. It also always includes
   a guaranteed climate zone and a conditioned-zone volume check — see "Climate zone and zone
   volume guarantees" below.
5. `repair_and_validate_gbxml_geometry()` — checks the (now-loaded) model for same-space overlaps and
   non-enclosed volumes match_surfaces() can't fix, and re-synchronizes interior surface pairs whose
   two sides disagree on vertex count. One call replaces the manual
   list_surfaces/get_surface_details/list_spaces/get_space_details diagnostic chain — see "Why
   repair_and_validate_gbxml_geometry" below.
6. Pass `osm_path` (or the auto-loaded session model) to any model-query/model-management tool.

## Where the measures come from

Baked into the Docker image at build time from a **pinned release tag** of
`NatLabRockies/gbxml-to-openstudio` (see `GBXML_TO_OS_TAG` in `docker/Dockerfile`), extracted to
`GBXML_MEASURES_DIR` (measures) and `GBXML_SEED_OSM` (the empty seed model the workflow starts
from). Bumping to a newer measures release is a one-line `ARG GBXML_TO_OS_TAG=...` change +
rebuild — no code changes needed.

## Climate zone and zone volume guarantees

`import_gbxml` runs two extra checks automatically after the model loads — no separate tool call:

- **ASHRAE climate zone**: the vendored `ChangeBuildingLocation` measure sets a climate zone by
  regexing the project's `.stat` file, but on a regex miss it doesn't fail — it silently writes the
  literal string `"Lookup From Stat File"` into the model as if it were a real value. `import_gbxml`
  re-validates whatever the measure left behind; if it's missing or garbage, it re-resolves in order:
  re-parse the same `.stat` file directly, then an ASHRAE-zone-by-WMO-station lookup (exact hash
  match, falling back to Haversine nearest-station by lat/lon) over a bundled ~2,570-station
  reference table. Result fields: `climate_zone`, `climate_zone_source` (`gbxml_measure`, `stat_file`,
  or `wmo_or_geographic_lookup`), `climate_zone_resolved`. If every tier misses, the zone is left
  unresolved (`climate_zone_resolved: false`, `climate_zone_warning` set) rather than guessing —
  `ok` stays `true`, but any downstream ASHRAE 90.1 baseline work needs `change_building_location`
  called explicitly first.
- **Conditioned zone volume**: flags conditioned (non-plenum, thermostat-assigned) thermal zones with
  zero or uncomputable volume — a sign of the same enclosure defects
  `repair_and_validate_gbxml_geometry` catches at the Space level, but one that specifically corrupts
  autosized equipment capacities. Result fields: `conditioned_zone_count`, `zero_volume_zone_count`,
  `zero_volume_zones`, `zero_volume_warning`. This is diagnostic only — fix flagged zones the same way
  as any other non-enclosed-space finding (`repair_missing_roof_ceiling`, then re-check).

## Why `repair_and_validate_gbxml_geometry`

gbXML/Revit exports commonly produce two geometry problems: shared walls between adjacent spaces
left as "Outdoors" instead of matched interior boundaries, and spaces missing a Floor or
RoofCeiling surface (breaking volume calculation). OpenStudio's own `intersectSurfaces()`/
`matchSurfaces()` (the existing `match_surfaces()` tool) fix the first case but — by design in the
SDK — never touch surfaces within the same space, so they can't fix true duplicate/overlapping
geometry. `repair_and_validate_gbxml_geometry()` runs `match_surfaces()` first, then re-synchronizes
desynchronized interior pairs (see "Paired-vertex desync" below), then reports same-space
overlaps (via coincident-plane + 2D polygon-intersection checks) and non-enclosed-volume spaces
(via `Space.isEnclosedVolume()`, not `volume() == 0` — volume() silently falls back to
`ceilingHeight * floorArea` on non-manifold geometry rather than signaling failure). One call
replaces what would otherwise be a long chain of `list_surfaces`/`get_surface_details`/
`list_spaces`/`get_space_details` calls.

For non-enclosed spaces that have a Floor but no RoofCeiling at all (common for small
closets/cabinets nested under a bigger room's ceiling in the source Revit model), follow up with
`repair_missing_roof_ceiling()` (geometry skill) to synthesize the missing surface, then call
`repair_and_validate_gbxml_geometry()` again to confirm. It only repairs spaces with a level floor
and uniformly level wall tops — anything sloped or ambiguous is reported as skipped rather than
guessed at.

For non-enclosed spaces that already have both a Floor *and* a RoofCeiling — the more common
real-world case, and one that can affect the large majority of spaces in a model — four distinct
defects cause this, and none are fixed by `match_surfaces()`:

- **Same-plane fragmentation**: Revit exporting one physical wall/floor/ceiling as many tiny
  same-space coplanar fragments (one per adjacent-room boundary segment). Areas still sum
  correctly, but the seams between fragments don't align to tight tolerance.
  `merge_coplanar_sliver_surfaces()` (geometry skill) groups same-space, coplanar, same-type
  fragments that share a boundary condition and construction and joins them back into fewer,
  larger surfaces.
- **Corner gaps**: surfaces that are *not* coplanar (e.g. two perpendicular walls, or a wall and
  the floor) whose shared corner is off by sub-centimeter float noise from the export.
  `weld_coincident_vertices()` (geometry skill) snaps each space's near-coincident vertices to a
  shared point before `Space.isEnclosedVolume()` (via `openstudio.model.Polyhedron`) ever runs —
  that check has its own undocumented, non-configurable internal snap tolerance, so it can't be
  relied on to be forgiving.
- **Missing surfaces**: a surface (usually an interior partition wall) dropped outright from the
  export — often systematically, e.g. the same wall missing from every stacked instance of a
  repeated apartment unit type across floors, not a random one-off.
  `patch_missing_surfaces()` (geometry skill) uses `Space.polyhedron().edgesNotTwo(True)` —
  the same manifold check `isEnclosedVolume()` runs internally, with `includeCreatedEdges=True`;
  `False` hides edges Polyhedron's own internal auto-heal step creates and understates the real
  defect — to find edges used by only one surface (a missing partner, not a tolerance gap), and
  reconstructs the surface(s) independently per separate hole: splitting a non-planar loop into
  planar facets via chords, and resolving a branch point (more than one missing surface meeting at
  a vertex) by pairing up its edges. Both searches are explicitly cost-bounded
  (`MAX_BRANCH_DEGREE`, `MAX_PAIRING_CANDIDATES`, `MAX_FACET_SPLIT_CANDIDATES` in
  `geometry/edge_topology.py` and `geometry/planar_facets.py`) — pairing a branch vertex's edges
  enumerates `(deg-1)!!` matchings, which is 105 at degree 8 but 654,729,075 at degree 20, and
  tool calls have no timeout and run on a thread that can't be cancelled. Anything past the caps
  is reported as skipped. A patched surface that `match_surfaces()` can't pair is set `Adiabatic`
  with `NoSun`/`NoWind` and flagged `boundary_condition_ambiguous` (counted in
  `ambiguous_boundary_condition_count`) — an assumption made visible rather than silently, which
  was the actual review finding. Adiabatic because these facets are topological closures traced
  from a hole's outline and need not correspond to a real building element; measured on the Austin
  fixture, 101 of them have no surface in any other space sharing their plane at all. Exposure must
  follow the boundary condition: a new `Surface` defaults to `SunExposed`/`WindExposed`, harmless
  against an adiabatic face but a live error (fictitious solar/wind on 100+ surfaces) if one is
  left `Outdoors`. Before assuming, a fallback pass pairs any two still-unmatched surfaces
  overlapping ≥99% of *both* their areas — `matchSurfaces()` uses an internal ~0.0125 m tolerance
  and misses patches that land a few centimetres off their counterpart (2 such pairs on the Austin
  fixture; a third candidate at 72% overlap is correctly declined). Override the remainder with
  `set_surface_boundary_conditions`, which takes the flagged names in one call.
- **Same-space overlaps** (aka shared-wall duplication): the flip side of a missing surface — a
  wall exported once per neighboring room instead of split at the boundary between them, leaving
  a surface duplicated, or a byproduct of patching a missing surface that happens to coincide
  with something already there. `trim_overlapping_surfaces()` (geometry skill) trims each side of a
  genuine 2D overlap to its own non-overlapping remainder, or removes it outright if fully
  contained within the other. Scoped to spaces currently failing `isEnclosedVolume()` — it never
  touches an overlap that coexists peacefully with an already-enclosed space. Only pairs that are
  genuinely the same thing twice are trimmed (same surface type, boundary condition, and
  construction, neither carrying a subsurface) — the same guards
  `merge_coplanar_sliver_surfaces()` uses, and for the same reason: `Surface.remove()` cascades
  to child windows/doors, and shrinking a parent strands them outside it.

## Paired-vertex desync

A fifth defect, distinct from the four above in two ways: nothing in the model reports it, and the
four repair tools are what *cause* it. An interior boundary is two Surfaces pointing at each other
via `adjacentSurface()`, and EnergyPlus requires both to describe the same polygon with the same
vertex count. When they disagree, E+ aborts at `GetSurfaceData` before simulating at all
(`Vertex size mismatch between base surface ... and outside boundary surface`). `validate_model`
has no geometry checks, and `match_surfaces()` doesn't catch it either — its returned count is a
count of *surfaces* whose boundary condition is `"Surface"`, not of consistent *pairs*, so a
mismatched pair increments it twice and looks healthy.

Each repair tool mutates one side of a pair in isolation: `merge_coplanar_sliver_surfaces()`
replaces a survivor's vertices while the survivor keeps its live `adjacentSurface` pointer, and
`weld_coincident_vertices()` runs a per-space vertex pool (so one physical corner can snap to
different coordinates in two adjacent spaces) and can skip one side as degenerate while rewriting
the other. `repair_and_validate_gbxml_geometry()` therefore re-synchronizes automatically on every
call — no separate tool — mirroring the authoritative side (largest area, then higher vertex count,
then name; converted through world coordinates, so a space origin can't displace the result) onto
its partner. Result fields: `paired_vertex_mismatches_repaired`,
`paired_vertex_mismatches_skipped`, `paired_area_mismatches`, each with a `_count`.

Skipped pairs set `ok` to `false` — they still block simulation. Three cases are skipped rather
than guessed at, each reported with a reason: a side carrying subsurfaces is never rewritten (its
windows and doors are positioned against the polygon it has); a mirrored result that collapses to
near-zero area is abandoned; and **any mirror that leaves either space with more unpaired edges
than it had is rolled back**.

That third guard is the important one. A vertex-count mismatch is *not* always a desync to mirror:
when `merge_coplanar_sliver_surfaces()` has collapsed one space's wall into a single surface while
the neighbour's side is still tiled into fragments, the two sides legitimately differ, and
overwriting the fragment with the merged polygon leaves the neighbour overlapping itself. Measured
on the Austin fixture, mirroring unguarded cost three spaces (4 non-enclosed became 7) and pushed
`patch_missing_surfaces()` off its known-good result (117/5/2/103 → 119/8/2/106). With the guard,
5 of the 7 candidate mirrors are rolled back and the pipeline lands on its expected numbers while
the 2 genuine desyncs are still repaired. `isEnclosedVolume()` is too coarse to catch this — most
spaces are *already* non-enclosed when the sync runs, so a closed→open test never fires — which is
why the guard measures `polyhedron().edgesNotTwo(True)`, the same metric
`patch_missing_surfaces()` works from. Pairs whose vertex counts agree but whose areas differ are listed
in `paired_area_mismatches` and never reshaped — E+ accepts them, `matchSurfaces()` has its own
~0.0125 m internal tolerance, and reshaping on that weaker signal would be exactly the guess these
tools refuse to make.

## Missing ground connections

A sixth defect, and unlike the others it does not stop the model simulating — it just makes the
answer wrong. Revit exports under-declare ground contact and the translator faithfully reproduces
the omission. Measured on this repo's fixtures: `2026_11Ja_path1.xml` is a building **with a
basement** whose translated model carries exactly **1 Ground surface out of 292** (the source
declares one `UndergroundSlab` and types the basement's own walls as plain `ExteriorWall`);
`austin_office.xml` and `austin_apartment_slivers.xml` declare no ground-contact surface type at
all. The defect is in the export, so reading `surfaceType` back out of the gbXML finds nothing —
it has to be found geometrically.

It matters because `Outdoors` carries `SunExposed`/`WindExposed`: a buried slab or basement wall
left that way takes fictitious solar gain and wind convection, the same error class as the
`patch_missing_surfaces` exposure fix. Nothing else reports it — `validate_model` has no geometry
checks, and the overlap/enclosure checks never look at boundary conditions.

`repair_and_validate_gbxml_geometry()` reports this on every call, taking z = 0 as grade (the
site-coordinate convention gbXML and OpenStudio share). Result fields:
`ground_contact_missing_count` / `ground_contact_missing` (names), plus
`ground_surfaces_existing_count`, `partially_below_grade_count`, and
`adiabatic_below_grade_count`. On that basement fixture it reports 17 walls against 1 existing
Ground surface.

**Report only — it never sets a boundary condition.** Whether a slab is on grade, over a
crawlspace, or over open parking is a modeling judgment that changes energy results materially.
The names are shaped to be replayed into one batched call:
`set_surface_boundary_conditions(surface_names=[...], outside_boundary_condition="Ground")`, which
derives `NoSun`/`NoWind` automatically for a non-`Outdoors` condition. Review the list first.

Three details worth knowing:

- **A wall counts as a basement wall when most of its height is buried**, not only when it is
  entirely below grade. Every one of that fixture's 17 basement walls runs z = −3.05 to z = +0.91
  — 77% buried, none of them fully — so an "entirely below grade" rule finds nothing there. Walls
  crossing grade with less than half buried go to `partially_below_grade` instead: visible, but
  not proposed for a batch fix. Setting a partly-buried wall to `Ground` does bury its
  above-grade portion; splitting it at z = 0 would be strictly more correct and no tool here does
  that, which is part of why this is reported rather than repaired.
- **Ten boundary conditions already mean ground-coupled**, not one — `Ground`, `Foundation`, and
  the eight `Ground*` preprocessor variants. The check reads them from the SDK, so an F/C-factor
  or Kiva `Foundation` surface is never reported as defective.
- `ok` is **not** affected. A model with no ground connection still simulates, and this fires on
  essentially every gbXML import, so `ok` keeps meaning "geometry is structurally sound".
  `ground_surfaces_existing_count` sits next to the finding on purpose: "1 existing, 17 missing"
  reads very differently from "40 existing, 1 missing", and no geometric rule can tell you which
  of those means the model's origin simply is not at grade.

Re-check with `repair_and_validate_gbxml_geometry()` after any of these. Order matters less between
`merge_coplanar_sliver_surfaces()` and `weld_coincident_vertices()` (they touch different surface
pairs) than for the other two: run `patch_missing_surfaces()` after those two have closed what
they can, and `trim_overlapping_surfaces()` after that, since it's scoped to still-non-enclosed
spaces.

**None guarantee full closure, and combining them isn't necessarily additive** — a space can
carry more than one of these four defects at once, so closing one doesn't guarantee the others
clear in the same pass. `patch_missing_surfaces()` and `trim_overlapping_surfaces()` can also
oscillate against each other on a structurally ambiguous mix of missing and duplicate geometry
(each pass's fix recreates the other's input) rather than converge — re-running the pair is a
legitimate way to confirm that before giving up on a space. Ambiguous cases are reported as
skipped, with the specific reason, rather than guessed at, in every one of these four tools. See
`docs/examples/22_repair_and_validate_gbxml_geometry.md` for a worked example with exact
before/after counts on a real fixture.

## Tools

`import_gbxml`, `repair_and_validate_gbxml_geometry`. See also `repair_missing_roof_ceiling`,
`merge_coplanar_sliver_surfaces`, `weld_coincident_vertices`, `patch_missing_surfaces`, and
`trim_overlapping_surfaces` (geometry skill) for the five automatable non-enclosed-space causes,
and `change_building_location` (common_measures skill, to set climate zone explicitly if
`import_gbxml` couldn't resolve one).
