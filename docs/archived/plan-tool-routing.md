# Plan: MCP Tool Routing & Discoverability

**Date:** 2026-03-16
**Branch:** optimize
**Status:** Phase 1-3 complete (2026-03-19)

## Problem Summary

This is a **context engineering** problem, not a prompt engineering problem.
Server instructions say "NEVER write scripts" — they were present and ignored.

Three confirmed failure modes, all rooted in how context is structured:

**FM1 — Tool overload:** 139 tools dump ~100K chars (~25-30K tokens) of
schemas at init. RAG-MCP research shows selection accuracy drops to 13.6%
at this scale. `create_measure` is buried in noise.

**FM2 — Analysis mode bypass:** File upload triggers Analysis sandbox.
LLM uses `bash_tool`/`create_file` exclusively, makes ZERO MCP `tools/call`
requests. Server instructions are cold context competing with 100K of
tool schemas. Confirmed with guardrailed image — instructions were ignored.

**FM3 — Filesystem context mismatch:** LLM tried bash to find
`/inputs/eplusout.err`, got "not found" (Analysis sandbox ≠ MCP container),
then built measure from warning text alone instead of falling back to MCP
`read_file`. Doesn't know `/inputs` and `/runs` are MCP-container paths.

## Completed Work (commit 7e79c7c)

- Quote escaping in create_measure/edit_measure (4 script builders)
- ok:false on syntax errors (create_measure_op, edit_measure_op)
- Intended Software Tool XML attributes (_add_intended_software_tools)
- Server instructions: NEVER/ALWAYS for 6 domains (measures, results, viz, models, weather, HVAC)
- LLM regression tests (test_08_measure_authoring.py, 4 tests)
- README: /inputs mount guidance for file access

## Industry Research

**RAG-MCP** (arxiv:2505.03275): 100+ tools → schemas consume 50-80% of
context, selection accuracy 13.6%. Semantic retrieval pre-filter → 50%
fewer tokens, 3x accuracy (43%). 4,400+ MCP servers on mcp.so as of 2025.

**Tool-to-Agent Retrieval** (arxiv:2511.01854): embed tools + agents in
shared vector space for granular tool-level retrieval by semantic similarity.

**Industry consensus** (LlamaIndex, Elasticpath, The New Stack 2026):
fewer tools = more reliable. Playbook agents with 5-10 tools outperform
100+ tool agents. Router Model pattern: pre-filter tool group, present subset.

## Current Tool Distribution (139 tools, 21 skills)

```
20  common_measures      (viz, thermostats, envelope, renewables, cleanup)
12  results              (extract_*, read_file, copy_file, query_timeseries)
10  component_properties (get/set component, sizing, economizer, SPM props)
 9  loop_operations      (plant loop, zone equipment CRUD)
 9  geometry             (surfaces, subsurfaces, floor prints, matching, WWR)
 8  simulation           (run, status, logs, artifacts, cancel, validate)
 8  hvac_systems         (baseline systems, terminals, DOAS, VRF, radiant)
 7  weather              (weather info, design days, sim control, run period)
 7  hvac                 (air loops, plant loops, zone equipment list/detail)
 6  spaces               (spaces, thermal zones — list/detail/create)
 6  model_management     (load, save, inspect, list_files, weather_files)
 6  loads                (people, lights, equipment, infiltration)
 5  object_management    (list/get/set/delete/rename any object)
 5  constructions        (materials, constructions, assignments)
 4  measure_authoring    (create, test, edit, list custom measures)
 4  comstock             (list comstock/common measures by category)
 2  skill_discovery      (list_skills, get_skill)
 2  simulation_outputs   (add output variable/meter)
 2  server_info          (status, versions)
 2  schedules            (get_schedule_details, create_schedule_ruleset)
 2  measures             (list_measure_arguments, apply_measure)
 2  building             (get_building_info, get_model_summary)
 1  space_types          (get_space_type_details)
```

## Proposed Tool Grouping

### Always-loaded core (~15 tools)

Tools needed in virtually every conversation. Small enough for reliable
selection. Covers model lifecycle + discovery.

