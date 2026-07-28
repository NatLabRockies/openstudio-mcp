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
   `error`/`warning` messages and `total_errors`/`total_warnings` counts.
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

## Tools

`import_gbxml`, `repair_and_validate_gbxml_geometry`.
