"""AST-derived MCP tool contracts + served-doc call extraction/validation.

Pure stdlib (ast/re/pathlib) — never imports mcp_server, so unit tests built
on this module cannot transitively import OpenStudio (plan finding E2).

Three capabilities:
  1. load_tool_registry() — AST-parse every mcp_server/skills/*/tools.py and
     return {mcp_name: ToolSig} with param names, required params, and tags.
  2. extract_calls(text) — find tool-style calls in served markdown/prompt
     text (fenced blocks included; ruby/python measure-body fences skipped;
     quoted strings never fabricate kwargs).
  3. validate_doc_calls(calls, registry) — flag unknown tools, unknown
     kwargs, bare-identifier positional args, and missing required args.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_SRC = REPO_ROOT / "mcp_server" / "skills"
SERVED_SKILLS_DIR = REPO_ROOT / ".claude" / "skills"


# ---------------------------------------------------------------------------
# 1. Tool registry from AST
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolSig:
    name: str                  # MCP-visible name from @mcp.tool(name=...)
    package: str               # owning mcp_server/skills/<package>
    params: tuple[str, ...]    # all parameter names, in order
    required: frozenset[str]   # parameters without defaults
    tags: frozenset[str]


def parse_tools_source(src: str, package: str) -> list[ToolSig]:
    """Extract ToolSigs from one tools.py source string (no import)."""
    sigs: list[ToolSig] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "tool"
            ):
                continue
            name = None
            tags: set[str] = set()
            for kw in dec.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    name = kw.value.value
                if kw.arg == "tags" and isinstance(kw.value, ast.Set):
                    tags = {
                        e.value for e in kw.value.elts
                        if isinstance(e, ast.Constant)
                    }
            if name is None:
                raise ValueError(
                    f"{package}/tools.py: @mcp.tool on {node.name} has no "
                    f"literal name= kwarg — MCP name must be explicit",
                )
            args = node.args
            params = [a.arg for a in (*args.posonlyargs, *args.args)]
            required = set(params[: len(params) - len(args.defaults)])
            for a, default in zip(args.kwonlyargs, args.kw_defaults):
                params.append(a.arg)
                if default is None:
                    required.add(a.arg)
            sigs.append(
                ToolSig(name, package, tuple(params),
                        frozenset(required), frozenset(tags)),
            )
    return sigs


def load_tool_registry() -> dict[str, ToolSig]:
    """Registry of every MCP tool, AST-parsed from mcp_server/skills."""
    registry: dict[str, ToolSig] = {}
    for tools_py in sorted(SKILLS_SRC.glob("*/tools.py")):
        for sig in parse_tools_source(
            tools_py.read_text(encoding="utf-8"), tools_py.parent.name,
        ):
            if sig.name in registry:
                raise ValueError(
                    f"duplicate MCP tool name '{sig.name}' "
                    f"({registry[sig.name].package} and {sig.package})",
                )
            registry[sig.name] = sig
    return registry


# ---------------------------------------------------------------------------
# 2. Call extraction from served text
# ---------------------------------------------------------------------------

@dataclass
class DocCall:
    name: str
    kwargs: dict[str, str]     # kwarg name -> raw value text
    positional: list[str]      # raw positional arg texts
    elided: bool               # a bare `...` appears among top-level args
    line: int
    context: str               # doc label, e.g. "simulate/SKILL.md"


# Fenced blocks whose language is a measure-body sample, not tool calls
_FENCE_RE = re.compile(r"```([^\n`]*)\n.*?```", re.DOTALL)
_SKIP_LANGS = {"ruby", "rb", "python", "py"}
# snake_case-with-underscore callee not preceded by `.` (excludes method calls)
_CALL_START = re.compile(r"(?<![\w.])([a-z][a-z0-9_]*_[a-z0-9_]*)\s*\(")
_BARE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_KWARG_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)\s*(.*)$", re.DOTALL)

_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = set(_OPEN.values())
_MAX_CALL_CHARS = 4000


def _scan_call_args(text: str, open_paren: int) -> tuple[str, int] | None:
    """Parse a call starting at `open_paren` -> (args_text, end_index), or None.

    Quote-aware ('...' and "..."), nesting-aware, and drops unquoted
    `#`-to-EOL comments from the returned args so Ruby interpolation inside
    strings survives while trailing code comments cannot corrupt the parse.
    """
    depth = 0
    quote: str | None = None
    buf: list[str] = []
    i = open_paren
    end = min(len(text), open_paren + _MAX_CALL_CHARS)
    while i < end:
        ch = text[i]
        if quote:
            if ch == "\\":
                buf.append(text[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#":
            eol = text.find("\n", i)
            i = end if eol == -1 else eol
            continue
        elif ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
            if depth == 0:
                return "".join(buf[1:]), i + 1  # drop the opening paren
        buf.append(ch)
        i += 1
    return None  # unbalanced within budget — not a call


def _split_top_level_args(args_text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(args_text):
        ch = args_text[i]
        if quote:
            if ch == "\\" and i + 1 < len(args_text):
                buf.append(args_text[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def extract_calls(text: str, context: str) -> list[DocCall]:
    """All tool-style calls in `text`, skipping ruby/python fenced blocks."""
    skip_spans = [
        (m.start(), m.end())
        for m in _FENCE_RE.finditer(text)
        if m.group(1).strip().lower() in _SKIP_LANGS
    ]
    calls: list[DocCall] = []
    consumed_until = -1  # matches inside an already-parsed call are string
    # content or nested values, never independent doc examples
    for m in _CALL_START.finditer(text):
        if m.start() < consumed_until:
            continue
        if any(s <= m.start() < e for s, e in skip_spans):
            continue
        parsed = _scan_call_args(text, m.end() - 1)
        if parsed is None:
            continue
        args_text, consumed_until = parsed
        kwargs: dict[str, str] = {}
        positional: list[str] = []
        elided = False
        for part in _split_top_level_args(args_text):
            if part == "...":
                elided = True
                continue
            kw = _KWARG_RE.match(part)
            if kw:
                kwargs[kw.group(1)] = kw.group(2).strip()
            else:
                positional.append(part)
        calls.append(DocCall(
            name=m.group(1),
            kwargs=kwargs,
            positional=positional,
            elided=elided,
            line=text.count("\n", 0, m.start()) + 1,
            context=context,
        ))
    return calls


# ---------------------------------------------------------------------------
# 3. Validation
# ---------------------------------------------------------------------------

def validate_doc_calls(
    calls: list[DocCall],
    registry: dict[str, ToolSig],
    known_exceptions: frozenset[tuple[str, str, str]] = frozenset(),
    ignore_names: frozenset[str] = frozenset(),
) -> list[str]:
    """Contract-check extracted calls against the AST registry.

    known_exceptions: (context, tool, kwarg) triples temporarily tolerated —
    each entry must cite the PR that removes it.
    ignore_names: snake_case callees that are legitimately not MCP tools
    (e.g. CLI commands quoted in prose).
    """
    errors: list[str] = []
    for c in calls:
        where = f"{c.context}:{c.line}"
        sig = registry.get(c.name)
        if sig is None:
            if c.name not in ignore_names:
                errors.append(f"{where}: unknown tool '{c.name}(...)'")
            continue
        for k in c.kwargs:
            if k not in sig.params:
                if (c.context, c.name, k) in known_exceptions:
                    continue
                errors.append(
                    f"{where}: {c.name}() has no parameter '{k}' "
                    f"(params: {', '.join(sig.params)})",
                )
        bare = [a for a in c.positional if _BARE_IDENT.match(a)]
        if bare:
            errors.append(
                f"{where}: {c.name}() passes bare identifier(s) "
                f"{bare} positionally — use keyword arguments so agents "
                f"see real parameter names",
            )
        if len(c.positional) > len(sig.params):
            errors.append(
                f"{where}: {c.name}() has {len(c.positional)} positional "
                f"args but only {len(sig.params)} parameters",
            )
        if not c.elided:
            satisfied = set(sig.params[: len(c.positional)]) | set(c.kwargs)
            missing = sorted(sig.required - satisfied)
            if missing:
                errors.append(
                    f"{where}: {c.name}() missing required argument(s) "
                    f"{missing}",
                )
    return errors


# ---------------------------------------------------------------------------
# 4. MCP prompt template extraction (from prompts_resources/tools.py AST)
# ---------------------------------------------------------------------------

def _render_str(node: ast.expr) -> str:
    """Render a string expression; f-string fields become __PARAM_<name>__."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                out.append(str(part.value))
            elif isinstance(part, ast.FormattedValue):
                expr = ast.unparse(part.value)
                token = expr if _BARE_IDENT.match(expr) else "expr"
                out.append(f"__PARAM_{token}__")
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _render_str(node.left) + _render_str(node.right)
    return ""


def extract_prompt_templates(path: Path) -> dict[str, str]:
    """MCP prompt name -> rendered template text with __PARAM_x__ markers."""
    templates: dict[str, str] = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "prompt"
            ):
                continue
            name = next(
                (kw.value.value for kw in dec.keywords
                 if kw.arg == "name" and isinstance(kw.value, ast.Constant)),
                node.name,
            )
            rendered = "".join(
                _render_str(stmt.value)
                for stmt in ast.walk(node)
                if isinstance(stmt, ast.Return) and stmt.value is not None
            )
            templates[name] = rendered
    return templates
