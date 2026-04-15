# Example 20: Hackathon — Deep Retrofit Package Analysis

Stack energy conservation measures on a baseline office building, simulate before and after, and quantify cumulative savings — all in a single AI-assisted session.

## Scenario

A hackathon team wants to find the maximum achievable energy savings from bundling multiple ECMs on a small commercial office building in Boston. They have four hours to model, simulate, and present results.

The **core package** (validated by integration test) stacks:
1. **High-R wall insulation** — upgrade all exterior walls to R-20
2. **Thermostat deadband widening** — expand heating/cooling deadband by 2°F each way

**Optional extensions** (require OpenStudio extension gem environment):
3. **High-performance windows** — replace all glazing with a better-performing construction
4. **Rooftop photovoltaics** — add PV panels on 75% of roof area

## Prompt

> Create a small office building in Boston. Run a baseline simulation, then stack high-R wall insulation and thermostat widening, re-simulate, and show me the savings from the package.

## Tool Call Sequence

### Step 1 — Baseline Model + Simulation

```
1. create_baseline_osm(name="office_baseline", ashrae_sys_num="03", wwr=0.4)
2. load_osm_model(osm_path=<returned path>)
3. change_building_location(weather_file="/inputs/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
4. save_osm_model(osm_path="/runs/office_baseline.osm")
5. run_simulation(osm_path="/runs/office_baseline.osm")
6. get_run_status(run_id=<id>)           # poll until "success"
7. extract_summary_metrics(run_id=<id>)  # record baseline EUI
```

### Step 2 — ECM 1: High-R Wall Insulation

Create an R-20 wall construction and assign it to every exterior wall.

```
8.  create_standard_opaque_material(
      name="R20_Insulation",
      thickness_m=0.141,          # R-20 IP: k=0.04 W/m-K → 3.52 m²·K/W
      conductivity_w_m_k=0.04,
      density_kg_m3=30.0,
      specific_heat_j_kg_k=1000.0)
9.  create_construction(name="High_R_Wall", material_names=["R20_Insulation"])
10. get_construction_details(construction_name="High_R_Wall")  # verify R-value
11. list_surfaces(surface_type="Wall", boundary="Outdoors", max_results=0)
    # For each exterior wall surface name:
12. assign_construction_to_surface(
      surface_name=<wall>, construction_name="High_R_Wall")
    ... repeat for each exterior wall ...
```

### Step 3 — ECM 2: Thermostat Deadband Widening

Expand the heating/cooling deadband by 2°F in each direction.

```
13. adjust_thermostat_setpoints(cooling_offset_f=2.0, heating_offset_f=-2.0)
```

### Step 4 — Retrofit Simulation + Comparison

```
14. save_osm_model(osm_path="/runs/office_retrofit.osm")
15. run_simulation(osm_path="/runs/office_retrofit.osm")
16. get_run_status(run_id=<id>)           # poll until "success"
17. compare_runs(
      baseline_run_id=<baseline_id>,
      retrofit_run_id=<retrofit_id>)
```

### Optional Extensions

#### ECM 3: High-Performance Windows (requires gem environment)

First create a high-performance glazing construction (e.g. low-e triple pane), then replace all windows with it:

```
18. create_standard_opaque_material(name="LowE_TriplePane", ...)   # or use SimpleGlazing
19. create_construction(name="HighPerf_Window", material_names=["LowE_TriplePane"])
20. replace_window_constructions(construction_name="HighPerf_Window")
```

#### ECM 4: Rooftop PV (requires gem environment)

```
19. add_rooftop_pv(fraction_of_surface=0.75, cell_efficiency=0.18)
```

> **Note on PV comparison:** `compare_runs` tracks end-use energy consumption.
> For PV, also check `extract_summary_metrics` to see the site energy reduction
> that accounts for onsite generation.

## Expected Results

| Scenario | EUI (kBtu/ft²/yr) | Savings vs. Baseline |
|----------|-------------------|----------------------|
| Baseline (System 3 PSZ-AC, Boston) | ~50–65 | — |
| + High-R Insulation | ~48–62 | ~3–6% |
| + Thermostat Widening (cumulative) | ~44–57 | ~8–15% |
| + Window Upgrade (if available) | ~42–54 | ~12–18% |
| + Rooftop PV offset | ~37–49 | ~18–28% |

*Exact values depend on model geometry and weather year.*

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `create_baseline_osm` | 10-zone model with PSZ-AC system and glazing |
| `change_building_location` | Weather file + design days (Boston TMY3) |
| `create_standard_opaque_material` | Define insulation layer (k, density, Cp, thickness) |
| `create_construction` | Assemble material layers into a wall construction |
| `get_construction_details` | Verify R-value of new assembly |
| `list_surfaces` | Find all exterior walls by boundary condition |
| `assign_construction_to_surface` | Apply new construction wall-by-wall |
| `adjust_thermostat_setpoints` | Widen heating/cooling deadband |
| `replace_window_constructions` | Swap all window glazing in one call (optional) |
| `add_rooftop_pv` | Add PV panels on roof shading surfaces (optional) |
| `run_simulation` | Launch EnergyPlus |
| `compare_runs` | EUI delta + per-end-use breakdown between two runs |

## Why This is a Great Hackathon Demo

This workflow demonstrates the unique value of AI-assisted building energy modeling:

- **Manual equivalent**: 4–8 hours per scenario in the OpenStudio GUI
- **With openstudio-mcp**: All ECMs modeled, simulated, and compared in minutes
- **Narrative**: "Here's the pathway to 15% savings from just two measures"
- **Extensibility**: Swap in any building type, location, or ECM package

## Notes

- Save the baseline model **before** applying any ECMs — the ECMs modify in-memory state
- ECM 1 uses a single-layer R-20 construction as a simplified approximation of a real multi-layer wall assembly; real projects would retain the original assembly and add an insulation layer
- `compare_runs` reports `energy_grand_total_kBtu` (consumption only, excludes water); for PV-inclusive scenarios, use `extract_summary_metrics` site energy instead
- `replace_window_constructions` and `add_rooftop_pv` require OpenStudio extension gems; the core ECMs (insulation + thermostat) work with the SDK alone

## Integration Test

See `tests/test_skill_ecm_package.py::test_skill_ecm_package_workflow`