```
model_management (4):  load_osm_model, save_osm_model, list_files, list_weather_files
model_creation   (2):  create_new_building, create_bar_building
building         (2):  get_building_info, get_model_summary
object_mgmt      (3):  list_model_objects, get_object_fields, set_object_property
simulation       (2):  run_simulation, get_run_status
results          (1):  extract_summary_metrics
discovery        (2):  list_skills, get_skill
```

Plus a meta-tool: `recommend_tools(task_description)` — returns the
relevant tool group for the task.

### On-demand groups (loaded when needed)

| Group | Tools | Count | Trigger phrases |
|-------|-------|-------|-----------------|
| **geometry** | spaces(6) + geometry(9) + constructions(5) | 20 | "add windows", "create space", "floor plan", "surfaces" |
| **hvac** | hvac_systems(8) + hvac(7) + loop_ops(9) + components(10) | 34 | "add HVAC", "boiler", "chiller", "air loop", "VAV" |
| **simulation** | simulation(8) + weather(7) + sim_outputs(2) | 17 | "run simulation", "weather", "design day", "run period" |
| **results** | results(12) + viz/report common_measures(3) | 15 | "EUI", "results", "energy use", "report", "chart" |
| **measures** | measure_authoring(4) + measures(2) + comstock(4) | 10 | "create measure", "write measure", "apply measure" |
| **loads** | loads(6) + schedules(2) + space_types(1) | 9 | "people", "lights", "equipment", "schedule" |
| **envelope** | remaining common_measures (thermostats, envelope, renewables, cleanup) | 14 | "thermostat", "insulation", "solar", "PV", "cleanup" |

**Total:** 15 core + 119 on-demand = 134 (+ 5 meta/info tools always available)

### How `recommend_tools` works

```
User: "Create a measure to fix OA warnings"

LLM calls: recommend_tools("create measure fix OA warnings")

Server returns:
{
  "recommended_group": "measures",
  "tools": [
    {"name": "create_measure", "description": "Create custom Ruby/Python measure..."},
    {"name": "test_measure", "description": "Run tests for a custom measure..."},
    {"name": "edit_measure", "description": "Edit existing measure..."},
    {"name": "apply_measure", "description": "Apply measure to model..."},
    {"name": "list_custom_measures", "description": "List custom measures..."},
    {"name": "list_measure_arguments", "description": "List measure arguments..."}
  ],
  "also_available": ["results", "simulation", "hvac", "geometry", "loads", "envelope"]
}
```

LLM now has 6 focused tools instead of 139. Calls `create_measure`.

### Key design decisions

**All tools stay registered.** The LLM can call any tool directly —
`recommend_tools` is advisory, not a gate. This preserves backward
compatibility for workflows that already work.

**Groups overlap intentionally.** `run_simulation` is in core AND in the
simulation group. `extract_summary_metrics` is in core AND in results.
The core set handles the 80% case; groups provide depth.

**Group assignment is by tag.** Each tool gets a `tags={"group_name"}`
annotation. `recommend_tools` does keyword matching against tool names,
descriptions, and tags. No embedding model needed (approach 2B from
previous plan).

## Implementation Phases

### Phase 1: FM3 fix + docstring hardening (small, do now)

**Fix A:** `read_file` docstring — add "/inputs and /runs are inside the
MCP container, not the host shell"
**File:** `mcp_server/skills/results/tools.py:23`

**Fix B:** Server instructions — add file access fallback guidance
**File:** `mcp_server/server.py` instructions string

**Fix C:** `list_files` docstring — add "/inputs contains user-provided
models, weather files, and data files"
**File:** `mcp_server/skills/model_management/tools.py`

**Fix D:** Docstring hardening for bypass-prone tools:
- `view_model` — "use instead of writing visualization scripts"
- `view_simulation_data` — "use instead of matplotlib/plotly"
- `generate_results_report` — "use instead of Python extraction scripts"
- `copy_file` — remove "bypasses MCP size limit" phrasing
- `create_measure` — add "ALWAYS use this tool" at top of docstring

**Tests:** Add to `tests/llm/test_05_guardrails.py`:
- `test_visualization_uses_mcp_not_script`
- `test_report_uses_mcp_not_script`
- `test_measure_uses_mcp_not_create_file`

