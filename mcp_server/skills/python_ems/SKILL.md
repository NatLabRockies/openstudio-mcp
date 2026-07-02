# Python EMS skill

EnergyPlus Python Plugin authoring + EMS actuator discovery.

Tools:
- `create_python_plugin` — template-first plugin scaffolding (zone_metric_aggregate,
  schedule_override, custom). Writes the script into the model's companion `files/`
  dir via ExternalFile, wires PythonPlugin:Instance/Variables/OutputVariable and
  the Output:Variable glue.
- `get_python_plugin` — list/inspect plugin instances incl. script source.
- `list_ems_actuators` — hidden sizing-only run, parses eplusout.edd for valid
  actuator triples.

Module layout:
- `templates.py` — pure codegen + AST validation (no openstudio import; unit-tested)
- `edd_parser.py` — pure .edd parsing (unit-tested)
- `operations.py` — model wiring (ExternalFile copy dest is controlled by pointing
  the model's workflowJSON at the OSM's dir)
- `actuators.py` — discovery run under the simulation sandbox

Plumbing this skill depends on:
- `simulation/operations.py::run_simulation` stages the OSM's sibling `files/` dir
- `model_management/operations.py::save_osm_model` carries `files/` on save-as

Served agent guidance lives in `.claude/skills/python-ems/SKILL.md`.
