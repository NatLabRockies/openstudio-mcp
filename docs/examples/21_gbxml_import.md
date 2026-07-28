# Example 21: gbXML Import from Revit

Translate a Revit-exported gbXML file into an OpenStudio model — no EnergyPlus run, no hand-written translation script.

## Scenario

An architect exports a building model from Revit 2022+ as gbXML and hands it to an energy modeler to pick up in OpenStudio. Rather than reverse-engineering the gbXML by hand, the modeler runs it through the same measure pipeline Revit's own OpenStudio CLI workflow uses (`NatLabRockies/gbxml-to-openstudio`): location, geometry, HVAC, and simulation-control measures, applied via `openstudio run --measures_only` so EnergyPlus never actually executes — only the model-building measures do. The project's own weather file goes along for the ride so the resulting `.osm` has the real site location embedded, not a placeholder.

## Prompt

> I have a gbXML export from Revit at `/inputs/25_SpacesOneZE.xml`, along with its project weather file `/inputs/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw` (and matching `.stat`/`.ddy`). Import it into OpenStudio and tell me what's in it.

## Tool Call Sequence

```
1. import_gbxml(
     gbxml_path="/inputs/25_SpacesOneZE.xml",
     epw_path="/inputs/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
   → runs ChangeBuildingLocation -> gbxml_import -> gbxml_import_advanced ->
     gbxml_import_hvac -> set_simulation_control -> gbxml_postprocess
   → { ok: true, osm_path: "/runs/gbxml_import_.../25_SpacesOneZE.osm",
       total_errors: 0, total_warnings: 0 }
2. load_osm_model(osm_path=<returned osm_path>)   # usually unnecessary — import_gbxml
                                                   # auto-loads the model into the session
3. list_spaces()             → 25 spaces
4. list_thermal_zones()      → 25 zones
5. list_surfaces()           → 228 surfaces
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `import_gbxml` | Translate gbXML -> OSM via the gbxml-to-openstudio measures, `--measures_only` (no simulation) |
| `load_osm_model` | Load a saved `.osm` into the session (not usually needed after `import_gbxml`, which auto-loads) |
| `list_spaces` / `list_thermal_zones` / `list_surfaces` | Verify the imported geometry and zoning |

## Required Inputs

`import_gbxml` expects **four files placed under `/inputs`** by the user before the call:

| File | Role |
|------|------|
| `*.xml` (gbXML) | The Revit export to translate |
| `*.epw` | The project's weather file — its location is embedded in the resulting `.osm` via `ChangeBuildingLocation` |
| `*.stat` | Design-day statistics for the EPW (same directory, same filename stem) |
| `*.ddy` | Design-day definitions for the EPW (same directory, same filename stem) |

The EPW is required, not optional — `gbxml_import_advanced` reads the model's weather-file timezone while building schedules and errors out without one, even though no simulation ever runs. The `.stat` file is required by `ChangeBuildingLocation` itself.

## Result Detail

The returned `step_messages` breaks any errors/warnings out **per measure step**, so a failure inside e.g. `gbxml_import_hvac` is distinguishable from one in `gbxml_import_advanced` — the response stays small (capped like every other measure-runner report in this server) instead of dumping the full `out.osw`:

```json
{
  "ok": true,
  "osm_path": "/runs/gbxml_import_.../25_SpacesOneZE.osm",
  "total_errors": 0,
  "total_warnings": 0,
  "step_messages": {
    "steps": [
      {"measure": "ChangeBuildingLocation", "result": "Success"},
      {"measure": "gbxml_import", "result": "Success"},
      {"measure": "gbxml_import_advanced", "result": "Success"},
      {"measure": "gbxml_import_hvac", "result": "Success"},
      {"measure": "set_simulation_control", "result": "Success"},
      {"measure": "gbxml_postprocess", "result": "Success"}
    ],
    "total_errors": 0,
    "total_warnings": 0
  }
}
```

## Common Pitfalls

- **Skipping the EPW/`.stat` doesn't work.** Even though `--measures_only` never runs EnergyPlus, `gbxml_import_advanced`'s schedule-building code needs a `WeatherFile` object on the model — it isn't optional for this pipeline.
- **Not every gbXML sample is pipeline-compatible.** The gbXML.org "Standard Test Model" (a schema-conformance fixture) lacks the populated `Schedule` data `gbxml_import_advanced`/`gbxml_import_hvac` expect and will crash inside `os_lib_schedules.rb`. Use a real Revit-style export (geometry + schedules + HVAC), not a bare schema-validation fixture.
- **The measures are pinned, not floating.** They're baked into the Docker image from a specific `gbxml-to-openstudio` release tag (`GBXML_TO_OS_TAG` in `docker/Dockerfile`) — bumping to a newer release is a one-line change + rebuild, not automatic.

## Integration Test

See `tests/test_gbxml_import.py::test_import_gbxml_basic`.
