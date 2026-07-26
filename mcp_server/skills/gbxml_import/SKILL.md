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
5. Pass `osm_path` (or the auto-loaded session model) to any model-query/model-management tool.

## Where the measures come from

Baked into the Docker image at build time from a **pinned release tag** of
`NatLabRockies/gbxml-to-openstudio` (see `GBXML_TO_OS_TAG` in `docker/Dockerfile`), extracted to
`GBXML_MEASURES_DIR` (measures) and `GBXML_SEED_OSM` (the empty seed model the workflow starts
from). Bumping to a newer measures release is a one-line `ARG GBXML_TO_OS_TAG=...` change +
rebuild — no code changes needed.

## Tools

`import_gbxml`.
