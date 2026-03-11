# Plan: List Tool Response Size Guardrails (v3) — COMPLETE

## Problem
List tools return unbounded responses. An 80-zone model produced 91K chars from
`list_thermal_zones(detailed=true)`. `list_files` returned 574 files / 230K chars.
`list_hvac_components` returned 228 items / 62K chars. All context waste.

## Design principles
1. All filtering runs server-side — zero context cost
2. Only the JSON response hits LLM context
3. **Filters are primary** — return only what's relevant to the task
4. **max_results=10 is the safety net** — LLM sees count, can filter or override
5. **Brief is always default** — name + handle + 1-2 context fields
6. Explicit tool params, not generic filter dicts — LLMs discover params better
7. Building-science defaults in docstrings teach the LLM common patterns

## Response shape (all list tools)
```json
{
  "ok": true,
  "count": 10,
  "total_available": 1345,
  "truncated": true,
  "surfaces": [... 10 items ...]
}
```
When `truncated: true`, LLM can:
- Add a filter and re-call: `list_surfaces(space_name="Office 1")` → 6 results
- Ask the user: "1345 surfaces — want to filter by space or type?"
- Override: `list_surfaces(max_results=50)`

---

## Part 1: max_results in `list_all_as_dicts()` + standalone tools

### `list_all_as_dicts()` helper
Add `max_results: int | None = None`. When set:
- Count all matching objects (for `total_available`)
- Return only first `max_results` items
- Add `truncated` and `total_available` to caller's response

### Individual tool defaults
| Tool | Default max_results | Rationale |
|------|-------------------|-----------|
| `list_surfaces` | 10 | Can be 1000+ in large models |
| `list_subsurfaces` | 10 | Can be 2000+ |
| `list_spaces` | 10 | Can be 500+ |
| `list_thermal_zones` | 10 | Can be 100+ |
| `list_people_loads` | 10 | Can be 500+ |
| `list_lighting_loads` | 10 | Can be 1000+ |
| `list_electric_equipment` | 10 | Can be 500+ |
| `list_gas_equipment` | 10 | Can be 300+ |
| `list_infiltration` | 10 | Can be 200+ |
| `list_materials` | 10 | Can be 500+ |
| `list_constructions` | 10 | Can be 200+ |
| `list_hvac_components` | 10 | Can be 200+ |
| `list_model_objects` | 10 | Can be 1000+ |
| `list_zone_hvac_equipment` | 10 | Can be 100+ |
| `list_schedule_rulesets` | 10 | Can be 300+ |
| `list_files` | 10 | Can be 10k+ |
| `list_air_loops` | None | Typically <10 |
| `list_plant_loops` | None | Typically <15 |
| `list_construction_sets` | None | Typically <20 |
| `list_building_stories` | None | Typically <10 |
| `list_space_types` | None | Typically <30 |
| `list_common_measures` | None | ~20 fixed |
| `list_comstock_measures` | None | ~60 fixed |

---

## Part 2: Filters by object type

### Tier 1 — high-count tools (fix first)

**`list_surfaces`** — most important, 80% use case is "find exterior walls"
```python
list_surfaces(
    space_name: str = None,        # filter by parent space
    surface_type: str = None,      # "Wall", "Floor", "RoofCeiling"
    boundary: str = None,          # "Outdoors", "Ground", "Surface"
    max_results: int = 10,
)
```
Docstring examples:
- Exterior walls: `surface_type="Wall", boundary="Outdoors"`
- All exterior: `boundary="Outdoors"`
- Surfaces in a space: `space_name="Office 1"`

**BUG FIX**: `list_surfaces(detailed=False)` brief mode must include
`outside_boundary_condition` — it's essential for the envelope retrofit
workflow but currently only in detailed mode. Move it to brief.

**`list_subsurfaces`**
```python
list_subsurfaces(
    surface_name: str = None,      # filter by parent surface
    space_name: str = None,        # transitive: surface→space
    subsurface_type: str = None,   # "FixedWindow", "OperableWindow", "Door", etc.
    max_results: int = 10,
)
```

**`list_model_objects`**
```python
list_model_objects(
    object_type: str,              # required (already exists)
    name_contains: str = None,     # substring match on name
    max_results: int = 10,
)
```

**`list_hvac_components`** — `category` filter already exists, add max_results
```python
list_hvac_components(
    category: str = None,          # already exists
    max_results: int = 10,
)
```

### Tier 2 — medium-count tools

**`list_spaces`**
```python
list_spaces(
    thermal_zone_name: str = None,
    building_story_name: str = None,
    space_type_name: str = None,
    max_results: int = 10,
)
```
Docstring: "Spaces on a story: `building_story_name='Floor 1'`"

