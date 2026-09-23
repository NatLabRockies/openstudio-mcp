# Copilot code review — openstudio-mcp

Condensed from `AGENTS.md` (full rules there). Copilot code review reads only the first
~4,000 characters of this file; keep it short.

## Project
MCP server exposing 150+ building-energy-modeling tools backed by the OpenStudio SDK
Python bindings. `mcp_server/skills/<name>/tools.py` = MCP tool defs; `operations.py` =
business logic returning plain dicts.

## Rules to enforce
- Operations never raise through MCP: return `{"ok": False, "error": "..."}`
- OpenStudio optionals checked with `.is_initialized()` before `.get()`
- No `getattr()` or string-based dispatch for OpenStudio API calls
- No `shell=True` in subprocess calls
- `list[str]` tool params typed `list[str] | str` + `parse_str_list()`
- Per-user data under `user_run_root()`/`user_measures_root()`; path args validated via `is_path_allowed()`
- Every new/changed MCP tool, bug fix or security fix has a test; tests carry a
  `# Regression:` or `# Validates:` comment, assert exact values, and integration tests mock nothing
- New integration test files are added to a shard in `.github/workflows/ci.yml`
- No hardcoded tool counts; roster lives in `EXPECTED_TOOLS`

## Review focus
Swallowed errors, missing `is_initialized()`, dead code, unvalidated input / type coercion,
path traversal, f-string SQL, return-shape drift between similar tools, resource leaks.
Give severity (critical > high > medium > low) and why it matters here.

## Do NOT flag (intentional SDK behavior)
- No rollback after a failed step: the SDK has no transactions; create-then-validate is standard
- `.get()` right after an API call that guarantees a result for valid input
- Plant loops without source equipment (scaffolds; equipment added later)
- Missing pre-validation before OpenStudio setters (they raise `RuntimeError`, caught upstream): LOW at most
- `except Exception: pass` in `_extract_*` for optional attributes, unless it hides a real bug
- DistrictHeating/DistrictCooling fuel fallback (documented future work)
