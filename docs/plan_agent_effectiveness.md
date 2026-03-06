# Plan: Agent Effectiveness — Remaining Nice-to-Haves

All core work completed in commits `8b253fc` and `cbc0283` on `optimize` branch.

## Completed Summary

| Item | Status |
|---|---|
| Phase 1A: Dedup tool-workflows (189→95 lines) | Done |
| Phase 1B: Cross-ref new-building → openstudio-patterns | Done |
| Phase 1C: Audit all SKILL.md files, remove context:fork | Done |
| Phase 1D: Trim CLAUDE.md API reference | Done |
| Phase 1E: Eval scenarios for 8 skills | Done |
| Phase 2A: CLAUDE.md "Use MCP Tools" instruction | Done |
| Phase 2B: MCP server `instructions` field | Done |
| Phase 2C: Guardrail language in create_*_osm descriptions | Done |
| Phase 2D: Strengthen list_skills/get_skill descriptions | Done |
| Phase 2E: Debug checklist (Docker verification) | All green |
| Phase 3: Troubleshoot skill | Done |
| End-to-end test (claude.ai) | Passed — agent called get_skill("new-building") first |
| EUI unit fix: report MJ/m2 + kBtu/ft2 | Done |

## Nice-to-Haves

### 1. Known gotchas in tool descriptions

Add domain-specific hints to tool descriptions where agents commonly make mistakes:
- `add_baseline_system`: "system_type is 1-10 (use list_baseline_systems to see options)"
- `set_weather_file`: "does not auto-load design days — call add_design_day separately"
- `run_simulation`: "requires weather file and design days to be set first"

### 2. Token count measurement

Measure total SKILL.md chars loaded in a multi-skill session before vs after dedup.
Rough estimate: ~1,076 total lines before → ~860 after (~20% reduction).

### 3. `conditioned_floor_area_m2` clarity

OpenStudio SDK returns 0.0 pre-simulation (requires EnergyPlus SQL output).
Options:
- Add note to `get_model_summary` response: `"note": "requires simulation to compute"`
- Compute from zone data pre-sim as fallback

### 4. `check_tool_coverage` tool (revisit if needed)

If agents still reinvent tools despite guardrails, add a tool that checks whether
an equivalent MCP tool exists before the agent writes code. Deferred — guardrails
working in initial testing.

