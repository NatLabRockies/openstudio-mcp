# Plan: CooledBeam + ChilledBeam Terminals + Zone Priority Tool

## Context
Energy modelers want AI agents to handle complex HVAC modifications like "replace
air terminals with chilled beams, make them primary." Two discovery paths must work:
1. **Tool path**: `replace_air_terminals(terminal_type="CooledBeam")` — fast, one call
2. **Measure path**: `create_measure` with Ruby code — flexible, custom logic

Both paths fail today. Additionally, no tool exists to reorder zone equipment priority.

### Naming Convention
- **CooledBeam** = 2-pipe, cooling-only (SDK: `AirTerminalSingleDuctConstantVolumeCooledBeam`)
- **FourPipeBeam** = 4-pipe, heating+cooling (already exists in tools, keep as-is)

### 2-Pipe vs 4-Pipe Guidance (for docstrings)
| Aspect | CooledBeam (2-pipe) | FourPipeBeam (4-pipe) |
|--------|--------------------|-----------------------|
| Coils | `CoilCoolingCooledBeam` only | `CoilCoolingFourPipeBeam` + `CoilHeatingFourPipeBeam` |
| Plant loops | CHW only | CHW + HW |
| Heating? | No — DOAS preheat handles it | Yes — beam provides zone heating |
| Best for | Cooling-dominated, interior zones | Cold climates, perimeter zones |

Both are **air terminals** via `air_loop.addBranchForZone()`, NOT zone equipment.

## Changes

### 1. Add CooledBeam to `replace_air_terminals`

**`mcp_server/skills/hvac_systems/air_terminals.py`**
- Add `_create_cooled_beam_terminal()` after `_create_four_pipe_beam_terminal()`
  - Cooling-only: CHW loop, no HW
  - `CoilCoolingCooledBeam` + `AirTerminalSingleDuctConstantVolumeCooledBeam(model, schedule, coil)`
- In `replace_terminals()`: add `elif "CooledBeam"` branch
- In `creators` dict: add `"CooledBeam"` entry

**`mcp_server/skills/hvac_systems/operations.py`**
- Add `"CooledBeam"` to `valid_types` in both replace functions

**`mcp_server/skills/hvac_systems/tools.py`**
- Update docstrings with CooledBeam + 2-pipe vs 4-pipe guidance

### 2. Add `set_zone_equipment_priority` Tool

SDK exposes direct priority methods on `ZoneHVACEquipmentList`:
- `model.getZoneHVACEquipmentLists` → list of `ZoneHVACEquipmentList` objects
- `equip_list.equipment` → vector of ModelObjects
- `equip_list.coolingPriority(equip)` / `equip_list.heatingPriority(equip)` — get
- `equip_list.setCoolingPriority(equip, n)` / `equip_list.setHeatingPriority(equip, n)` — set

**`mcp_server/skills/loop_operations/operations.py`** — `set_zone_equipment_priority()`
**`mcp_server/skills/loop_operations/tools.py`** — MCP registration
**`tests/test_skill_registration.py`** — add to EXPECTED_TOOLS

### 3. Improve `create_measure` Docstring for HVAC Measure Path

**`mcp_server/skills/measure_authoring/tools.py`**
- Add air terminal SDK patterns (CooledBeam, FourPipeBeam constructors)
- WARNING that beams are air terminals, not zone equipment
- Plant loop wiring and zone equipment priority patterns

### 4. Integration Tests

**`tests/test_replace_air_terminals.py`** — 2 tests:
- `test_replace_to_cooled_beam` — DOAS+FanCoil → CooledBeam → verify
- `test_replace_cooled_beam_no_chw` — System 3 (no CHW) → expect error

**`tests/test_loop_operations.py`** — 1 test:
- `test_set_zone_equipment_priority` — add 2 baseboards → reorder → verify

### 5. LLM Tests

**`tests/llm/test_06_progressive.py`** — 3 progressive cases (9 tests):
- `replace_terminals_cooled_beam` — tool path
- `measure_replace_terminals` — measure path
- `zone_equipment_priority` — priority reorder

**`tests/llm/test_04_workflows.py`** — 1 workflow case:
- `hvac_chilled_beam_comparison` — load → replace → save → sim → extract

### 6. CLAUDE.md + SKILL.md Updates

- CLAUDE.md: add `set_zone_equipment_priority` to loop_operations, update tool count to 134
- SKILL.md (hvac_systems): add CooledBeam to terminal types table

## Status: COMPLETE

All integration tests passing (3/3). All LLM tests passing (13/13).

### LLM Test Results

**Progressive (9/9):**
- `replace_terminals_cooled_beam` — 3/3 (L1/L2/L3), first attempt. Docstring keywords work well.
- `measure_replace_terminals` — 3/3 (L1/L2/L3), first attempt. Agent correctly chose `create_measure`.
- `zone_equipment_priority` — 3/3 after prompt fix. Original prompts referenced equipment not on the baseline model. Fixed by having prompts add equipment first.

**Workflow (1/1):**
- `hvac_chilled_beam_comparison` — passed, 22 turns. Agent recovered from missing weather file (added `change_building_location` mid-workflow).

### Lessons
- New tools with niche names have cold-start discovery problems if the model lacks matching objects. Prompts must ensure the model state supports the tool.
- `set_zone_equipment_priority` requires ALL equipment in `ZoneHVACEquipmentList` (includes air terminals), not just zone HVAC equipment. Test accounts for this.
