## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Import the provided Revit gbXML into an OpenStudio model without simulating it" | import_gbxml | gbxml_path present, epw_path present |
| "Convert the available gbXML file to OSM using the project weather file" | import_gbxml | gbxml_path present, epw_path present |
| "Repair and validate the loaded gbXML geometry" | repair_and_validate_gbxml_geometry | — |
| "Check this imported gbXML model for overlaps and non-enclosed spaces" | repair_and_validate_gbxml_geometry | — |
| "Set the ground temperatures on this model from the project weather file" | set_ground_temperatures | — |
| "This imported model has no ground temperatures — apply the EPW's" | set_ground_temperatures | — |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "What spaces are in the currently loaded model?" | import_gbxml, repair_and_validate_gbxml_geometry | list_spaces, get_model_summary |
| "Validate the current OSM before simulation" | import_gbxml, repair_and_validate_gbxml_geometry | validate_model, inspect_osm_summary |
| "Import the FloorspaceJS floor plan at /inputs/sddc_office/floorplan.json" | import_gbxml, repair_and_validate_gbxml_geometry | import_floorspacejs |
