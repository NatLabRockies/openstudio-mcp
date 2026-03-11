"""Validate Claude Code SKILL.md files.

Checks:
1. YAML frontmatter parses correctly
2. Required frontmatter fields present
3. Every backtick-quoted tool name exists in registered MCP tools
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from mcp_server.skills import register_all_skills

# Repo-relative path (host/CI), fallback to Docker baked-in path
_REPO_SKILLS = Path(__file__).resolve().parent.parent / ".claude" / "skills"
_DOCKER_SKILLS = Path("/skills")
SKILLS_DIR = _REPO_SKILLS if _REPO_SKILLS.exists() else _DOCKER_SKILLS


def _get_registered_tool_names() -> set[str]:
    """Register all MCP tools and return the set of tool names."""
    registered = {}

    class FakeMCP:
        def tool(self, name=None):
            def decorator(fn):
                tool_name = name or fn.__name__
                registered[tool_name] = fn
                return fn
            return decorator
        def prompt(self, **kw):
            return lambda fn: fn
        def resource(self, *a, **kw):
            return lambda fn: fn

    register_all_skills(FakeMCP())
    return set(registered.keys())


def _parse_skill_md(path: Path) -> tuple[dict, str]:
    """Parse SKILL.md into (frontmatter_dict, body_text)."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    assert match, f"No YAML frontmatter in {path}"
    frontmatter = yaml.safe_load(match.group(1))
    body = match.group(2)
    return frontmatter, body


def _find_skill_files() -> list[Path]:
    """Find all SKILL.md files under .claude/skills/."""
    if not SKILLS_DIR.exists():
        return []
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


def _extract_tool_references(body: str) -> set[str]:
    """Extract tool names from backtick-quoted references in markdown.

    Matches patterns like `tool_name(` and `tool_name` when the name
    looks like a snake_case MCP tool (contains underscore or known tool).
    """
    # Match `tool_name(...)` patterns (function call style)
    call_refs = set(re.findall(r"`(\w+)\(", body))

    # Match standalone `tool_name` that contain underscores (snake_case = likely tool)
    standalone_refs = set(re.findall(r"`(\w+)`", body))
    snake_case = {r for r in standalone_refs if "_" in r}

    return call_refs | snake_case


# ---- tests ------------------------------------------------------------------


def test_skill_files_exist():
    """At least one SKILL.md exists under .claude/skills/."""
    files = _find_skill_files()
    assert len(files) >= 3, f"Expected >= 3 SKILL.md files, found {len(files)}"


def test_frontmatter_valid():
    """Every SKILL.md has valid YAML frontmatter with description."""
    for path in _find_skill_files():
        fm, _ = _parse_skill_md(path)
        skill_name = path.parent.name
        assert isinstance(fm, dict), f"{skill_name}: frontmatter is not a dict"
        assert "description" in fm, f"{skill_name}: missing 'description'"
        assert len(fm["description"]) > 10, f"{skill_name}: description too short"


def test_tool_references_valid():
    """Every tool name referenced in SKILL.md body exists in MCP registry."""
    registered = _get_registered_tool_names()

    # Known non-tool identifiers that look like snake_case but aren't tools
    false_positives = {
        "people_per_area", "watts_per_area", "default_value",
        "schedule_type", "floor_to_ceiling_height", "thermal_zone_name",
        "space_names", "material_names", "floor_vertices",
        "heating_fuel", "cooling_fuel", "system_type", "system_name",
        "economizer_type", "dry_bulb_max_c", "dry_bulb_range_c",
        "day_type", "design_loop_exit_temperature_c",
        "loop_design_temperature_difference_c",
        "surface_name", "construction_name", "component_name",
        "air_loop_name", "plant_loop_name", "variable_name",
        "object_name", "new_name", "object_type", "measure_dir",
        "epw_path", "osm_path", "run_id",
        "fraction_of_roof", "cooling_offset_f", "heating_offset_f",
        "alter_design_days", "begin_month", "begin_day",
        "end_month", "end_day", "do_zone_sizing", "run_for_sizing_periods",
        "reporting_frequency", "variable_names", "component_type",
        "start_month", "end_month", "zone_equipment_type",
        "sensible_effectiveness", "energy_recovery", "heat_recovery",
        "outdoor_unit_capacity_w", "radiant_type", "ventilation_system",
        "terminal_type", "terminal_options", "thermal_zone_names",
        "fixed_windows", "operable_windows", "geometry_diagnostics",
    }

    all_errors = []
    for path in _find_skill_files():
        _, body = _parse_skill_md(path)
        skill_name = path.parent.name
        refs = _extract_tool_references(body)
        unknown = refs - registered - false_positives
        if unknown:
            all_errors.append(f"{skill_name}: unknown tools {sorted(unknown)}")

    assert not all_errors, "Tool reference errors:\n" + "\n".join(all_errors)
