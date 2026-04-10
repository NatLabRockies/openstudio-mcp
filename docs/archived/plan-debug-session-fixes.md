# Plan: Debug Session Fixes

Issues discovered from analyzing `docs/debug/` chat session + logs where an agent
authored a WSHP measure on Claude.ai.

## 1. `compare_runs` fuel-type bug

**Problem:** `compare_runs_op` lines 414-417 sum ALL numeric columns per end-use category,
including Water (converted to kBtu). Heat Rejection showed ~7.5M kBtu because it added
electricity + cooling tower evaporative water. Physically meaningless.

**Fix:**
- `extract_end_use_breakdown` already returns per-fuel columns (Electricity, Natural Gas,
  Additional Fuel, District Cooling, District Heating, Steam, Water)
- `compare_runs_op` should produce per-fuel deltas, not collapse to single total
- Also add per-fuel EUI totals (total electricity kBtu, total gas kBtu, etc.)
- Keep a grand total but **exclude Water** (it's volume, not energy)

**Changes:**
- `sql_extract.py::extract_end_use_breakdown` — no change needed (already returns per-fuel)
- `operations.py::compare_runs_op` — rewrite end-use delta logic:
  - Iterate fuel columns, not sum all numerics
  - Return `end_use_deltas` as list of `{category, fuel, baseline, retrofit, delta, delta_pct}`
  - Add `fuel_totals` section: `{fuel, baseline_total, retrofit_total, delta, delta_pct}`
  - Exclude Water from energy totals (or put in separate `water_use` section)
- Update test in `tests/test_results.py` (or wherever compare_runs is tested)

**Files:** `mcp_server/skills/results/operations.py`, `mcp_server/skills/results/sql_extract.py`

---

## 2. `create_new_building` climate zone error

**Problem:** When weather_file not provided and model has no climate zone,
`create_typical_building` receives "Lookup From Model" and fails with unclear
nil error from the measure. Agent in debug session had to recover manually with
`change_building_location` + `create_typical_building`.

**Fix:**
- In `create_new_building`, if no `weather_file` and no `climate_zone` explicitly provided,
  check if model already has a climate zone set
- If not, return clear error: "climate_zone required when no weather_file provided.
  Use change_building_location first, or pass climate_zone='4A' directly."
- Don't silently pass "Lookup From Model" when we know it will fail

**Files:** `mcp_server/skills/geometry/operations.py`

---

## 3. Skill/tool discovery before complex tasks

**Problem:** Server instructions say "for multi-step workflows, call list_skills() first"
but agent in debug session didn't call `get_skill("measure-authoring")` until after
first measure failed. The skill has templates, patterns, error handling guidance.

**Fix:**
- Strengthen `create_measure` docstring: "TIP: call get_skill('measure-authoring') first
  for templates, API patterns, and common pitfalls"
- Add same hint to `edit_measure` docstring
- Consider adding a `hint` field in `create_measure` response when test fails:
  "Did you consult get_skill('measure-authoring')?"

**Files:** `mcp_server/skills/measure_authoring/tools.py`

---

## 4. Discourage raw IDF reads

**Problem:** Agent read raw EnergyPlus IDF files to debug curve coefficients instead of
using `inspect_component`, `extract_component_sizing`, `get_object_fields`. Burns tokens
on huge files when structured tools return the same data more concisely.

**Fix:**
- `read_file` tool: add docstring guidance — "For EnergyPlus IDF/IDD files, prefer
  inspect_component, extract_component_sizing, or get_object_fields which return
  structured data with less context usage"
- Don't hard-block (agent may have legitimate reasons), just steer away

**Files:** `mcp_server/skills/results/tools.py`

---

## 5. `search_api` introspection tool — SDK method lookup

**Problem:** Agent authored Ruby measures calling nonexistent OS 3.11 methods
(`setRatedCoolingCoefficientOfPerformance`, `setLatentEffectivenessat75CoolingAirFlow`,
`setMaximumCyclingRate`). No way to verify method existence at runtime. Caused 3 separate
test-fix cycles.

**What the LLM needs:** For a given class, what are the constructor args and available
methods? Not wiring patterns — just the API surface.

**Approach:** New MCP tool `search_api(class_pattern, method_pattern?)` that introspects
the live `openstudio.model` module:

```python
# Pseudocode
import openstudio.model as m
import inspect

def search_api(class_pattern: str, method_pattern: str | None = None):
    # 1. Find matching classes via regex on dir(m)
    # 2. For each class, get methods via dir(cls) filtered by method_pattern
    # 3. Filter out dunder, internal, inherited-from-object methods
    # 4. Group: constructors (\_\_init\_\_), getters (get*/is*), setters (set*), other
    # 5. Return with max_results cap
```

**Output format (compact):**
```json
{
  "class": "CoilCoolingFourPipeBeam",
  "constructor": "CoilCoolingFourPipeBeam(model)",
  "setters": ["setName", "setBeamRatedCoolingCapacityperBeamLength", ...],
  "getters": ["name", "beamRatedCoolingCapacityperBeamLength", ...],
  "other": ["clone", "remove", ...]
}
```

**Context control:**
- `max_classes` param (default 5) — cap on matched classes
- `method_pattern` param — regex filter on method names (e.g. "COP|cop|Rated")
- Only return method names, not signatures (Python SWIG bindings don't have useful
  signatures anyway)
- Group by setter/getter/other for quick scanning
- Exclude inherited ModelObject/IdfObject base methods (remove, clone, name, etc.)
  unless `include_base=True`

**Skill integration:**
- measure-authoring SKILL.md: "Before writing SDK calls, use search_api to verify
  methods exist. Training data may reference deprecated/removed methods."
- `create_measure` docstring: mention search_api

**Files:**
- New: `mcp_server/skills/api_reference/` skill (tools.py, operations.py, SKILL.md)
- Update: `.claude/skills/measure-authoring/SKILL.md`
- Update: `mcp_server/skills/measure_authoring/tools.py` (docstring hints)
- Test: `tests/test_api_reference.py`

---

## 6. Wiring pattern reference — openstudio-resources simulation tests

**Problem:** Agent doesn't know how to connect model objects (coils→loops, terminals→air
loops, SPMs→nodes). The openstudio-resources simulation tests are the canonical reference
for this, but they're not in the Docker container and not searchable.

