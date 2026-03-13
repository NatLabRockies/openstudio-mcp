# Plan: AI-Assisted Measure Authoring (Phase 9)

## Context
Writing OpenStudio Measures requires programming (Ruby or Python) + SDK API
knowledge. This forces building energy modelers to also be programmers. The
MCP server should let an AI agent create, test, edit, and apply custom
measures — so the modeler describes what they want and the AI handles the code.

## Key Discoveries

### SDK Scaffolding
`openstudio.BCLMeasure()` constructor creates complete working measures:
```python
m = openstudio.BCLMeasure(
    "My Measure", "MyMeasure",
    openstudio.toPath("/runs/custom_measures/my_measure"),
    "Envelope.Opaque",
    openstudio.MeasureType("ModelMeasure"),
    "Description", "Modeler description",
    openstudio.MeasureLanguage("Python"),  # or omit for Ruby
)
m.save()
```
Generates: measure.py/rb, measure.xml, tests/ with 3 tests + example_model.osm

### Language Coexistence
Python and Ruby measures coexist in the same OSW — tested both orderings,
both work. No language-switching issues.

### Testing Framework
SDK generates test files with 3 tests: arg count, bad args, good args.
- **Python**: `python3 -m pytest tests/ -v` — 0.5s, works now
- **Ruby**: `openstudio measure -r .` — ~10s, runs Minitest + Rubocop
- Note: `openstudio measure -r` does NOT run Python tests (issue #4907)

### Language Choice: User-Specified, Both Supported
`language` is a required parameter on `create_measure` — the user (or AI on
user's behalf) explicitly chooses Ruby or Python per measure.
- **Ruby** when measure needs openstudio-standards gem (space type lookups,
  HVAC templates, construction libraries) — Python can't access Ruby gems
- **Python** for pure model manipulation — LLMs write better Python
- AI should ask the user which language they prefer if not obvious from context

## New Skill: `measure_authoring` (3 new tools)

Existing `apply_measure` handles execution. New tools handle authoring lifecycle.

### Tool 1: `create_measure`

```python
create_measure(
    name: str,                    # snake_case → dir name + class name
    description: str,             # what it does (plain English)
    run_body: str,                # code for the run() method body
    arguments: list[dict] = [],   # [{name, display_name, type, required, default_value}]
    taxonomy_tag: str = "Whole Building.Space Types",
    modeler_description: str = "",
    language: str,                # "Ruby" or "Python" (required — user chooses)
)
```

**Flow:**
1. SDK scaffolds via `BCLMeasure()` + `.save()`
2. Read generated script (measure.rb or measure.py)
3. Replace template `arguments()` with generated code from argument spec
4. Replace template `run()` body with provided `run_body` (between markers)
5. Update generated test file to match new arguments + expected behavior
6. Syntax check: `ruby -c` or `python3 -c "compile(...)"`
7. Return `{ok, measure_dir, validation, language, class_name}`

**Output dir:** `/runs/custom_measures/<name>/`
**Max run_body:** 20KB
Idempotent — overwrites if exists.

### Tool 2: `test_measure`

```python
test_measure(
    measure_dir: str,        # path to measure
    arguments: dict = {},    # test argument values (for good-args test)
)
```

**Flow (language-aware):**
- **Python**: `python3 -m pytest tests/ -v` (0.5s)
- **Ruby**: `openstudio measure -r .` (~10s)
- Parse output for pass/fail/error counts
- Return `{ok, passed, failed, errors, test_output}`

**Timeout:** 60s

Leverages SDK-generated test framework. The test file is updated by
`create_measure` and `edit_measure` to reflect current arguments.

### Tool 3: `edit_measure`

```python
edit_measure(
    measure_name: str,              # existing custom measure name
    run_body: str = None,           # new run() body
    arguments: list[dict] = None,   # new argument spec
    description: str = None,        # updated description
)
```

**Flow:**
1. Resolve `/runs/custom_measures/<measure_name>/`
2. Read current script, detect language
3. Replace `run()` body between markers if provided
4. Regenerate `arguments()` method if new spec provided
5. Update test file if arguments changed
6. Update measure.xml if metadata changed (BCLMeasure.load + save)
7. Syntax check
8. Return `{ok, measure_dir, changes_made, validation}`

### Existing: `apply_measure` (no changes)

Already works with any measure directory path.

## Script Generation Details

### Markers for Replaceable Sections

`create_measure` inserts markers so `edit_measure` can find and replace:

**Ruby:**
```ruby
def run(model, runner, user_arguments)
  super(model, runner, user_arguments)
  if !runner.validateUserArguments(arguments(model), user_arguments)
    return false
  end
  r_value = runner.getDoubleArgumentValue("r_value", user_arguments)
  # --- begin user logic ---
  model.getSurfaces.each do |surface|
    # user's code here
  end
  # --- end user logic ---
  return true
end
```

**Python:**
```python
def run(self, model, runner, user_arguments):
    super().run(model, runner, user_arguments)
    if not runner.validateUserArguments(self.arguments(model), user_arguments):
        return False
    r_value = runner.getDoubleArgumentValue("r_value", user_arguments)
    # --- begin user logic ---
    for surface in model.getSurfaces():
        # user's code here
    # --- end user logic ---
    return True
```

### Arguments Generation

From spec `[{name: "r_value", type: "Double", required: true, default_value: "13"}]`:

**Ruby arguments():**
```ruby
def arguments(model)
  args = OpenStudio::Measure::OSArgumentVector.new
  r_value = OpenStudio::Measure::OSArgument.makeDoubleArgument("r_value", true)
  r_value.setDisplayName("R-Value")
  r_value.setDefaultValue(13.0)
  args << r_value
  return args
end
```

**Ruby extraction (in run):**
```ruby
r_value = runner.getDoubleArgumentValue("r_value", user_arguments)
```

**Python arguments():**
```python
def arguments(self, model=None):
    args = openstudio.measure.OSArgumentVector()
    r_value = openstudio.measure.OSArgument.makeDoubleArgument("r_value", True)
    r_value.setDisplayName("R-Value")
    r_value.setDefaultValue(13.0)
    args.append(r_value)
    return args
```

### Test File Updates

When `create_measure` or `edit_measure` changes arguments, the generated test
file is updated:
- `test_number_of_arguments_and_argument_names` — update arg count + names
- `test_good_argument_values` — update `args_dict` with default values
- `test_bad_argument_values` — update with empty/invalid values per type

## Tool Docstrings (API Reference for LLMs)

`create_measure` includes condensed API patterns so the LLM knows what to write:

**Ruby common patterns:**
```
model.getSurfaces.each { |s| ... }
model.getThermalZones.each { |z| ... }
model.getSpaces.each { |space| ... }
model.getBuilding.setName(name)
opt = surface.construction; if opt.is_initialized then c = opt.get end
runner.registerInfo/Warning/Error("msg")
runner.registerInitialCondition/FinalCondition("msg")
```

**Python common patterns:**
```
for s in model.getSurfaces(): ...
for z in model.getThermalZones(): ...
model.getBuilding().setName(name)
opt = surface.construction(); if opt.is_initialized(): c = opt.get()
runner.registerInfo/registerWarning/registerError("msg")
```

## File Plan

| File | ~Lines | Content |
|------|--------|---------|
| `mcp_server/skills/measure_authoring/__init__.py` | 0 | empty |
| `mcp_server/skills/measure_authoring/operations.py` | ~250 | create, test, edit ops |
| `mcp_server/skills/measure_authoring/tools.py` | ~120 | MCP registrations + docstrings |
| `tests/test_measure_authoring.py` | ~180 | integration tests (Docker) |

### Key existing files to reference
- `mcp_server/skills/measures/operations.py` — apply_measure, subprocess/OSW patterns
- `mcp_server/config.py` — RUN_ROOT, ALLOWED_PATH_ROOTS
- `tests/assets/measures/set_building_name/` — reference measure

## Tests (Integration, Docker)

1. `test_create_measure_python` — scaffold Python, verify files + syntax
2. `test_create_measure_ruby` — scaffold Ruby, verify files + syntax
3. `test_create_with_arguments` — typed args, verify in script + XML
4. `test_create_bad_syntax` — invalid code → error returned
5. `test_test_measure_python_passes` — create + test Python measure
6. `test_test_measure_ruby_passes` — create + test Ruby measure
7. `test_test_measure_reports_errors` — measure that fails → errors reported
8. `test_edit_run_body` — create → edit → verify updated code
9. `test_edit_arguments` — edit arg spec → verify script + XML + test file
10. `test_full_lifecycle` — create → test → apply → verify model changed

**CI shard:** 3 (with existing test_measures.py)

## Implementation Order

1. `operations.py` — create_measure_op, test_measure_op, edit_measure_op
2. `tools.py` — MCP wrappers with API reference docstrings
3. Integration tests
4. CI + CLAUDE.md updates

## Verification

1. Docker build: `docker build -f docker/Dockerfile -t openstudio-mcp:dev .`
2. Run tests: `docker run --rm -v ... pytest -vv tests/test_measure_authoring.py`
3. Manual test via MCP: create_measure → test_measure → apply_measure → verify
