# OpenStudio®-MCP SWR 26-035

[![DOI](https://zenodo.org/badge/1160362004.svg)](https://doi.org/10.5281/zenodo.21905081)
[![SoftwareX paper](https://img.shields.io/badge/SoftwareX-10.1016%2Fj.softx.2026.103020-orange)](https://doi.org/10.1016/j.softx.2026.103020)

**Model Context Protocol server for [OpenStudio](https://openstudio.net/) building energy simulation.** It lets MCP hosts — Claude Desktop, Claude Code, Codex, VS Code — create, query, and modify OpenStudio models, run EnergyPlus, and read results, all in plain language. The server handles the OpenStudio/EnergyPlus complexity behind MCP tool calls.

**150+ tools · bundled workflow skills · 500+ integration tests**

Published in *SoftwareX* — see [Cite this work](#cite-this-work).

## Contents

- [What you can ask for](#what-you-can-ask-for)
- [Quick start (local)](#quick-start-local)
  - [1. Get the image](#1-get-the-image)
  - [2. Configure your host](#2-configure-your-host)
  - [3. Verify and chat](#3-verify-and-chat)
  - [Working with your own files](#working-with-your-own-files)
  - [Client compatibility](#client-compatibility)
- [Remote & multi-user (HTTP)](#remote--multi-user-http)
- [Security and simulation sandbox](#security-and-simulation-sandbox)
  - [Sandbox options](#sandbox-options)
  - [Secure deployment guidance](#secure-deployment-guidance)
- [Skills & Tools](#skills--tools-150-total)
- [Tool reference](#tool-reference)
- [Reference](#reference)
  - [ASHRAE baseline systems](#ashrae-baseline-systems)
  - [HVAC component types](#hvac-component-types)
- [Examples](#examples)
- [Testing](#testing)
- [Linting and formatting](#linting-and-formatting-uv--pre-commit)
- [Architecture](#architecture)
  - [Contributing](#contributing)
- [Cite this work](#cite-this-work)
- [License](#license)

---

## What you can ask for

- *"Create a 10-zone office with VAV reheat and run an annual simulation."*
- *"What's the EUI? Show me the unmet heating hours."*
- *"Switch the HVAC from VAV to VRF heat pumps and compare energy use."*
- *"Add R-30 roof insulation and see how it affects the cooling load."*
- *"Build two adjacent zones from floor plans, match the shared wall, add 40% south glazing."*
- *"Write a measure that sets all lights to 8 W/m², test it, apply it, and compare the EUI."*
- *"Submit this OpenStudio analysis JSON to my server, wait for completion, and download the results"*
- *"Apply the AEDG Small Office measure from my local measures directory"*

The AI picks the right tools, calls them in sequence, and summarizes — no scripting.

---

## Quick start (local)

Runs the server locally over stdio — one container per user, launched by your MCP host. For a shared deployment, see [Remote & multi-user](#remote--multi-user-http).

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) running, and an MCP host ([Claude Desktop](https://claude.ai/download) is the easiest start).

### 1. Get the image

**Option A: Pull from Docker Hub** (no checkout needed)

```bash
docker pull nrel/openstudio-mcp:v1.2.1
```

Tags on [`nrel/openstudio-mcp`](https://hub.docker.com/r/nrel/openstudio-mcp/tags):

| Tag | What it is |
|-----|------------|
| `vX.Y.Z` (e.g. `v1.2.1`) | A tagged release. Pin one of these for reproducible work |
| `dev` | Latest `develop` branch build; moves on every merge |

Every tag is a multi-arch manifest (amd64 + arm64), so the same `docker pull` works on Intel/AMD and Apple Silicon.

**Option B: Build locally** (for development, or to run unreleased changes)

```bash
git clone https://github.com/NatLabRockies/openstudio-mcp.git
cd openstudio-mcp
```

| Machine | Build command |
|---------|---------------|
| Intel/AMD (Linux, Windows, Intel Mac) | `docker build -t openstudio-mcp:dev -f docker/Dockerfile .` |
| Apple Silicon (M-series) | `docker build --platform linux/arm64 -t openstudio-mcp:dev -f docker/Dockerfile.arm64 .` |

Both produce a local image tagged `openstudio-mcp:dev`. The arm64 Dockerfile builds natively from NREL's arm64 `.deb` (the upstream `nrel/openstudio` base is amd64-only, so plain `Dockerfile` runs under slow emulation on Apple Silicon).

**Remember your image name.** Step 2 uses `openstudio-mcp:dev` (the local build). If you pulled instead, substitute `nrel/openstudio-mcp:v1.2.1` (or whichever tag you pulled) wherever `openstudio-mcp:dev` appears.

### 2. Configure your host

Pick three host folders first: one with your models (mounted read-only at `/inputs`), one for simulation output (`/runs`), and one for measures you author or download (`/measures`). Create them if they don't exist. In the snippets below they are `/path/to/models`, `/path/to/runs`, and `/path/to/measures`; replace them with absolute paths.

**Option A: Claude Desktop (JSON)**

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows), then restart Claude Desktop.

```json
{
  "mcpServers": {
    "openstudio-mcp": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/path/to/models:/inputs:ro",
        "-v", "/path/to/runs:/runs",
        "-v", "/path/to/measures:/measures",
        "-e", "OPENSTUDIO_MCP_MODE=prod",
        "openstudio-mcp:dev", "openstudio-mcp"
      ]
    }
  }
}
```

**Option B: Codex & other clients (TOML)**

Add to your client config (e.g., `~/.codex/config.toml` on macOS/Linux, `%USERPROFILE%\.codex\config.toml` on Windows).

```toml
[mcp_servers.openstudio-mcp]
command = "docker"
startup_timeout_sec = 120
args = [
  "run", "--rm", "-i",
  "-v", "/path/to/models:/inputs:ro",
  "-v", "/path/to/runs:/runs",
  "-v", "/path/to/measures:/measures",
  "-e", "OPENSTUDIO_MCP_MODE=prod",
  "openstudio-mcp:dev", "openstudio-mcp"
]
```

**Image name:** the second-to-last argument (`openstudio-mcp:dev`) must match the image from step 1. If you pulled from Docker Hub, change it to `nrel/openstudio-mcp:v1.2.1` (or the tag you pulled). Otherwise Docker fails with `Unable to find image 'openstudio-mcp:dev'`.

**Mounts:** each `-v host:container` line shares a host folder with the container. The container is discarded on exit (`--rm`), so anything you want to keep must live on a mount:

| Container path | Host folder | Why |
|----------------|-------------|-----|
| `/inputs` (read-only) | your models, weather files, gbXML, error files | The AI can only open files it can see. Put a file here and refer to it as `/inputs/<name>` in your prompt |
| `/runs` | simulation output | Every run writes to `/runs/<run_id>/` (OSM, SQL, HTML reports). Without the mount, results vanish when the container exits |
| `/measures` | authored + BCL measures | `create_measure` and BCL downloads land under `/measures/<user>/{custom,bcl}`. Mount it so measures survive restarts; `list_local_measures` discovers them |

**Use absolute paths.** On Windows, use forward slashes in Docker args:
```json
"-v", "C:/Users/you/models:/inputs:ro",
"-v", "C:/Users/you/openstudio-runs:/runs",
"-v", "C:/Users/you/openstudio-measures:/measures",
```

**Restart your client** after saving the config file.

### 3. Verify and chat

Open your host's tools menu (in Claude Desktop, the tools/connectors button under the prompt box) and confirm the `openstudio-mcp` server is listed with its tools. Then try these prompts in order of complexity:

> **Simple:** "Create an example model and tell me about it"

> **Medium:** "Create a baseline office with ASHRAE System 3 and show me the HVAC components"

> **Advanced:** "Load my model at /inputs/MyBuilding.osm, apply the 90.1-2019 typical building template, and run a simulation"

The AI reads your prompt, picks the right tools from the 150+ available, calls them in sequence, and summarizes the results, no scripting required.

### Working with Your Own Files

**Place files in the host folder mapped to `/inputs`** (see [step 2](#2-configure-your-host)) rather than uploading them (drag-and-drop or attach) through the web or desktop chat interface. Uploads never reach the MCP tools; mounted files do.

```bash
# Example: analyzing an EnergyPlus error file in an AI-chat session
# 1. Copy to the host folder mounted at /inputs
cp eplusout.err /path/to/models/

# 2. Reference by MCP path in your prompt
"Analyze the warnings in /inputs/eplusout.err and create a measure to fix them"
```

**Why not upload?** Attaching a file to the chat (drag-and-drop, the paperclip button, or paste) only gives the AI the file's contents in the conversation. It never lands on disk inside the Docker container, so MCP tools like `load_osm_model` can't open it, and the AI may fall back to writing scripts instead of using the 150+ MCP tools. A file in the `/inputs` mount is on disk where the tools can read it. Simulation outputs (results, SQL, HTML reports) are already under `/runs` and need no copying.

### Client Compatibility

Any MCP host can launch the same `docker run` command. See the [MCP documentation](https://modelcontextprotocol.io/quickstart/user) for host-specific config locations ([VS Code Copilot](https://code.visualstudio.com/), [Claude Code](https://docs.anthropic.com/en/docs/claude-code), [Codex](https://developers.openai.com/codex), [Windsurf](https://windsurf.com/), [Gemini CLI](https://github.com/google-gemini/gemini-cli)).

| Client | Status | Notes |
|--------|--------|-------|
| Claude Desktop | Full support | All tools available |
| Claude Code | Full support | ToolSearch auto-defers tools for efficient discovery |
| Codex | Compatible | MCP client via config |
| VS Code Copilot | Compatible | MCP support via config |
| Windsurf | Compatible | Host tool cap is ~100; use includeTools/excludeTools to limit the exposed tool set |
| Gemini CLI | Compatible | Use includeTools/excludeTools if needed |
| OpenAI API | Compatible | Use defer_loading for best results |

---

## Remote & multi-user (HTTP)

The quick start runs one container per user over stdio. To host it on one machine and let teammates connect from their own laptops — each with an isolated session, run directory, and optional bearer-token or JWT auth — run it over streamable HTTP (`-e MCP_TRANSPORT=http`). Works with Claude Code, VS Code, and any host that supports streamable-HTTP MCP servers.

Since a remote server can't see files on your laptop, the `file_transfer` tools (`request_upload` / `get_upload` / `request_download`) move models, weather files, and measure `.zip`s in and out over a signed, out-of-band channel — see **[docs/remote-multi-user.md §6](docs/remote-multi-user.md)**.

See **[docs/remote-multi-user.md](docs/remote-multi-user.md)** for setup, auth, the isolation model, and log access — and **[docs/run-retention.md](docs/run-retention.md)** for optional disk garbage-collection.

---

## Security and simulation sandbox

OpenStudio measures are Ruby or Python programs and must be treated as untrusted
code. EnergyPlus workflows can also invoke measure code. Docker isolates the
container from the host, while openstudio-mcp adds a second sandbox around the
child processes used by `apply_measure`, `test_measure`, measure metadata
refresh, and simulations.

The default `OSMCP_SANDBOX=auto` mode provides the following controls on Linux,
including Docker Desktop's Linux VM:

- **Privilege drop:** child processes run as the image's unprivileged
  `sandbox` user (UID/GID 1001), while the MCP server retains only the
  privileges needed to prepare run directories.
- **Filesystem policy:** Landlock denies filesystem access by default. The
  current run or staged measure directory is writable; required system and
  OpenStudio directories are read-only. `/repo`, `/inputs`, and other users'
  run directories are not exposed to measure code.
- **Network policy:** seccomp denies outbound IP networking by default.
- **Secret isolation:** child processes receive an allowlisted environment
  instead of inheriting API keys, tokens, and other server environment
  variables.
- **Process hardening:** `no_new_privs` prevents privilege recovery through
  setuid executables. Resource limits constrain generated file size and process
  count, and simulations have a wall-clock timeout.
- **Staging:** input models, weather files, measures, and OSWs are copied into a
  private run directory before execution. Escaping symlinks are rejected.

On Linux, `auto` fails closed if Landlock or the seccomp network filter cannot
be installed: the untrusted child process does not run. On native macOS or
Windows without Docker, kernel confinement is unavailable and the server warns
that only environment filtering is active. Use the Docker image when running
untrusted measures.

### Sandbox options

| Variable | Default | Behavior |
|----------|---------|----------|
| `OSMCP_SANDBOX` | `auto` | `auto`, `full`, and `landlock` request environment filtering, UID/GID drop, resource limits, Landlock filesystem confinement, and seccomp network denial. `posix` omits Landlock and seccomp. `off` disables child-process confinement and is only appropriate for trusted local code. Unknown values fall back to `auto`. |
| `OSMCP_SANDBOX_NET` | `deny` | `deny` blocks outbound IP networking. `allow` permits it for trusted measures that must fetch external resources. |
| `OSMCP_SANDBOX_UID` / `OSMCP_SANDBOX_GID` | `1001` | Account used for confined child processes. Values less than 1 are rejected. The default matches the `sandbox` user built into the image. |
| `OSMCP_SANDBOX_RLIMIT_FSIZE` | `10737418240` | Maximum size in bytes of one file created by a child process. `0` disables this limit. |
| `OSMCP_SANDBOX_RLIMIT_NPROC` | `1024` | Maximum processes/threads for the sandbox UID. `0` disables this limit. |
| `OSMCP_SANDBOX_RLIMIT_NOFILE` | `0` | Optional open-file descriptor limit. |
| `OSMCP_SANDBOX_RLIMIT_CPU` | `0` | Optional CPU-seconds limit. Disabled by default because annual simulations can be long-running. |
| `OSMCP_SANDBOX_RLIMIT_AS` | `0` | Optional virtual-memory limit. Prefer Docker memory limits because restrictive address-space limits can break EnergyPlus. |
| `OSMCP_SIM_TIMEOUT_SECONDS` | `7200` | Wall-clock timeout for a simulation. `0` disables the timeout. |

### Secure deployment guidance

- Mount `/inputs` read-only: `-v /host/inputs:/inputs:ro`.
- Mount only the output directory at `/runs`; any process allowed to write
  `/runs` can modify that host directory by design.
- Do not mount the repository, home directory, Docker socket, credentials, or
  broad host paths into production containers. The `/repo` source mount in the
  testing commands is for development only.
- Keep `OSMCP_SANDBOX=auto` and `OSMCP_SANDBOX_NET=deny` for untrusted measure
  authoring. Docker's `--network none` can provide an additional
  container-wide network boundary when remote access is not required.
- Use Docker CPU, memory, PID, and disk quotas as outer limits. The in-process
  resource limits are defense in depth, not replacements for container limits.

The sandbox protects the host and other run directories, but it intentionally
allows measure code to modify its own staged run directory. Treat resulting
OSM, SQL, report, and log files as untrusted outputs.

---

## Skills & Tools (150+ total)

In Claude Code, the bundled skills add workflow automation and domain knowledge:

| Skill | Type | What it does |
|-------|------|--------------|
| `/simulate` | Workflow | one-command simulate + results extraction |
| `/energy-report` | Workflow | comprehensive multi-category energy report |
| `/new-building` | Workflow | full model creation from scratch |
| `/retrofit` | Workflow | before/after ECM analysis |
| `/add-hvac` | Task | guided HVAC system selection |
| `/qaqc` | Task | pre-simulation model quality check |
| `/view` | Task | quick 3D model visualization |
| `/troubleshoot` | Task | diagnose simulation failures |
| `measure-authoring` | Knowledge | measure creation, SDK verification, wiring patterns |
| `ashrae-baseline-guide` | Knowledge | ASHRAE 90.1 system selection |
| `openstudio-patterns` | Knowledge | tool dependencies and model relationships |
| `tool-workflows` | Knowledge | multi-tool recipes for common operations |
| `/attribute-space-types` | Task | attribute standards space types to conditioned spaces (post-gbXML) |
| `/gbxml-import` | Task | Revit gbXML import + geometry-defect repair workflow |
| `/osaf-analysis` | Task | OpenStudio Analysis Framework workflow: algorithm selection, validation, submission |
| `/python-ems` | Task | custom EnergyPlus Python Plugin control/reporting logic (EMS) |
| `/file-transfer` | Task | move files to/from a remote server (signed upload/download URLs) |

Workflow/task skills are invoked with `/name`; knowledge skills load automatically. Any MCP host can also discover these guides via the `list_skills()` and `get_skill(name)` tools (baked into the image at `/skills`).

---

## Tool reference

150+ tools, grouped by area — expand a group to see its tools. New here? `create_new_building`, `run_simulation`, and `extract_summary_metrics` cover most workflows; `list_skills()` and `recommend_tools(task)` help the AI find the rest.

<details>
<summary><b>Model creation & management</b> — 13 tools</summary>

| Tool | Description |
|------|-------------|
| `create_new_building` | Create a complete building end-to-end (geometry + weather + typical template) |
| `create_bar_building` | Create bar-building geometry from type, floor area, aspect ratio |
| `create_typical_building` | Add constructions, loads, HVAC, SWH to a model with geometry |
| `create_example_osm` | Minimal single-zone example (testing/demos) |
| `create_baseline_osm` | 10-zone baseline with ASHRAE system 1–10 (testing/demos) |
| `inspect_osm_summary` | Quick structural summary of an OSM file |
| `load_osm_model` | Load OSM into memory for querying/editing |
| `save_osm_model` | Save the in-memory model to disk |
| `list_files` | Discover files in /inputs and /runs |
| `get_building_info` | Building name, area, volume, orientation |
| `get_model_summary` | Object counts by category |
| `delete_object` | Delete any named object (28+ types) |
| `rename_object` | Rename any named object |

</details>

<details>
<summary><b>Generic object access</b> — 3 tools</summary>

Read/write any OpenStudio object by introspection — covers types without a dedicated tool.

| Tool | Description |
|------|-------------|
| `list_model_objects` | List objects of any type (CamelCase, IDD colon, or underscore) |
| `get_object_fields` | Read all properties of an object — returns values + available setters |
| `set_object_property` | Write any property via official setters — auto-coerces types |

</details>

<details>
<summary><b>Spaces & thermal zones</b> — 6 tools</summary>

| Tool | Description |
|------|-------------|
| `list_spaces` | List spaces with area/volume |
| `get_space_details` | Surfaces, loads, zone for a space |
| `list_thermal_zones` | List thermal zones with spaces |
| `get_thermal_zone_details` | Zone equipment, thermostat, multiplier |
| `create_space` | Create a space (optional story/space type) |
| `create_thermal_zone` | Create a thermal zone, assign spaces |

</details>

<details>
<summary><b>Geometry</b> — 17 tools</summary>

| Tool | Description |
|------|-------------|
| `list_surfaces` | List surfaces (walls, floors, roofs) |
| `get_surface_details` | Vertices, construction, boundary |
| `list_subsurfaces` | List windows, doors, skylights |
| `create_surface` | Create a surface from explicit 3D vertices |
| `create_subsurface` | Create a window/door on a parent surface |
| `create_space_from_floor_print` | Extrude a floor polygon into a space with all surfaces |
| `match_surfaces` | Intersect + match shared walls between adjacent spaces |
| `set_window_to_wall_ratio` | Add a centered window by glazing ratio |
| `import_floorspacejs` | Import geometry from a FloorSpaceJS JSON file |
| `repair_missing_roof_ceiling` | Synthesize a RoofCeiling for spaces with a floor but no ceiling |
| `set_surface_boundary_conditions` | Set the outside boundary condition on a batch of named surfaces |
| `weld_coincident_vertices` | Snap near-coincident vertices to a shared point, closing corner gaps |
| `merge_coplanar_sliver_surfaces` | Merge same-space coplanar fragments into fewer, larger surfaces |
| `trim_overlapping_surfaces` | Trim same-space surfaces with a genuine 2D overlap to their remainder |
| `patch_missing_surfaces` | Reconstruct a space's missing surfaces from unpaired polyhedron edges |
| `get_foundation_options` | Kiva-eligible floors/walls, blockers, exposed perimeter, foundation archetype menu |
| `set_kiva_foundation` | Model foundation heat transfer with EnergyPlus Kiva (2D soil domain per floor) |

</details>

<details>
<summary><b>gbXML import</b> — 2 tools</summary>

Revit gbXML → OSM translation and geometry-defect repair. See examples [21](docs/examples/21_gbxml_import.md), [22](docs/examples/22_repair_and_validate_gbxml_geometry.md).

| Tool | Description |
|------|-------------|
| `import_gbxml` | Translate a Revit-exported gbXML file into an OpenStudio model |
| `repair_and_validate_gbxml_geometry` | Check for surface overlaps and non-enclosed space volumes, optionally repair |

</details>

<details>
<summary><b>Constructions & materials</b> — 6 tools</summary>

List constructions/sets via `list_model_objects("Construction")` / `("DefaultConstructionSet")`.

| Tool | Description |
|------|-------------|
| `list_materials` | Materials with thermal properties |
| `get_construction_details` | Construction layers with thermal properties |
| `create_standard_opaque_material` | Material with conductivity/density |
| `create_construction` | Layered construction from materials |
| `assign_construction_to_surface` | Assign a construction to a surface |
| `add_layer_to_construction` | Add a material layer to an existing construction (copies it) |

</details>

<details>
<summary><b>Schedules</b> — 2 tools</summary>

List schedules via `list_model_objects("ScheduleRuleset")`.

| Tool | Description |
|------|-------------|
| `get_schedule_details` | Schedule type, values, rules |
| `create_schedule_ruleset` | Constant schedule (Fractional/Temp/OnOff) |

</details>

<details>
<summary><b>Loads</b> — 6 tools</summary>

List loads via `list_model_objects("People")`, `("Lights")`, etc.; use `get_object_fields` for definitions.

| Tool | Description |
|------|-------------|
| `get_load_details` | Detailed info for any load by name |
| `create_people_definition` | People load (by area or count) |
| `create_lights_definition` | Lighting load (by area or wattage) |
| `create_electric_equipment` | Electric equipment load |
| `create_gas_equipment` | Gas equipment load |
| `create_infiltration` | Infiltration (by area or ACH) |

</details>

<details>
<summary><b>Space types</b> — 9 tools</summary>

List space types via `list_model_objects("SpaceType")`.

| Tool | Description |
|------|-------------|
| `get_space_type_details` | Space-type loads, schedules, standards |
| `assign_space_type_simple` | One standards combo -> every conditioned space, one call |
| `start_space_type_wizard` | Scan conditioned spaces, start the multi-turn assignment wizard |
| `choose_space_type_templates` | Narrow the wizard to one or more standards templates |
| `choose_space_type_building_types` | Narrow to building types, show the remaining space table |
| `get_space_type_wizard_status` | Wizard progress + a page of the remaining space table |
| `assign_space_type_batch` | Assign one standards combo to a batch of space indices |
| `finish_space_type_wizard` | Save the model and end the wizard |
| `cancel_space_type_wizard` | Abandon wizard tracking (does not undo assignments) |

</details>

<details>
<summary><b>HVAC — query & build</b> — 7 tools</summary>

| Tool | Description |
|------|-------------|
| `list_air_loops` | Air loops with zones served |
| `get_air_loop_details` | Air-loop components, sizing, OA system |
| `add_air_loop` | Create an air loop and connect zones |
| `list_plant_loops` | Plant loops (heating, cooling, condenser) |
| `get_plant_loop_details` | Plant-loop supply/demand components |
| `list_zone_hvac_equipment` | Zone-level HVAC equipment |
| `get_zone_hvac_details` | Zone equipment details |

</details>

<details>
<summary><b>HVAC systems (templates)</b> — 8 tools</summary>

| Tool | Description |
|------|-------------|
| `add_baseline_system` | ASHRAE 90.1 baseline system (types 1–10) |
| `list_baseline_systems` | All baseline + modern template types |
| `get_baseline_system_info` | Metadata for a specific system type |
| `replace_air_terminals` | Replace ALL terminals on an air loop |
| `replace_zone_terminal` | Replace the terminal on a single zone |
| `add_doas_system` | DOAS with fan coils, radiant, or chilled beams |
| `add_vrf_system` | VRF multi-zone heat-pump system |
| `add_radiant_system` | Low-temperature radiant heating/cooling |

</details>

<details>
<summary><b>HVAC component properties</b> — 10 tools</summary>

List components via `list_model_objects("BoilerHotWater")`, loop detail tools, etc. Covers 15 component types (see [reference](#hvac-component-types)).

| Tool | Description |
|------|-------------|
| `get_component_properties` | Read all properties of a named component |
| `set_component_properties` | Modify properties on a named component |
| `set_economizer_properties` | OA economizer settings on an air loop |
| `set_sizing_properties` | Plant-loop sizing (exit temp, delta-T) |
| `set_sizing_system_properties` | Air-loop SizingSystem (SAT, OA, flow methods) |
| `get_sizing_system_properties` | Read all SizingSystem properties |
| `set_sizing_zone_properties` | SizingZone properties (supports zone lists) |
| `get_sizing_zone_properties` | Read all SizingZone properties |
| `get_setpoint_manager_properties` | Read SPM properties (7 types) |
| `set_setpoint_manager_properties` | Modify SPM properties (7 types) |

</details>

<details>
<summary><b>Plant loops, air-loop supply branches, setpoint managers & zone equipment</b> — 14 tools</summary>

| Tool | Description |
|------|-------------|
| `create_plant_loop` | Plant loop with pump, bypass, SPM |
| `add_supply_equipment` | Add boiler/chiller/tower to supply side |
| `remove_supply_equipment` | Remove supply-side equipment |
| `add_demand_component` | Add coil/heater to the demand side |
| `remove_demand_component` | Remove a demand-side component |
| `add_air_loop_supply_component` | Add a coil or fan to an air loop's supply branch (append or insert before/after) |
| `remove_air_loop_supply_component` | Remove a coil or fan from an air loop, keeping its setpoint managers |
| `replace_air_loop_supply_component` | Swap a coil or fan in place (add-first order, avoids the SDK segfault) |
| `add_setpoint_manager` | Put one of 7 setpoint manager types on a loop node; refuses silent same-control-variable collisions |
| `remove_setpoint_manager` | Delete a setpoint manager; warns when a loop outlet loses temperature control |
| `add_zone_equipment` | Add baseboard/unit heater to a zone |
| `remove_zone_equipment` | Remove zone equipment |
| `remove_all_zone_equipment` | Batch-remove all equipment from zones |
| `set_zone_equipment_priority` | Reorder zone cooling/heating priority |

</details>

<details>
<summary><b>Weather & simulation config</b> — 8 tools</summary>

| Tool | Description |
|------|-------------|
| `list_weather_files` | Available EPW files (with .stat/.ddy) |
| `get_weather_info` | City, lat, lon, timezone, and ground-temperature state |
| `set_ground_temperatures` | Apply an EPW header's ground temperatures to the model |
| `add_design_day` | Add a heating/cooling design day |
| `get_simulation_control` | Read sizing flags and timesteps/hour |
| `set_simulation_control` | Modify sizing flags and/or timestep |
| `get_run_period` | Read run-period dates |
| `set_run_period` | Set run-period dates |

</details>

<details>
<summary><b>Simulation & outputs</b> — 10 tools</summary>

| Tool | Description |
|------|-------------|
| `run_simulation` | Run a simulation from an OSM + optional EPW |
| `run_osw` | Run EnergyPlus from an OSW file |
| `validate_osw` | Validate an OSW workflow file |
| `validate_model` | Pre-sim check: weather, design days, HVAC, constructions |
| `get_run_status` | Poll run status |
| `get_run_logs` | Tail simulation logs |
| `get_run_artifacts` | List output files |
| `cancel_run` | Cancel a running simulation |
| `add_output_variable` | Add an EnergyPlus output variable |
| `add_output_meter` | Add an EnergyPlus output meter |

</details>

<details>
<summary><b>Run retention</b> — 4 tools</summary>

Reclaim disk from old run directories. See [docs/run-retention.md](docs/run-retention.md).

| Tool | Description |
|------|-------------|
| `cleanup_runs` | Delete old run dirs you own (preview with `dry_run`, then delete) |
| `delete_run` | Delete one of your run directories |
| `pin_run` | Protect a run from automatic cleanup |
| `unpin_run` | Allow a pinned run to be cleaned up again |

</details>

<details>
<summary><b>File transfer (remote HTTP mode)</b> — 5 tools</summary>

Move files between your machine and a remote server over signed, one-time URLs. See [Remote & multi-user](#remote--multi-user-http).

| Tool | Description |
|------|-------------|
| `request_upload` | Get a one-time URL to upload a local file to the server |
| `get_upload` | Check an upload's status and get its server-side path |
| `list_uploads` | List your uploaded files |
| `delete_upload` | Delete an uploaded file and free its quota |
| `request_download` | Get a one-time URL to download a server file to your machine |

</details>

<details>
<summary><b>OpenStudio Server analysis</b> — 20 tools</summary>

OSA JSON validation blocks DOE analyses with fewer than two measure variables
and, by default, requires the foundational `view_model`, `openstudio_results`,
and `generic_qaqc` measures in the workflow. Package validation also requires
those measures in the support ZIP. Use `single_run` for a single datapoint, a
schema-supported sampling type such as `lhs` for one-variable sampling, or add
another real variable before choosing DOE. OSAF's DOE runner accepts a
one-variable payload but later fails during analysis startup.

| Tool | Description |
|------|-------------|
| `openstudio_analysis_create_osa_json` | Create an OpenStudio Server OSA JSON file |
| `openstudio_analysis_validate_osa_json` | Validate an OSA JSON file locally |
| `openstudio_analysis_default_output_variables` | Return the foundational output variables used by generated OSA JSON |
| `openstudio_analysis_foundational_measures` | Return the common measures appended to generated OSA workflows |
| `openstudio_analysis_preflight_seed` | Simulate/reuse a seed run and write seed QA/QC evidence before packaging |
| `openstudio_analysis_prepare_package` | Create an OSAF support ZIP only after seed simulation QA/QC passes |
| `openstudio_analysis_create_osa_json_from_measures` | Create OSA JSON from measure directories, static arguments, and variable parameters |
| `openstudio_analysis_add_measure_to_osa_json` | Add a measure step and optional algorithm variables to an existing OSA JSON workflow |
| `openstudio_analysis_create_project` | Create an OpenStudio Server project |
| `openstudio_analysis_submit` | Submit OSA JSON and optional support ZIP to a project |
| `openstudio_analysis_status` | Check analysis status |
| `openstudio_analysis_start` | Start an existing analysis with OSAF's action endpoint |
| `openstudio_analysis_wait` | Poll analysis status until completion/failure/timeout |
| `openstudio_analysis_test_server_config` | Check server health, submit a single_run smoke test, and run one datapoint |
| `openstudio_analysis_download_data` | Download exported analysis data |
| `openstudio_analysis_results_json` | Fetch analysis result data as JSON |
| `openstudio_analysis_submit_wait_download` | Submit analysis, wait for completion, and download results |
| `openstudio_analysis_algorithms` | List OSAF analysis algorithms and when to use them |
| `openstudio_analysis_validate_package` | Validate an OSAF analysis support ZIP before upload |
| `openstudio_analysis_start_sampled_run` | Start a sampled analysis in the required OSAF order |

</details>

<details>
<summary><b>Results extraction</b> — 12 tools</summary>

| Tool | Description |
|------|-------------|
| `extract_summary_metrics` | EUI, energy, unmet hours |
| `extract_end_use_breakdown` | Energy by end use and fuel (IP/SI) |
| `extract_envelope_summary` | Opaque + fenestration U-values and areas |
| `extract_hvac_sizing` | Autosized zone/system HVAC capacities |
| `extract_zone_summary` | Per-zone areas, conditions, multipliers |
| `extract_component_sizing` | Autosized component values (filterable) |
| `query_timeseries` | Time-series output data with date/cap filters |
| `extract_simulation_errors` | Parse eplusout.err into Fatal/Severe/Warning |
| `list_output_variables` | Output variables from a completed run |
| `compare_runs` | Compare two runs: EUI delta + end-use breakdown |
| `read_file` | Read any file by absolute path (mounts only) |
| `copy_file` | Copy a file to a host-mounted path |

</details>

<details>
<summary><b>Measures</b> — 11 tools</summary>

Find, download, and apply bundled/BCL measures, or write/test/apply custom ones. See examples [1](docs/examples/01_custom_measure_lighting.md), [2](docs/examples/02_custom_measure_hvac.md), [19](docs/examples/19_systemd_fourpipebeam_retrofit.md).

| Tool | Description |
|------|-------------|
| `list_local_measures` | Discover mounted, downloaded, bundled, and custom OpenStudio measures |
| `find_measure` | Find a measure locally first, then BCL; download a strong BCL match |
| `search_bcl_measures` | Search BCL measure candidates without downloading |
| `download_measure_from_bcl` | Download and extract a measure ZIP into your per-user BCL cache (`/measures/<user>/bcl`) |
| `list_comstock_measures` | List ~61 bundled [ComStock](https://github.com/NREL/ComStock) measures |
| `list_measure_arguments` | List a measure's arguments, defaults, choices |
| `apply_measure` | Apply an OpenStudio measure to the in-memory model |
| `create_measure` | Create a custom Ruby/Python ModelMeasure |
| `edit_measure` | Edit a custom measure's code or arguments |
| `test_measure` | Run a custom measure's tests (auto-detects language) |
| `list_custom_measures` | List custom measures you've created |

</details>

<details>
<summary><b>Python EMS plugins</b> — 5 tools</summary>

Custom EnergyPlus Python Plugin control/reporting logic. See example [20](docs/examples/20_python_ems_demand_response.md).

| Tool | Description |
|------|-------------|
| `list_ems_actuators` | Discover valid EMS actuators (component, control type, key) for the loaded model |
| `create_python_plugin` | Add a Python EMS plugin (control or reporting) to the model |
| `get_python_plugin` | List the model's Python plugins or inspect one by name |
| `edit_python_plugin` | Replace an existing plugin's script source |
| `install_plugin_packages` | Install Python packages (e.g. numpy) for use inside plugins |

</details>

<details>
<summary><b>Common measures (curated wrappers)</b> — 20 tools</summary>

Typed wrappers over ~79 bundled [common measures](https://github.com/NREL/openstudio-common-measures-gem) (reporting, envelope, renewables, visualization, cleanup).

| Tool | Description |
|------|-------------|
| `list_common_measures` | List bundled measures by category |
| `view_model` | Interactive 3D Three.js viewer of geometry |
| `view_simulation_data` | 3D viewer with simulation data on surfaces |
| `generate_results_report` | ~25-section HTML report |
| `run_qaqc_checks` | ASHRAE baseline QA/QC checks |
| `adjust_thermostat_setpoints` | Shift heating/cooling setpoints |
| `replace_window_constructions` | Bulk-replace exterior window constructions |
| `enable_ideal_air_loads` | Ideal air loads on all zones (quick sizing) |
| `clean_unused_objects` | Remove orphan/unused objects |
| `change_building_location` | Set weather + climate zone + design days |
| `set_thermostat_schedules` | Apply thermostat schedules from a library |
| `replace_thermostat_schedules` | Replace existing thermostat schedules |
| `shift_schedule_time` | Shift schedule profiles by hours |
| `add_rooftop_pv` | Add rooftop PV panels |
| `add_pv_to_shading` | Add PV to shading surfaces |
| `add_ev_load` | Add EV charging load |
| `add_zone_ventilation` | Add zone ventilation design flow |
| `set_lifecycle_cost_params` | Set lifecycle-cost parameters |
| `add_cost_per_floor_area` | Add cost per floor area |
| `set_adiabatic_boundaries` | Set walls/floors adiabatic |

</details>

<details>
<summary><b>Discovery, info & routing</b> — 8 tools</summary>

| Tool | Description |
|------|-------------|
| `list_skills` | List available workflow guides |
| `get_skill` | Step-by-step instructions for a workflow |
| `get_skill_file` | Fetch a supporting file advertised by `get_skill` |
| `recommend_tools` | Recommend the relevant tool group for a task |
| `search_api` | Look up OpenStudio SDK classes + methods (verify before calling) |
| `search_wiring_patterns` | Ruby wiring recipes for HVAC, plus SDK crash hazards for remove/addToNode queries |
| `get_server_status` | Server health check |
| `get_versions` | OpenStudio, EnergyPlus, Ruby versions |

</details>

---

## Reference

### ASHRAE baseline systems

All 10 ASHRAE 90.1 Appendix G baseline systems via `add_baseline_system`, plus modern templates **DOAS**, **VRF**, **Radiant**.

| # | Type | Description |
|---|------|-------------|
| 1 | PTAC | Packaged terminal AC (zone-level) |
| 2 | PTHP | Packaged terminal heat pump (zone-level) |
| 3 | PSZ-AC | Packaged single-zone rooftop AC |
| 4 | PSZ-HP | Packaged single-zone heat pump |
| 5 | Packaged VAV w/ Reheat | VAV with hot-water reheat |
| 6 | Packaged VAV w/ PFP Boxes | VAV with parallel fan-powered boxes |
| 7 | VAV w/ Reheat | Central VAV, chiller + boiler + tower |
| 8 | VAV w/ PFP Boxes | Central VAV, parallel fan-powered terminals |
| 9 | Gas Unit Heater | Heating-only (warehouses, garages) |
| 10 | Electric Unit Heater | Heating-only, electric |

### HVAC component types

The component-properties tools query/modify these 15 types:

| Category | Components |
|----------|------------|
| Coils | CoilHeatingGas, CoilHeatingElectric, CoilHeatingWater, CoilCoolingWater, CoilCoolingDXSingleSpeed, CoilCoolingDXTwoSpeed, CoilHeatingDXSingleSpeed |
| Plant | BoilerHotWater, ChillerElectricEIR, CoolingTowerSingleSpeed |
| Fans | FanConstantVolume, FanVariableVolume, FanOnOff |
| Pumps | PumpConstantSpeed, PumpVariableSpeed |

---

## Examples

25 worked examples with full tool-call sequences:

| # | Example | # | Example |
|---|---------|---|---------|
| 1 | [Custom Measure: Lighting](docs/examples/01_custom_measure_lighting.md) | 12 | [`/simulate`](docs/examples/12_simulate.md) |
| 2 | [Custom Measure: Chilled Beams](docs/examples/02_custom_measure_hvac.md) | 13 | [`/energy-report`](docs/examples/13_energy_report.md) |
| 3 | [Baseline Comparison](docs/examples/03_baseline_comparison.md) | 14 | [`/qaqc`](docs/examples/14_qaqc.md) |
| 4 | [HVAC Design Exploration](docs/examples/04_hvac_design_exploration.md) | 15 | [`/add-hvac`](docs/examples/15_add_hvac.md) |
| 5 | [Envelope Retrofit](docs/examples/05_envelope_retrofit.md) | 16 | [`/new-building`](docs/examples/16_new_building.md) |
| 6 | [Internal Loads](docs/examples/06_internal_loads.md) | 17 | [`/retrofit`](docs/examples/17_retrofit.md) |
| 7 | [Full Building Model](docs/examples/07_full_building.md) | 18 | [`/view`](docs/examples/18_view.md) |
| 8 | [Geometry from Scratch](docs/examples/08_geometry_creation.md) | 19 | [Four-Pipe Beam Retrofit (E2E)](docs/examples/19_systemd_fourpipebeam_retrofit.md) |
| 9 | [Fenestration by Orientation](docs/examples/09_fenestration_by_orientation.md) | 20 | [Demand Response with Python EMS](docs/examples/20_python_ems_demand_response.md) |
| 10 | [Typical Building (ComStock)](docs/examples/10_comstock_typical_building.md) | 21 | [gbXML Import from Revit](docs/examples/21_gbxml_import.md) |
| 11 | [Results Deep Dive](docs/examples/11_results_extraction.md) | 22 | [Repairing & Validating gbXML Geometry](docs/examples/22_repair_and_validate_gbxml_geometry.md) |
| 23 | [Attributing Space Types (post-gbXML)](docs/examples/23_attribute_space_types.md) | 24 | [Guaranteed Climate Zone & Zone Volume Checks](docs/examples/24_gbxml_climate_zone_and_zone_volume_checks.md) |
| 25 | [Ground &amp; Foundation Heat Transfer](docs/examples/25_ground_and_foundation_heat_transfer.md) | | |

---

## Testing

Full guide — framework, annotated examples, CI shards, writing tests — in **[docs/testing/](docs/testing/README.md)**.

```bash
# Unit tests (no Docker)
pytest tests/test_skill_registration.py -v

# Integration tests (Docker)
docker build -t openstudio-mcp:dev -f docker/Dockerfile .
docker run --rm -v "$PWD:/repo" -v "$PWD/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc 'cd /repo && pytest -vv -s tests/'
```

## Linting and formatting (uv + pre-commit)

CI runs the same pre-commit hooks (`.github/workflows/format_and_lint.yml`).

```bash
# Install dev dependencies with uv
uv pip install -e ".[dev]"

# Run the pre-commit hooks locally
uv run pre-commit run --all-files
```

---

## Architecture

- **Transport:** stdio (default) or streamable HTTP for [remote/multi-user](#remote--multi-user-http)
- **Protocol:** MCP (JSON-RPC); in stdio prod mode, stdout is reserved for JSON-RPC and logs go to stderr
- **Skills:** 30+ skill modules under `mcp_server/skills/<name>/`, each with `tools.py` (MCP registration) + `operations.py` (business logic); they auto-register
- **State:** per-session in-memory model via `model_manager`; runs under `/runs/<run_id>/` (or `/runs/<user>/<run_id>/` in HTTP mode)

Set `OPENSTUDIO_MCP_MODE=prod` for MCP hosts (quiet logs, no banner). Full system diagram, security analysis, and hardening notes: **[docs/architecture.md](docs/architecture.md)**.

### Contributing

<details>
<summary>Adding skills, tools, and component types</summary>

**New MCP skill**
1. Create `mcp_server/skills/<name>/__init__.py`, `operations.py`, `tools.py`
2. `operations.py` — pure logic, returns `{"ok": True/False, ...}`
3. `tools.py` — exports `register(mcp)`, defines tool schemas
4. Add `tests/test_<name>.py` and a CI step in `.github/workflows/ci.yml`
5. Auto-registers via `skills/__init__.py`; add each tool name to `EXPECTED_TOOLS` in `tests/test_skill_registration.py` — the roster's single source of truth (never hardcode counts)

**New Claude Code skill (workflow guide)**
1. Create `.claude/skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`)
2. Add workflow instructions referencing MCP tool names; `user-invocable: true|false`, `context: fork` for fire-and-forget
3. Add `tests/test_skill_<name>.py` + a CI shard, an example in `docs/examples/`, and a README row
4. Auto-appears in `list_skills()` via the `/skills` mount

**New HVAC component type**
1. Add `_get_<type>_props(obj)` / `_set_<type>_props(obj, props)` in `components.py`
2. Add an entry to `COMPONENT_TYPES`; add a test in `tests/test_component_properties.py`
3. No dynamic dispatch — every OpenStudio API call must be explicit and grepable

</details>

---

## Cite this work

If you use OpenStudio-MCP in research, please cite the *SoftwareX* article:

> Ball, B.L., Long, N., Fleming, K., Goldwasser, D., 2026. OpenStudio-MCP: a model context protocol (MCP) server for AI agent-driven building energy modeling with the OpenStudio SDK. *SoftwareX* 36, 103020. https://doi.org/10.1016/j.softx.2026.103020

```bibtex
@article{ball2026openstudiomcp,
  title   = {{OpenStudio-MCP}: a model context protocol ({MCP}) server for {AI} agent-driven building energy modeling with the {OpenStudio} {SDK}},
  author  = {Ball, Brian L. and Long, Nicholas and Fleming, Katherine and Goldwasser, David},
  journal = {SoftwareX},
  volume  = {36},
  pages   = {103020},
  year    = {2026},
  issn    = {2352-7110},
  doi     = {10.1016/j.softx.2026.103020}
}
```

---

## License

See [LICENSE](LICENSE.txt).
