"""End-to-end HVAC-only system swap — natural language prompt, vendored measure.

Mimics the 2026-11-04 user session that exposed the hvac_only leak: load the
44-zone SystemD model, baseline sim, replace only the HVAC with a
standards-tuned VAV system, second sim, compare. The agent must discover
``hvac_only`` on ``create_typical_building`` from the tool docs / skills (the
prompt never names the argument), and the vendored measure must leave the
non-HVAC inputs alone (``non_hvac_changes == []``, same unmet-hours tolerance
in both runs).

Expected results (SystemD_baseline + Boston weather, sonnet, 2026-11-04):
  Baseline EUI:  28.17 kBtu/ft2 (pinned 28.21, same as test_07), 57 unmet hours
  Swap EUI:      39.04 kBtu/ft2 with ~3,960 unmet hours: the fixture's 24/7
                 Mech/Elec/Data/Stair zones end up on an AHU that follows the
                 occupancy schedule (see the troubleshoot skill). compare_runs
                 therefore reports comparable=False for the unmet-hours cap;
                 the test checks the tolerance and end-use parts, not that flag.
"""
from __future__ import annotations

import pytest

from .conftest import fail_with_mode, summary_metric_euis
from .runner import run_claude
from .verify import assert_sim_valid, verify_run

pytestmark = [pytest.mark.llm, pytest.mark.tier2]

# /inputs is mounted from tests/assets/ (read-only) — same as real user experience
SYSTEMD = "/inputs/SystemD_baseline.osm"
BOSTON_EPW = "/inputs/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
SYSTEM = "VAV air-cooled chiller with gas boiler reheat"

# SystemD_baseline + Boston, measured 2026-03-13 (test_07) — the swap must not move it.
BASELINE_EUI = 28.21
# Same model after the vendored hvac_only swap to SYSTEM (90.1-2019, CZ 5A),
# measured 2026-11-04 with openstudio-standards 0.8.5 (39.04; upstream's leaking
# swap gave ~67). Re-pin on OpenStudio, standards-gem or ComStock tag bump only.
HVAC_ONLY_SWAP_EUI = 39.04


def _calls(result, name: str) -> list[dict]:
    prefix = "mcp__openstudio__"
    return [c["input"] for c in result.mcp_tool_calls
            if c["tool"].removeprefix(prefix) == name]


