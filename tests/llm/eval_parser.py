"""Parse eval.md files into Tier 1 test cases.

Each eval.md has two tables:
  - "Should trigger" → tool selection cases (prompt → expected tools)
  - "Should NOT trigger" → negative cases (prompt should NOT call these tools)

Format:
  | Query | Expected tools | Critical params |
  |---|---|---|
  | "Create a 5-zone office" | create_baseline_osm, load_osm_model | ... |
"""
from __future__ import annotations

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / ".claude" / "skills"


def _parse_table_rows(text: str) -> list[list[str]]:
    """Extract rows from a markdown table (skip header + separator)."""
    rows = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        # Skip separator rows (all dashes)
        if cells and all(re.match(r"^-+$", c) for c in cells):
            continue
        # Skip header row
        if cells and cells[0].lower() in ("query", ""):
            continue
        if cells:
            rows.append(cells)
    return rows


def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes from a string."""
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or \
       (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def load_should_trigger() -> list[dict]:
    """Parse "Should trigger" tables from all eval.md files.

    Returns list of:
        {"prompt": str, "expected_tools": list[str], "skill": str}
    """
    cases = []
    for eval_md in sorted(SKILLS_DIR.rglob("eval.md")):
        skill_name = eval_md.parent.name
        text = eval_md.read_text()

        # Extract "Should trigger" section
        match = re.search(
            r"##\s*Should\s+trigger\s*\n(.*?)(?=\n##|\Z)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if not match:
            continue

        for row in _parse_table_rows(match.group(1)):
            if len(row) < 2:
                continue
            prompt = _strip_quotes(row[0])
            # Parse comma-separated tool names, handle "x2" and "OR" variants
            raw_tools = row[1]
            # Remove annotations like "(x2)", "x2"
            raw_tools = re.sub(r"\(x\d+\)", "", raw_tools)
            raw_tools = re.sub(r"\bx\d+\b", "", raw_tools)
            # Split on comma or "OR"
            tools = []
            for part in re.split(r",|\bOR\b", raw_tools):
                t = part.strip()
                # Skip vague entries like "save baseline, apply measure, run, compare"
                if t and "_" in t:
                    tools.append(t)

            if prompt and tools:
                cases.append({
                    "prompt": prompt,
                    "expected_tools": tools,
                    "skill": skill_name,
                })
    return cases


def load_should_not_trigger() -> list[dict]:
    """Parse "Should NOT trigger" tables from all eval.md files.

    Returns list of:
        {"prompt": str, "reason": str, "skill": str}
    """
    cases = []
    for eval_md in sorted(SKILLS_DIR.rglob("eval.md")):
        skill_name = eval_md.parent.name
        text = eval_md.read_text()

        match = re.search(
            r"##\s*Should\s+NOT\s+trigger\s*\n(.*?)(?=\n##|\Z)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if not match:
            continue

        for row in _parse_table_rows(match.group(1)):
            if len(row) < 2:
                continue
            prompt = _strip_quotes(row[0])
            reason = row[1].strip()
            if prompt:
                cases.append({
                    "prompt": prompt,
                    "reason": reason,
                    "skill": skill_name,
                })
    return cases
