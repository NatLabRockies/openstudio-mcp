"""Unit tests for skill discovery tools (list_skills, get_skill).

Tests frontmatter parsing, directory scanning, and error handling
without needing Docker or OpenStudio.
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_server.skills.skill_discovery.operations import (
    _parse_frontmatter,
    list_skills_op,
    get_skill_op,
)


# --- Frontmatter parsing ---

def test_parse_frontmatter_basic():
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
    text = '---\nname: "my-skill"\ndescription: \'A skill\'\n---\nBody'
    fm, body = _parse_frontmatter(text)
    assert fm["name"] == "my-skill"
    assert fm["description"] == "A skill"
    assert body == "Body"


def test_parse_frontmatter_claude_extensions():
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
    text = "# Just a markdown file\nNo frontmatter."
    fm, body = _parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_unclosed():
    text = "---\nname: broken\nNo closing delimiter"
    fm, body = _parse_frontmatter(text)
    assert fm == {}
    assert body == text


# --- list_skills ---

def test_list_skills_with_skills(tmp_path):
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
    """Empty skills directory returns empty list."""
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = list_skills_op()

    assert result["ok"] is True
    assert result["count"] == 0
    assert result["skills"] == []


def test_list_skills_no_dir(tmp_path):
    """Non-existent skills directory returns empty list with message."""
    fake = tmp_path / "nonexistent"
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", fake):
        result = list_skills_op()

    assert result["ok"] is True
    assert result["count"] == 0
    assert "message" in result


def test_list_skills_falls_back_to_dirname(tmp_path):
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
    """Returns error when skill doesn't exist."""
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = get_skill_op("nonexistent")

    assert result["ok"] is False
    assert "not found" in result["error"]
    assert "list_skills" in result["error"]


def test_get_skill_no_dir(tmp_path):
    """Returns error when skills directory doesn't exist."""
    fake = tmp_path / "nonexistent"
    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", fake):
        result = get_skill_op("simulate")

    assert result["ok"] is False


def test_get_skill_supporting_files(tmp_path):
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
    """Path traversal attempts are blocked."""
    (tmp_path / "simulate").mkdir()
    (tmp_path / "simulate" / "SKILL.md").write_text(
        "---\nname: simulate\n---\nBody", encoding="utf-8",
    )

    with patch("mcp_server.skills.skill_discovery.operations.SKILLS_DIR", tmp_path):
        result = get_skill_op("../../../etc/passwd")

    assert result["ok"] is False
