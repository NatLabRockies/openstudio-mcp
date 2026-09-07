"""Skill discovery operations — list and read workflow guides from /skills."""
from __future__ import annotations

from pathlib import Path

from mcp_server.config import SKILLS_DIR


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from SKILL.md into (dict, body).

    Uses simple string splitting — no pyyaml dependency needed.
    Handles key: value pairs and ignores complex YAML (lists, nesting).
    """
    if not text.startswith("---"):
        return {}, text
    # Find closing --- on its own line (skip the opening one)
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 4:].strip()
    fm: dict = {}
    for raw_line in fm_text.splitlines():
        line = raw_line.strip()
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
    if safe_name in (".", "..", "") or "/" in name or "\\" in name:
        return {"ok": False, "error": f"Invalid skill name: '{name}'"}
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

    # List agent-support files so the agent knows to fetch them
    supporting = [
        f.name for f in sorted(skill_dir.iterdir())
        if f.is_file() and _is_agent_support_file(f.name)
    ]
    if supporting:
        result["supporting_files"] = supporting
        result["supporting_files_hint"] = (
            "Fetch with get_skill_file(skill_name=..., filename=...)"
        )

    return result


# Extensions a skill may serve to agents as supporting reference material.
# SKILL.md is delivered via get_skill; eval.md is test data; README.md is
# developer notes; hidden files and other artifacts are never served.
_SUPPORT_EXTENSIONS = {".md", ".txt", ".csv", ".json"}
_NON_SUPPORT_NAMES = {"SKILL.md", "eval.md", "README.md"}


def _is_agent_support_file(name: str) -> bool:
    """Whether a file in a skill directory is agent-facing support material."""
    if name in _NON_SUPPORT_NAMES or name.startswith("."):
        return False
    return Path(name).suffix.lower() in _SUPPORT_EXTENSIONS


def get_skill_file_op(skill_name: str, filename: str) -> dict:
    """Read one supporting file of a skill (the sole retrieval affordance).

    Resolves inside the configured SKILLS_DIR only; rejects absolute paths,
    traversal, and files that are not agent support material.
    """
    safe_skill = Path(skill_name).name
    if (
        safe_skill in (".", "..", "")
        or "/" in skill_name or "\\" in skill_name
    ):
        return {"ok": False, "error": f"Invalid skill name: '{skill_name}'"}
    skill_dir = SKILLS_DIR / safe_skill
    if not (skill_dir / "SKILL.md").is_file():
        return {
            "ok": False,
            "error": (
                f"Skill '{skill_name}' not found. "
                "Use list_skills() to see available workflows."
            ),
        }

    if (
        not filename
        or Path(filename).is_absolute()
        or "/" in filename or "\\" in filename
        or Path(filename).name != filename
    ):
        return {"ok": False, "error": f"Invalid filename: '{filename}'"}
    if not _is_agent_support_file(filename):
        return {
            "ok": False,
            "error": (
                f"'{filename}' is not an agent support file. Available: "
                "see supporting_files in get_skill(...)."
            ),
        }

    target = (skill_dir / filename).resolve()
    try:
        target.relative_to(SKILLS_DIR.resolve())
    except ValueError:
        return {"ok": False, "error": f"Invalid filename: '{filename}'"}
    if not target.is_file():
        return {
            "ok": False,
            "error": (
                f"File '{filename}' not found in skill '{safe_skill}'. "
                "Check supporting_files in get_skill(...)."
            ),
        }

    try:
        content = target.read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"Failed to read file: {e}"}

    return {
        "ok": True,
        "skill": safe_skill,
        "filename": filename,
        "content": content,
    }
