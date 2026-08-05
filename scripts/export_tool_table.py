"""Export the tool roster grouped by skill — paper Table 1 + counts (D5/B9).

Run INSIDE the container at the archived tag so the printed counts are the
artifact's counts, one counting rule everywhere: len(EXPECTED_TOOLS).

  docker run --rm -v .:/repo openstudio-mcp:v1.2.0 \
      bash -lc "cd /repo && python scripts/export_tool_table.py \
                --md paper/table1.md --json paper/tool_counts.json"

Cross-checks the registered roster against tests/test_skill_registration.py
EXPECTED_TOOLS and refuses to emit on any mismatch.
"""
from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class _Recorder:
    """Minimal MCP stand-in that records tool names passed to @mcp.tool."""

    def __init__(self):
        self.tools: list[str] = []

    def tool(self, name=None, **_kwargs):
        def decorator(fn):
            self.tools.append(name or fn.__name__)
            return fn
        return decorator

    def prompt(self, **_kwargs):
        return lambda fn: fn

    def resource(self, *_args, **_kwargs):
        return lambda fn: fn


def collect_tools_by_skill() -> dict[str, list[str]]:
    """Skill module name -> sorted tool names it registers.

    Mirrors mcp_server.skills.register_all_skills discovery, but registers
    each skill into its own recorder so tools attribute to their module.
    """
    import mcp_server.skills as skills_pkg

    by_skill: dict[str, list[str]] = {}
    for _importer, modname, ispkg in pkgutil.iter_modules(skills_pkg.__path__):
        if not ispkg:
            continue
        tools_mod = importlib.import_module(f"mcp_server.skills.{modname}.tools")
        if not hasattr(tools_mod, "register"):
            continue
        rec = _Recorder()
        tools_mod.register(rec)
        if rec.tools:
            by_skill[modname] = sorted(rec.tools)
    return by_skill


def cross_check(by_skill: dict[str, list[str]]) -> set[str]:
    """Assert the grouped roster equals EXPECTED_TOOLS; return the set."""
    sys.path.insert(0, str(REPO / "tests"))
    from test_skill_registration import EXPECTED_TOOLS

    registered = {t for tools in by_skill.values() for t in tools}
    missing = EXPECTED_TOOLS - registered
    extra = registered - EXPECTED_TOOLS
    if missing or extra:
        sys.exit(f"ABORT: roster mismatch vs EXPECTED_TOOLS — "
                 f"missing={sorted(missing)}, extra={sorted(extra)}")
    return registered


def render_md(by_skill: dict[str, list[str]], total: int) -> str:
    lines = [
        "# Tool roster by skill",
        "",
        f"{total} tools across {len(by_skill)} skills.",
        "",
        "| Skill | Tools | Names |",
        "|---|---|---|",
    ]
    for skill in sorted(by_skill):
        tools = by_skill[skill]
        lines.append(f"| {skill} | {len(tools)} | {', '.join(tools)} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--md", default=None, help="write markdown table here")
    ap.add_argument("--json", default=None, help="write counts JSON here")
    args = ap.parse_args()

    by_skill = collect_tools_by_skill()
    registered = cross_check(by_skill)
    total = len(registered)

    md = render_md(by_skill, total)
    counts = {"total_tools": total, "skills": len(by_skill),
              "per_skill": {k: len(v) for k, v in sorted(by_skill.items())}}

    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(counts, indent=2), encoding="utf-8")
    if not (args.md or args.json):
        print(md)
    print(json.dumps(counts["per_skill"], indent=2), file=sys.stderr)
    print(f"total: {total} tools / {len(by_skill)} skills", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
