# Plan: Claude Code Skills for openstudio-mcp

## Context

Claude Code supports `.claude/skills/<name>/SKILL.md` files — prompt-based instructions that teach Claude workflows, domain knowledge, and task recipes. These are **different from MCP server skills** (`mcp_server/skills/`). Claude Code skills orchestrate the existing 124 MCP tools into user-friendly workflows.

**Key distinction:**
- MCP tools = programmatic capabilities (create objects, run simulations, extract results)
- Claude Code skills = prompt recipes that chain MCP tools into coherent workflows

Reference: https://code.claude.com/docs/en/skills

## Proposed Skills

### Tier 1: High-Impact Workflow Skills

#### 1. `/new-building` — Create a complete building model
**Why:** Most common user task. Currently requires 10-20 individual tool calls in the right order. Users don't know which tools to call or in what sequence.

**Workflow:**
1. Ask user for building type, size, floors, climate zone
2. `create_baseline_osm` or `create_space_from_floor_print` for geometry
3. `create_standard_opaque_material` + `create_construction` for envelope
4. `create_people_definition` + `create_lights_definition` + `create_electric_equipment` for loads
5. `create_schedule_ruleset` for occupancy/lighting/equipment schedules
6. Select and apply HVAC via `add_baseline_system` or modern templates
7. Prompt user for weather file location (EPW/DDY in docker-mounted dir), then `set_weather_file` + `add_design_day`
8. `run_simulation` and report results

**Config:** `disable-model-invocation: true` (interactive, no fork — needs back-and-forth)

#### 2. `/simulate` — One-command simulate + report
**Why:** Running a simulation currently requires: validate → run → poll status → extract results. Users just want "simulate and tell me the results."

**Workflow:**
1. `run_simulation` with current model
2. Poll `get_run_status` until complete
3. `extract_summary_metrics` + `extract_end_use_breakdown`
4. Present formatted results summary (EUI, end uses, unmet hours)

**Config:** `context: fork` (fire-and-forget, no back-and-forth needed), `disable-model-invocation: true`

#### 3. `/energy-report` — Comprehensive energy analysis
**Why:** After simulation, users want a full picture — not just EUI. This skill extracts all result categories and presents a structured report.

**Workflow:**
1. Check for completed simulation (or run one)
2. Extract: `extract_summary_metrics`, `extract_end_use_breakdown`, `extract_envelope_summary`, `extract_hvac_sizing`, `extract_zone_summary`, `extract_component_sizing`
3. Optionally `run_qaqc_checks` and `generate_results_report`
4. Present structured report with sections: Overview, Envelope, HVAC, Zones, End Uses, QA/QC flags

**Config:** `context: fork` (fire-and-forget extraction), `disable-model-invocation: true`

#### 4. `/retrofit` — Energy conservation measure analysis
**Why:** Common workflow: load existing model → apply upgrades → compare before/after. Requires domain knowledge about which measures to suggest.

**Workflow:**
1. Load model, run baseline simulation
2. Suggest ECMs based on model properties (envelope, HVAC, lighting)
3. Apply selected measures (`adjust_thermostat_setpoints`, `replace_window_constructions`, `add_rooftop_pv`, etc.)
4. Re-simulate
5. Compare before/after: EUI delta, end-use changes, cost implications

**Config:** `disable-model-invocation: true` (interactive, no fork — user picks ECMs)
**Supporting files:** `ecm-catalog.md` with available measures and typical savings ranges

### Tier 2: Task Skills

#### 5. `/add-hvac` — Guided HVAC system selection
**Why:** Users often don't know which ASHRAE system type to pick. This skill guides selection based on building attributes.

**Workflow:**
1. `get_building_info` + `list_thermal_zones` to understand model
2. Ask about building type, heating fuel, preferences
3. Recommend system type using ASHRAE 90.1 Table G3.1.1 logic
4. Apply via `add_baseline_system` or modern template tools
5. Validate with `list_air_loops` / `list_zone_hvac_equipment`

**Config:** default (Claude can auto-invoke when user asks about HVAC)

#### 6. `/qaqc` — Model quality check
**Why:** Common pre-simulation step. Users want to catch issues before wasting a simulation run.

**Workflow:**
1. `inspect_osm_summary` for high-level model state
2. Check for missing elements: zones without HVAC, spaces without loads, unassigned constructions
3. `run_qaqc_checks` (common measures)
4. Report issues with suggested fixes

