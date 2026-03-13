# Plan: LLM Discoverability Gap Coverage

## Status: COMPLETE

## Context
131 MCP tools, 107 LLM tests (96.3% pass rate). Progressive tests cover 18 cases but cluster around building creation, HVAC selection, and visualization. Major energy modeler workflows have zero LLM coverage: simulation+results, envelope mods, loads, plant loops, schedules, design days, measures.

## Current Coverage Map

| Category | Progressive | Workflow | Gap |
|----------|------------|----------|-----|
| Building creation | 2 (create_building, import_floorplan) | 4 | -- |
| HVAC systems | 1 (add_hvac) | 3 (vav, doas, vrf) | -- |
| Weather/location | 1 (set_weather) | 1 | -- |
| Visualization | 1 (view_model) | 0 | -- |
| QA/QC | 1 (run_qaqc) | 1 | -- |
| Thermostat | 1 | 1 | -- |
| Solar PV | 1 (add_pv) | 1 | -- |
| Geometry query | 4 (spaces, zones, subsurfaces, surface_details) | 1 (manual_geometry) | -- |
| Generic access | 3 (inspect, modify, list_dynamic) | 1 (inspect_modify_boiler) | -- |
| Floor area/materials | 2 (floor_area, materials) | 0 | -- |
| Schedules | 1 (list only) | 0 | **get_schedule_details, create** |
| **Simulation** | 0 | 0 | **run_simulation, results** |
| **Results extraction** | 0 | 0 | **EUI, end-use, sizing, zones** |
| **Envelope** | 0 | 0 | **WWR, constructions, windows** |
| **Loads** | 0 | 0 | **create, get_load_details** |
| **Plant loops** | 0 | 0 | **create, add equipment** |
| **Design conditions** | 0 | 0 | **design days, run period, sim control** |
| **Measures** | 0 | 0 | **apply_measure, ideal air, clean** |
| **Model management** | 0 | 0 | **save, inspect_osm_summary** |
| **Space types** | 0 | 0 | **get_space_type_details** |
| **EV/ventilation** | 0 | 0 | **add_ev_load, add_zone_ventilation** |
| **Construction details** | 0 | 0 | **get_construction_details** |

## New Progressive Cases (16)

All follow existing L1/L2/L3 pattern. `needs_model=True` unless noted.

### Simulation & Results (4 cases, need simulation run)

These need a completed simulation. Option A: run sim in test_01_setup and save run_id. Option B: prompt includes "run simulation then extract". Option B is more realistic (tests the chain) but slower.

**Decision:** Add a `test_01_setup::test_run_simulation` step that runs a sim on the baseline model and saves `run_id` to a file. Results cases load run_id and extract.

```python
{
    "id": "run_simulation",
    "needs_model": True,
    "expected": ["run_simulation", "run_osw"],
    "L1": "Simulate the building and get the energy results.",
    "L2": "Run an EnergyPlus simulation on this model.",
    "L3": "Run the simulation using run_simulation.",
},
{
    "id": "get_eui",
    "needs_model": False,  # uses run_id, not model
    "needs_run": True,
    "expected": ["extract_summary_metrics"],
    "L1": "What's the building's energy use?",
    "L2": "Extract the EUI from the simulation results.",
    "L3": "Extract summary metrics using extract_summary_metrics.",
},
{
    "id": "end_use_breakdown",
    "needs_model": False,
    "needs_run": True,
    "expected": ["extract_end_use_breakdown"],
    "L1": "How much energy goes to heating vs cooling?",
    "L2": "Show the end use breakdown from the simulation.",
    "L3": "Extract end use breakdown using extract_end_use_breakdown.",
},
{
    "id": "hvac_sizing",
    "needs_model": False,
    "needs_run": True,
    "expected": ["extract_hvac_sizing", "extract_component_sizing"],
    "L1": "Are the HVAC systems properly sized?",
    "L2": "Show the HVAC sizing results from the simulation.",
    "L3": "Extract HVAC sizing using extract_hvac_sizing.",
},
```

**Problem:** Simulation takes ~60s. Running it in test_01_setup adds setup time but avoids repeating it per test. The run_id needs to be discoverable — save to a known file or use `get_run_status` to find latest.

**Decision:** Add `test_run_baseline_simulation` to test_01_setup. Save run_id to `{RUNS_DIR}/llm-test-run-id.txt`. Results cases read from this file. If file missing, skip with "run test_01_setup first".

