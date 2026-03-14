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
    """Extract tool names from backtick-quoted function calls in markdown.

    Only matches `tool_name(` patterns where tool_name contains an underscore —
    all MCP tool names use snake_case (e.g. create_measure), so this filters
    out Ruby method refs like `run()` or `arguments()`.
    """
    return {m for m in re.findall(r"`(\w+)\(", body) if "_" in m}


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

    all_errors = []
    for path in _find_skill_files():
        _, body = _parse_skill_md(path)
        skill_name = path.parent.name
        refs = _extract_tool_references(body)
        unknown = refs - registered
        if unknown:
            all_errors.append(f"{skill_name}: unknown tools {sorted(unknown)}")

    assert not all_errors, "Tool reference errors:\n" + "\n".join(all_errors)