**Config:** default (Claude can auto-invoke when discussing model quality)

#### 7. `/view` — Quick model visualization
**Why:** Users frequently want to see their model. Simple wrapper around `view_model`.

**Workflow:**
1. `view_model` with sensible defaults
2. Report file location

**Config:** `disable-model-invocation: true`, `argument-hint: [format]`

### Tier 3: Reference/Knowledge Skills

#### 8. `ashrae-baseline-guide` — ASHRAE 90.1 system selection reference
**Why:** Critical domain knowledge for correct system selection. Claude needs this context to make good recommendations.

**Content:** ASHRAE 90.1 Appendix G Table G3.1.1 system selection criteria:
- Building type → system type mapping
- Climate zone considerations
- Heating fuel logic
- System capacity thresholds

**Config:** `user-invocable: false` (background knowledge for Claude only)

#### 9. `openstudio-patterns` — Common OpenStudio modeling patterns
**Why:** Teaches Claude correct tool sequencing and common pitfalls.

**Content:**
- Tool dependency graph (what must exist before what)
- Common error patterns and fixes
- Model object relationships (Space → ThermalZone → AirLoop)
- When to use `create_baseline_osm` vs `create_space_from_floor_print`

**Config:** `user-invocable: false`

#### 10. `tool-workflows` — Tool chaining recipes
**Why:** Quick reference for multi-tool operations that don't warrant a full skill.

**Content:**
- "Add a window" = `list_surfaces` → pick wall → `create_subsurface`
- "Change wall insulation" = `list_constructions` → `create_standard_opaque_material` → `create_construction` → `assign_construction_to_surface`
- "Add output variables" = `add_output_variable` → `add_output_meter` → `set_run_period` → simulate

**Config:** `user-invocable: false`

## Directory Structure

```
.claude/skills/
├── new-building/
│   └── SKILL.md
├── simulate/
│   └── SKILL.md
├── energy-report/
│   └── SKILL.md
├── retrofit/
│   ├── SKILL.md
│   └── ecm-catalog.md
├── add-hvac/
│   └── SKILL.md
├── qaqc/
│   └── SKILL.md
├── view/
│   └── SKILL.md
├── ashrae-baseline-guide/
│   └── SKILL.md
├── openstudio-patterns/
│   └── SKILL.md
└── tool-workflows/
│   └── SKILL.md
```

## Implementation Order

1. **`/simulate`** — Smallest, highest frequency, easiest to validate
2. **`/energy-report`** — Builds on simulate, high value
3. **`/qaqc`** — Quick win, useful before simulation
4. **`openstudio-patterns`** + **`tool-workflows`** — Background knowledge improves all interactions
5. **`/add-hvac`** + **`ashrae-baseline-guide`** — Domain-heavy, needs careful content
6. **`/new-building`** — Largest skill, depends on all others being solid
7. **`/retrofit`** — Most complex workflow, needs ECM catalog
8. **`/view`** — Trivial, add anytime

## Estimated Effort

- Tier 1 skills: ~1-2 hrs each (mostly prompt engineering + testing)
- Tier 2 skills: ~30-60 min each
- Tier 3 skills: ~1-2 hrs each (domain research for content)

## Testing Strategy

Each user-invocable skill gets an integration test in `tests/test_skill_<name>.py` following the existing `subprocess.Popen` + `StreamReader` pattern from `test_stdio_smoke.py`. Non-user-invocable background knowledge skills (Tier 3) don't need integration tests — they're static prompt content.

### Test Pattern

For each skill, the test launches an MCP server subprocess:
1. `initialize` → load/create a model as needed
2. Execute the tool calls the skill would orchestrate (in sequence)
3. Assert each step returns `"ok": true`
4. Assert final output contains expected data (EUI present, report sections, etc.)

### Test Files

| Skill | Test File | Key Assertions |
|-------|-----------|----------------|
| `/simulate` | `tests/test_skill_simulate.py` | `run_simulation` succeeds, `extract_summary_metrics` returns EUI, `extract_end_use_breakdown` has categories |
| `/energy-report` | `tests/test_skill_energy_report.py` | All 6 extract tools return data, report has envelope/HVAC/zone sections |
| `/qaqc` | `tests/test_skill_qaqc.py` | `inspect_osm_summary` returns model stats, `run_qaqc_checks` completes |
| `/add-hvac` | `tests/test_skill_add_hvac.py` | `get_building_info` + `list_thermal_zones` → `add_baseline_system` → `list_zone_hvac_equipment` confirms equipment |
| `/new-building` | `tests/test_skill_new_building.py` | Full workflow: geometry → envelope → loads → HVAC → weather → simulate, model has all expected objects |
| `/retrofit` | `tests/test_skill_retrofit.py` | Baseline sim → apply measure (e.g. `adjust_thermostat_setpoints`) → re-sim → EUI changed |
| `/view` | `tests/test_skill_view.py` | `view_model` returns file path, file exists |

