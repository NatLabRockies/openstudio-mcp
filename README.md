# openstudio-mcp

[![MCP Badge](https://lobehub.com/badge/mcp/natlabrockies-openstudio-mcp?style=for-the-badge)](https://lobehub.com/mcp/natlabrockies-openstudio-mcp)

**Model Context Protocol (MCP)** server for **OpenStudio** building energy simulation. Enables LLMs and MCP hosts (Claude Desktop, Cursor, Claude Code, etc.) to create, query, and modify OpenStudio models, run EnergyPlus simulations, and inspect results — all through natural language.

**22 skills &bull; 126 MCP tools &bull; 6 prompts &bull; 4 resources &bull; 260+ integration tests**

---

## What Can It Do?

Ask your AI assistant to do things like:

- *"Create a 10-zone office building with VAV reheat and run an annual simulation"*
- *"What's the EUI? Show me the unmet heating hours."*
- *"Switch the HVAC from VAV to VRF heat pumps and compare energy use"*
- *"Add R-30 roof insulation and see how it affects the cooling load"*
- *"Build two adjacent zones from floor plans, match the shared wall, add 40% south glazing"*
- *"Apply the AEDG Small Office measure from my local measures directory"*

The server handles all the OpenStudio/EnergyPlus complexity behind MCP tool calls.

---

## Quick Start

### Prerequisites

- **Docker Desktop** installed and running ([download](https://www.docker.com/products/docker-desktop/))
- **An MCP host** — an AI application that can connect to MCP tool servers. [Claude Desktop](https://claude.ai/download) is the recommended starting point.

### Step 1: Clone & Build

```bash
git clone https://github.com/yourusername/openstudio-mcp.git
cd openstudio-mcp
docker build -t openstudio-mcp:dev -f docker/Dockerfile .
```

### Step 2: Configure Claude Desktop

Open your Claude Desktop config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add (or merge into) the `mcpServers` block:

```json
{
  "mcpServers": {
    "openstudio-mcp": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "./tests/assets:/inputs",
        "-v", "./runs:/runs",
        "-v", "./.claude/skills:/skills:ro",
        "-e", "OPENSTUDIO_MCP_MODE=prod",
        "openstudio-mcp:dev", "openstudio-mcp"
      ]
    }
  }
}
```

- `./tests/assets:/inputs` — mounts the included test models so you can experiment right away. Replace with your own folder (e.g. `~/my-models:/inputs`) when ready.
- `./runs:/runs` — simulation outputs are written here
- `./.claude/skills:/skills:ro` — makes workflow guides available via `list_skills()` / `get_skill()` tools
- **Restart Claude Desktop** after saving the config file

### Step 3: Verify Connection

Open Claude Desktop and look for the **hammer icon** (MCP tools indicator) in the chat input area. Click it to see the 124 openstudio-mcp tools listed. If the icon doesn't appear, check that Docker is running and the config JSON is valid.

### Step 4: Start Chatting

Try these prompts in order of complexity:

> **Simple:** "Create an example model and tell me about it"

> **Medium:** "Create a baseline office with ASHRAE System 3 and show me the HVAC components"

> **Advanced:** "Load my model at /inputs/MyBuilding.osm, apply the 90.1-2019 typical building template, and run a simulation"

The AI reads your prompt, picks the right tools from the 124 available, calls them in sequence, and summarizes the results — no scripting required.

### Other MCP Hosts

[Cursor](https://www.cursor.com/), [VS Code](https://code.visualstudio.com/), and [Claude Code](https://docs.anthropic.com/en/docs/claude-code) also support MCP with similar JSON config. See the [MCP documentation](https://modelcontextprotocol.io/quickstart/user) for host-specific setup.

---

## Examples

### Example 1: [Energy Code Baseline Comparison](docs/examples/01_baseline_comparison.md)

Compare ASHRAE 90.1 System 3 (PSZ-AC) vs System 7 (VAV) for a small office.

```
You: Create a baseline model with ASHRAE System 3, set the Chicago weather file,
     and run a simulation. Then do the same with System 7 and compare the EUI.
```

Behind the scenes, the AI orchestrates these tool calls:

```
1. create_baseline_osm(name="office_sys3", ashrae_sys_num="03")
2. load_osm_model(osm_path=...)
3. set_weather_file(epw_path="/inputs/Chicago.epw")
4. save_osm_model(osm_path="/runs/office_sys3.osm")
5. run_simulation(osm_path="/runs/office_sys3.osm", epw_path="/inputs/Chicago.epw")
6. get_run_status(run_id=...)          # polls until complete
7. extract_summary_metrics(run_id=...) # gets EUI, energy by fuel
   ... repeats steps 1-7 for System 7 ...
8. Compares results and summarizes
```

### Example 2: [HVAC System Design Exploration](docs/examples/02_hvac_design_exploration.md)

Iterate on an HVAC design by swapping components and tuning setpoints.

```
You: Create a 10-zone building with a DOAS + fan coil system. Set the
     chilled water supply to 44°F and the hot water to 140°F. What
     components are on each plant loop?
```

```
1. create_baseline_osm(name="doas_office")
2. load_osm_model(osm_path=...)
3. add_doas_system(thermal_zone_names=[...], zone_equipment_type="FanCoil")
4. list_plant_loops()
5. set_sizing_properties(plant_loop_name="Chilled Water Loop",
     design_loop_exit_temperature_c=6.67)
6. set_sizing_properties(plant_loop_name="Hot Water Loop",
     design_loop_exit_temperature_c=60.0)
7. get_plant_loop_details(plant_loop_name="Chilled Water Loop")
8. get_plant_loop_details(plant_loop_name="Hot Water Loop")
```

```
You: The cooling tower is oversized. What are its current properties?
     Set the design water flow rate to 0.005 m3/s.
```

```
9.  get_component_properties(component_name="Cooling Tower...")
10. set_component_properties(component_name="Cooling Tower...",
      properties={"design_water_flow_rate_m3_per_s": 0.005})
```

### Example 3: [Envelope Retrofit Analysis](docs/examples/03_envelope_retrofit.md)

Upgrade wall insulation and see the impact on heating energy.

```
You: Load my existing model, show me the current wall constructions,
     then create a new R-20 wall and assign it to all exterior walls.
```

```
1. load_osm_model(osm_path="/inputs/my_building.osm")
2. list_constructions()
3. list_surfaces()  # see which surfaces are exterior walls
4. create_standard_opaque_material(name="R20_Insulation",
     thickness_m=0.089, conductivity_w_m_k=0.04,
     density_kg_m3=30, specific_heat_j_kg_k=1000)
5. create_construction(name="High_R_Wall",
     material_names=["Exterior Finish", "R20_Insulation", "Gypsum Board"])
6. assign_construction_to_surface(
     surface_name="Story 1 East Wall", construction_name="High_R_Wall")
   ... repeat for each exterior wall ...
7. save_osm_model(osm_path="/runs/retrofitted.osm")
```

### Example 4: [Internal Loads Setup](docs/examples/04_internal_loads.md)

Define occupancy, lighting, and equipment for a space.

```
You: Add people at 5.5 per 1000 sqft, lighting at 10 W/sqft, and plug loads
     at 1 W/sqft to the open office space. Use an occupancy schedule that's
     on during business hours.
```

```
1. create_schedule_ruleset(name="Office_Occ", schedule_type="Fractional",
     default_value=0.5)
2. create_people_definition(name="Office People", space_name="Open Office",
     people_per_area=0.059, schedule_name="Office_Occ")
3. create_lights_definition(name="Office Lights", space_name="Open Office",
     watts_per_area=10.76)
4. create_electric_equipment(name="Office Plugs", space_name="Open Office",
     watts_per_area=1.076)
5. list_people_loads()   # verify
6. list_lighting_loads() # verify
```

### Example 5: [Apply an OpenStudio Measure](docs/examples/05_apply_measure.md)

Apply a BCL measure from a local directory to modify the model.

```
You: List the arguments for the "set_building_name" measure,
     then apply it with the name "My New Office Building".
```

```
1. list_measure_arguments(measure_dir="/inputs/measures/set_building_name")
   → returns: [{name: "building_name", type: "String", default: "Test Building"}]
2. apply_measure(measure_dir="/inputs/measures/set_building_name",
     arguments={"building_name": "My New Office Building"})
3. get_building_info()  # verify name changed
```

### Example 6: [Model Cleanup and Organization](docs/examples/06_model_cleanup.md)

Rename and delete objects to clean up a model.

```
You: Rename "Thermal Zone 1" to "North Office Zone" and delete the
     unused "Storage Space" from the model.
```

```
1. rename_object(object_name="Thermal Zone 1", new_name="North Office Zone")
2. delete_object(object_name="Storage Space")
3. list_spaces()        # verify
4. list_thermal_zones() # verify
```

### Example 7: [Full Building Model](docs/examples/07_full_building.md)

Build a complete model programmatically — spaces, zones, HVAC, loads, weather, and simulate.

```
You: Build me a 3-zone model: a north office, south office, and core corridor.
     Use ASHRAE System 5 (packaged VAV with reheat), Chicago weather,
     and run an annual simulation.
```

```
1.  create_example_osm(name="three_zone_office")
2.  load_osm_model(osm_path=...)
3.  create_space(name="North Office")
4.  create_space(name="South Office")
5.  create_space(name="Core Corridor")
6.  create_thermal_zone(name="North Zone", space_names=["North Office"])
7.  create_thermal_zone(name="South Zone", space_names=["South Office"])
8.  create_thermal_zone(name="Core Zone", space_names=["Core Corridor"])
9.  add_baseline_system(system_type=5,
      thermal_zone_names=["North Zone", "South Zone", "Core Zone"])
10. create_people_definition(name="Office People",
      space_name="North Office", people_per_area=0.059)
11. create_lights_definition(name="Office Lights",
      space_name="North Office", watts_per_area=10.76)
12. set_weather_file(epw_path="/inputs/Chicago.epw")
13. add_design_day(name="Chicago Heating 99.6%", day_type="WinterDesignDay",
      month=1, day=21, dry_bulb_max_c=-20.6, dry_bulb_range_c=0.0)
14. add_design_day(name="Chicago Cooling .4%", day_type="SummerDesignDay",
      month=7, day=21, dry_bulb_max_c=33.3, dry_bulb_range_c=10.7)
15. save_osm_model(osm_path="/runs/three_zone.osm")
16. run_simulation(osm_path="/runs/three_zone.osm", epw_path="/inputs/Chicago.epw")
17. get_run_status(run_id=...)
18. extract_summary_metrics(run_id=...)
```

### Example 8: [Geometry Creation from Scratch](docs/examples/08_geometry_creation.md)

Build a multi-zone model from floor plans, match shared walls, and add glazing.

```
You: Create a two-zone office — west and east, each 10m x 10m, 3m tall,
     side by side. Match the shared wall, add 40% south glazing,
     and set the run period to January only.
```

```
1.  create_example_osm(name="two_zone")
2.  load_osm_model(osm_path=...)
3.  create_thermal_zone(name="Zone West")
4.  create_thermal_zone(name="Zone East")
5.  create_space_from_floor_print(name="West Office",
      floor_vertices=[[0,0],[10,0],[10,10],[0,10]],
      floor_to_ceiling_height=3.0, thermal_zone_name="Zone West")
6.  create_space_from_floor_print(name="East Office",
      floor_vertices=[[10,0],[20,0],[20,10],[10,10]],
      floor_to_ceiling_height=3.0, thermal_zone_name="Zone East")
7.  match_surfaces()                     # shared wall → interior boundary
8.  list_surfaces()                      # find exterior wall names
9.  set_window_to_wall_ratio(surface_name="...", ratio=0.4)
10. set_simulation_control(do_zone_sizing=true, run_for_sizing_periods=true)
11. set_run_period(begin_month=1, begin_day=1, end_month=1, end_day=31)
12. save_osm_model(save_path="/runs/two_zone.osm")
```

### Example 9: [Fenestration by Orientation](docs/examples/09_fenestration_by_orientation.md)

Apply different window-to-wall ratios per cardinal direction on an existing model.

```
You: Add windows to my baseline model — 40% on south walls, 25% north,
     30% east and west.
```

```
1. create_baseline_osm(name="fenestration_study", ashrae_sys_num="03")
2. load_osm_model(osm_path=...)
3. list_surfaces()   # get all surfaces with azimuth for orientation binning
   # South: 135-225°, North: 315-45°, East: 45-135°, West: 225-315°
4. set_window_to_wall_ratio(surface_name="South Wall 1", ratio=0.4)
5. set_window_to_wall_ratio(surface_name="North Wall 1", ratio=0.25)
6. set_window_to_wall_ratio(surface_name="East Wall 1", ratio=0.3)
7. set_window_to_wall_ratio(surface_name="West Wall 1", ratio=0.3)
   ... repeat for all exterior walls ...
8. list_subsurfaces()  # verify all windows created
9. save_osm_model(save_path="/runs/with_fenestration.osm")
```

### Example 10: [Standards-Based Typical Building](docs/examples/10_comstock_typical_building.md)

Apply 90.1-2019 constructions, loads, HVAC, and schedules to any model with geometry.

```
You: Load my small office model and apply the 90.1-2019 typical building
     template for climate zone 2A. Show me what was added.
```

```
1. list_comstock_measures(category="setup")    # browse available templates
2. load_osm_model(osm_path="SmallOffice.osm")
3. set_weather_file(epw_path="Houston.epw")
4. create_typical_building(template="90.1-2019",
     climate_zone="ASHRAE 169-2013-2A")
5. get_model_summary()        # verify HVAC + constructions added
6. list_air_loops()           # inspect HVAC system
7. list_constructions()       # inspect envelope
8. save_osm_model(save_path="/runs/typical_office.osm")
```

### Example 11: [Simulation Results Deep Dive](docs/examples/11_results_extraction.md)

Extract structured results — energy breakdown, envelope, HVAC sizing, timeseries — without reading raw HTML.

```
You: Show me the end-use energy breakdown, envelope summary, HVAC sizing,
     and daily electricity for January from my last simulation run.
```

```
1. extract_end_use_breakdown(run_id=<id>, units="IP")
2. extract_envelope_summary(run_id=<id>)
3. extract_hvac_sizing(run_id=<id>)
4. extract_zone_summary(run_id=<id>)
5. extract_component_sizing(run_id=<id>, component_type="Coil")
6. query_timeseries(run_id=<id>, variable_name="Electricity:Facility",
     frequency="Daily", start_month=1, end_month=1)
```

### Example 12: [One-Command Simulation (`/simulate`)](docs/examples/12_simulate.md)

Run a simulation and get results in one step.

```
You: /simulate
```

```
1. save_osm_model(save_path="/runs/model.osm")
2. run_simulation(osm_path="/runs/model.osm", epw_path="/inputs/weather.epw")
3. get_run_status(run_id=...)          # polls until complete
4. extract_summary_metrics(run_id=...) # EUI, total energy, unmet hours
5. extract_end_use_breakdown(run_id=...)
6. Presents formatted results summary
```

### Example 13: [Comprehensive Energy Report (`/energy-report`)](docs/examples/13_energy_report.md)

Extract all result categories from a completed simulation.

```
You: /energy-report
```

```
1. extract_summary_metrics(run_id=...)       # EUI, total energy
2. extract_end_use_breakdown(run_id=...)     # by fuel + end use
3. extract_envelope_summary(run_id=...)      # U-values, SHGC
4. extract_hvac_sizing(run_id=...)           # zone/system capacities
5. extract_zone_summary(run_id=...)          # per-zone loads
6. extract_component_sizing(run_id=...)      # autosized values
7. Presents structured report with all sections
```

### Example 14: [Model Quality Check (`/qaqc`)](docs/examples/14_qaqc.md)

Check your model for common issues before running a simulation.

```
You: /qaqc
```

```
1. inspect_osm_summary()             # structural overview
2. get_model_summary()               # object counts
3. list_thermal_zones()              # zones without HVAC?
4. list_spaces()                     # spaces without zones?
5. get_weather_info()                # EPW attached?
6. get_run_period()                  # simulation dates set?
7. list_zone_hvac_equipment()        # HVAC present?
8. Reports issues by severity (errors, warnings, info)
```

### Example 15: [Guided HVAC Selection (`/add-hvac`)](docs/examples/15_add_hvac.md)

Get a recommendation for the right HVAC system based on your building.

```
You: /add-hvac
```

```
1. get_building_info()                        # building type, area
2. list_thermal_zones()                       # zone count, names
3. Recommends system type based on ASHRAE 90.1 Table G3.1.1
4. add_baseline_system(system_type=3,
     thermal_zone_names=["Zone 1", "Zone 2"],
     heating_fuel="NaturalGas")
5. list_air_loops()                           # verify
6. list_zone_hvac_equipment()                 # verify
```

### Example 16: [Complete Building from Scratch (`/new-building`)](docs/examples/16_new_building.md)

Create a full building model step by step.

```
You: /new-building
```

```
1.  create_baseline_osm(name="office", ashrae_sys_num="03")
2.  load_osm_model(osm_path=...)
3.  list_surfaces()                           # find exterior walls
4.  set_window_to_wall_ratio(surface_name="South Wall", ratio=0.4)
5.  create_schedule_ruleset(name="Occ", schedule_type="Fractional", default_value=0.5)
6.  create_people_definition(name="People", space_name=..., people_per_area=0.059)
7.  create_lights_definition(name="Lights", space_name=..., watts_per_area=10.76)
8.  create_electric_equipment(name="Plugs", space_name=..., watts_per_area=1.076)
9.  set_weather_file(epw_path="/inputs/weather.epw")
10. add_design_day(name="Htg 99.6%", ...)
11. add_design_day(name="Clg 0.4%", ...)
12. save_osm_model(save_path="/runs/office.osm")
13. run_simulation(osm_path="/runs/office.osm", epw_path="/inputs/weather.epw")
14. extract_summary_metrics(run_id=...)
```

### Example 17: [Retrofit Analysis (`/retrofit`)](docs/examples/17_retrofit.md)

Apply energy conservation measures and compare before/after performance.

```
You: /retrofit
```

```
1.  save_osm_model(save_path="/runs/baseline.osm")
2.  run_simulation(osm_path="/runs/baseline.osm", epw_path=...)
3.  extract_summary_metrics(run_id=<baseline>)  # record baseline EUI
4.  adjust_thermostat_setpoints(cooling_offset_f=2.0, heating_offset_f=-2.0)
5.  save_osm_model(save_path="/runs/retrofit.osm")
6.  run_simulation(osm_path="/runs/retrofit.osm", epw_path=...)
7.  extract_summary_metrics(run_id=<retrofit>)   # compare EUI
8.  extract_end_use_breakdown(run_id=<retrofit>)
9.  Presents side-by-side comparison
```

### Example 18: [Model Visualization (`/view`)](docs/examples/18_view.md)

Generate an interactive 3D view of your model.

```
You: /view
```

```
1. view_model()
2. Reports output file path — open in browser
```

---

## Claude Code Skills

When using openstudio-mcp with [Claude Code](https://docs.anthropic.com/en/docs/claude-code), 10 bundled skills provide workflow automation and domain knowledge:

| Skill | Type | Description |
|-------|------|-------------|
| `/simulate` | Workflow | One-command simulate + results extraction |
| `/energy-report` | Workflow | Comprehensive multi-category energy report |
| `/qaqc` | Task | Pre-simulation model quality check |
| `/add-hvac` | Task | Guided ASHRAE system selection |
| `/new-building` | Workflow | Full model creation from scratch |
| `/retrofit` | Workflow | Before/after ECM analysis |
| `/view` | Task | Quick 3D model visualization |
| `ashrae-baseline-guide` | Knowledge | ASHRAE 90.1 system selection criteria (auto-loaded) |
| `openstudio-patterns` | Knowledge | Tool dependencies and model relationships (auto-loaded) |
| `tool-workflows` | Knowledge | Multi-tool recipes for common operations (auto-loaded) |

Workflow skills are invoked with `/skill-name`. Knowledge skills load automatically when relevant.

### Workflow Guides for All MCP Clients

The same workflow guides are also available as MCP tools, so any MCP client (Claude Desktop, Cursor, etc.) can discover them:

- `list_skills()` — see available workflows with descriptions
- `get_skill(name)` — get step-by-step instructions for a specific workflow

Mount the skills directory when running the container: `-v ./.claude/skills:/skills:ro`

---

## Skills & Tools (126 total)

### Skill Discovery (2 tools)
| Tool | Description |
|------|-------------|
| `list_skills` | List available workflow guides |
| `get_skill` | Get step-by-step instructions for a workflow |

### Server Info (2 tools)
| Tool | Description |
|------|-------------|
| `get_server_status` | Server health check |
| `get_versions` | OpenStudio, EnergyPlus, Ruby versions |

### Model Management (6 tools)
| Tool | Description |
|------|-------------|
| `create_example_osm` | Create single-zone example model |
| `create_baseline_osm` | Create 10-zone baseline with ASHRAE system 1-10 |
| `inspect_osm_summary` | Quick structural summary of OSM file |
| `load_osm_model` | Load OSM into memory for querying/editing |
| `save_osm_model` | Save in-memory model to disk |
| `list_files` | Discover files in /inputs and /runs (OSM, EPW, results) |

### Building (3 tools)
| Tool | Description |
|------|-------------|
| `get_building_info` | Building name, area, volume, orientation |
| `get_model_summary` | Object counts by category |
| `list_building_stories` | List building stories with spaces |

### Spaces (6 tools)
| Tool | Description |
|------|-------------|
| `list_spaces` | List all spaces with area/volume |
| `get_space_details` | Detailed space info (surfaces, loads, zone) |
| `list_thermal_zones` | List thermal zones with spaces |
| `get_thermal_zone_details` | Zone equipment, thermostat, multiplier |
| `create_space` | Create space with optional story/space type |
| `create_thermal_zone` | Create thermal zone, assign spaces |

### Geometry (8 tools)
| Tool | Description |
|------|-------------|
| `list_surfaces` | List surfaces (walls, floors, roofs) |
| `get_surface_details` | Surface vertices, construction, boundary |
| `list_subsurfaces` | List windows, doors, skylights |
| `create_surface` | Create surface with explicit 3D vertices |
| `create_subsurface` | Create window/door on a parent surface |
| `create_space_from_floor_print` | Extrude floor polygon into space with all surfaces |
| `match_surfaces` | Intersect + match shared walls between adjacent spaces |
| `set_window_to_wall_ratio` | Add centered window by glazing ratio (e.g. 0.4 = 40%) |

### Constructions (6 tools)
| Tool | Description |
|------|-------------|
| `list_materials` | List materials with thermal properties |
| `list_constructions` | List constructions with layers |
| `list_construction_sets` | List default construction sets |
| `create_standard_opaque_material` | Create material with conductivity/density |
| `create_construction` | Create layered construction from materials |
| `assign_construction_to_surface` | Assign construction to surface |

### Schedules (3 tools)
| Tool | Description |
|------|-------------|
| `list_schedule_rulesets` | List schedule rulesets |
| `get_schedule_details` | Schedule type, values, rules |
| `create_schedule_ruleset` | Create constant schedule (Fractional/Temp/OnOff) |

### HVAC (7 tools)
| Tool | Description |
|------|-------------|
| `list_air_loops` | List air loops with zones served |
| `get_air_loop_details` | Air loop components, sizing, OA system |
| `add_air_loop` | Create air loop and connect zones |
| `list_plant_loops` | List plant loops (heating, cooling, condenser) |
| `get_plant_loop_details` | Plant loop supply/demand components |
| `list_zone_hvac_equipment` | List zone-level HVAC equipment |
| `get_zone_hvac_details` | Zone equipment details |

### Loads (10 tools)
| Tool | Description |
|------|-------------|
| `list_people_loads` | List people/occupancy definitions |
| `list_lighting_loads` | List lighting definitions |
| `list_electric_equipment` | List electric equipment |
| `list_gas_equipment` | List gas equipment |
| `list_infiltration` | List infiltration definitions |
| `create_people_definition` | Create people load (by area or count) |
| `create_lights_definition` | Create lighting load (by area or wattage) |
| `create_electric_equipment` | Create electric equipment load |
| `create_gas_equipment` | Create gas equipment load |
| `create_infiltration` | Create infiltration (by area or ACH) |

### Space Types (2 tools)
| Tool | Description |
|------|-------------|
| `list_space_types` | List space types with default loads |
| `get_space_type_details` | Space type loads, schedules, standards |

### Simulation (7 tools)
| Tool | Description |
|------|-------------|
| `validate_osw` | Validate OSW workflow file |
| `run_osw` | Run EnergyPlus simulation from an OSW file |
| `run_simulation` | Run simulation from just an OSM + optional EPW |
| `get_run_status` | Poll simulation run status |
| `get_run_logs` | Tail simulation logs |
| `get_run_artifacts` | List simulation output files |
| `cancel_run` | Cancel running simulation |

### Results (9 tools)
| Tool | Description |
|------|-------------|
| `extract_summary_metrics` | Extract EUI, energy, unmet hours from results |
| `read_run_artifact` | Read simulation output file contents |
| `copy_run_artifact` | Copy large artifact to host-mounted path |
| `extract_end_use_breakdown` | Energy breakdown by end use and fuel type (IP/SI) |
| `extract_envelope_summary` | Opaque + fenestration U-values and areas |
| `extract_hvac_sizing` | Autosized zone and system HVAC capacities |
| `extract_zone_summary` | Per-zone areas, conditions, multipliers |
| `extract_component_sizing` | Autosized HVAC component values (filterable) |
| `query_timeseries` | Time-series output variable data with date/cap filters |

### Simulation Outputs (2 tools)
| Tool | Description |
|------|-------------|
| `add_output_variable` | Add EnergyPlus output variable |
| `add_output_meter` | Add EnergyPlus output meter |

### HVAC Systems (8 tools)
| Tool | Description |
|------|-------------|
| `add_baseline_system` | Add ASHRAE 90.1 baseline system (types 1-10) |
| `list_baseline_systems` | List all baseline + modern template types |
| `get_baseline_system_info` | Get metadata for specific system type |
| `replace_air_terminals` | Replace ALL terminals on an air loop |
| `replace_zone_terminal` | Replace terminal on a single zone |
| `add_doas_system` | Add DOAS with fan coils, radiant, or chilled beams |
| `add_vrf_system` | Add VRF multi-zone heat pump system |
| `add_radiant_system` | Add low-temperature radiant heating/cooling |

### Component Properties (6 tools)
| Tool | Description |
|------|-------------|
| `list_hvac_components` | List all HVAC components (15 types: coils, plant, fans, pumps) |
| `get_component_properties` | Read all properties of a named component |
| `set_component_properties` | Modify properties on a named component |
| `set_economizer_properties` | Modify OA economizer settings on air loop |
| `set_sizing_properties` | Modify plant loop sizing (exit temp, delta-T) |
| `set_setpoint_manager_properties` | Modify setpoint manager min/max temps |

### Loop Operations (4 tools)
| Tool | Description |
|------|-------------|
| `add_supply_equipment` | Add boiler/chiller/tower to plant loop supply |
| `remove_supply_equipment` | Remove equipment from plant loop supply |
| `add_zone_equipment` | Add baseboard/unit heater to thermal zone |
| `remove_zone_equipment` | Remove equipment from thermal zone |

### Object Management (3 tools)
| Tool | Description |
|------|-------------|
| `delete_object` | Delete any named object (28+ supported types) |
| `rename_object` | Rename any named object |
| `list_model_objects` | List all objects of a given type |

### Weather & Simulation Config (7 tools)
| Tool | Description |
|------|-------------|
| `get_weather_info` | Read weather file info (city, lat, lon, timezone) |
| `set_weather_file` | Attach EPW weather file to model |
| `add_design_day` | Add heating/cooling design day |
| `get_simulation_control` | Read sizing flags and timesteps per hour |
| `set_simulation_control` | Modify sizing flags and/or timestep |
| `get_run_period` | Read run period begin/end dates |
| `set_run_period` | Set run period dates (auto-enables weather file run) |

### Measures (2 tools)
| Tool | Description |
|------|-------------|
| `list_measure_arguments` | List measure arguments with defaults and choices |
| `apply_measure` | Apply OpenStudio measure to in-memory model |

### ComStock Measures (2 tools)

~61 bundled [ComStock](https://github.com/NREL/ComStock) measures (openstudio-standards-based templates for space types, constructions, HVAC, schedules). Pre-installed in Docker image.

| Tool | Description |
|------|-------------|
| `list_comstock_measures` | List bundled measures with category filter (baseline/upgrade/setup) |
| `create_typical_building` | Add constructions, loads, HVAC, SWH to a model with geometry |

### Common Measures (21 tools)

~79 bundled [openstudio-common-measures-gem](https://github.com/NREL/openstudio-common-measures-gem) measures (reporting, thermostats, envelope, renewables, visualization, model cleanup). Pre-installed in Docker image. 20 curated measures with 21 dedicated wrapper tools.

| Tool | Description |
|------|-------------|
| `list_common_measures` | List bundled measures with category filter (reporting/thermostat/envelope/loads/renewables/etc.) |
| `view_model` | Generate interactive 3D Three.js HTML viewer of model geometry |
| `view_simulation_data` | Generate 3D viewer with simulation data overlaid on surfaces |
| `generate_results_report` | Comprehensive HTML report (~25 sections: energy, HVAC, envelope, zones) |
| `run_qaqc_checks` | ASHRAE baseline QA/QC checks (efficiency, capacity, envelope, loads) |
| `adjust_thermostat_setpoints` | Shift all heating/cooling setpoints by degree offset |
| `replace_window_constructions` | Bulk-replace all exterior window constructions |
| `enable_ideal_air_loads` | Enable ideal air loads on all zones (quick sizing studies) |
| `clean_unused_objects` | Remove orphan objects and unused resources |
| `inject_idf` | Inject raw IDF objects from external file |
| `change_building_location` | Set weather file + climate zone + design days |
| `set_thermostat_schedules` | Apply thermostat schedules from library |
| `replace_thermostat_schedules` | Replace existing thermostat schedules |
| `shift_schedule_time` | Shift schedule profiles by hours |
| `add_rooftop_pv` | Add rooftop PV panels |
| `add_pv_to_shading` | Add PV to shading surfaces by type |
| `add_ev_load` | Add electric vehicle charging load |
| `add_zone_ventilation` | Add zone ventilation design flow rate |
| `set_lifecycle_cost_params` | Set lifecycle cost analysis parameters |
| `add_cost_per_floor_area` | Add cost per floor area to building |
| `set_adiabatic_boundaries` | Set exterior walls/floors to adiabatic |

---

## ASHRAE Baseline Systems

All 10 ASHRAE 90.1 Appendix G baseline systems are supported via `add_baseline_system`:

| System | Type | Description |
|--------|------|-------------|
| 01 | PTAC | Packaged terminal AC (zone-level) |
| 02 | PTHP | Packaged terminal heat pump (zone-level) |
| 03 | PSZ-AC | Packaged single-zone rooftop AC |
| 04 | PSZ-HP | Packaged single-zone heat pump |
| 05 | Packaged VAV w/ Reheat | VAV with hot water reheat coils |
| 06 | Packaged VAV w/ PFP Boxes | VAV with parallel fan-powered boxes |
| 07 | VAV w/ Reheat | Central VAV, chiller + boiler + cooling tower |
| 08 | VAV w/ PFP Boxes | Central VAV with parallel fan-powered terminal |
| 09 | Gas Unit Heater | Heating-only (warehouses, garages) |
| 10 | Electric Unit Heater | Heating-only, electric |

Plus 3 modern templates: **DOAS**, **VRF**, **Radiant**.

---

## Supported HVAC Component Types

The component properties tools can query and modify these 15 HVAC component types:

| Category | Components |
|----------|------------|
| **Coils** | CoilHeatingGas, CoilHeatingElectric, CoilHeatingWater, CoilCoolingWater, CoilCoolingDXSingleSpeed, CoilCoolingDXTwoSpeed, CoilHeatingDXSingleSpeed |
| **Plant** | BoilerHotWater, ChillerElectricEIR, CoolingTowerSingleSpeed |
| **Fans** | FanConstantVolume, FanVariableVolume, FanOnOff |
| **Pumps** | PumpConstantSpeed, PumpVariableSpeed |

---

## Testing

### Unit tests (no Docker)

```bash
pytest tests/test_skill_registration.py -v
```

### Integration tests (Docker)

```bash
docker build -t openstudio-mcp:dev -f docker/Dockerfile .

# Run all integration tests
docker run --rm -v "$PWD:/repo" -v "$PWD/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc 'cd /repo && pytest -vv -s tests/'

# Run specific test file
docker run --rm -v "$PWD:/repo" -v "$PWD/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc 'cd /repo && pytest -vv -s tests/test_hvac_systems.py'
```

---

## Dev vs Prod Mode

| Mode | Purpose | Behavior |
|------|---------|----------|
| `dev` (default) | Local development | FastMCP banner + INFO logs |
| `prod` | MCP host usage | Banner disabled, quieter logs |

```bash
# Prod mode (recommended for MCP hosts)
docker run --rm -i -e OPENSTUDIO_MCP_MODE=prod openstudio-mcp:dev openstudio-mcp
```

In **prod mode**, stdout is reserved exclusively for MCP JSON-RPC messages. Logs go to stderr.

---

## Architecture

- **Transport:** stdio (container spawned by host)
- **Protocol:** MCP (JSON-RPC over stdin/stdout)
- **Model state:** single in-memory model via `model_manager`
- **Runs:** stored under `/runs/<run_id>/`
- **Skills pattern:** each skill in `mcp_server/skills/<name>/` with `tools.py` (MCP registration) + `operations.py` (business logic)

Full system diagram, security analysis & hardening recommendations: **[docs/architecture.md](docs/architecture.md)**

---

## Contributing

### Adding a new MCP skill

1. Create `mcp_server/skills/<name>/__init__.py`, `operations.py`, `tools.py`
2. `operations.py` — pure business logic, returns `{"ok": True/False, ...}` dicts
3. `tools.py` — exports `register(mcp)`, defines MCP tool schemas
4. Add tests in `tests/test_<name>.py`
5. Add CI step in `.github/workflows/ci.yml`
6. The skill auto-registers via `skills/__init__.py` discovery
7. Update `EXPECTED_TOOLS` in `tests/test_skill_registration.py`
8. Update tool counts in `README.md` and `CLAUDE.md`

### Adding a new Claude Code skill (workflow guide)

1. Create `.claude/skills/<name>/SKILL.md` with YAML frontmatter:
   ```yaml
   ---
   name: my-skill
   description: Short description for discovery
   ---
   ```
2. Add workflow instructions in the markdown body referencing MCP tool names
3. For user-invocable skills, add `user-invocable: true` (or omit — default)
4. For background knowledge, add `user-invocable: false`
5. For fire-and-forget workflows, add `context: fork`
6. Add integration test in `tests/test_skill_<name>.py` exercising the tool sequence
7. Add test to a CI shard in `.github/workflows/ci.yml`
8. Add example doc in `docs/examples/<N>_<name>.md`
9. Update README examples section and Claude Code Skills table
10. The skill auto-appears in `list_skills()` / `get_skill()` via the `/skills` mount

### Adding a new HVAC component type

1. Add `_get_<type>_props(obj)` and `_set_<type>_props(obj, properties)` in `components.py`
2. Add entry to `COMPONENT_TYPES` dict
3. Add test in `tests/test_component_properties.py`
4. No dynamic dispatch — every OpenStudio API call must be explicit and grepable

---

## License

See [LICENSE](LICENSE.md).
