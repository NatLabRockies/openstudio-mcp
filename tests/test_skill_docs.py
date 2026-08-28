"""Contract validation for every served agent-guidance surface.

Validates that .claude/skills/**/*.md, eval.md tables, and the six MCP
prompt templates only instruct calls that the live tool registry accepts:
real tool names, real kwarg names, required args present. The registry is
AST-parsed from mcp_server/skills/*/tools.py — no imports, so this stays a
true unit test (plan finding E2).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from doc_contract_lib import (
    REPO_ROOT,
    SERVED_SKILLS_DIR,
    extract_calls,
    extract_prompt_templates,
    load_tool_registry,
    validate_doc_calls,
)
from llm.eval_parser import parse_eval_files
from test_skill_registration import EXPECTED_TOOLS

pytestmark = pytest.mark.unit

PROMPTS_TOOLS_PY = (
    REPO_ROOT / "mcp_server" / "skills" / "prompts_resources" / "tools.py"
)

# (context, tool, kwarg) triples temporarily tolerated — each entry must
# cite the PR that removes it. Empty since apply_measure gained run_id (B1).
KNOWN_EXCEPTIONS: frozenset[tuple[str, str, str]] = frozenset()

# snake_case callees in served docs that are legitimately not MCP tools
IGNORE_NAMES: frozenset[str] = frozenset()


def _served_markdown_files() -> list[Path]:
    # eval.md is validated by test_eval_tables_are_machine_checkable under its
    # own table grammar ("(x2)" annotations etc.), not the call scanner
    return sorted(
        p for p in SERVED_SKILLS_DIR.glob("*/*.md") if p.name != "eval.md"
    )


def _parse_skill_md(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    assert match, f"No YAML frontmatter in {path}"
    return yaml.safe_load(match.group(1)), match.group(2)


def _context(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


# ---- registry ---------------------------------------------------------------


def test_ast_registry_matches_expected_tools():
    # Validates: AST-parsed @mcp.tool roster == EXPECTED_TOOLS — the doc
    # validator checks against the real registry, not a drifted copy
    names = set(load_tool_registry())
    assert names == EXPECTED_TOOLS, (
        f"AST registry drift: missing={sorted(EXPECTED_TOOLS - names)}, "
        f"extra={sorted(names - EXPECTED_TOOLS)}"
    )


# ---- SKILL.md frontmatter ---------------------------------------------------


def test_skill_files_exist():
    # Validates: served skills corpus present (>= 10 SKILL.md under .claude/skills)
    files = sorted(SERVED_SKILLS_DIR.glob("*/SKILL.md"))
    assert len(files) >= 10, f"Expected >= 10 SKILL.md files, found {len(files)}"


def test_frontmatter_valid():
    # Validates: every SKILL.md has YAML frontmatter with a non-trivial description
    for path in sorted(SERVED_SKILLS_DIR.glob("*/SKILL.md")):
        fm, _ = _parse_skill_md(path)
        skill = path.parent.name
        assert isinstance(fm, dict), f"{skill}: frontmatter is not a dict"
        assert "description" in fm, f"{skill}: missing 'description'"
        assert len(fm["description"]) > 10, f"{skill}: description too short"


# ---- served call contracts --------------------------------------------------


def test_served_skill_calls_match_tool_contracts():
    # Regression: served skills taught save_osm_model(save_path=), compare_runs
    # positional ids, get_run_logs(log_type=), shift_schedule_time(
    # shift_value_hours=), add_rooftop_pv(fraction_of_roof=), economizer/sizing
    # flat kwargs (plan A1-A8) — agents copied them and failed
    registry = load_tool_registry()
    errors: list[str] = []
    for path in _served_markdown_files():
        text = path.read_text(encoding="utf-8")
        if path.name == "SKILL.md":
            _, text = _parse_skill_md(path)
        calls = extract_calls(text, _context(path))
        errors.extend(validate_doc_calls(
            calls, registry,
            known_exceptions=KNOWN_EXCEPTIONS,
            ignore_names=IGNORE_NAMES,
        ))
    assert not errors, "Served-doc contract errors:\n" + "\n".join(errors)


def test_mcp_prompt_templates_are_executable():
    # Regression: MCP prompts emitted run_simulation() without osm_path,
    # get_run_status() without run_id, assign_construction_to_surface() with
    # no fields, and compare_runs(run_id_a, run_id_b) (plan C5)
    registry = load_tool_registry()
    templates = extract_prompt_templates(PROMPTS_TOOLS_PY)
    assert len(templates) >= 6, f"expected >= 6 MCP prompts, got {sorted(templates)}"
    errors: list[str] = []
    for name, text in sorted(templates.items()):
        calls = extract_calls(text, f"prompt:{name}")
        errors.extend(validate_doc_calls(calls, registry))
    assert not errors, "MCP prompt contract errors:\n" + "\n".join(errors)


def test_full_building_simulation_prompt_applies_system_type():
    # Regression: full_building_simulation accepted system_type but no step
    # applied it — the built model silently ignored the requested system (C5)
    registry = load_tool_registry()
    text = extract_prompt_templates(PROMPTS_TOOLS_PY)["full_building_simulation"]
    calls = extract_calls(text, "prompt:full_building_simulation")
    carrying = [
        c.name for c in calls
        if c.name in registry and any(
            "__PARAM_system_type__" in v
            for v in (*c.kwargs.values(), *c.positional)
        )
    ]
    assert carrying, (
        "full_building_simulation's system_type parameter must be passed to "
        "at least one tool call in the emitted steps"
    )


# ---- eval.md tables ---------------------------------------------------------


def test_eval_tables_are_machine_checkable():
    # Regression: eval tables carried ghost tools (list_infiltration), wildcard
    # rows (extract_*), a ghost critical param (format), and prose-only
    # negative tables no test could assert (plan E3)
    registry = load_tool_registry()
    parsed = parse_eval_files()
    errors = list(parsed["errors"])

    for case in parsed["cases"]:
        where = f"{case['skill']}/eval.md ('{case['prompt'][:40]}')"
        unknown = [t for t in case["expected_tools"] if t not in registry]
        if unknown:
            errors.append(f"{where}: unknown expected tools {unknown}")
        for crit in case["critical_params"]:
            carriers = [
                t for t in case["expected_tools"]
                if t in registry and crit.param in registry[t].params
            ]
            if not carriers:
                errors.append(
                    f"{where}: critical param '{crit.param}' is not a "
                    f"parameter of any expected tool {case['expected_tools']}",
                )

    for case in parsed["negative_cases"]:
        where = f"{case['skill']}/eval.md negative ('{case['prompt'][:40]}')"
        unknown = [
            t for t in (*case["forbidden_tools"], *case["alternatives"])
            if t not in registry
        ]
        if unknown:
            errors.append(f"{where}: unknown tools {unknown}")

    assert not errors, "Eval table errors:\n" + "\n".join(errors)


def test_every_eval_file_has_negative_cases():
    # Validates: each eval.md contributes assertable negative-routing cases —
    # the load_should_not_trigger data is actually consumed by an LLM test
    parsed = parse_eval_files()
    skills_with_neg = {c["skill"] for c in parsed["negative_cases"]}
    eval_files = {p.parent.name for p in SERVED_SKILLS_DIR.rglob("eval.md")}
    missing = eval_files - skills_with_neg
    assert not missing, (
        f"eval.md files with no machine-checkable negative cases: {sorted(missing)}"
    )


# ---- cross-surface consistency (C1/C2) --------------------------------------


def test_polling_cadence_consistent_across_surfaces():
    # Regression: simulate SKILL.md said poll every 3-5 s while the tool
    # docstring said once per minute and server instructions said 1-2 min —
    # sleep-less clients burned an LLM turn per poll (plan C1)
    _, simulate = _parse_skill_md(SERVED_SKILLS_DIR / "simulate" / "SKILL.md")
    assert not re.search(r"\d+\s*-\s*\d+\s*second", simulate), (
        "simulate SKILL.md must not instruct seconds-scale polling"
    )
    canonical = "once per minute"
    assert canonical in simulate, (
        f"simulate SKILL.md must carry the canonical cadence '{canonical}'"
    )
    sim_tools = (REPO_ROOT / "mcp_server" / "skills" / "simulation"
                 / "tools.py").read_text(encoding="utf-8")
    assert canonical in sim_tools, "get_run_status docstring lost the cadence"
    server_py = (REPO_ROOT / "mcp_server" / "server.py").read_text(encoding="utf-8")
    assert canonical in server_py, (
        "server instructions must match the docstring cadence tier"
    )
    assert "1-2 minutes" not in server_py, (
        "server instructions contradict the once-per-minute docstring tier"
    )


def test_weather_discovery_routes_to_list_weather_files():
    # Regression: simulate + tool-workflows routed weather discovery via
    # list_files() while server instructions + docstring say list_weather_files
    # (plan C2)
    _, simulate = _parse_skill_md(SERVED_SKILLS_DIR / "simulate" / "SKILL.md")
    assert "list_weather_files" in simulate, (
        "simulate SKILL.md must route weather discovery to list_weather_files"
    )
    assert "list_files(" not in simulate, (
        "simulate SKILL.md must not use list_files for weather discovery"
    )
    _, workflows = _parse_skill_md(SERVED_SKILLS_DIR / "tool-workflows" / "SKILL.md")
    weather = re.search(r"## Set Up Weather\n(.*?)(?=\n## |\Z)", workflows, re.DOTALL)
    assert weather, "tool-workflows lost its Set Up Weather section"
    assert "list_weather_files" in weather.group(1), (
        "tool-workflows weather recipe must use list_weather_files"
    )
    assert "list_files(" not in weather.group(1), (
        "tool-workflows weather recipe must not use list_files"
    )


# ---- corpus invariant (D1-D6) -----------------------------------------------


def test_no_internal_skill_md_files():
    # Regression: mcp_server/skills/*/SKILL.md carried agent guidance that
    # get_skill never serves (it reads the configured SKILLS_DIR only) — HVAC
    # comfort doctrine, OSAF defaults, unit tables stranded (plan D1-D6).
    # Internal developer notes are README.md; .claude/skills is the ONLY
    # agent-guidance corpus.
    stranded = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in (REPO_ROOT / "mcp_server" / "skills").glob("*/SKILL.md")
    )
    assert stranded == [], (
        f"internal SKILL.md files are never served — migrate agent guidance "
        f"to .claude/skills and rename to README.md: {stranded}"
    )
