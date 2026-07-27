# Plan: Python EMS (EnergyPlus Python Plugins) skill

**Status:** proposed · **Scope decision:** Python plugins only, no Erl/classic EMS tools

## Why

EnergyPlus Python Plugins are the modern EMS: user Python classes with callbacks
into the simulation (sensors, actuators, custom outputs, supervisory control).
Nothing in openstudio-mcp exposes this today (zero grep hits for
`PythonPlugin`/`EnergyManagementSystem`/`ExternalFile`). Enabling it lets agents
implement controls no packaged HVAC object covers: setpoint resets, demand
limiting, shade control, custom metrics.

Classic Erl EMS is explicitly out of scope: plugins cover the same calling
points and LLMs write Python far better than Erl.

## Verified facts (empirical, 2026-07, `openstudio-mcp:dev` image)

Everything below the MCP layer already works; all verified by running it:

- OpenStudio 3.11 bindings have all needed classes: `PythonPluginInstance`,
  `PythonPluginVariable`, `PythonPluginTrendVariable`, `PythonPluginOutputVariable`,
  `PythonPluginSearchPaths`, `ExternalFile`, `OutputEnergyManagementSystem`.
- Image ships EnergyPlus 25.2.0 at `/usr/local/openstudio-3.11.0/EnergyPlus/`
  with embedded CPython 3.12 (`libpython3.12.so`, `python_lib/`, complete
  `pyenergyplus/` incl. `plugin.py`). End-to-end proven: `exampleModel()` +
  plugin → `openstudio run -w` → plugin callback executed, sim completed.
- `ExternalFile.getExternalFile(model, path)` copies the .py into
  `<workflowJSON root>/files/` immediately; OSM stores only the bare filename.
  Unsaved model → root is process cwd (must be controlled, see plumbing).
- `PythonPluginInstance(ext_file, class_name)` validates at construction that
  the class exists in the file (`validPluginClassNamesInFile()`).
- ForwardTranslator emits everything unconditionally and auto-generates
  `PythonPlugin:SearchPaths` with the absolute dir of the resolved .py. All
  `PythonPluginVariable`s collapse into one extensible `PythonPlugin:Variables`.
- Object names pass through FT verbatim (spaces included): plugin code can
  reference the same names the agent sees in `list_thermal_zones` etc.
- Reporting convention: `Output:Variable` with key = the
  `PythonPlugin:OutputVariable` object's name, variable name = the literal
  string `PythonPlugin:OutputVariable`. Tools must hide this weirdness.
- Plugin contract: subclass `EnergyPlusPlugin`, override one or more of 18
  `on_*` callbacks; `return 0` ok, nonzero = fatal to the run; handle lookups
  return -1 when not found; look up handles lazily after
  `api_data_fully_ready(state)`; globals must be declared in
  `PythonPlugin:Variables` before `get_global_handle` finds them.
- E+ embeds its interpreter in isolated mode: `PYTHONPATH`/`VIRTUAL_ENV`
  ignored. Third-party packages reach plugins ONLY via a
  `PythonPlugin:SearchPaths` entry. Stdlib-only out of the box.
- Actuator discovery: `Output:EnergyManagementSystem` (Verbose) → `eplusout.edd`
  lists every legal (component type, control type, key) triple.
- Upstream reference set: 23 `PythonPlugin*.idf/.py` pairs in
  `NREL/EnergyPlus/testfiles`; OpenStudio-resources has
  `model/simulationtests/python_plugin.py` using the exact OSM API above.

## Design

### Template-first authoring

Not all agents are smart. `create_python_plugin` takes a `template` argument;
templates generate the whole plugin class (handle caching, readiness guards,
error handling, -1 checks, severe+abort on bad handles) from typed slots. A
`custom` template accepts a free-form code body but the tool description and
SKILL.md steer agents to named templates first; `custom` is validated
(syntax `compile()`, class present, callback names legal) but is the escape
hatch, not the default.

v1 templates (each ports a proven E+ testfile):

