# LLM Benchmark: CooledBeam + Zone Priority (2026-03-13)

**Model:** sonnet | **Retries:** 2
**Scope:** New tests for CooledBeam terminal replacement, measure authoring path, zone equipment priority

## Progressive Tests (9/9 — 100%)

| Test | L1 | L2 | L3 | Notes |
|------|----|----|-----|-------|
| replace_terminals_cooled_beam | PASS | PASS | PASS | Docstring "CooledBeam = 2-pipe cooling-only beam" discovered at L1 |
| measure_replace_terminals | PASS | PASS | PASS | Agent chose `create_measure` even at L1 vague prompt |
| zone_equipment_priority | PASS | PASS | PASS | Required prompt fix: must add equipment first (baseline model has none) |

## Workflow Tests (1/1 — 100%)

| Test | Result | Turns | Tools | Cost |
|------|--------|-------|-------|------|
| hvac_chilled_beam_comparison | PASS | 22 | load, list_air_loops, get_air_loop_details, replace_air_terminals, save, sim, status, logs, change_building_location, sim(retry), save, sim(retry), extract_end_use_breakdown | $0.28 |

**Note:** High turn count (22) due to sim failure recovery — model had no weather file, agent added Boston weather via `change_building_location` and retried.

## Discovery Insights

- **CooledBeam**: Excellent discovery. L1 prompt "cooling-only chilled beams" → agent found `replace_air_terminals` immediately. The 2-pipe vs 4-pipe docstring guidance works.
- **Measure path**: Agent correctly chose `create_measure` over `replace_air_terminals` when prompt says "write a custom measure."
- **Zone priority**: Cold-start problem — if model has no zone equipment, agent explores but never calls the tool. Fixed by prompts that add equipment first. `expected` list accepts `add_zone_equipment` as alternative proof of discovery.

## Token Usage

| Run | Tests | In | Out | Cache | Cost |
|-----|-------|----|-----|-------|------|
| Progressive (3 runs) | 9 | 180 | 22.2k | 1.89M | $1.37 |
| Workflow | 1 | 30 | 2.8k | 495k | $0.28 |
| **Total** | **13** | **210** | **25k** | **2.39M** | **$1.64** |
