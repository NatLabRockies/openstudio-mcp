## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Upload my local model office.osm (about 2 MB) to the server" | request_upload | filename=office.osm |
| "I have a measure zip on my laptop the server needs" | request_upload | kind=measure |
| "Give me a download link for the results of run run_abc123" | request_download | run_id=run_abc123 |
| "What files have I uploaded?" | list_uploads | — |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "Load the model at /inputs/office.osm" | request_upload | load_osm_model |
| "Show me the last lines of the simulation error log for run run_abc123" | request_download | get_run_logs, read_file, extract_simulation_errors |
| "What weather files are on the server?" | request_upload | list_weather_files, list_files |