### Envelope (3 cases)

```python
{
    "id": "set_wwr",
    "needs_model": True,
    "expected": ["set_window_to_wall_ratio"],
    "L1": "Add windows to the building.",
    "L2": "Set the window-to-wall ratio to 40% on all facades.",
    "L3": "Set the window to wall ratio to 0.4 using set_window_to_wall_ratio.",
},
{
    "id": "replace_windows",
    "needs_model": True,
    "expected": ["replace_window_constructions"],
    "L1": "Upgrade the windows to double-pane low-e.",
    "L2": "Replace all window constructions with better performing glazing.",
    "L3": "Replace window constructions using replace_window_constructions.",
},
{
    "id": "construction_details",
    "needs_model": True,
    "expected": ["get_construction_details"],
    "L1": "What layers make up the exterior wall?",
    "L2": "Show the material layers of a wall construction.",
    "L3": "Get construction details using get_construction_details.",
},
```

### Loads (2 cases)

```python
{
    "id": "check_loads",
    "needs_model": True,
    "expected": ["get_load_details", "get_object_fields", "list_model_objects"],
    "L1": "What loads are assigned to the first space?",
    "L2": "Get the people and lighting load details for a space.",
    "L3": "Get load details using get_load_details.",
},
{
    "id": "create_loads",
    "needs_model": True,
    "expected": ["create_people_definition", "create_lights_definition"],
    "L1": "Add people and lighting to the office spaces.",
    "L2": "Create a people load of 0.05 people/sqft and lighting at 10 W/sqft.",
    "L3": "Create a people definition using create_people_definition with "
          "people_per_floor_area 0.05.",
},
```

### Plant Loops (1 case)

```python
{
    "id": "create_plant_loop",
    "needs_model": True,
    "expected": ["create_plant_loop"],
    "L1": "Create a hot water heating loop.",
    "L2": "Create a plant loop for hot water heating with a 82C design temp.",
    "L3": "Create a plant loop using create_plant_loop with loop_type heating.",
},
```

### Schedules & Space Types (2 cases)

```python
{
    "id": "schedule_details",
    "needs_model": True,
    "expected": ["get_schedule_details"],
    "L1": "What hours is the HVAC running?",
    "L2": "Show the details of an HVAC operation schedule.",
    "L3": "Get schedule details using get_schedule_details.",
},
{
    "id": "space_type_info",
    "needs_model": True,
    "expected": ["get_space_type_details", "get_object_fields"],
    "L1": "What type of space is this and what are its defaults?",
    "L2": "Show the space type details including default loads and schedules.",
    "L3": "Get space type details using get_space_type_details.",
},
```

### Design Conditions (2 cases)

```python
{
    "id": "set_run_period",
    "needs_model": True,
    "expected": ["set_run_period", "get_run_period"],
    "L1": "Set the simulation to run for a full year.",
    "L2": "Set the run period from January 1 to December 31.",
    "L3": "Set the run period using set_run_period with start 1/1 end 12/31.",
},
{
    "id": "ideal_air",
    "needs_model": True,
    "expected": ["enable_ideal_air_loads"],
    "L1": "Use ideal air loads for quick sizing.",
    "L2": "Enable ideal air loads on all zones for sizing runs.",
    "L3": "Enable ideal air loads using enable_ideal_air_loads.",
},
```

### Model Management & Misc (2 cases)

```python
{
    "id": "save_model",
    "needs_model": True,
    "expected": ["save_osm_model"],
    "L1": "Save my changes.",
    "L2": "Save the model to /runs/my_model.osm.",
    "L3": "Save the model using save_osm_model to /runs/my_model.osm.",
},
{
    "id": "add_ev",
    "needs_model": True,
    "expected": ["add_ev_load"],
    "L1": "Add electric vehicle charging to the building.",
    "L2": "Add EV charging load to the parking area.",
    "L3": "Add EV charging using add_ev_load.",
},
```

## New Workflow Cases (4)

### 1. Simulate and Extract Results
```python
{
    "id": "simulate_and_extract",
    "prompt": LOAD + (
        "Run a simulation using run_simulation. "
        "Then extract the summary metrics using extract_summary_metrics. "
        "Then extract the end use breakdown using extract_end_use_breakdown. "
        "Use MCP tools only."
    ),
    "required_tools": ["load_osm_model", "run_simulation",
                        "extract_summary_metrics", "extract_end_use_breakdown"],
    "timeout": 300,
},
```

