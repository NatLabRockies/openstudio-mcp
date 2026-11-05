# Example 10: Standards-Based Typical Building

Apply ASHRAE 90.1-2019 constructions, loads, HVAC, schedules, and service water heating to any model that already has geometry — using the ComStock `create_typical_building` tool.

## Scenario

An engineer has a small office model with geometry and space types but no HVAC, constructions, or internal loads. They want to apply the full 90.1-2019 template for climate zone 2A (Houston) in a single step, then inspect what was added.

## Prompt

> Load my small office model and apply the 90.1-2019 typical building template for climate zone 2A. Show me what was added.

## Tool Call Sequence

```
1. list_comstock_measures(category="setup")    -- browse available templates
2. load_osm_model(osm_path="SmallOffice.osm")
3. change_building_location(weather_file="Houston.epw")
4. create_typical_building(template="90.1-2019",
     climate_zone="ASHRAE 169-2013-2A")        -- adds everything
5. get_model_summary()                         -- verify HVAC + constructions
6. list_air_loops()                            -- inspect HVAC system
7. list_model_objects(object_type="Construction")                        -- inspect envelope
8. save_osm_model(save_path="/runs/typical_office.osm")
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `list_comstock_measures` | Discover available measures and templates |
| `create_typical_building` | Apply full standards template (constructions, loads, HVAC, SWH) |
| `get_model_summary` | Verify objects were added to the model |
| `list_air_loops` | Inspect the HVAC system created by the template |
| `list_model_objects` | Inspect envelope constructions assigned to surfaces |

## Tips

- **Model prep:** The model must have geometry (spaces with surfaces) before applying the template. Use `create_space_from_floor_print` or load an existing model.
- **Climate zone:** Pass explicitly (e.g. `"ASHRAE 169-2013-2A"`) or use `"Lookup From Model"` if the model already has it set.
- **HVAC-only swap:** `create_typical_building(system_type="VAV chiller with gas boiler reheat", hvac_only=True)` replaces just the HVAC on an already-configured model, sized against its own loads, infiltration and constructions. The response reports `restored` (SWH equipment put back) and `non_hvac_changes` (expected empty). Confirm it is empty before `compare_runs`.
- **Infiltration basis:** the measure is openstudio-mcp's vendored fork of the ComStock measure (see `mcp_server/skills/comstock/measures/create_typical_building_from_model/VENDORED.md`). `add_infiltration`, `airtightness_value` (m3/h-m2 at 75 Pa, 0 = standard default 13.8), `airtightness_area_covered` (`4-sided` / `5-sided` / `6-sided`) and `air_barrier` are explicit args; defaults reproduce upstream.
- **Building type:** Defaults to `"SmallOffice"`. The tool auto-sets `standardsBuildingType` on the building and space types if missing.
- **Selective application:** Use boolean flags (`add_hvac`, `add_constructions`, `add_space_type_loads`, etc.) to apply only specific components.
- **Remove existing:** `remove_objects=True` (default) clears existing HVAC/loads before adding new ones.

## Integration Test

See `tests/test_example_workflows.py::test_workflow_comstock_typical_building`
