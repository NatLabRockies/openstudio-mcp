"""Skill discovery operations — list and read workflow guides from /skills."""
from __future__ import annotations

import os
from pathlib import Path

from mcp_server.config import SKILLS_DIR


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from SKILL.md into (dict, body).

    Uses simple string splitting — no pyyaml dependency needed.
    Handles key: value pairs and ignores complex YAML (lists, nesting).
    """
    if not text.startswith("---"):
        return {}, text
    # Find closing --- (skip the opening one)
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 3:].strip()
    fm: dict = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip('"').strip("'")
        fm[key.strip()] = value
    return fm, body


def list_skills_op() -> dict:
    """List available workflow guides from SKILLS_DIR."""
    if not SKILLS_DIR.is_dir():
        return {
            "ok": True,
            "skills": [],
            "count": 0,
            "message": (
                "No skills directory found. Mount .claude/skills to "
                f"{SKILLS_DIR} for workflow guides."
            ),
        }

    skills = []
    for entry in sorted(SKILLS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, _ = _parse_frontmatter(text)
        name = fm.get("name", entry.name)
        description = fm.get("description", "")
        skills.append({"name": name, "description": description})

    return {"ok": True, "skills": skills, "count": len(skills)}


def get_skill_op(name: str) -> dict:
    """Read a specific skill's workflow instructions."""
    if not SKILLS_DIR.is_dir():
        return {
            "ok": False,
            "error": (
                "No skills directory found. Mount .claude/skills to "
                f"{SKILLS_DIR} for workflow guides."
            ),
        }

    # Sanitize: prevent path traversal
    safe_name = Path(name).name
    skill_dir = SKILLS_DIR / safe_name
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        return {
            "ok": False,
            "error": (
                f"Skill '{name}' not found. "
                "Use list_skills() to see available workflows."
            ),
        }

    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"Failed to read skill: {e}"}

    fm, body = _parse_frontmatter(text)

    result: dict = {
        "ok": True,
        "name": fm.get("name", safe_name),
        "content": body,
    }

    # List supporting files so agent knows to ask for them
    supporting = []
    for f in sorted(skill_dir.iterdir()):
        if f.name != "SKILL.md" and f.is_file():
            supporting.append(f.name)
    if supporting:
        result["supporting_files"] = supporting

    return result
