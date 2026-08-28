"""Parse eval.md files into machine-checkable Tier 1 test cases.

Each eval.md has two tables:

  ## Should trigger
  | Query | Expected tools | Critical params |
    Expected tools: comma- or OR-separated MCP registry names. Annotations
    "(x2)" / "x2" are stripped. Wildcards and prose are format errors.
    Critical params grammar (one comma-separated item each):
      —  or empty        no assertion
      name               param must be present on a matched call
      name present       same as bare name
      name=value         param must equal value (quotes optional; numeric
                         values compare numerically)
    A critical assertion applies to called tools that are BOTH in the row's
    expected list AND have that parameter in their schema.

  ## Should NOT trigger
  | Query | Forbidden tools | Expected alternatives |
    Forbidden tools: registry names the agent must NOT call.
    Expected alternatives: registry names; at least one must be called.
    (The old "| Query | Why |" format is prose-only and unassertable — it is
    reported as a format error.)

parse_eval_files() returns cases plus format errors; the unit validator in
tests/test_skill_docs.py asserts there are no format errors, so eval content
that drifts from this grammar fails CI instead of being silently skipped.
"""
from __future__ import annotations

import ast as _ast
import contextlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / ".claude" / "skills"

_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_NO_ASSERT = {"", "—", "-", "–"}  # noqa: RUF001 — em/en dash cells mean "no assertion"

NEGATIVE_HEADER = ["query", "forbidden tools", "expected alternatives"]


@dataclass(frozen=True)
class CriticalParam:
    param: str
    op: str            # "present" | "equals"
    value: str | None  # only for "equals"


# ---------------------------------------------------------------------------
# Markdown table parsing
# ---------------------------------------------------------------------------

def _parse_table(text: str) -> tuple[list[str], list[list[str]]]:
    """First markdown table in `text` -> (header_cells, data_rows)."""
    header: list[str] = []
    rows: list[list[str]] = []
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if cells and all(re.match(r"^:?-+:?$", c) for c in cells):
            continue  # separator row
        if not header:
            header = cells
            continue
        if cells:
            rows.append(cells)
    return header, rows


def _section(text: str, title_re: str) -> str | None:
    m = re.search(
        rf"##\s*{title_re}\s*\n(.*?)(?=\n##|\Z)", text,
        re.DOTALL | re.IGNORECASE,
    )
    return m.group(1) if m else None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _parse_tool_list(cell: str, where: str, errors: list[str]) -> list[str]:
    cell = re.sub(r"\(x\d+\)", "", cell)
    cell = re.sub(r"\bx\d+\b", "", cell)
    tools: list[str] = []
    for part in re.split(r",|\bOR\b", cell):
        t = part.strip()
        if not t:
            continue
        if not _TOOL_NAME_RE.match(t) or "_" not in t:
            errors.append(f"{where}: unparseable tool name '{t}' — use exact "
                          f"MCP registry names (no wildcards, no prose)")
            continue
        tools.append(t)
    return tools


def parse_critical_params(
    cell: str, where: str = "", errors: list[str] | None = None,
) -> list[CriticalParam]:
    """Parse one Critical params cell under the documented grammar."""
    errors = errors if errors is not None else []
    cell = cell.strip()
    if cell in _NO_ASSERT:
        return []
    out: list[CriticalParam] = []
    for raw_item in cell.split(","):
        item = raw_item.strip()
        if not item:
            continue
        m = re.match(r"^([a-z_][a-z0-9_]*)\s*=\s*(.+)$", item)
        if m:
            out.append(CriticalParam(m.group(1), "equals",
                                     _strip_quotes(m.group(2))))
            continue
        m = re.match(r"^([a-z_][a-z0-9_]*)(\s+present)?$", item)
        if m:
            out.append(CriticalParam(m.group(1), "present", None))
            continue
        errors.append(f"{where}: unparseable critical param '{item}' — "
                      f"grammar is 'name', 'name present', or 'name=value'")
    return out


# ---------------------------------------------------------------------------
# eval.md loading
# ---------------------------------------------------------------------------

def parse_eval_files(skills_dir: Path | None = None) -> dict:
    """Parse every eval.md -> {"cases": [...], "negative_cases": [...],
    "errors": [...]}.

    Rows with format errors are excluded from cases and reported in errors.
    """
    skills_dir = skills_dir or SKILLS_DIR
    cases: list[dict] = []
    negative: list[dict] = []
    errors: list[str] = []

    for eval_md in sorted(skills_dir.rglob("eval.md")):
        skill = eval_md.parent.name
        text = eval_md.read_text(encoding="utf-8")

        pos = _section(text, r"Should\s+trigger")
        if pos:
            _header, rows = _parse_table(pos)
            for i, row in enumerate(rows, 1):
                where = f"{skill}/eval.md should-trigger row {i}"
                if len(row) < 3:
                    errors.append(f"{where}: expected 3 columns "
                                  f"(Query | Expected tools | Critical params)")
                    continue
                row_errors: list[str] = []
                tools = _parse_tool_list(row[1], where, row_errors)
                criticals = parse_critical_params(row[2], where, row_errors)
                errors.extend(row_errors)
                prompt = _strip_quotes(row[0])
                if prompt and tools and not row_errors:
                    cases.append({
                        "prompt": prompt,
                        "expected_tools": tools,
                        "critical_params": criticals,
                        "skill": skill,
                    })

        neg = _section(text, r"Should\s+NOT\s+trigger")
        if neg is None:
            continue
        header, rows = _parse_table(neg)
        if [h.lower() for h in header] != NEGATIVE_HEADER:
            errors.append(
                f"{skill}/eval.md: 'Should NOT trigger' table header is "
                f"{header} — prose-only negatives are unassertable; use "
                f"| Query | Forbidden tools | Expected alternatives |",
            )
            continue
        for i, row in enumerate(rows, 1):
            where = f"{skill}/eval.md should-NOT-trigger row {i}"
            if len(row) < 3:
                errors.append(f"{where}: expected 3 columns")
                continue
            row_errors = []
            forbidden = _parse_tool_list(row[1], where, row_errors)
            alternatives = _parse_tool_list(row[2], where, row_errors)
            errors.extend(row_errors)
            if not forbidden:
                errors.append(f"{where}: no forbidden tools declared")
            if not alternatives:
                errors.append(f"{where}: no expected alternatives declared")
            prompt = _strip_quotes(row[0])
            if prompt and forbidden and alternatives and not row_errors:
                negative.append({
                    "prompt": prompt,
                    "forbidden_tools": forbidden,
                    "alternatives": alternatives,
                    "skill": skill,
                })

    return {"cases": cases, "negative_cases": negative, "errors": errors}


