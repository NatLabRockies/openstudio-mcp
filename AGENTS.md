# AGENTS.md — Codex CLI Instructions

## Project
OpenStudio MCP server — 22 skills, 126 tools, ~14K prod lines.

## Architecture
- `mcp_server/skills/<name>/tools.py` — MCP tool defs, calls operations
- `mcp_server/skills/<name>/operations.py` — business logic, returns `{"ok": True/False, ...}`
- `mcp_server/model_manager.py` — singleton model state (`get_model()`, `load_model()`, `save_model()`)
- `mcp_server/osm_helpers.py` — shared helpers (`fetch_object()`, `optional_name()`, `list_all_as_dicts()`)

## Conventions
- Operations never raise through MCP — return `{"ok": False, "error": "..."}`
- All OpenStudio optionals checked with `is_initialized()` before access
- `_extract_*` functions return dicts with `snake_case` keys
- No `getattr()` for OpenStudio API calls — every method must be explicit
- No `shell=True` in subprocess calls
- Tool functions use `_tool` suffix internally, MCP name strips it

## Review Focus
When reviewing code, check for:
1. **Error handling** — bare `except Exception: pass`, swallowed errors, missing error context
2. **is_initialized()** — OpenStudio optionals accessed without checking `.is_initialized()`
3. **Dead code** — unused imports, unreachable branches, commented-out code
4. **Type safety** — implicit string-to-number coercion, unvalidated inputs
5. **Security** — path traversal in file ops, f-string SQL, unsanitized user input
6. **Consistency** — return shape mismatches between similar tools, naming drift
7. **Resource leaks** — unclosed files, temp dirs not cleaned up

## OpenStudio SDK Behavior (important for reviewers)

These SDK behaviors are intentional — do NOT flag them as bugs:

- **No transactional rollback.** Once an object is created in the model via SWIG
  bindings, it exists permanently. Create-then-validate is the standard pattern.
  "Should rollback on failure" is not actionable — the SDK doesn't support it.
- **`.get()` on optionals** is safe when the preceding API call guarantees a result
  for valid inputs (e.g., `Space.fromFloorPrint()` with a valid polygon). Only flag
  `.get()` when the input is user-supplied and could legitimately be invalid.
- **Plant loops without source equipment** are intentional scaffolds. Users add
  boilers/chillers afterward via `add_supply_equipment`. DOAS and radiant templates
  create the loop structure; source equipment is a separate step.
- **OpenStudio setters validate inputs** and throw `RuntimeError` on bad values.
  The outer `except RuntimeError` in operations already catches these. Missing
  pre-validation is LOW severity (nice-to-have), not HIGH.
- **`except Exception: pass` in extractors** is often intentional — OpenStudio
  objects may lack optional attributes depending on version or object type. Flag
  only when the exception would hide a real bug vs. a legitimately missing field.
- **DistrictHeating/DistrictCooling** fuel options are documented as future work.
  Silent fallback to default fuel is known, not a current bug.

## Output Format
Use `docs/review_schema.json` for structured findings.
Severity: critical > high > medium > low.
Always include a reason — not just "bad practice" but why it matters here.