**Problem:** Simulation requires weather file. Baseline model may not have one.

**Decision:** Use the HVAC baseline model (created with create_baseline_osm which includes weather). Or add weather in the prompt. Need to verify baseline has weather set.

### 2. Create Loads and Assign to Space
```python
{
    "id": "create_and_assign_loads",
    "prompt": LOAD + (
        "Create a people definition using create_people_definition with "
        "people_per_floor_area 0.05 and name 'Office People'. "
        "Then create a lights definition using create_lights_definition with "
        "watts_per_floor_area 10 and name 'Office Lights'. "
        "Use MCP tools only."
    ),
    "required_tools": ["load_osm_model", "create_people_definition",
                        "create_lights_definition"],
    "timeout": 120,
},
```

### 3. Envelope Retrofit
```python
{
    "id": "envelope_retrofit",
    "prompt": LOAD + (
        "Set the window-to-wall ratio to 0.4 using set_window_to_wall_ratio. "
        "Then replace window constructions using replace_window_constructions. "
        "Use MCP tools only."
    ),
    "required_tools": ["load_osm_model", "set_window_to_wall_ratio",
                        "replace_window_constructions"],
    "timeout": 180,
},
```

### 4. Plant Loop with Equipment
```python
{
    "id": "plant_loop_with_boiler",
    "prompt": LOAD + (
        "Create a heating plant loop using create_plant_loop with loop_type "
        "heating. Then add a hot water boiler using add_supply_equipment "
        "with equipment_type BoilerHotWater. Use MCP tools only."
    ),
    "required_tools": ["load_osm_model", "create_plant_loop",
                        "add_supply_equipment"],
    "timeout": 120,
},
```

## Implementation

### Step 1: Setup — simulation run
In `test_01_setup.py`, add:
- `test_run_baseline_simulation` — runs sim on baseline+HVAC model, saves run_id

In `conftest.py`, add:
- `SIM_RUN_ID_FILE` path
- `get_sim_run_id()` — reads from file, returns None if missing
- `sim_run_exists()` — for skip checks

### Step 2: Progressive cases
Add 16 cases to `PROGRESSIVE_CASES` in `test_06_progressive.py`:
- 4 results cases with `needs_run=True`
- 12 model-only cases

Handle `needs_run` in test runner — load run_id, build LOAD_RUN prefix.

### Step 3: Workflow cases
Add 4 cases to `WORKFLOW_CASES` in `test_04_workflows.py`.

### Step 4: Markers
- `results` marker on simulation/results cases
- `smoke` marker: add 2-3 new L3 cases (save_model, set_wwr, get_eui)

## Summary

| Change | Tests added |
|--------|------------|
| 16 progressive cases (L1/L2/L3) | +48 |
| 4 workflow cases | +4 |
| 1 setup (simulation run) | +1 |
| **Total** | **+53** |

**New total: ~160 tests** (was 107)

### Net coverage after implementation

| Category | Before | After |
|----------|--------|-------|
| Simulation + results | 0 | 4 progressive + 1 workflow |
| Envelope | 0 | 3 progressive + 1 workflow |
| Loads | 0 | 2 progressive + 1 workflow |
| Plant loops | 0 | 1 progressive + 1 workflow |
| Schedules | 1 (list only) | 2 (+ details) |
| Space types | 0 | 1 |
| Design conditions | 0 | 2 |
| Model management | 0 | 1 |
| Measures (ideal air) | 0 | 1 |
| EV | 0 | 1 |

## Run 6 Results: 153/159 (96.2%)

All 16 new progressive cases pass at L2+L3. 15/16 pass at L1 (check_loads_L1 fails — too vague).
All 4 new workflow cases pass. No regressions from tool removal (131 tools).

### Resolved Questions

1. Baseline has no weather → sim setup calls `change_building_location` with Boston EPW first. Works.
2. 420s timeout sufficient for sim setup (weather + sim + polling).
3. Saved run_id method works well — results tests skip if no run_id, fast execution.
4. `create_loads` L1 "add people and lighting" → agent finds `create_people_definition` + `create_lights_definition`. PASS.
5. `schedule_details` L1 "what hours is the HVAC running" → agent finds `get_schedule_details`. PASS.