### Phase 2: Tool annotations + tags (medium, enables Phase 3)

Add `tags` and `annotations` to all 139 tools:
- `tags={"core"}` on always-loaded tools
- `tags={"geometry"}`, `tags={"hvac"}`, etc. on group tools
- `readOnlyHint=True` on all list/get/extract tools
- `destructiveHint=True` on delete_object, remove_* tools

This is mechanical — ~2 hours across 21 tools.py files. Adds no new
behavior but provides the metadata infrastructure for Phase 3.

**Files:** all `mcp_server/skills/*/tools.py`

### Phase 3: recommend_tools meta-tool (high impact)

Add `recommend_tools(task_description: str)` tool that:
1. Keyword-matches task against tool names, descriptions, and tags
2. Returns the matching group's tools with descriptions
3. Lists other available groups

**Implementation:**
- New file: `mcp_server/skills/tool_router/operations.py`
- Build keyword index from tool registry at startup
- Match using simple token overlap (no ML dependency)
- Return top group + tool descriptions

**Files:** new `mcp_server/skills/tool_router/` skill

### Phase 4: Lazy loading via tools/list_changed (future, if needed)

If Phase 3 is insufficient, implement true lazy loading:
- Init registers only core ~15 tools
- `recommend_tools` dynamically registers group tools via FastMCP
- Sends `tools/list_changed` notification so client refreshes
- Unregisters after conversation ends or group changes

Requires FastMCP `tools/list_changed` support (listed in capabilities
output). Significant architecture change — only if Phases 1-3 fail.

### Phase 5: RAG-based discovery (future, if needed)

Embed all tool descriptions in vector index. `recommend_tools` does
semantic search. Highest accuracy but adds embedding model dependency.

Only if keyword matching (Phase 3) proves insufficient.

## Testing Strategy

### What we can test
- Tool schema token cost (unit test)
- recommend_tools accuracy (unit test)
- LLM tool selection with reduced vs full tool set (LLM A/B test)
- FM3 file access fallback (LLM test)
- Guardrail bypass for viz/results/measures (LLM test)

### What we can't test
- Analysis mode activation (requires file upload in Claude Desktop GUI)
- Competition between Analysis tools and MCP tools in same conversation
- FM2 specifically (MCP tools ignored entirely when Analysis mode active)

### Test files
```
tests/test_tool_routing.py          — unit tests (no Docker, no LLM)
tests/llm/test_09_tool_routing.py   — LLM A/B selection tests
tests/llm/test_05_guardrails.py     — extend with bypass tests
```

### Test 1: Tool schema size (unit, Phase 2 gate)

Measure token cost of full tool dump vs core-only subset. This is the
baseline metric for FM1 — if we reduce it, we've addressed tool overload.

```python
# tests/test_tool_routing.py

def test_tool_schema_token_count():
    """Full tool schema must be measurably large; core subset must be small."""
    all_tools = get_all_tool_schemas()       # serialize all 139
    core_tools = get_core_tool_schemas()     # serialize core ~15

    all_tokens = count_tokens(json.dumps(all_tools))
    core_tokens = count_tokens(json.dumps(core_tools))

    # Document current cost
    print(f"All tools: {all_tokens} tokens")
    print(f"Core tools: {core_tokens} tokens")
    print(f"Reduction: {100 - core_tokens/all_tokens*100:.0f}%")

    # Core must be <30% of full
    assert core_tokens < all_tokens * 0.3

def test_all_tools_have_tags():
    """Every tool must have at least one group tag after Phase 2."""
    for tool in get_all_tool_schemas():
        tags = tool.get("_meta", {}).get("fastmcp", {}).get("tags", [])
        assert len(tags) > 0, f"Tool {tool['name']} has no tags"

def test_core_tools_complete():
    """Core tool set must cover model lifecycle."""
    core_names = {t["name"] for t in get_core_tool_schemas()}
    required = {
        "load_osm_model", "save_osm_model", "list_files",
        "create_new_building", "get_building_info",
        "list_model_objects", "get_object_fields",
        "run_simulation", "get_run_status",
        "extract_summary_metrics",
        "list_skills",
    }
    missing = required - core_names
    assert not missing, f"Core missing: {missing}"
```