**What the LLM needs:** "Show me how a CoilCoolingFourPipeBeam gets wired to a plant loop
and air terminal" — a snippet showing the construction + connection pattern, not just
method names (that's #5).

**Approach:** Bundle a curated subset of openstudio-resources simulation tests in the
container and provide a search tool.

**Details:**
- At Docker build time, clone openstudio-resources (or download specific files) into
  `/opt/openstudio-resources/`
- Only keep `model/simulationtests/*.py` — the wiring pattern files (~50 files, ~2MB)
- New MCP tool `search_wiring_patterns(pattern, max_results=3, context_lines=30)`:
  - Greps the simulation test files for class/method pattern
  - Extracts the enclosing function around each match (detect `def ...` boundaries)
  - Returns function name, file name, and the function body
  - Cap: `max_results` functions, `max_lines` per function (default 50)

**Context control:**
- Return enclosing function only, not whole file
- Default 3 results, 50 lines each = ~150 lines max
- Agent can increase if needed
- Pair with #5: `search_api` for "does this method exist?",
  `search_wiring_patterns` for "how do I connect these objects?"

**Skill integration:**
- measure-authoring SKILL.md: "For HVAC object wiring (connecting coils to loops,
  terminals to air loops), use search_wiring_patterns to find working examples from
  openstudio-resources simulation tests"

**Files:**
- `docker/Dockerfile` — add openstudio-resources download step
- New: `mcp_server/skills/api_reference/` (same skill as #5, add wiring tool)
- Test: `tests/test_api_reference.py`

---

## Implementation order

1. **#1 compare_runs** — DONE (commit a58f2a0)
2. **#2 create_new_building** — DONE (commit a58f2a0)
3. **#4 read_file IDF hint** — DONE (tool routing commit)
4. **#3 skill discovery hints** — DONE (tool routing commit)
5. **#5 search_api tool** — DONE (tool routing commit)
6. **#6 wiring patterns** — DONE (24 curated recipes, no Docker build change needed)

## Unresolved questions

- #1: should Water appear in output at all, or separate section?
- #5: do SWIG Python bindings expose enough via `dir()` to be useful? need to verify in container
- #5: Ruby measures call Ruby API — Python introspection gives Python method names. are they 1:1?
- #6: openstudio-resources tests are Python — measures are Ruby. method names same but syntax differs. sufficient?
- #6: how large is the simulationtests subset? need to check before bundling
- #6: should this be a build-time download or a git submodule?