| Template | Ported from | Slots |
|---|---|---|
| `zone_metric_aggregate` | PythonPluginCustomOutputVariable | zone variable name, zones (default all), aggregation (volume-weighted avg / sum / min / max), output var name+units |
| `schedule_override` | PythonPluginCustomSchedule | schedule name (Schedule:Constant), rules: list of {days, hour range, value} |
| `node_setpoint_reset` (phase 2) | PythonPluginReplaceTraditionalManagers | node name, sensor (e.g. OAT), reset curve points |
| `custom` | n/a | calling_point, code_body, sensors, actuators, globals |

### Reusability model (answer to "how reusable are they?")

A generated .py is bound to a model only through object names baked in at
codegen time; plugins have no argument mechanism like measures do. Three reuse
levels:

1. **Templates** (ship with the server): fully reusable, name-agnostic. This is
   the reusable artifact.
2. **Dynamic-discovery scripts** (`get_object_names(state, "Zone")`): portable
   across models with the same shape; templates use this where sensible
   (e.g. `zone_metric_aggregate` default "all zones").
3. **Baked instances**: per-model, travel with the OSM in its `files/`
   companion dir through save/load/download.

Cross-model reuse = re-run `create_python_plugin` with the same template+slots
on the other model. No plugin library/registry in v1.

### Per-user package environment (answer to Q5: yes)

Not a full venv (the E+ embedded 3.12 interpreter is fixed); a per-identity
site-packages dir wired in via SearchPaths:

- `user_pkgs_root()` in `config.py`, identity-scoped like `user_run_root()`
  (CLAUDE.md rule 14: never `_SHARED_READ_ROOTS`, never process-global).
- `install_plugin_packages(packages)` runs
  `pip install --only-binary=:all: --target <user_pkgs_root>` from the server
  venv (also 3.12, so wheel tags match E+). Wheels-only: no setup.py execution
  in the server process. Size quota (reuse file-transfer quota pattern), pinned
  versions allowed, returns installed versions + bytes used.
- `create_python_plugin` adds a `PythonPluginSearchPaths` entry for the dir
  when packages are installed (FT retains verbatim paths).
- Sandbox: the sim subprocess needs Landlock read access to `user_pkgs_root()`;
  add to the RO set in `sandbox.py` (run dir already RW).
- arm64: wheels must exist for aarch64/cp312 (numpy does; document the
  constraint).

## Tools (new skill `mcp_server/skills/python_ems/`)

| Tool | Args (sketch) | Does |
|---|---|---|
| `create_python_plugin` | name, template, slots (typed per template), globals `list[str]\|str`, output_variables, run_during_warmup=False | codegen .py under user-scoped staging → syntax check → `ExternalFile` + `PythonPluginInstance` + `PythonPluginVariable`s + `PythonPluginOutputVariable`s + the `Output:Variable` glue |
| `list_ems_actuators` | component_type filter, key filter, include_internal_variables, max_results | inject `Output:EnergyManagementSystem` Verbose, design-day-only run, parse `eplusout.edd`, return triples + units; cache per model until model mutated |
| `get_python_plugin` | name (optional; omitted = list all) | instance details, script source, wired globals/outputs |
| `edit_python_plugin` | name, code | rewrite BOTH source and the `files/` copy (ExternalFile copies at creation; editing source alone is a silent no-op), revalidate syntax + class |
| `install_plugin_packages` | packages `list[str]\|str` | per-user pip install as above (phase 2) |

Removal: `delete_object` on the `PythonPluginInstance` suffices for v1.
All names → `EXPECTED_TOOLS` in `tests/test_skill_registration.py`. Docs keep
saying "150+ tools".

## Plumbing changes (the actual net-new work outside the skill)

1. **ExternalFile copy root**: force the loaded model's workflow dir to a
   per-model staging dir under `user_run_root()` (model_manager change), so
   `ExternalFile` copies land in a contained, `is_path_allowed`-validated
   `files/` dir instead of process cwd. Needs a small spike on the exact
   workflowJSON API call.
2. **`run_simulation` staging**: today it stages only OSM + `workflow.osw` with
   `"file_paths": []` (`simulation/operations.py:856-868`). Also copy the
   model's `files/` dir into the staging dir; `run_osw`'s `_copy_tree`
   (`:167`) already copies the OSW parent wholesale, and workflow-time FT
   resolves the OSM's relative File Name via osw dir then `files/` (verified).
