"""Unit: the measure-authoring skill documents Python at parity with Ruby.

Reads the skill file directly (no Docker/OpenStudio). Guards the regression where
the skill carried Ruby-only worked examples and framed Python as "less common" —
steering the AI away from the fully-supported, tested Python measure path.
"""
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SKILL = (
    Path(__file__).resolve().parents[1]
    / ".claude" / "skills" / "measure-authoring" / "SKILL.md"
)


def test_skill_documents_python_run_body_patterns():
    # Regression: skill had only "Common run_body Patterns (Ruby)" and called
    # Python "less common"; Python ModelMeasures are fully supported + tested.
    text = SKILL.read_text(encoding="utf-8")

    # A dedicated Python patterns section with real Python idioms — not just the word "Python".
    assert "## Common run_body Patterns (Python)" in text, "missing Python patterns section"
    assert (
        "for z in model.getThermalZones():" in text
        or "for s in model.getSurfaces():" in text
    ), "Python section must show Python iteration syntax (for x in model.get...())"
    assert "str(" in text and ".name())" in text, \
        "must document OptionalString handling, e.g. str(obj.name())"
    assert "openstudio.model." in text, "must reference the Python SDK module path"


def test_skill_framing_no_longer_steers_away_from_python():
    # Regression: 'Python: Works but less common' nudged the AI to avoid Python.
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "less common" not in text, "drop the 'Python is less common' framing"
    assert "fully supported" in text, "state that both languages are fully supported"
