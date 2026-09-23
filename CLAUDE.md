# CLAUDE.md — Instructions for Claude Code

@AGENTS.md

The rest of this file is Claude Code specific; shared project rules live in `AGENTS.md` (imported above).

## Critical: Use MCP Tools — Do Not Reinvent
Always use openstudio-mcp tools for BEM tasks:
- Never generate raw IDF files
- OSM files are created/modified only through MCP tools (create_typical_building, create_new_building, etc)
- Never write Python/Ruby/others scripts to parse SQL results, create visualizations, build HVAC wiring, or extract data — equivalent MCP tools already exist (extract_*, query_timeseries, view_model, view_simulation_data, add_baseline_system, etc.). Sanctioned exception: custom ReportingMeasures via create_measure, when no extract_* tool covers the metric (see measure-authoring skill)
- If a task genuinely cannot be done with existing tools, ASK THE USER before writing any code or scripts
- For workflow guidance, run: `list_skills()` or `get_skill("new-building")`

## LLM Tests
- Targeted: `LLM_TESTS_ENABLED=1 pytest tests/llm/test_06_progressive.py -k "thermostat_L1" -v`
- Full suite only for final validation
- Markers: `-m smoke`, `-m generic`, `-m progressive` (current counts: `pytest tests/llm --co -q -m <marker>`)
- Benchmark results go in `docs/testing/llm-test-benchmark.md`