**All load tools** (people, lights, electric, gas, infiltration) — same pattern:
```python
list_people_loads(
    space_name: str = None,        # filter by parent space
    space_type_name: str = None,   # filter by parent space type
    max_results: int = 10,
)
```
Docstring: "Loads in a space: `space_name='Office 1'`"

**`list_thermal_zones`**
```python
list_thermal_zones(
    air_loop_name: str = None,     # filter by parent air loop
    max_results: int = 10,
)
```
Docstring: "Zones on an air loop: `air_loop_name='DOAS'`"

**`list_zone_hvac_equipment`**
```python
list_zone_hvac_equipment(
    thermal_zone_name: str = None,
    equipment_type: str = None,    # iddObjectType filter
    max_results: int = 10,
)
```

**`list_materials`**
```python
list_materials(
    material_type: str = None,     # iddObjectType filter
    max_results: int = 10,
)
```

**`list_schedule_rulesets`**, **`list_constructions`** — just add max_results=10.

### Tier 3 — no filters needed (low count)
`list_air_loops`, `list_plant_loops`, `list_construction_sets`,
`list_building_stories`, `list_space_types` — max_results=None, no filters.

---

## Part 3: Brief mode fixes

### `list_surfaces` brief — add `outside_boundary_condition`
Currently brief returns: name, surface_type, gross_area_m2, space.
Missing `outside_boundary_condition` which the LLM needs to filter
exterior vs interior surfaces. Add it to brief. This is the #1 brief
mode bug — causes unnecessary `detailed=True` calls on large models.

### All other brief modes — already correct
Verified: spaces, thermal_zones, air_loops, plant_loops, loads, materials,
constructions, schedules all have appropriate brief fields.

---

## Part 4: `get_load_details(name)` — unified load detail tool

One tool covers all 5 load types (people, lights, electric, gas, infiltration).

```python
def get_load_details(load_name: str) -> dict:
    """Get detailed info for any load object (people, lights, electric/gas equipment, infiltration).

    Tries each load type by name until found. Returns load_type + all fields.
    """
    model = get_model()
    for type_name, getter_name, extract_fn in LOAD_TYPES:
        obj = fetch_object(model, type_name, name=load_name)
        if obj is not None:
            return {"ok": True, "load_type": type_name, "load": extract_fn(model, obj)}
    return {"ok": False, "error": f"Load '{load_name}' not found"}
```

`LOAD_TYPES` dispatcher:
```python
LOAD_TYPES = [
    ("People", "getPeopleByName", _extract_people),
    ("Lights", "getLightsByName", _extract_lights),
    ("ElectricEquipment", "getElectricEquipmentByName", _extract_electric_equipment),
    ("GasEquipment", "getGasEquipmentByName", _extract_gas_equipment),
    ("SpaceInfiltrationDesignFlowRate", "getSpaceInfiltrationDesignFlowRateByName", _extract_infiltration),
]
```

Also add `get_construction_details(name)` — returns layer details for one construction.

---

## Part 5: Response size test

`tests/test_response_sizes.py`:
- Create baseline model (10 zones, ~60 surfaces, air loops, plant loops, loads)
- Call every list_* tool with DEFAULT params (no filters, default max_results)
- Assert `len(json.dumps(result)) < 10_000` per tool
- With max_results=10 and brief defaults, each response should be well under 10K
- Also test: unfiltered call shows `truncated: true` when model exceeds max_results
- Also test: filtered call returns correct subset

---

## Implementation order

### Batch 1 — max_results (safety net, biggest impact)
1. Add `max_results` + `total_available` + `truncated` to `list_all_as_dicts()`
2. Wire max_results=10 default into all tier 1+2 tool registrations
3. Add max_results to standalone tools (list_files, list_model_objects, list_hvac_components)
4. Response size test

### Batch 2 — tier 1 filters
5. `list_surfaces` — space_name, surface_type, boundary + fix brief mode
6. `list_subsurfaces` — surface_name, space_name, subsurface_type
7. `list_model_objects` — name_contains

### Batch 3 — tier 2 filters
8. `list_spaces` — thermal_zone_name, building_story_name, space_type_name
9. All 5 load tools — space_name, space_type_name
10. `list_thermal_zones` — air_loop_name
11. `list_zone_hvac_equipment` — thermal_zone_name, equipment_type

### Batch 4 — missing detail tools
12. `get_load_details(name)` — unified dispatcher
13. `get_construction_details(name)`

### Batch 5 — docstring examples
14. Add "Common filters:" examples to every filtered tool's docstring

## Estimated impact
- Default list call: ~500 chars (10 items x ~50 chars brief) vs current ~50K-200K
- 100-1000x context reduction on large models
- No functionality loss — filters + override get any data needed

## Questions
- max_results=10: right number? could also be 20 — balance between "enough to
  see patterns" and "small enough to not waste context"
- Should `list_all_as_dicts` sort before or after truncation? Before makes the
  first 10 alphabetically stable. After would need a sort param.
