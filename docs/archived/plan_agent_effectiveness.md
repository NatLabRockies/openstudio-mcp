# Plan: Agent Effectiveness — Complete

All work completed on `optimize` branch.

## Completed

| Item | Commit |
|---|---|
| Phase 1A: Dedup tool-workflows (189→95 lines) | `8b253fc` |
| Phase 1B: Cross-ref new-building → openstudio-patterns | `8b253fc` |
| Phase 1C: Audit all SKILL.md files, remove context:fork | `8b253fc` |
| Phase 1D: Trim CLAUDE.md API reference | `8b253fc` |
| Phase 1E: Eval scenarios for 8 skills | `cbc0283` |
| Phase 2A: CLAUDE.md "Use MCP Tools" instruction | `8b253fc` |
| Phase 2B: MCP server `instructions` field | `8b253fc` |
| Phase 2C: Guardrail language in create_*_osm descriptions | `8b253fc` |
| Phase 2D: Strengthen list_skills/get_skill descriptions | `8b253fc` |
| Phase 2E: Debug checklist (Docker verification) | All green |
| Phase 3: Troubleshoot skill | `8b253fc` |
| EUI unit fix: report MJ/m2 + kBtu/ft2 | `77818fa` |
| conditioned_floor_area_m2: compute from model | `f537294` |
| run_qaqc_checks: clear error + hint when no run_id | `f537294` |
| get_run_artifacts: filesystem fallback for measure runs | `eb9f429` |
| report_path + report_size_bytes in viewer responses | `eb9f429` |
| user_message in copy_run_artifact + viewer responses | pending |
| End-to-end test #1 (claude.ai) | Passed |
| End-to-end test #2 (claude.ai) | Passed — all fixes verified |

## Resolved Issues

- `create_baseline_osm` intermittent `model_loaded` — confirmed working in both test sessions, stale from pre-v0.4.0

## Remaining Nice-to-Haves

2. **Token count measurement** — measure SKILL.md chars before vs after dedup (~20% est.)
3. **`check_tool_coverage` tool** — deferred, guardrails working in testing
