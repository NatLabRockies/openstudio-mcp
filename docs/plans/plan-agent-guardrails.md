# Plan: Agent Guardrails — Prevent LLM Tool Bypass

**Date:** 2026-03-16
**Branch:** optimize
**Context:** Claude Desktop Analysis mode caused LLM to hand-write measure files
instead of using MCP `create_measure`. Root cause: uploaded file triggered
Analysis sandbox, LLM used `bash_tool`/`create_file` instead of MCP tools.

## Completed

### Fix 1: Quote escaping in create_measure/edit_measure
- `_escape_ruby_str()` / `_escape_python_str()` in all 4 script builders
- edit_measure regex now matches full `def description...end` block
- Tests: `test_create_measure_with_quotes_in_description`, `test_edit_description_with_quotes`

### Fix 2: ok:false on syntax errors
- `create_measure_op` and `edit_measure_op` return `ok: false` + error when syntax check fails
- Tests: `test_create_bad_syntax`, `test_create_bad_syntax_returns_ok_false`

### Fix 3: Intended Software Tool XML attributes
- `_add_intended_software_tools()` patches measure.xml with Apply Measure Now / OS App / PAT
- Test: `test_measure_xml_has_intended_software_tool`

### Fix 4: Server instructions — explicit tool routing
- Measures: never write .rb/.py/.xml directly
- Results: never write Python/SQL scripts
- Visualization: never write matplotlib/plotly
- Models: never write raw IDF/OSM
- Weather: never download/write EPW
- HVAC: never write SDK scripts

### Fix 5: LLM regression tests (test_08_measure_authoring.py)
- 4 tests reproducing the original debug chat scenario
- Validates quote escaping, edit with quotes, XML attrs, syntax error reporting

## Remaining Work

### P1: Strengthen tool docstrings (prevent script bypass)

These tools have sparse docstrings that don't explicitly say "use instead of scripts":

**view_model** — `common_measures/tools.py:50`
```
Current:  "Generate 3D HTML viewer of model geometry."
Add:      "Use this instead of writing visualization scripts.
           Wraps ComStock measure. Output: HTML in /runs/exports/."
```

**view_simulation_data** — `common_measures/tools.py:58`
```
Current:  "Generate 3D HTML viewer with simulation data overlaid."
Add:      "Use this for heatmaps/charts instead of matplotlib/plotly scripts."
```

**generate_results_report** — `common_measures/tools.py:78`
```
Current:  "Generate comprehensive HTML report from simulation results (~25 sections)."
Add:      "Use this instead of writing Python extraction/reporting scripts.
           Wraps ComStock measure. Output: HTML report in /runs/exports/."
```

**copy_file** — `results/tools.py:48`
```
Current:  "Copy a file or directory to an accessible path.
           Bypasses the MCP size limit for large files like HTML reports."
Change:   "Copy a file or directory to /runs/exports/ for export.
           Read-only copy operation — does not move, delete, or modify files."
```

### P2: LLM guardrail tests for visualization + results bypass

Add to `tests/llm/test_05_guardrails.py`:

**test_visualization_uses_mcp_not_script** — prompt: "Show me a chart of
monthly energy use from run X." Assert: calls `view_simulation_data` or
`query_timeseries`, NOT `bash_tool` writing Python.

**test_report_uses_mcp_not_script** — prompt: "Generate a report of
simulation results from run X." Assert: calls `generate_results_report`,
NOT `bash_tool` writing HTML/Python.

**test_measure_uses_mcp_not_create_file** — prompt: "Write a measure that
sets all lights to 8 W/m2." Assert: calls `create_measure`, NOT
`create_file`/`bash_tool`.

Depends on: test_01_setup (needs run_id for results tests).

### P3: create_measure docstring — add bypass warning at top

`measure_authoring/tools.py:38` — the 146-line docstring has extensive
Ruby/Python code examples. LLM could read these and decide it has enough
syntax knowledge to write measure files directly.

Add as first line of docstring:
```
ALWAYS use this tool to author measures — never write measure.rb/.py/.xml
files by hand. The code examples below show what to pass as 'run_body',
not what to write directly.
```

### P4: Analysis mode bypasses MCP entirely (CONFIRMED)

**Confirmed 2026-03-16:** Rebuilt Docker image with all guardrails. MCP
server started, sent updated instructions with "NEVER write scripts",
listed 138 tools. LLM made ZERO `tools/call` requests. Used Analysis
mode `bash_tool`/`create_file` exclusively. Server instructions were
present and ignored.

**Root cause:** Claude Desktop Analysis mode and MCP are separate
execution contexts. When a file upload triggers Analysis mode,
Analysis tools (`bash_tool`, `create_file`) become the primary toolset.
MCP tools are available but the LLM never reaches for them. This is a
Claude Desktop architecture issue, not an MCP server issue.

**Server instructions cannot fix this.** They are advisory metadata on
the MCP connection. When Analysis mode is active, the LLM's routing
gives priority to Analysis tools.

**User workarounds (document in README/docs):**
1. Don't upload files — paste error content as text in chat
2. Copy files to MCP-accessible mount first: place in `tests/assets/`
   (mounted as `/inputs` in container) instead of uploading
3. Start conversation without upload, reference file by MCP path:
   "Analyze warnings in /inputs/eplusout.err"
4. After Analysis reads the file, explicitly prompt: "Now use the
   openstudio-mcp create_measure tool to build the fix"

**Potential future fixes (require Claude Desktop changes):**
- Analysis mode should check for relevant MCP tools before using
  built-in tools for creation/authoring tasks
- MCP servers should be able to declare "claim" over file types or
  task categories (e.g. "I handle .err files, .osm files, measures")
- File uploads should be mountable into MCP containers

### P5: Guardrail test for HVAC scripting bypass

**test_hvac_uses_mcp_not_script** — prompt: "Add a VAV system to all zones."
Assert: calls `add_baseline_system`, NOT `bash_tool` writing OpenStudio Ruby.

Lower priority — HVAC tools are well-described and this bypass is less
likely than measure/results/visualization.

## Unresolved Questions
- Can Claude Desktop Analysis sandbox paths be mounted into MCP containers?
- Should create_measure docstring code examples be moved to SKILL.md to reduce docstring length?
- Are there other Claude Desktop modes (besides Analysis) that introduce competing tool sets?
