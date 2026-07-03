# Python EMS skill

EnergyPlus Python Plugin authoring + EMS actuator discovery.

Tools:
- `create_python_plugin` — template-first plugin scaffolding (zone_metric_aggregate,
  schedule_override, node_setpoint_reset, custom). Writes the script into the model's
  companion `files/` dir via ExternalFile, wires PythonPlugin:Instance/Variables/
  OutputVariable/TrendVariable and the Output:Variable glue.
- `get_python_plugin` — list/inspect plugin instances incl. script source + search paths.
- `edit_python_plugin` — validated script replacement (class name must stay).
- `list_ems_actuators` — hidden sizing-only run, parses eplusout.edd for valid
  actuator triples.
- `install_plugin_packages` — wheels-only pip into the per-user python_packages dir
  (config.user_pkgs_root, inside the run root); reaches plugins via
  PythonPlugin:SearchPaths + a read-only Landlock grant in the sim sandbox
  (simulation _launch passes extra_ro). Quota: OSMCP_PKGS_QUOTA_MB (hard cap).

Module layout:
- `templates.py` — pure codegen + AST/package-spec validation (no openstudio import; unit-tested)
- `edd_parser.py` — pure .edd parsing (unit-tested)
- `operations.py` — create + model wiring (ExternalFile copy dest is controlled by
  pointing the model's workflowJSON at the OSM's dir)
- `manage.py` — get/edit existing plugin instances
- `packages.py` — per-user pip install (wheels-only)
- `actuators.py` — discovery run under the simulation sandbox

Plumbing this skill depends on:
- `simulation/operations.py::run_simulation` stages the OSM's sibling `files/` dir
- `model_management/operations.py::save_osm_model` carries `files/` on save-as

Served agent guidance lives in `.claude/skills/python-ems/SKILL.md`.
