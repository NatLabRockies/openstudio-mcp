"""Unit tests for skill discovery tools (list_skills, get_skill).

Tests frontmatter parsing, directory scanning, and error handling
without needing Docker or OpenStudio.
"""
from __future__ import annotations

import textwrap
from unittest.mock import patch

import pytest

from mcp_server.skills.skill_discovery.operations import (
    _parse_frontmatter,
    get_skill_file_op,
    get_skill_op,
    list_skills_op,
)

pytestmark = pytest.mark.unit

# --- Frontmatter parsing ---

def test_parse_frontmatter_basic():
    # Validates: frontmatter parser extracts name and description from YAML header
    text = textwrap.dedent("""\
        ---
        name: simulate
        description: Run a simulation
        ---
        # Body content
        Some instructions.
    """)
    fm, body = _parse_frontmatter(text)
    assert fm["name"] == "simulate"
    assert fm["description"] == "Run a simulation"
    assert body.startswith("# Body content")


def test_parse_frontmatter_quoted_values():
    # Validates: frontmatter parser strips single and double quotes from values
    text = '---\nname: "my-skill"\ndescription: \'A skill\'\n---\nBody'
    fm, body = _parse_frontmatter(text)
    assert fm["name"] == "my-skill"
    assert fm["description"] == "A skill"
    assert body == "Body"


def test_parse_frontmatter_claude_extensions():
    # Validates: non-standard frontmatter keys (context, disable-model-invocation) are preserved
    """Claude Code extensions like context: fork don't break parsing."""
    text = textwrap.dedent("""\
        ---
        name: simulate
        description: Fire and forget simulation
        context: fork
        disable-model-invocation: true
        ---
        Body here.
    """)
    fm, body = _parse_frontmatter(text)
    assert fm["name"] == "simulate"
    assert fm["context"] == "fork"
    assert fm["disable-model-invocation"] == "true"


def test_parse_frontmatter_no_frontmatter():
    # Validates: files without YAML frontmatter return empty dict and full text as body
    text = "# Just a markdown file\nNo frontmatter."
    fm, body = _parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_unclosed():
    # Validates: unclosed frontmatter (missing closing ---) treated as no frontmatter
    text = "---\nname: broken\nNo closing delimiter"
    fm, body = _parse_frontmatter(text)
    assert fm == {}
    assert body == text


# --- list_skills ---

def test_list_skills_with_skills(tmp_path):
    # Validates: list_skills scans SKILL.md files and returns correct count and metadata
    """Scans directory and returns skill metadata."""
    # Create two skill dirs
    (tmp_path / "simulate").mkdir()
    (tmp_path / "simulate" / "SKILL.md").write_text(
        "---\nname: simulate\ndescription: Run sim\n---\nBody",
        encoding="utf-8",
    )
    (tmp_path / "retrofit").mkdir()
    (tmp_path / "retrofit" / "SKILL.md").write_text(
        "---\nname: retrofit\ndescription: ECM analysis\n---\nBody",
        encoding="utf-8",
    )
    # Create a non-skill dir (no SKILL.md)
    (tmp_path / "random_dir").mkdir()

    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = list_skills_op()

    assert result["ok"] is True
    assert result["count"] == 2
    names = {s["name"] for s in result["skills"]}
    assert names == {"simulate", "retrofit"}


def test_list_skills_empty_dir(tmp_path):
    # Validates: empty skills directory returns ok=True with count=0 and empty list
    """Empty skills directory returns empty list."""
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = list_skills_op()

    assert result["ok"] is True
    assert result["count"] == 0
    assert result["skills"] == []


def test_list_skills_no_dir(tmp_path):
    # Validates: non-existent skills directory returns ok=True with count=0 and informational message
    """Non-existent skills directory returns empty list with message."""
    fake = tmp_path / "nonexistent"
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", fake):
        result = list_skills_op()

    assert result["ok"] is True
    assert result["count"] == 0
    assert "not found" in result["message"].lower() or "no skills" in result["message"].lower(), \
        f"Expected informational message about missing dir, got: {result['message']}"


def test_list_skills_falls_back_to_dirname(tmp_path):
    # Validates: SKILL.md without name field falls back to directory name
    """If frontmatter has no name, uses directory name."""
    (tmp_path / "my-skill").mkdir()
    (tmp_path / "my-skill" / "SKILL.md").write_text(
        "---\ndescription: A skill without name\n---\nBody",
        encoding="utf-8",
    )

    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = list_skills_op()

    assert result["skills"][0]["name"] == "my-skill"


# --- get_skill ---

