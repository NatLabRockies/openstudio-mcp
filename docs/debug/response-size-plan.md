# Plan: Response Size Guardrails

## Problem
List tools return unbounded responses. A 80-zone model produced 91K chars from
`list_thermal_zones(detailed=true)`. `list_files` returned 574 files / 230K chars.
Burns LLM context and degrades agent performance.

## Approach: `max_results` with truncation warning

### 1. Add `max_results` to `list_all_as_dicts()` helper
- Default: `None` (no limit) for backward compat
- When truncated, return `"truncated": true, "total_available": N`
- Every tool that uses this helper gets the param for free

### 2. Add `max_results` to standalone list tools
These don't use `list_all_as_dicts`:
- `list_files` — already has `max_depth`, add `max_results`
- `list_model_objects` — own iteration loop
- `list_hvac_components` — iterates COMPONENT_TYPES
- `list_common_measures` / `list_comstock_measures` — filesystem scan

### 3. Response size integration test
Create `tests/test_response_sizes.py`:
- Create baseline model (10 zones, surfaces, air loops, plant loops)
- Call every list_* tool
- Assert `len(json.dumps(result)) < 50_000` (50K char budget)
- Catches regressions + new tools that forget limits

### 4. Detailed-mode field audit
Some `_extract_*` functions include nested arrays in detailed mode:
- `_extract_air_loop` detailed: `thermal_zones[]`, `supply_components[]`,
  `detailed_components{}`, `setpoint_managers[]` — worst offender
- `_extract_plant_loop` detailed: `supply_components[]`, `demand_components[]`
- `_extract_construction`: `layers[]`

Options:
- a) Move nested arrays to `get_*_details` only (not list)
- b) Cap nested arrays at 5 items + truncation flag
- c) Add `fields` param to control which nested data is included

Recommend (a) — simplest, matches existing `detailed=True/False` pattern.

## Tools by risk tier

### Tier 1 — high risk, fix first
| Tool | Max items | Nested? |
|------|-----------|---------|
| list_files | 10k+ | no |
| list_surfaces | 1000+ | no |
| list_subsurfaces | 2000+ | no |
| list_air_loops (detailed) | 10 but huge per-item | YES |
| list_model_objects | 1000+ | no |
| list_hvac_components | 200+ | no |

### Tier 2 — medium risk
| Tool | Max items | Nested? |
|------|-----------|---------|
| list_spaces | 500+ | no |
| list_thermal_zones | 100+ | no |
| list_materials | 500+ | no |
| list_constructions | 200+ | layers[] |
| list_people_loads | 500+ | no |
| list_lighting_loads | 1000+ | no |
| list_electric_equipment | 500+ | no |
| list_schedule_rulesets | 300+ | no |

### Tier 3 — low risk (small counts or already bounded)
| Tool | Notes |
|------|-------|
| list_plant_loops | typically <15, components truncated at 10 |
| list_zone_hvac_equipment | 3 fields/item |
| list_construction_sets | typically <20 |
| list_gas_equipment | typically <100 |
| list_infiltration | typically <200 |
| list_building_stories | typically <50 |
| list_space_types | typically <100 |
| list_common_measures | ~20 fixed |
| list_comstock_measures | ~60 fixed |
| read_file | 400KB limit exists |
| query_timeseries | 10k point limit exists |

## Implementation order
1. `list_all_as_dicts` — add `max_results` param
2. Standalone list tools — add `max_results`
3. Response size test
4. Nested array cleanup (tier 1 tools)

## Unresolved
- Default `max_results` value? 200? 500? Or leave None and rely on LLM guidance?
- Should `list_files` default `max_depth=2` instead of unlimited?
- Worth adding `offset` for pagination, or just `max_results` + "use get_*_details"?
