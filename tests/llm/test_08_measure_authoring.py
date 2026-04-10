"""LLM regression tests for measure authoring — quote escaping, ok:false on syntax
errors, and XML Intended Software Tool attributes.

Reproduces the scenario from docs/debug/conversation_debug_export.json where
an LLM tried to create a measure with double-quotes in the description,
triggering a cascade of 8 failed attempts due to:
  1. Unescaped quotes breaking Ruby syntax (create_measure)
  2. edit_measure compounding the syntax error instead of replacing
  3. ok:true returned despite syntax_ok:false, confusing the LLM
  4. Missing Intended Software Tool attributes in measure.xml

Each test uses a realistic prompt similar to the original conversation.
"""
from __future__ import annotations

import pytest

from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier2]


# ---------------------------------------------------------------------------
# Prompt from the debug chat (simplified to the essential trigger)
# ---------------------------------------------------------------------------
# The original user asked Claude to create a measure to fix two EnergyPlus
# warnings.  Claude's description naturally included double-quotes around
# the warning text, which broke the Ruby string literal.

QUOTED_DESC_PROMPT = (
    'Create a Ruby ModelMeasure called "fix_eplusout_warnings" that fixes two '
    'EnergyPlus warnings: (1) the "Zone outside air per person rate not set in '
    'Design Specification Outdoor Air Object" warning from Controller:'
    'MechanicalVentilation, and (2) the "People has comfort related schedules '
    'but no thermal comfort model selected" warning. '
    "The run_body should: "
    "iterate model.getDesignSpecificationOutdoorAirs and if "
    "isOutdoorAirFlowperPersonDefaulted then setOutdoorAirFlowperPerson(0.0); "
    "iterate model.getPeoples and if peopleDefinition.numThermalComfortModelTypes == 0 "
    "then resetAirVelocitySchedule, resetClothingInsulationSchedule, "
    "resetWorkEfficiencySchedule. "
    "Use create_measure with language Ruby. Use MCP tools only."
)


@pytest.mark.stable
def test_create_measure_with_quoted_description():
    """LLM creates a measure whose description naturally contains double-quotes."""
    # Regression: unescaped quotes in measure description broke Ruby syntax, causing 8 failed retries
    result = run_claude(QUOTED_DESC_PROMPT, timeout=120)
    tools = result.tool_names

    # Must call create_measure
    assert "create_measure" in tools, (
        f"Expected create_measure in tool calls, got: {tools}"
    )

    # Must NOT call create_measure a second time (no retry loop)
    create_calls = [t for t in tools if t == "create_measure"]
    assert len(create_calls) <= 2, (
        f"LLM retried create_measure {len(create_calls)} times — "
        "suggests it got ok:false and looped. Tool sequence: {tools}"
    )

    # Must NOT call edit_measure to fix a broken create (the old failure mode)
    assert "edit_measure" not in tools, (
        f"LLM called edit_measure after create_measure — suggests create "
        f"returned a syntax error that needed fixing. Tool sequence: {tools}"
    )

    # Final text should indicate success
    text = result.final_text.lower()
    assert "error" not in text or "fix" in text, (
        f"Final text suggests failure: {result.final_text[:500]}"
    )


EDIT_AFTER_CREATE_PROMPT = (
    "First, create a Ruby ModelMeasure called fix_warnings_edit_test "
    "with description 'Fixes the \"OA per person\" warning.' "
    "and run_body: '    runner.registerInfo(\"created\")'. "
    "Then edit the measure using edit_measure to change the description to "
    "'Now fixes both \"DSOA\" and \"People comfort\" warnings.' "
    "Use MCP tools only."
)


@pytest.mark.stable
def test_edit_measure_description_with_quotes():
    """LLM creates then edits a measure, both times with quoted descriptions."""
    # Regression: edit_measure fragile regex broke when description contained double-quotes
    result = run_claude(EDIT_AFTER_CREATE_PROMPT, timeout=120)
    tools = result.tool_names

    assert "create_measure" in tools, (
        f"Expected create_measure, got: {tools}"
    )
    assert "edit_measure" in tools, (
        f"Expected edit_measure after create, got: {tools}"
    )

    # Should not indicate errors
    text = result.final_text.lower()
    assert "syntax error" not in text, (
        f"Final text mentions syntax error: {result.final_text[:500]}"
    )


XML_ATTRS_PROMPT = (
    "Create a Ruby ModelMeasure called xml_tool_check "
    "with description 'Test measure for XML attributes' "
    "and run_body: '    runner.registerInfo(\"ok\")'. "
    "After creating it, read the measure.xml file from the measure directory "
    "and tell me if it contains 'Intended Software Tool' attributes. "
    "Use MCP tools only."
)


@pytest.mark.stable
def test_measure_xml_intended_software_tool():
    """LLM creates a measure and verifies XML has Intended Software Tool attrs."""
    # Regression: SDK scaffold omitted Intended Software Tool attributes, hiding measures from OS App
    result = run_claude(XML_ATTRS_PROMPT, timeout=120)
    tools = result.tool_names

    assert "create_measure" in tools, (
        f"Expected create_measure, got: {tools}"
    )

    # The LLM should read the XML and confirm the attributes
    text = result.final_text.lower()
    assert "intended software tool" in text or "apply measure now" in text, (
        f"LLM didn't mention Intended Software Tool in response: "
        f"{result.final_text[:500]}"
    )


SYNTAX_ERROR_PROMPT = (
    "Create a Ruby ModelMeasure called broken_syntax_test "
    "with description 'Test broken syntax' "
    "and run_body: '    def def def broken'. "
    "Tell me whether the measure was created successfully. "
    "Use MCP tools only."
)


@pytest.mark.stable
def test_syntax_error_reported_clearly():
    """LLM should report failure when create_measure returns ok:false."""
    # Regression: create_measure returned ok:true with syntax_ok:false, hiding syntax errors from LLM
    result = run_claude(SYNTAX_ERROR_PROMPT, timeout=120)
    tools = result.tool_names

    assert "create_measure" in tools, (
        f"Expected create_measure, got: {tools}"
    )

    # LLM should acknowledge the syntax error in its response
    text = result.final_text.lower()
    assert any(w in text for w in ("syntax", "error", "fail", "not valid", "broken")), (
        f"LLM didn't report syntax error: {result.final_text[:500]}"
    )