### Test 2: recommend_tools accuracy (unit, Phase 3 gate)

Parameterized test: given task description, does recommend_tools return
the right group with the right tools? Pure keyword matching, deterministic.

```python
# tests/test_tool_routing.py

ROUTING_CASES = [
    # (task_description, expected_group, must_include_tool)
    ("create a measure to fix OA warnings", "measures", "create_measure"),
    ("write a Ruby measure that sets lights", "measures", "create_measure"),
    ("what's the EUI", "results", "extract_summary_metrics"),
    ("show me monthly energy breakdown", "results", "extract_end_use_breakdown"),
    ("generate a report of simulation results", "results", "generate_results_report"),
    ("add VAV reheat to all zones", "hvac", "add_baseline_system"),
    ("add a boiler to the hot water loop", "hvac", "add_supply_equipment"),
    ("set chiller COP to 5.5", "hvac", "set_component_properties"),
    ("create a 2-story office building", "core", "create_new_building"),
    ("run an annual simulation", "simulation", "run_simulation"),
    ("set weather to Boston", "simulation", "change_building_location"),
    ("add R-30 roof insulation", "geometry", "create_construction"),
    ("set window to wall ratio to 40%", "geometry", "set_window_to_wall_ratio"),
    ("add 50 W/m2 plug loads", "loads", "create_electric_equipment"),
    ("show me a 3D view of the building", "core", "view_model"),
    ("adjust cooling setpoint by 2F", "envelope", "adjust_thermostat_setpoints"),
    ("add rooftop solar panels", "envelope", "add_rooftop_pv"),
    ("apply the lighting measure I created", "measures", "apply_measure"),
    ("test my custom measure", "measures", "test_measure"),
    ("what zones are in the building", "core", "list_model_objects"),
    ("read the error file at /inputs/eplusout.err", "core", "read_file"),
    ("extract HVAC sizing from the simulation", "results", "extract_hvac_sizing"),
    ("add a design day for Chicago", "simulation", "add_design_day"),
    ("delete the unused boiler", "hvac", "delete_object"),
    ("create a fractional schedule", "loads", "create_schedule_ruleset"),
]

@pytest.mark.parametrize("task,expected_group,must_include",
                         ROUTING_CASES,
                         ids=[c[2] for c in ROUTING_CASES])
def test_recommend_tools(task, expected_group, must_include):
    result = recommend_tools_op(task)
    assert result["ok"]
    assert result["recommended_group"] == expected_group
    tool_names = [t["name"] for t in result["tools"]]
    assert must_include in tool_names, (
        f"'{must_include}' not in recommended tools for '{task}': {tool_names}"
    )
```

### Test 3: LLM A/B tool selection (LLM test, Phase 3 validation)

Same prompts, two configurations: all 139 tools vs core + recommend_tools.
Measures whether reduced context improves tool selection accuracy.

```python
# tests/llm/test_09_tool_routing.py

AB_CASES = [
    # (prompt, expected_mcp_tool)
    ("Create a Ruby measure that sets all lights to 8 W/m2",
     "create_measure"),
    ("What's the total site EUI from run {run_id}",
     "extract_summary_metrics"),
    ("Show me a 3D view of the model",
     "view_model"),
    ("Read the warnings in /inputs/eplusout.err",
     "read_file"),
    ("Add System 7 VAV reheat to all zones",
     "add_baseline_system"),
]

@pytest.mark.parametrize("case", AB_CASES)
def test_tool_selection_with_all_tools(case):
    """Baseline: all 139 tools available."""
    prompt, expected = case
    result = run_claude(prompt + " Use MCP tools only.",
                        allowed_tools="mcp__openstudio__*")
    assert expected in result.tool_names

@pytest.mark.parametrize("case", AB_CASES)
def test_tool_selection_with_core_tools(case):
    """Reduced: only core tools + recommend_tools."""
    prompt, expected = case
    core_filter = ",".join(f"mcp__openstudio__{t}" for t in CORE_TOOLS)
    result = run_claude(prompt + " Use MCP tools only.",
                        allowed_tools=core_filter)
    # Should either call the tool directly (if in core)
    # or call recommend_tools first, then the right tool
    assert expected in result.tool_names or "recommend_tools" in result.tool_names
```

