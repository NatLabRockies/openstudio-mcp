## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Which OSAF algorithm should I use for a one-variable sampling sweep?" | openstudio_analysis_algorithms | category present |
| "Create an OSA JSON configuration for a single-run office analysis" | openstudio_analysis_create_osa_json | output_path present, analysis_name present, analysis_type=single_run |
| "Validate the OSA configuration at /inputs/office_analysis.json before submission" | openstudio_analysis_validate_osa_json | osa_json_path=/inputs/office_analysis.json |
| "Submit /inputs/office_analysis.json to OpenStudio Server project project_123" | openstudio_analysis_submit | project_id=project_123, osa_json_path=/inputs/office_analysis.json |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "What is the current status of OpenStudio Server analysis analysis_123?" | openstudio_analysis_create_osa_json, openstudio_analysis_submit, openstudio_analysis_start | openstudio_analysis_status |
| "Download the CSV results for analysis analysis_123 to /runs/osaf-results" | openstudio_analysis_create_osa_json, openstudio_analysis_submit, openstudio_analysis_start | openstudio_analysis_download_data |
| "Run the loaded OSM through a local EnergyPlus simulation" | openstudio_analysis_create_osa_json, openstudio_analysis_submit, openstudio_analysis_start | run_simulation, save_osm_model |