### CI Shard Assignment

Add skill tests to CI shards in `.github/workflows/ci.yml`, balanced by estimated runtime:
- **Shard 1:** `test_skill_simulate.py` (runs simulation, ~60s)
- **Shard 2:** `test_skill_new_building.py`, `test_skill_view.py` (heavy creation + sim)
- **Shard 3:** `test_skill_qaqc.py`, `test_skill_add_hvac.py` (model creation + query)
- **Shard 4:** `test_skill_energy_report.py`, `test_skill_retrofit.py` (sim + extraction)

### Notes

- Tests validate the tool-call sequences the skills orchestrate, not the SKILL.md prompt text itself
- Each test is self-contained: creates its own model, doesn't depend on other test state
- Tests reuse existing helpers (`StreamReader`, `_write_json`, `_read_json_line`) — consider extracting to `tests/conftest.py` or `tests/helpers.py` if not already shared

## README Examples

Each user-invocable skill gets a README example derived from its integration test. Since the test validates the tool-call sequence actually works, the example is guaranteed accurate.

### Approach

1. Write the integration test first (validates the workflow end-to-end)
2. Extract the tool-call sequence from the test into a README example
3. Add to the existing `## Examples` section in `README.md` (currently has Examples 1-11)

### New Examples

| Example # | Skill | Title | Derived From |
|-----------|-------|-------|--------------|
| 12 | `/simulate` | One-Command Simulation | `test_skill_simulate.py` |
| 13 | `/energy-report` | Comprehensive Energy Report | `test_skill_energy_report.py` |
| 14 | `/qaqc` | Model Quality Check | `test_skill_qaqc.py` |
| 15 | `/add-hvac` | Guided HVAC Selection | `test_skill_add_hvac.py` |
| 16 | `/new-building` | Complete Building from Scratch | `test_skill_new_building.py` |
| 17 | `/retrofit` | Retrofit Analysis | `test_skill_retrofit.py` |
| 18 | `/view` | Model Visualization | `test_skill_view.py` |

### Example Format

Follow existing README pattern — natural language prompt, then numbered tool-call sequence:

```
### Example 12: One-Command Simulation

Run a simulation and get results in one step using `/simulate`.

> **You:** `/simulate`

Behind the scenes:

1. run_simulation(osm_path=...)
2. get_run_status(run_id=...)        # polls until complete
3. extract_summary_metrics(run_id=...)
4. extract_end_use_breakdown(run_id=...)
5. Presents EUI, end-use breakdown, unmet hours
```

### Workflow

For each skill, implementation order is: **test → example → skill**

1. Write `tests/test_skill_<name>.py` — validates tool sequence works
2. Extract tool calls into `README.md` example — user-facing documentation
3. Write `.claude/skills/<name>/SKILL.md` — prompt recipe referencing the same sequence

This ensures examples always reflect tested, working workflows.

## Other Considerations

- **Token budget:** Claude Code loads skill descriptions into context (2% of window). 10 skills with short descriptions should fit comfortably. Monitor with `/context`.
- **Versioning:** `.claude/skills/` committed to repo so all users get them.
- **MCP server SKILL.md files:** Separate concern. The existing `mcp_server/skills/hvac_systems/SKILL.md` is internal documentation, not a Claude Code skill. Could add more of those later but that's a different effort.

## Resolved Decisions

- **`context: fork`** — Only for fire-and-forget skills (`/simulate`, `/energy-report`). Interactive workflows (`/new-building`, `/retrofit`, `/add-hvac`) stay inline to preserve back-and-forth.
- **Background knowledge** — Separate files per skill for readability.
- **Weather files** — User provides EPW/DDY in docker-mounted directory. Skills prompt user for file name and location.
- **Auto-save** — `/simulate` does not auto-save. `run_simulation` operates on the loaded model directly.
- **Permissions** — Prompt user for `allowed-tools` on each skill. Define explicit tool lists per skill rather than blanket access.