3. **save/load portability**: `save_osm_model` copies the `files/` companion
   dir next to the target OSM; `load_osm_model` picks up a sibling `files/`
   dir into the new staging dir. Keeps controls attached across
   save/download/upload/load.
4. **.edd parser**: net-new module (nothing parses .edd today; variable
   discovery is SQL-only via `list_output_variables`).
5. **Sandbox RO roots** for `user_pkgs_root()` (phase 2, see above).

Security posture: plugin code is arbitrary user Python executing inside the
EnergyPlus process, same threat class as measures, and every sim already runs
under the PR #63 sandbox (`sandbox.wrap_cmd`, `simulation/operations.py:307`;
all deploys are Docker/Linux so the tier is always on). No new sandbox layer
needed; only path validation + the RO-root addition.

## File layout (250-line rule)

```
mcp_server/skills/python_ems/
  tools.py          # register(mcp) only
  operations.py     # create/get/edit
  templates.py      # codegen builders (mirrors measure_authoring pattern)
  actuators.py      # list_ems_actuators op: design-day run + cache
  edd_parser.py     # pure parsing, unit-testable
  packages.py       # phase 2
  SKILL.md
.claude/skills/python-ems/SKILL.md   # served knowledge: callback guide,
                                     # handle discipline, actuator cheat sheet,
                                     # 3 worked examples, "use templates first"
tests/test_python_ems.py             # integration
tests/unit/... (or test_python_ems_unit.py)  # codegen + edd parser, no openstudio import
```

## Tests / examples

Integration (`tests/test_python_ems.py`, add to lightest CI shard `FILES=`):

1. `test_zone_metric_template_end_to_end`
   `# Validates: template scaffold + FT wiring + plugin executes; reported "Averaged Building Temperature" equals volume-weighted mean of per-zone Zone Mean Air Temperature recomputed from the same SQL (pytest.approx)`
   (port of PythonPluginCustomOutputVariable onto example model)
2. `test_schedule_override_actuator`
   `# Validates: actuator path; Schedule Value timeseries steps exactly 15.6/21.0 at the coded hours/days`
   (port of PythonPluginCustomSchedule onto a ScheduleConstant thermostat)
3. `test_list_ems_actuators_discovers_triples`
   `# Validates: .edd discovery via design-day run; exact triple ("Schedule:Constant","Schedule Value","<name>") present`
4. `test_plugin_bad_actuator_fails_loudly`
   `# Validates: -1 handle → issue_severe + nonzero return kills run; extract_simulation_errors surfaces the plugin message`
5. `test_custom_template_rejects_syntax_error`
   `# Validates: broken code_body → ok False + line info, model untouched`
6. `test_plugin_travels_through_save_load`
   `# Validates: save_osm_model/load_osm_model carry files/; plugin still executes after round-trip`
7. (phase 2) `test_install_plugin_packages_numpy`
   `# Validates: per-user site dir import inside E+ embedded interpreter; numpy-computed mean equals plain-Python mean`

Unit: template codegen slot rendering, callback-name validation, edd_parser on
a fixture .edd (no `openstudio` import).

LLM tier (later): one progressive case, "add a control that resets the heating
setpoint at night", asserting `create_python_plugin` selection with a named
template.

Worked examples for users/agents live in the served SKILL.md (the three
template ports above, shown as full tool-call sequences).

## Phasing

- **Phase 1**: plumbing 1-4, `create_python_plugin`
  (`zone_metric_aggregate`, `schedule_override`, `custom`),
  `list_ems_actuators`, `get_python_plugin`, tests 1-6, SKILL.md.
- **Phase 2**: `install_plugin_packages` + sandbox RO root + numpy test,
  `edit_python_plugin`, `node_setpoint_reset` template, trend-variable support,
  LLM test.

## Open questions

- Design-day discovery run: hidden throwaway run or visible in run list? cleanup policy?
- Package quota default (suggest 250 MB/user)?
- Locked-down deploys without PyPI egress: document "operator pre-bakes packages into image" as the fallback?
- `edit_python_plugin` in v1 or defer (delete + recreate covers it)?
- Cache invalidation for `list_ems_actuators`: any model mutation, or HVAC/schedule mutations only?
- numpy CI test on both arches or amd64 only?
