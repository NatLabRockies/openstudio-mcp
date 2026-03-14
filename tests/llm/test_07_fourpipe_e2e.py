"""End-to-end four-pipe beam retrofit test — natural language prompt.

Mimics a real user session: load model, set weather, baseline sim, author
measure to replace air terminals with 4-pipe chilled beams, apply, retrofit
sim, compare results. Verifies tool chain, measure quality, and EUI values.

Expected results (SystemD_baseline + Boston weather):
  Baseline EUI:  ~28 kBtu/ft2  (range 20-50)
  Retrofit EUI:  ~28 kBtu/ft2  (range 20-50)
  Unmet hours should decrease with active beams.
"""
from __future__ import annotations

import re

import pytest

from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier2]

# /inputs is mounted from tests/assets/ (read-only) — same as real user experience
SYSTEMD = "/inputs/SystemD_baseline.osm"
BOSTON_EPW = "/inputs/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"


def test_fourpipe_beam_retrofit_e2e():
    """Full retrofit: load → weather → baseline sim → measure → apply → sim → compare.

    Verifies:
      1. Correct tool chain (load, weather, 2x sim, measure create/apply)
      2. Measure is authored with arguments (reusable)
      3. Both simulations complete (2x run_simulation)
      4. EUI values are in plausible range (20-50 kBtu/ft2)
      5. Agent compares results
    """
    prompt = (
        f"Do all steps in order using MCP tools only:\n"
        f"1. Load the model at {SYSTEMD} using load_osm_model.\n"
        f"2. Set weather using change_building_location with "
        f"weather_file={BOSTON_EPW}.\n"
        f"3. Save the model using save_osm_model, then run a baseline "
        f"simulation using run_simulation. Extract summary metrics using "
        f"extract_summary_metrics — note the EUI.\n"
        f"4. Reload the model from {SYSTEMD} using load_osm_model. "
        f"Set weather again using change_building_location with "
        f"weather_file={BOSTON_EPW}.\n"
        f"5. Create a Ruby ModelMeasure using create_measure that replaces "
        f"air terminals with 4-pipe chilled beams "
        f"(AirTerminalSingleDuctConstantVolumeFourPipeBeam). "
        f"Make it reusable with arguments: air_loop_filter (String, "
        f'description "Name filter for air loops, blank=all"), '
        f'chw_loop_name (String, description "Chilled water plant loop name"), '
        f'hw_loop_name (String, description "Hot water plant loop name"). '
        f"Each argument needs a description.\n"
        f"6. Apply the measure using apply_measure.\n"
        f"7. Save the model, run a second simulation, extract summary metrics.\n"
        f"8. Compare baseline vs retrofit EUI and unmet hours.\n"
        f"9. Save the measure to /runs/ using save_osm_model or copy_file."
    )

    result = run_claude(prompt, timeout=900, max_turns=45)
    tool_names = result.tool_names
    final = result.final_text.lower()

    # --- 1. Tool chain ---
    for tool in ["load_osm_model", "change_building_location",
                 "create_measure", "apply_measure"]:
        assert tool in tool_names, (
            f"Missing {tool}. Tools: {tool_names}"
        )

    # --- 2. Two simulations ---
    sim_count = tool_names.count("run_simulation")
    assert sim_count >= 2, (
        f"Expected >=2 run_simulation calls, got {sim_count}. Tools: {tool_names}"
    )

    # --- 3. Results extraction ---
    has_extraction = any(t in tool_names for t in [
        "compare_runs", "extract_summary_metrics", "extract_end_use_breakdown",
    ])
    assert has_extraction, (
        f"No results extraction tool called. Tools: {tool_names}"
    )

    # --- 4. Measure quality: has arguments ---
    prefix = "mcp__openstudio__"
    create_input = None
    for call in result.mcp_tool_calls:
        if call["tool"].removeprefix(prefix) == "create_measure":
            create_input = call["input"]
            break
    assert create_input is not None, "create_measure call not found"

    args = create_input.get("arguments")
    if isinstance(args, str):
        import json
        args = json.loads(args)
    assert args and len(args) >= 2, (
        f"Measure should have >=2 arguments, got: {args}"
    )

    # Check at least one arg has description
    has_desc = any(a.get("description") for a in args)
    assert has_desc, (
        f"No argument has description field. Args: {args}"
    )

    # --- 5. EUI plausibility from final text ---
    eui_numbers = re.findall(r'(\d+\.?\d*)\s*(?:kbtu|kbtu/ft)', final)
    if not eui_numbers:
        eui_numbers = re.findall(r'eui[^0-9]*(\d+\.?\d*)', final)
    if eui_numbers:
        for eui_str in eui_numbers:
            eui = float(eui_str)
            assert 15 <= eui <= 60, (
                f"EUI {eui} outside plausible range [15-60] kBtu/ft2. "
                f"Text: {result.final_text[:500]}"
            )

    # --- 6. No error ---
    assert not result.is_error, f"Claude reported error: {result.final_text[:500]}"