The A/B comparison is the strongest signal. If core+recommend_tools
matches or beats all-tools accuracy, the grouping works.

### Test 4: FM3 file access fallback (LLM test, Phase 1 validation)

Does the LLM use MCP `read_file` when given a `/inputs/` path?

```python
# tests/llm/test_09_tool_routing.py

def test_read_file_uses_mcp_not_bash():
    """LLM must use MCP read_file for /inputs paths, not bash."""
    result = run_claude(
        "Read the file at /inputs/eplusout.err and count the warnings. "
        "Use MCP tools only.",
        timeout=120,
    )
    assert "read_file" in result.tool_names, (
        f"Expected read_file, got: {result.tool_names}"
    )
```

### Test 5: Guardrail bypass tests (LLM test, Phase 1)

Extend `tests/llm/test_05_guardrails.py`:

```python
def test_visualization_uses_mcp_not_script():
    """Must use view_model/view_simulation_data, not write matplotlib."""
    result = run_claude(
        LOAD + "show me a 3D visualization of the building. "
        "Use MCP tools only.",
        timeout=120,
    )
    assert any(t in {"view_model", "view_simulation_data"}
               for t in result.tool_names)

def test_report_uses_mcp_not_script():
    """Must use generate_results_report, not write Python/HTML."""
    run_id = get_sim_run_id()
    if not run_id:
        pytest.skip("No simulation run_id")
    result = run_claude(
        f"Generate a comprehensive report from simulation run '{run_id}'. "
        "Use MCP tools only.",
        timeout=120,
    )
    assert "generate_results_report" in result.tool_names

def test_measure_uses_create_measure_not_create_file():
    """Must use create_measure, not write measure.rb directly."""
    result = run_claude(
        "Write a Ruby OpenStudio measure that sets all lights to 8 W/m2. "
        "Use MCP tools only.",
        timeout=120,
    )
    assert "create_measure" in result.tool_names
```

### Test progression by phase

| Phase | Unit tests | LLM tests | What they prove |
|-------|-----------|-----------|-----------------|
| 1 (docstrings) | — | FM3 fallback, guardrail bypass | Instructions/docstrings steer LLM to MCP tools |
| 2 (tags) | all_tools_have_tags, core_tools_complete | — | Metadata infrastructure ready |
| 3 (recommend_tools) | recommend_tools accuracy (25 cases), schema_token_count | A/B selection comparison | Grouping improves selection accuracy |
| 4 (lazy loading) | core < 30% of full tokens | A/B with restricted allowedTools | Token reduction measurable |

## Success Criteria

Quantitative:
- Tool schema tokens: core < 30% of full (~7K vs ~25K)
- recommend_tools: >90% accuracy on 25 routing cases
- LLM A/B: core+recommend equals or beats all-tools selection rate
- Guardrail tests: 100% pass (test_05 + test_08 + test_09)

Qualitative:
- LLM calls `create_measure` (not `create_file`) for measure authoring
- LLM calls `read_file` with `/inputs/` path when bash can't find a file
- LLM calls `extract_summary_metrics` (not Python script) for EUI
- LLM calls `view_model` (not matplotlib) for visualization

## Analysis Mode Gap (not fixable from MCP side)

File upload → Analysis sandbox → bash_tool momentum cannot be fixed by
MCP server changes. Documented workaround in README: place files in
`/inputs` mount instead of uploading.

Not testable in our harness — requires Claude Desktop GUI interaction.

## Unresolved Questions

- Does Claude Desktop use `readOnlyHint`/tags for routing, or purely informational?
- Should `recommend_tools` be the FIRST tool called, or just available?
- Move create_measure code examples from docstring to SKILL.md to reduce schema size?
- Can FastMCP dynamically register/unregister tools at runtime?
- What's the token cost of 15 core tools vs 139? Need to measure.
- Does `--allowedTools` on `claude -p` support comma-separated tool lists?
