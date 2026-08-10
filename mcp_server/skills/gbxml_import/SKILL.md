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
   `gbxml_import_hvac` → `set_simulation_control` → `gbxml_postprocess`.
   `ChangeBuildingLocation` always runs, even though no simulation ever does —
   `gbxml_import_advanced` reads the model's WeatherFile timezone while building
   schedules and errors out without one. This is also what embeds the project's
   real location in the resulting `.osm`, rather than a placeholder.
4. Result includes `osm_path` (auto-loaded as the current session model), plus per-step
   `error`/`warning` messages and `total_errors`/`total_warnings` counts. It also always includes
   a guaranteed climate zone and a conditioned-zone volume check — see "Climate zone and zone
   volume guarantees" below.
5. `repair_and_validate_gbxml_geometry()` — checks the (now-loaded) model for same-space overlaps and
   non-enclosed volumes match_surfaces() can't fix. One call replaces the manual
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
geometry. `repair_and_validate_gbxml_geometry()` runs `match_surfaces()` first, then reports same-space
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
  a vertex) via a bounded search over ways to pair up its edges.
- **Same-space overlaps**: the flip side of a missing surface — a surface duplicated (the
  historical "11 Jay St" pattern: a wall exported once per neighboring room instead of split at the
  boundary between them), or a byproduct of patching a missing surface that happens to coincide
  with something already there. `trim_overlapping_surfaces()` (geometry skill) trims each side of a
  genuine 2D overlap to its own non-overlapping remainder, or removes it outright if fully
  contained within the other. Scoped to spaces currently failing `isEnclosedVolume()` — it never
  touches an overlap that coexists peacefully with an already-enclosed space.

Re-check with `repair_and_validate_gbxml_geometry()` after any of these. Order matters less between
`merge_coplanar_sliver_surfaces()` and `weld_coincident_vertices()` (they touch different surface
pairs) than for the other two: run `patch_missing_surfaces()` after those two have closed what
they can, and `trim_overlapping_surfaces()` after that, since it's scoped to still-non-enclosed
spaces. **None guarantee full closure**, and combining them isn't necessarily additive: on the real
fixture used in this project's own tests (74 spaces, 69 non-enclosed),
`merge_coplanar_sliver_surfaces()` alone fixes 2, `weld_coincident_vertices()` alone fixes 0 (real
work — 22 spaces get vertices snapped — but the spaces it touches have other simultaneous defects a
2cm weld doesn't close), and running both nets the same 2 as merge alone, with zero regressions
either way — 69 -> 67. `patch_missing_surfaces()` and `trim_overlapping_surfaces()` together
close all but 4 of what's left: 67 -> 4. The honest remainder on this fixture is a confirmed
patch/trim oscillation — each pass's fix creates exactly the input the other pass "fixes" right
back (verified directly by running repeated rounds, not assumed) — or a structurally ambiguous mix
of missing and duplicate geometry neither tool can resolve alone. Ambiguous cases are reported as
skipped, with the specific reason, rather than guessed at in every one of these four tools.

## Tools

`import_gbxml`, `repair_and_validate_gbxml_geometry`. See also `repair_missing_roof_ceiling`,
`merge_coplanar_sliver_surfaces`, `weld_coincident_vertices`, `patch_missing_surfaces`, and
`trim_overlapping_surfaces` (geometry skill) for the five automatable non-enclosed-space causes,
and `change_building_location` (common_measures skill, to set climate zone explicitly if
`import_gbxml` couldn't resolve one).
