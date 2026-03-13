# Plan: Results & Error Management (Phase 10)

## Context
Energy modelers using openstudio-mcp can run simulations and extract results,
but error diagnosis is manual (raw log parsing), results lack validation, and
there's no tool to compare two simulation runs. These gaps force extra agent
turns and make failure recovery unreliable.

## Changes

### 1. `extract_simulation_errors(run_id)` — NEW TOOL

Parse `eplusout.err` and return structured error/warning summary.

**`mcp_server/skills/results/operations.py`**
```python
def extract_simulation_errors(run_id: str) -> dict:
    """Parse EnergyPlus .err file into categorized messages."""
    # Parse lines matching: ** Fatal **, ** Severe  **, ** Warning **
    # Return: {ok, fatal: [{msg}], severe: [{msg}], warning_count,
    #          summary: "3 Severe, 47 Warning, 0 Fatal"}
```

**`mcp_server/skills/results/tools.py`** — MCP registration

EnergyPlus .err format:
```
   ** Severe  ** Node "NODE NAME" not found in any AirLoopHVAC
   **   ~~~   ** ...continued message
   ** Warning ** Zone "ZONE" has no thermostat
   ** Fatal  ** Errors occurred during processing
```

### 2. `compare_runs(run_id_1, run_id_2)` — NEW TOOL

Auto-diff two simulation results.

**`mcp_server/skills/results/operations.py`**
```python
def compare_runs(baseline_run_id: str, retrofit_run_id: str) -> dict:
    """Compare two simulation results — EUI, end-uses, unmet hours."""
    # Extract summary_metrics from both
    # Extract end_use_breakdown from both
    # Compute deltas (absolute + %)
    # Return: {ok, baseline: {eui, unmet_hours}, retrofit: {eui, unmet_hours},
    #          delta_eui, delta_pct, end_use_deltas: [{category, baseline, retrofit, delta}]}
```

### 3. `list_output_variables(run_id)` — NEW TOOL

Query SQL ReportDataDictionary for available timeseries variables.

**`mcp_server/skills/results/operations.py`**
```python
def list_output_variables(run_id: str) -> dict:
    """List output variables available in simulation results."""
    # Query: SELECT DISTINCT Name, KeyValue, ReportingFrequency
    #        FROM ReportDataDictionary WHERE IsMeter=0
    # Return: {ok, variables: [{name, key_values: [...], frequency}]}
```

### 4. Add warnings to `extract_summary_metrics`

Flag suspicious results without breaking existing return format.

**`mcp_server/skills/results/operations.py`** — modify existing function
- Add `warnings: []` to return dict
- EUI = 0 or negative → warning
- Unmet hours > 300 → warning
- No conditioned floor area → warning

### 5. Error summary in `get_run_status` on failure

When `status=failed`, auto-parse first Fatal/Severe line from err file.

**`mcp_server/skills/simulation/operations.py`** — modify `_refresh_status()`
- If status == "failed" and eplusout.err exists, extract first Fatal line
- Add `error_summary` field to run status dict

### 6. `validate_model()` — NEW TOOL

Pre-simulation model validation (lightweight, no simulation needed).

**`mcp_server/skills/simulation/operations.py`**
```python
def validate_model() -> dict:
    """Pre-simulation model check: weather, design days, HVAC, constructions."""
    # Check: weather file attached, >=1 design day, zones have HVAC or ideal air,
    #        surfaces have constructions, thermostat setpoints reasonable
    # Return: {ok, errors: [...], warnings: [...]}
```

### 7. Update skills + docs

- Update troubleshoot skill to reference `extract_simulation_errors`
- Update retrofit skill to reference `compare_runs`
- Update tool-workflows skill with error recovery recipe
- Add `list_output_variables` to energy-report workflow

## Implementation Order

1. `extract_simulation_errors` — highest impact, smallest effort
2. Error summary in `get_run_status` — pairs with #1
3. `compare_runs` — high value for retrofit workflows
4. `list_output_variables` — enables timeseries discovery
5. Warnings in `extract_summary_metrics` — small enhancement
6. `validate_model` — medium effort, pre-flight checks
7. Skill/doc updates

## Verification

```bash
# Unit tests
pytest tests/test_results_extraction.py -v

# Integration
docker run --rm -v "C:/projects/openstudio-mcp:/repo" -v "C:/projects/openstudio-mcp/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_results_extraction.py"

# LLM tests for error recovery + comparison
LLM_TESTS_ENABLED=1 pytest tests/llm/test_04_workflows.py -k "measure_" -v
```

## Unresolved Questions

- `compare_runs`: diff envelope/HVAC sizing too, or just headline metrics?
- `extract_simulation_errors`: parse openstudio.log for measure failures too, or just eplusout.err?
- `validate_model`: new skill or add to simulation skill?
- `extract_summary_metrics` warnings: always-on or opt-in flag?
- Parametric/batch runs — separate phase or scope here?