def test_hvac_only_swap_e2e(request):
    """Full swap: load → weather → baseline sim → hvac_only swap → sim → compare."""
    # Validates: the agent reaches create_typical_building(hvac_only=True) from a
    # natural-language "replace only the HVAC" request, the vendored measure reports no
    # non-HVAC changes, and both runs simulate with the same unmet-hours tolerance
    prompt = (
        f"Do all steps in order using MCP tools only:\n"
        f"1. Load the model at {SYSTEMD} using load_osm_model.\n"
        f"2. Set weather using change_building_location with "
        f"weather_file={BOSTON_EPW}.\n"
        f"3. Save the model using save_osm_model, then run a baseline "
        f"simulation using run_simulation. Extract summary metrics using "
        f"extract_summary_metrics — note the EUI and unmet hours.\n"
        f"4. Replace ONLY the HVAC system with the standards-tuned system type "
        f'"{SYSTEM}" (template 90.1-2019, climate zone ASHRAE 169-2013-5A). '
        f"Loads, schedules, thermostats, constructions and infiltration must stay "
        f"exactly as modeled. Confirm from the tool response that nothing outside "
        f"the HVAC changed.\n"
        f"5. Save the model, run a second simulation, extract summary metrics.\n"
        f"6. Compare the two runs with compare_runs and report EUI and unmet-hours "
        f"deltas and whether the comparison is apples-to-apples."
    )

    result = run_claude(prompt, timeout=900, max_turns=45)
    tool_names = result.tool_names

    # --- 1. Tool chain ---
    for tool in ["load_osm_model", "change_building_location",
                 "create_typical_building", "compare_runs"]:
        if tool not in tool_names:
            fail_with_mode(request, "wrong_tool",
                           f"Missing {tool}. Tools: {tool_names}")

    # --- 2. Two simulations ---
    sim_count = tool_names.count("run_simulation")
    if sim_count < 2:
        fail_with_mode(request, "wrong_tool",
                       f"Expected >=2 run_simulation calls, got {sim_count}. Tools: {tool_names}")

    # --- 3. The swap call used hvac_only, not a full re-typical ---
    swap_inputs = _calls(result, "create_typical_building")
    assert swap_inputs, "create_typical_building call not found in MCP tool calls"
    swap_in = swap_inputs[-1]
    if swap_in.get("hvac_only") not in (True, "true", "True"):
        fail_with_mode(request, "wrong_args",
                       f"create_typical_building must be called with hvac_only=True, got {swap_in}")
    if "vav" not in str(swap_in.get("system_type", "")).lower():
        fail_with_mode(request, "wrong_args",
                       f"system_type should be the requested VAV system, got {swap_in.get('system_type')}")

    # --- 4. Vendored measure: HVAC replaced, nothing else reported changed ---
    swap_results = [r for r in result.results_for("create_typical_building") if r.get("ok")]
    if not swap_results:
        fail_with_mode(request, "tool_error",
                       f"create_typical_building never succeeded: "
                       f"{result.results_for('create_typical_building')}")
    swap = swap_results[-1]
    assert swap.get("hvac_only") is True, swap
    assert swap.get("non_hvac_changes") == [], (
        f"hvac_only swap must leave non-HVAC inputs untouched, got {swap.get('non_hvac_changes')}"
    )
    assert swap.get("non_hvac_changes_total") == 0, swap.get("non_hvac_changes_total")

    # --- 5. EUIs from tool results (not agent prose) ---
    euis = summary_metric_euis(result)
    if len(euis) < 2:
        fail_with_mode(
            request, "outcome_mismatch",
            f"Expected baseline + swap EUIs from extract_summary_metrics "
            f"results, got {euis} — a simulation likely failed. "
            f"Text: {result.final_text[:300]}",
        )
    if euis[0] != pytest.approx(BASELINE_EUI, rel=0.05):
        fail_with_mode(request, "outcome_mismatch",
                       f"Baseline EUI {euis[0]:.2f} outside 5% of pinned {BASELINE_EUI} kBtu/ft2")
    if euis[-1] != pytest.approx(HVAC_ONLY_SWAP_EUI, rel=0.05):
        fail_with_mode(request, "outcome_mismatch",
                       f"Swap EUI {euis[-1]:.2f} outside 5% of pinned {HVAC_ONLY_SWAP_EUI} kBtu/ft2")

    # --- 6. compare_runs saw the same reporting tolerance in both runs ---
    # (upstream wrote 1 R into the swapped model; the fork gates that step)
    cmp_results = [r for r in result.results_for("compare_runs") if r.get("ok")]
    if not cmp_results:
        fail_with_mode(request, "tool_error",
                       f"compare_runs never succeeded: {result.results_for('compare_runs')}")
    cmp = cmp_results[-1]
    tol = cmp["unmet_hours_tolerance_c"]
    assert tol["baseline"] == tol["retrofit"], (
        f"unmet-hours tolerance differs between runs: {tol}"
    )
    assert not [w for w in cmp["comparability_warnings"] if "tolerance" in w.lower()], (
        cmp["comparability_warnings"]
    )
    assert cmp["non_hvac_end_use_drift"] == [], (
        f"non-HVAC end uses moved after an HVAC-only swap: {cmp['non_hvac_end_use_drift']}"
    )

    # --- 7. D6 verifier: both sims independently valid (non-LLM session).
    # The swap run's unmet hours are not capped: SystemD has 24/7 zones served
    # by an AHU on the occupancy schedule (see troubleshoot skill), so a central
    # VAV leaves ~3,960 unmet hours there. The baseline keeps its cap.
    run_ids = [r.get("run_id") for r in result.results_for("run_simulation")
               if r.get("ok") and r.get("run_id")]
    if len(run_ids) < 2:
        fail_with_mode(request, "outcome_mismatch",
                       f"Expected 2 successful sims to verify, got run_ids: {run_ids}")
    try:
        assert_sim_valid(verify_run(run_ids[0]), eui_ref=BASELINE_EUI, max_unmet=300)
        assert_sim_valid(verify_run(run_ids[-1]), eui_ref=HVAC_ONLY_SWAP_EUI, max_unmet=None)
    except AssertionError as e:
        fail_with_mode(request, "outcome_mismatch", f"D6 verifier: {e}")

    # --- 8. No error ---
    assert not result.is_error, f"Claude reported error: {result.final_text[:500]}"