def load_should_trigger() -> list[dict]:
    """Positive cases: {"prompt", "expected_tools", "critical_params", "skill"}."""
    return parse_eval_files()["cases"]


def load_should_not_trigger() -> list[dict]:
    """Negative cases: {"prompt", "forbidden_tools", "alternatives", "skill"}."""
    return parse_eval_files()["negative_cases"]


# ---------------------------------------------------------------------------
# Normalized call representation (direct + CodeMode)
# ---------------------------------------------------------------------------

_CODE_MODE_META = frozenset({"search", "get_schema", "execute"})
_MCP_PREFIX = "mcp__openstudio__"
_CALL_TOOL_RE = re.compile(r"call_tool\(\s*[\"'](\w+)[\"']\s*,?\s*")


def _balanced_braces(code: str, start: int) -> str | None:
    if start >= len(code) or code[start] != "{":
        return None
    depth = 0
    quote: str | None = None
    for i in range(start, len(code)):
        ch = code[i]
        if quote:
            if ch == "\\":
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return code[start : i + 1]
    return None


def _quote_bare_keys(t: str) -> str:
    """JS-ish object -> JSON: quote bare keys."""
    return re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', t)


def _parse_args_object(text: str | None) -> dict:
    """Best-effort parse of a call_tool args object (JSON / Python / JS-ish)."""
    if not text:
        return {}
    for attempt in (
        json.loads,
        _ast.literal_eval,
        lambda t: json.loads(_quote_bare_keys(t)),
    ):
        with contextlib.suppress(Exception):
            obj = attempt(text)
            if isinstance(obj, dict):
                return obj
    return {}


def calls_from_code(code: str) -> list[dict]:
    """Extract call_tool("name", {...}) invocations from a CodeMode block."""
    calls = []
    for m in _CALL_TOOL_RE.finditer(code):
        args_text = _balanced_braces(code, m.end())
        calls.append({"tool": m.group(1), "input": _parse_args_object(args_text)})
    return calls


def normalize_calls(result_or_calls) -> list[dict]:
    """Uniform [{"tool", "input"}] from an AgentResult or raw tool-call list.

    Direct MCP calls keep their input dicts; CodeMode execute blocks are
    expanded into the tools they invoke (inputs parsed best-effort).
    """
    raw = (result_or_calls if isinstance(result_or_calls, list)
           else result_or_calls.mcp_tool_calls)
    calls: list[dict] = []
    for c in raw:
        name = c["tool"].removeprefix(_MCP_PREFIX)
        if name in _CODE_MODE_META:
            if name == "execute":
                calls.extend(calls_from_code(c["input"].get("code", "")))
            continue
        calls.append({"tool": name, "input": c.get("input") or {}})
    return calls


# ---------------------------------------------------------------------------
# Critical-param matcher
# ---------------------------------------------------------------------------

def _values_equal(actual, expected: str) -> bool:
    if isinstance(actual, bool) and expected.lower() in ("true", "false"):
        return actual == (expected.lower() == "true")
    try:
        return float(actual) == float(expected)
    except (TypeError, ValueError):
        return str(actual) == expected


def check_critical_params(
    criticals: list[CriticalParam],
    expected_tools: list[str],
    calls: list[dict],
    registry: dict[str, set[str] | frozenset[str] | tuple],
) -> list[str]:
    """Return failure strings for unmet critical-param assertions.

    For each assertion, candidate calls are those whose tool is in the row's
    expected list AND whose schema contains the parameter. Any candidate
    satisfying the assertion passes it.
    """
    failures: list[str] = []
    for crit in criticals:
        candidates = [
            c for c in calls
            if c["tool"] in expected_tools
            and crit.param in registry.get(c["tool"], ())
        ]
        if not candidates:
            failures.append(
                f"no call to an expected tool carrying '{crit.param}' "
                f"(expected tools: {expected_tools})",
            )
            continue
        if crit.op == "present":
            if not any(crit.param in c["input"] for c in candidates):
                failures.append(
                    f"'{crit.param}' missing from inputs of "
                    f"{sorted({c['tool'] for c in candidates})}",
                )
        else:
            if not any(
                crit.param in c["input"]
                and _values_equal(c["input"][crit.param], crit.value)
                for c in candidates
            ):
                got = [
                    f"{c['tool']}({crit.param}={c['input'].get(crit.param)!r})"
                    for c in candidates
                ]
                failures.append(
                    f"'{crit.param}' != {crit.value!r} on every candidate: {got}",
                )
    return failures