def test_get_skill_found(tmp_path):
    # Validates: get_skill returns body content without frontmatter delimiters
    """Returns stripped body when skill exists."""
    (tmp_path / "simulate").mkdir()
    (tmp_path / "simulate" / "SKILL.md").write_text(
        "---\nname: simulate\ndescription: Run sim\n---\n# Simulate\nStep 1...",
        encoding="utf-8",
    )

    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = get_skill_op("simulate")

    assert result["ok"] is True
    assert result["name"] == "simulate"
    assert "# Simulate" in result["content"]
    assert "---" not in result["content"]


def test_get_skill_not_found(tmp_path):
    # Validates: get_skill returns ok=False with actionable error mentioning list_skills
    """Returns error when skill doesn't exist."""
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = get_skill_op("nonexistent")

    assert result["ok"] is False
    assert "not found" in result["error"]
    assert "list_skills" in result["error"]


def test_get_skill_no_dir(tmp_path):
    # Validates: get_skill returns ok=False with error when skills directory missing
    """Returns error when skills directory doesn't exist."""
    fake = tmp_path / "nonexistent"
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", fake):
        result = get_skill_op("simulate")

    assert result["ok"] is False
    assert "error" in result, "Missing error message when skills dir doesn't exist"
    assert result["error"].strip(), "Error message should not be empty"


def test_get_skill_supporting_files(tmp_path):
    # Validates: get_skill includes non-SKILL.md files in supporting_files list
    """Lists supporting files in response."""
    skill_dir = tmp_path / "retrofit"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: retrofit\n---\nBody",
        encoding="utf-8",
    )
    (skill_dir / "ecm-catalog.md").write_text("ECM list", encoding="utf-8")

    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = get_skill_op("retrofit")

    assert result["ok"] is True
    assert "ecm-catalog.md" in result["supporting_files"]


def test_get_skill_path_traversal(tmp_path):
    # Validates: path traversal via '../' in skill name is rejected with ok=False
    """Path traversal attempts are blocked."""
    (tmp_path / "simulate").mkdir()
    (tmp_path / "simulate" / "SKILL.md").write_text(
        "---\nname: simulate\n---\nBody", encoding="utf-8",
    )

    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = get_skill_op("../../../etc/passwd")

    assert result["ok"] is False
    assert "error" in result, "Path traversal rejection should include error message"
    assert result["error"].strip(), "Error message should not be empty for path traversal rejection"


# --- get_skill_file + support-file classification ---

def _support_skill_dir(tmp_path):
    d = tmp_path / "retrofit"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: retrofit\n---\nBody", encoding="utf-8")
    (d / "eval.md").write_text("| Query |", encoding="utf-8")
    (d / "ecm-catalog.md").write_text("## Envelope\nECM list", encoding="utf-8")
    (d / ".hidden.md").write_text("secret", encoding="utf-8")
    (d / "notes.pyc").write_text("junk", encoding="utf-8")
    return tmp_path


def test_supporting_files_filtered_to_agent_support(tmp_path):
    # Regression: get_skill listed eval.md (test data) and would list hidden/
    # developer artifacts in supporting_files (F4) — only agent support shows
    root = _support_skill_dir(tmp_path)
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", root):
        result = get_skill_op("retrofit")
    assert result["ok"] is True
    assert result["supporting_files"] == ["ecm-catalog.md"]
    assert "get_skill_file" in result["supporting_files_hint"]


def test_get_skill_file_returns_content(tmp_path):
    # Validates: get_skill_file serves an advertised support file's content
    root = _support_skill_dir(tmp_path)
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", root):
        result = get_skill_file_op("retrofit", "ecm-catalog.md")
    assert result["ok"] is True
    assert result["skill"] == "retrofit"
    assert result["filename"] == "ecm-catalog.md"
    assert result["content"] == "## Envelope\nECM list"


def test_get_skill_file_missing_file(tmp_path):
    # Validates: missing support file returns ok=False pointing at get_skill
    root = _support_skill_dir(tmp_path)
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", root):
        result = get_skill_file_op("retrofit", "nope.md")
    assert result["ok"] is False
    assert "not found" in result["error"].lower()
    assert "supporting_files" in result["error"]


@pytest.mark.parametrize("bad", [
    "../retrofit/ecm-catalog.md", "/etc/passwd", r"..\x.md",
    "SKILL.md", "eval.md", "README.md", ".hidden.md", "notes.pyc", "",
])
def test_get_skill_file_rejects_non_support_and_traversal(tmp_path, bad):
    # Validates: traversal, absolute paths, hidden files, test data, and
    # developer artifacts are refused — only classified agent support serves
    root = _support_skill_dir(tmp_path)
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", root):
        result = get_skill_file_op("retrofit", bad)
    assert result["ok"] is False
    assert result["error"].strip()


def test_get_skill_file_unknown_skill(tmp_path):
    # Validates: unknown skill name gets the list_skills-pointing error
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = get_skill_file_op("ghost", "x.md")
    assert result["ok"] is False
    assert "not found" in result["error"].lower()
