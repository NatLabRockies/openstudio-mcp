# analysis

OpenStudio Server / OSAF analysis workflows.

## Defaults

When creating OSA JSON with `openstudio_analysis_create_osa_json` or
`openstudio_analysis_create_osa_json_from_measures`, omit `output_variables`
unless the user explicitly asks for a custom set. The tools then include the
foundational OpenStudio Results outputs with `export: true` and
`visualize: true` so they appear in exported data and OSAF plots:

- `openstudio_results.electricity_ip`
- `openstudio_results.natural_gas_ip`
- `openstudio_results.eui`
- `openstudio_results.total_site_eui`
- `openstudio_results.net_site_energy`
- `openstudio_results.annual_peak_electric_demand`
- all OpenStudio Results unmet-hours whole-building fields
- all `openstudio_results.electricity_*_ip` end-use categories
- all `openstudio_results.natural_gas_*_ip` end-use categories

Use `openstudio_analysis_default_output_variables` when a client needs to
inspect, copy, or extend the default output-variable payload explicitly.

## Foundational Measures

Generated analyses include these common measures by default:

- `view_model`
- `openstudio_results`
- `generic_qaqc`

Use `openstudio_analysis_foundational_measures` to inspect the configured
measure paths. `openstudio_analysis_prepare_package` copies these measure
directories from `COMMON_MEASURES_DIR` into `measures/` before writing the ZIP.
OSA JSON validation and submission require them in `analysis.problem.workflow`
by default, and package validation requires them in the ZIP, so raw uploads do
not silently miss standard reports, QA/QC, or model visualization.

## Server Config Smoke Test

Use `openstudio_analysis_test_server_config` to verify an OpenStudio Server
configuration before larger analyses. It:

1. Checks `GET /status.json`.
2. Creates and submits a `single_run` OSA JSON using the package seed/weather
   and every packaged measure.
3. Sets packaged measure arguments to their `measure.xml` `default_value` so
   the smoke test exercises the full workflow without sweeping.
4. Disables verbose/debug CLI logging and report/OSW/model/ZIP downloads to
   avoid Mongo BSON limits from large smoke-test artifacts.
5. Uploads the support ZIP.
6. Starts `single_run` to generate one datapoint.
7. Starts `batch_run` to simulate that datapoint.
8. Polls until the datapoint completes or reports failure.

Prefer an EPW from the package weather files. DDY/STAT files are support files,
not the weather file for the OSA seed.

## Packaging Gate

Use `openstudio_analysis_prepare_package` before uploading a support ZIP. It
requires the seed model to have simulated successfully and passed basic QA/QC,
writing `lib/seed_simulation_qaqc.json`. It reuses an existing matching seed
simulation when the seed and weather hashes match.

## Analysis Type Guardrails

Do not use OSAF `doe` for a one-variable sweep. OSAF accepts the payload but
fails during analysis startup. Use `single_run` for a single datapoint, use a
schema-supported sampling type such as `lhs` for one-variable sampling, or add
at least two real measure variables before choosing `doe`.

For sampled analyses such as `lhs`, start the sampler action first to generate
datapoints, then start `batch_run` to simulate the generated datapoints. Starting
`batch_run` before the sampler can complete the analysis with zero datapoints.
Prefer `openstudio_analysis_start_sampled_run` for this sequence; it calls the
sampler such as `lhs` first and then calls `batch_run`.
