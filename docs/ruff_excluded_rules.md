# Ruff Rules Excluded: PLR and N

Why `PLR` (pylint-refactor) and `N` (pep8-naming) are intentionally excluded
from this project's ruff config.

## N (pep8-naming)

Enforces Python naming conventions: `CamelCase` classes, `snake_case`
functions/variables, `UPPER_CASE` constants.

**Conflict: OpenStudio SDK is camelCase.** Nearly every file in `mcp_server/`
calls OpenStudio SWIG bindings which use camelCase method names:

```python
# SDK methods are camelCase -- not our choice
model.getSpaces()
zone.thermalZone()
surface.nameString()
loop.supplyComponents()
material.thermalResistance()
```

Variables that hold SDK return values naturally mirror this:

```python
airLoopHVAC = model.getAirLoopHVACs()[0]  # N806: variable should be lowercase
oaSystem = loop.airLoopHVACOutdoorAirSystem()  # N806
```

Extractor functions return dicts keyed to match SDK attribute names for
consistency:

```python
result["thermalResistance"] = material.thermalResistance()
```

**Scope of suppression:** ~40+ files touch the SDK. Suppressing `N` per-file
would cover nearly the entire codebase, making the rule effectively disabled
anyway but with extra noise in the config.

**What we do instead:** Follow Python naming for our own code (function names,
module names, classes). SDK-interface code inherits SDK naming by necessity.

## PLR (pylint-refactor)

Complexity and structure checks. The specific sub-rules and why they conflict:

### PLR0911 — too-many-return-statements

Our operations.py functions use early-return validation chains by design:

```python
def some_operation(name: str, value: int) -> dict:
    model = get_model()              # return if no model
    obj = fetch_object(model, name)  # return if not found
    if value < 0:                    # return if invalid
        return {"ok": False, "error": "negative value"}
    # ... actual work ...
    return {"ok": True, ...}
```

This pattern (from CLAUDE.md rule #4: "operations return dicts with ok/False,
never raise through MCP") inherently produces 4-8 return statements per
function. Refactoring to reduce returns would mean nested if/else or exceptions
-- both worse for this codebase.

### PLR0912 — too-many-branches

ASHRAE baseline HVAC has 10 system types, each with different wiring logic.
`add_baseline_system()` dispatches on system number with a 10-branch if/elif.
This is the domain, not accidental complexity.

### PLR0913 / PLR0917 — too-many-arguments

Public API functions have many parameters because the domain requires them:

- `add_baseline_system(system_number, thermal_zone_names, heating_fuel,
  cooling_fuel, economizer, ...)` -- 8 params
- `query_timeseries(sql_path, variable_name, key_value, start_month,
  start_day, end_month, end_day, frequency, max_points)` -- 9 params
- `add_doas_system(thermal_zone_names, energy_recovery, ventilation_system,
  terminal_type, ...)` -- 7 params

These are MCP tool interfaces. Splitting into config objects would add
abstraction without reducing actual complexity, and would break the flat
dict-in/dict-out pattern that makes tools LLM-friendly.

### PLR0915 — too-many-statements

HVAC wiring functions (`_build_sys1()` through `_build_sys10()`) are 50-80
statements each. They create OpenStudio objects, set properties, and wire
components together in sequence. Each statement is a distinct SDK call that
can't be meaningfully abstracted without losing explicitness (CLAUDE.md: "every
OpenStudio API method must be called directly so it's grepable").

### PLR2004 — magic-value-comparison

ASHRAE system numbers (1-10) are the domain vocabulary:

```python
if system_number == 3:  # PLR2004: magic value
    # System 3: PSZ-AC (Packaged Single Zone Air Conditioner)
```

These aren't magic numbers -- they're ASHRAE 90.1 Appendix G standard
identifiers that every building energy modeler recognizes. Extracting them to
named constants would reduce readability for domain experts.

**Note:** The `add-linters` branch also ignores `PLR2004` globally and
`PLR0913` in tests, confirming these are recognized as false positives for
this codebase.

## Summary

| Rule | Why excluded | Alternative |
|------|-------------|-------------|
| `N` | SDK is camelCase; ~40 files affected | Follow Python naming for our own code |
| `PLR0911` | Early-return validation is the pattern | Keep flat guard clauses |
| `PLR0912` | 10 ASHRAE system types = 10 branches | Domain complexity |
| `PLR0913` | MCP tools need many params | Flat dict-in/dict-out |
| `PLR0915` | HVAC wiring is inherently long | Explicit > abstract |
| `PLR2004` | ASHRAE system numbers are domain terms | Not magic |
