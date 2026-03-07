# openstudio-mcp

[![MCP Badge](https://lobehub.com/badge/mcp/natlabrockies-openstudio-mcp?style=for-the-badge)](https://lobehub.com/mcp/natlabrockies-openstudio-mcp)

**Model Context Protocol (MCP)** server for **OpenStudio** building energy simulation. Enables LLMs and MCP hosts (Claude Desktop, Cursor, Claude Code, etc.) to create, query, and modify OpenStudio models, run EnergyPlus simulations, and inspect results — all through natural language.

**22 skills &bull; 127 MCP tools &bull; 6 prompts &bull; 4 resources &bull; 450+ integration tests**

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
git clone https://github.com/NatLabRockies/openstudio-mcp.git
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

Open Claude Desktop and look for the **hammer icon** (MCP tools indicator) in the chat input area. Click it to see the 127 openstudio-mcp tools listed. If the icon doesn't appear, check that Docker is running and the config JSON is valid.

### Step 4: Start Chatting

Try these prompts in order of complexity:

> **Simple:** "Create an example model and tell me about it"

> **Medium:** "Create a baseline office with ASHRAE System 3 and show me the HVAC components"

> **Advanced:** "Load my model at /inputs/MyBuilding.osm, apply the 90.1-2019 typical building template, and run a simulation"

The AI reads your prompt, picks the right tools from the 127 available, calls them in sequence, and summarizes the results — no scripting required.

### Other MCP Hosts

[Cursor](https://www.cursor.com/), [VS Code](https://code.visualstudio.com/), and [Claude Code](https://docs.anthropic.com/en/docs/claude-code) also support MCP with similar JSON config. See the [MCP documentation](https://modelcontextprotocol.io/quickstart/user) for host-specific setup.

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

## Skills & Tools (127 total)

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

### Loop Operations (5 tools)
| Tool | Description |
|------|-------------|
| `add_supply_equipment` | Add boiler/chiller/tower to plant loop supply |
| `remove_supply_equipment` | Remove equipment from plant loop supply |
| `add_zone_equipment` | Add baseboard/unit heater to thermal zone |
| `remove_zone_equipment` | Remove equipment from thermal zone |
| `remove_all_zone_equipment` | Batch-remove ALL equipment from multiple zones |

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

## Examples

18 worked examples with full tool-call sequences — click to expand:

| # | Example | Description |
|---|---------|-------------|
| 1 | [Baseline Comparison](docs/examples/01_baseline_comparison.md) | Compare ASHRAE System 3 vs System 7 EUI |
| 2 | [HVAC Design Exploration](docs/examples/02_hvac_design_exploration.md) | DOAS + fan coils, tune setpoints, resize components |
| 3 | [Envelope Retrofit](docs/examples/03_envelope_retrofit.md) | Upgrade wall insulation, measure heating impact |
| 4 | [Internal Loads](docs/examples/04_internal_loads.md) | People, lighting, plug loads with schedules |
| 5 | [Apply a Measure](docs/examples/05_apply_measure.md) | Run a BCL measure from a local directory |
| 6 | [Model Cleanup](docs/examples/06_model_cleanup.md) | Rename/delete objects to organize a model |
| 7 | [Full Building Model](docs/examples/07_full_building.md) | Spaces, zones, HVAC, loads, weather, simulate |
| 8 | [Geometry from Scratch](docs/examples/08_geometry_creation.md) | Floor-print extrusion, surface matching, glazing |
| 9 | [Fenestration by Orientation](docs/examples/09_fenestration_by_orientation.md) | Per-orientation window-to-wall ratios |
| 10 | [Typical Building (ComStock)](docs/examples/10_comstock_typical_building.md) | 90.1-2019 template: constructions, loads, HVAC |
| 11 | [Results Deep Dive](docs/examples/11_results_extraction.md) | End-use breakdown, envelope, HVAC sizing, timeseries |
| 12 | [`/simulate`](docs/examples/12_simulate.md) | One-command simulate + results |
| 13 | [`/energy-report`](docs/examples/13_energy_report.md) | Comprehensive multi-category report |
| 14 | [`/qaqc`](docs/examples/14_qaqc.md) | Pre-simulation model quality check |
| 15 | [`/add-hvac`](docs/examples/15_add_hvac.md) | Guided ASHRAE system selection |
| 16 | [`/new-building`](docs/examples/16_new_building.md) | Full model creation from scratch |
| 17 | [`/retrofit`](docs/examples/17_retrofit.md) | Before/after ECM analysis |
| 18 | [`/view`](docs/examples/18_view.md) | Interactive 3D model visualization |

---

## Testing

For the full testing guide — framework details, annotated examples, CI shards, and how to write new tests — see **[`docs/testing.md`](docs/testing.md)**.

### Quick start

```bash
# Unit tests (no Docker)
pytest tests/test_skill_registration.py -v

# Integration tests (Docker)
docker build -t openstudio-mcp:dev -f docker/Dockerfile .

docker run --rm -v "$PWD:/repo" -v "$PWD/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc 'cd /repo && pytest -vv -s tests/'
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
