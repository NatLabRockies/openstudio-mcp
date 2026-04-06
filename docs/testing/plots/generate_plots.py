"""Generate LLM test benchmark plots.

Data sources:
- Runs 1-13: docs/testing/llm-test-benchmark.md run-history table
- Run 14 (2026-03-28): docs/sweeps/sonnet-2026-03-28/benchmark.json (+ haiku/opus)
- Run 15 (2026-04-05): docs/sweeps/codemode-off-2026-04-05/benchmark.json
- Run 16 (2026-04-05): docs/sweeps/codemode-on-2026-04-05/benchmark.json (experiment)

Run from repo root:
    python docs/testing/plots/generate_plots.py
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from pathlib import Path

OUT = Path(__file__).parent

plt.rcParams.update(
    {
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 120,
    }
)

COLOR_PASS = "#2e7d32"     # green
COLOR_WARN = "#ef6c00"     # orange
COLOR_FAIL = "#c62828"     # red
COLOR_LINE = "#1565c0"     # blue
COLOR_ALT = "#7b1fa2"      # purple
COLOR_EXP = "#546e7a"      # blue-gray (experimental)


# -------------------------------------------------------------------- #
# 1. Run history timeline                                              #
# -------------------------------------------------------------------- #
def run_history() -> None:
    # Runs 1-15 are the main sonnet progression. Run 16 (CodeMode ON) is
    # plotted as an experimental outlier in a different color.
    runs = list(range(1, 16))
    rates = [
        44.0, 83.3, 91.1, 93.3, 96.3, 96.2, 97.5, 92.0, 100.0, 96.5,
        95.9, 95.9, 95.8,
        94.4,   # Run 14: 2026-03-28 sonnet 170/180 (full suite)
        95.3,   # Run 15: 2026-04-05 codemode-OFF 123/129 (progressive-only)
    ]
    tests = [
        50, 90, 90, 90, 107, 159, 159, 25, 9, 172, 171, 170, 230,
        180, 129,
    ]
    dates = [
        "03-05", "03-06", "03-07", "03-07", "03-10", "03-11", "03-12",
        "03-13", "03-19", "03-19", "03-20", "03-20", "03-26",
        "03-28", "04-05",
    ]

    # Experimental outlier: Run 16 April 5 CodeMode ON
    exp_run = 16
    exp_rate = 24.0
    exp_tests = 129

    inflections = [
        (2,  83.3, "A"),
        (3,  91.1, "B"),
        (6,  96.2, "C"),
        (14, 94.4, "D"),
    ]
    inflection_labels = {
        "A": "+system prompt (anti-loop guidance)",
        "B": "+tool description improvements",
        "C": "+progressive tier introduced (L1/L2/L3)",
        "D": "cross-model sweep (sonnet/haiku/opus)",
    }

    fig, ax1 = plt.subplots(figsize=(13, 6.5))

    ax2 = ax1.twinx()
    all_runs = runs + [exp_run]
    all_tests = tests + [exp_tests]
    bar_h = ax2.bar(all_runs, all_tests, alpha=0.18, color=COLOR_WARN,
                    zorder=1, width=0.6, label="Tests run (right axis)")
    ax2.set_ylabel("Tests run (bars)", color=COLOR_WARN)
    ax2.tick_params(axis="y", labelcolor=COLOR_WARN)
    ax2.set_ylim(0, max(all_tests) * 1.45)
    ax2.spines["top"].set_visible(False)

    line_h, = ax1.plot(runs, rates, marker="o", linewidth=2.5, markersize=9,
                       color=COLOR_LINE, zorder=3,
                       label="Pass rate — sonnet, default config")
    ax1.fill_between(runs, rates, alpha=0.08, color=COLOR_LINE, zorder=2)

    # Experimental point + dashed connector
    exp_h = ax1.scatter([exp_run], [exp_rate], marker="X", s=170,
                        color=COLOR_FAIL, zorder=4,
                        label="Run 16 — CodeMode ON (A/B experiment, excluded from main line)")
    ax1.plot([runs[-1], exp_run], [rates[-1], exp_rate],
             linestyle=":", color=COLOR_FAIL, linewidth=1.5, alpha=0.6, zorder=3)
    ax1.text(exp_run, exp_rate - 3, "CodeMode ON\n24.0% (outlier)",
             ha="center", va="top", fontsize=8.5, color=COLOR_FAIL, fontweight="bold")

    target_h = ax1.axhline(95, color=COLOR_PASS, linestyle="--", alpha=0.6,
                           linewidth=1.5, label="95% target")

    for run_idx, rate, letter in inflections:
        ax1.scatter(run_idx, rate, s=260, facecolor="white",
                    edgecolor=COLOR_FAIL, linewidth=2, zorder=5)
        ax1.text(run_idx, rate, letter, ha="center", va="center",
                 fontsize=10, fontweight="bold", color=COLOR_FAIL, zorder=6)

    ax1.set_xlabel("Run # (date below)")
    ax1.set_ylabel("Pass rate (%)", color=COLOR_LINE)
    ax1.set_ylim(18, 110)
    xticks = all_runs
    ax1.set_xticks(xticks)
    xlabels = [f"{r}\n{d}" for r, d in zip(runs, dates)] + ["16\n04-05"]
    ax1.set_xticklabels(xlabels, fontsize=8.5)
    ax1.tick_params(axis="y", labelcolor=COLOR_LINE)
    ax1.grid(axis="y", alpha=0.3, linestyle="--")

    legend_items = [line_h, exp_h, bar_h, target_h]
    for letter, text in inflection_labels.items():
        legend_items.append(
            Line2D([0], [0], marker="o", markerfacecolor="white",
                   markeredgecolor=COLOR_FAIL, markersize=10, linewidth=0,
                   label=f"{letter}: {text}")
        )
    ax1.legend(handles=legend_items, loc="lower center", fontsize=8.3,
               framealpha=0.95, ncol=2)

    ax1.set_title("LLM Test Suite Pass Rate — Run History "
                  "(Runs 1–16, 2026-03-05 → 2026-04-05)")
    fig.tight_layout()
    fig.savefig(OUT / "run_history.png", bbox_inches="tight")
    plt.close(fig)


# -------------------------------------------------------------------- #
# 2. Progressive L1/L2/L3 — Run 15 (2026-04-05 codemode-OFF)           #
# -------------------------------------------------------------------- #
def progressive_l1_l2_l3() -> None:
    levels = ["L1\n(vague)", "L2\n(moderate)", "L3\n(explicit)"]
    passed = [40, 42, 41]
    total = 43
    rates = [p / total * 100 for p in passed]

    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 6),
                                     gridspec_kw={"width_ratios": [1, 1.5]})

    bars = ax_a.bar(levels, rates, color=[COLOR_FAIL, COLOR_WARN, COLOR_PASS],
                    edgecolor="black", linewidth=0.5)
    for bar, p in zip(bars, passed):
        ax_a.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                  f"{p}/{total}\n({bar.get_height():.1f}%)",
                  ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax_a.set_ylabel("Pass rate (%)")
    ax_a.set_ylim(0, 118)
    ax_a.set_title("Progressive Tier Pass Rate by Prompt Specificity\n"
                   "Run 15 (2026-04-05, sonnet) — 43 operations × 3 levels")
    ax_a.grid(axis="y", alpha=0.3, linestyle="--")
    ax_a.axhline(100, color="gray", linestyle=":", alpha=0.4)

    level_legend = [
        mpatches.Patch(color=COLOR_FAIL, label="L1 — vague keywords only"),
        mpatches.Patch(color=COLOR_WARN, label="L2 — moderate domain context"),
        mpatches.Patch(color=COLOR_PASS, label="L3 — explicit tool name"),
    ]
    ax_a.legend(handles=level_legend, loc="lower left", fontsize=8.5, framealpha=0.95)

    # Right: Run 15 problem cases (the only 6 failures / 129 tests)
    cases = [
        ("thermal_zones", 0, 1, 1),         # L1 fail
        ("test_measure", 0, 1, 1),          # L1 fail
        ("zone_equipment_priority", 1, 1, 0),  # L3 fail
        ("edit_measure", 0, 0, 0),          # all 3 fail (regression)
    ]
    names = [c[0] for c in cases]
    l1 = [c[1] for c in cases]
    l2 = [c[2] for c in cases]
    l3 = [c[3] for c in cases]
    x = np.arange(len(names))
    w = 0.26
    ax_b.bar(x - w, l1, w, label="L1 (vague)", color=COLOR_FAIL,
             edgecolor="black", linewidth=0.3)
    ax_b.bar(x, l2, w, label="L2 (moderate)", color=COLOR_WARN,
             edgecolor="black", linewidth=0.3)
    ax_b.bar(x + w, l3, w, label="L3 (explicit)", color=COLOR_PASS,
             edgecolor="black", linewidth=0.3)
    ax_b.set_xticks(x)
    ax_b.set_xticklabels(names, rotation=12, ha="right", fontsize=9)
    ax_b.set_ylim(0, 1.35)
    ax_b.set_yticks([0, 1])
    ax_b.set_yticklabels(["FAIL", "PASS"])
    ax_b.set_title("Problem Cases — Run 15 failures\n"
                   "(39/43 operations pass all 3 levels; edit_measure is an all-level regression)")
    ax_b.legend(loc="upper right", fontsize=8.5, framealpha=0.95)
    ax_b.grid(axis="y", alpha=0.3, linestyle="--")

    fig.tight_layout()
    fig.savefig(OUT / "progressive_l1_l2_l3.png", bbox_inches="tight")
    plt.close(fig)


# -------------------------------------------------------------------- #
# 3. Tier pass rates — Run 14 (2026-03-28 sonnet full suite)           #
# -------------------------------------------------------------------- #
def tier_pass_rates() -> None:
    tiers = ["setup", "tier1\n(no model)", "tier2\n(workflows)", "tier3\n(skill evals)",
             "tier4\n(guardrails)", "progressive\n(L1/L2/L3)"]
    # Run 14: 2026-03-28 sonnet
    passed = [6, 4, 33, 21, 3, 103]
    total = [6, 4, 37, 26, 3, 104]
    rates = [p / t * 100 for p, t in zip(passed, total)]

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = [COLOR_PASS if r >= 95 else (COLOR_WARN if r >= 85 else COLOR_FAIL) for r in rates]
    bars = ax.bar(tiers, rates, color=colors, edgecolor="black", linewidth=0.5)

    for bar, p, t in zip(bars, passed, total):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.3,
                f"{p}/{t}\n({bar.get_height():.1f}%)",
                ha="center", va="bottom", fontsize=9.5, fontweight="bold")

    target_h = ax.axhline(95, color=COLOR_PASS, linestyle="--", alpha=0.6,
                          linewidth=1.5, label="95% target")

    ax.set_ylabel("Pass rate (%)")
    ax.set_ylim(0, 118)
    ax.set_title("LLM Test Pass Rate by Tier — Run 14 (2026-03-28, sonnet)\n"
                 "170/180 = 94.4% overall, full suite incl. expanded progressive tier")
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    color_legend = [
        mpatches.Patch(color=COLOR_PASS, label="≥ 95% (on target)"),
        mpatches.Patch(color=COLOR_WARN, label="85–94% (warning)"),
        mpatches.Patch(color=COLOR_FAIL, label="< 85% (attention)"),
        target_h,
    ]
    ax.legend(handles=color_legend, loc="lower right", fontsize=9, framealpha=0.95)

    fig.tight_layout()
    fig.savefig(OUT / "tier_pass_rates.png", bbox_inches="tight")
    plt.close(fig)


# -------------------------------------------------------------------- #
# 4. Token profile — from 2026-03-28 sonnet per-tier averages          #
# -------------------------------------------------------------------- #
def token_profile() -> None:
    tiers = ["setup", "tier1", "tier2", "tier3", "tier4", "progressive"]
    # Per-test averages (actual values from sonnet-2026-03-28/benchmark.json)
    input_tok  = [10, 5, 16, 10, 12, 10]
    output_tok = [771, 318, 3315, 910, 2496, 869]
    cache_tok  = [98_124, 34_137, 216_796, 89_930, 186_112, 84_657]
    cost       = [0.087, 0.047, 0.179, 0.082, 0.162, 0.087]
    turns      = [5.5, 2.2, 10.5, 5.8, 8.7, 5.9]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    x = np.arange(len(tiers))
    axes[0].bar(x, cache_tok, color="#90caf9", edgecolor="black", linewidth=0.3,
                label="cache-read (tool defs served from cache)")
    axes[0].bar(x, output_tok, bottom=cache_tok, color=COLOR_WARN,
                edgecolor="black", linewidth=0.3, label="output (model-generated)")
    axes[0].bar(x, input_tok,
                bottom=[c + o for c, o in zip(cache_tok, output_tok)],
                color=COLOR_LINE, edgecolor="black", linewidth=0.3,
                label="input (fresh tokens sent)")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(tiers, fontsize=9)
    axes[0].set_ylabel("Tokens per test (log scale)")
    axes[0].set_yscale("log")
    axes[0].set_title("Token Profile by Tier — per-test averages\n"
                      "Run 14 (2026-03-28 sonnet) — cache-read dominates by 100×+")
    axes[0].legend(loc="upper left", fontsize=9, framealpha=0.95)
    axes[0].grid(axis="y", alpha=0.3, linestyle="--", which="both")

    ax_r = axes[1]
    ax_r2 = ax_r.twinx()
    bars_cost = ax_r.bar(x - 0.2, cost, 0.4, color=COLOR_LINE,
                         edgecolor="black", linewidth=0.3,
                         label="notional cost per test (USD, left)")
    bars_turns = ax_r2.bar(x + 0.2, turns, 0.4, color=COLOR_WARN,
                           edgecolor="black", linewidth=0.3,
                           label="avg conversation turns (right)")
    for bar, c in zip(bars_cost, cost):
        ax_r.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.004,
                  f"${c:.2f}", ha="center", va="bottom", fontsize=8)
    for bar, t in zip(bars_turns, turns):
        ax_r2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,
                   f"{t:.1f}", ha="center", va="bottom", fontsize=8)
    ax_r.set_xticks(x)
    ax_r.set_xticklabels(tiers, fontsize=9)
    ax_r.set_ylabel("Notional cost per test (USD)", color=COLOR_LINE)
    ax_r.tick_params(axis="y", labelcolor=COLOR_LINE)
    ax_r2.set_ylabel("Avg turns per test", color=COLOR_WARN)
    ax_r2.tick_params(axis="y", labelcolor=COLOR_WARN)
    ax_r.set_title("Cost & Turn Count by Tier\n"
                   "(free on Claude Max — cost is notional API pricing)")
    ax_r.set_ylim(0, max(cost) * 1.3)
    ax_r2.set_ylim(0, max(turns) * 1.3)

    h1, l1 = ax_r.get_legend_handles_labels()
    h2, l2 = ax_r2.get_legend_handles_labels()
    ax_r.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9, framealpha=0.95)

    fig.tight_layout()
    fig.savefig(OUT / "token_profile.png", bbox_inches="tight")
    plt.close(fig)


# -------------------------------------------------------------------- #
# 5. Failure modes — Run 14 (full suite) + historical stacked          #
# -------------------------------------------------------------------- #
def failure_modes() -> None:
    # Run 14 (2026-03-28 sonnet) failure modes
    modes_short = ["wrong_tool", "timeout", "no_mcp_tool"]
    counts = [9, 1, 0]
    descriptions = [
        "eval + workflow:\n2× qaqc, 2× troubleshoot\n1× energy-report,\n1× e2e workflow,\n2× measure quality,\n1× misc",
        "1× systemd\nfourpipebeam e2e\n(exceeded wall clock)",
        "—",
    ]

    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 6),
                                     gridspec_kw={"width_ratios": [1, 1.3]})

    colors = [COLOR_FAIL, COLOR_WARN, COLOR_ALT]
    bars = ax_a.bar(modes_short, counts, color=colors, edgecolor="black", linewidth=0.5)
    for bar, d in zip(bars, descriptions):
        if bar.get_height() > 0:
            ax_a.text(bar.get_x() + bar.get_width() / 2, bar.get_height() / 2,
                      d, ha="center", va="center",
                      fontsize=8.5, color="white", fontweight="bold")
        else:
            ax_a.text(bar.get_x() + bar.get_width() / 2, 0.2,
                      "0", ha="center", va="bottom",
                      fontsize=9, color="black")
    ax_a.set_ylabel("Failure count")
    ax_a.set_title("Run 14 Failures by Mode\n"
                   "(10 failed / 180 attempted = 94.4% pass)")
    ax_a.set_ylim(0, max(counts) + 2)
    ax_a.grid(axis="y", alpha=0.3, linestyle="--")

    mode_legend = [
        mpatches.Patch(color=COLOR_FAIL,
                       label="wrong_tool: MCP tool called, but not expected one"),
        mpatches.Patch(color=COLOR_WARN,
                       label="timeout: exceeded wall clock before finishing"),
        mpatches.Patch(color=COLOR_ALT,
                       label="no_mcp_tool: agent called no MCP tool at all"),
    ]
    ax_a.legend(handles=mode_legend, loc="upper right", fontsize=8, framealpha=0.95)

    # Right: historical pass/fail stacked
    runs = list(range(1, 17))
    passed = [22, 75, 82, 84, 103, 153, 155, 23, 9, 166, 164, 163, 160, 170, 123, 31]
    total  = [50, 90, 90, 90, 107, 159, 159, 25, 9, 172, 171, 170, 167, 180, 129, 129]
    failed = [t - p for p, t in zip(passed, total)]

    # Run 16 is experimental — shade differently
    regular = 15
    ax_b.bar(runs[:regular], passed[:regular], label="passed",
             color=COLOR_PASS, edgecolor="black", linewidth=0.3)
    ax_b.bar(runs[:regular], failed[:regular], bottom=passed[:regular],
             label="failed", color=COLOR_FAIL, edgecolor="black", linewidth=0.3)
    # Run 16 (CodeMode ON) in muted colors
    ax_b.bar([runs[regular]], [passed[regular]], color=COLOR_PASS,
             edgecolor="black", linewidth=0.3, alpha=0.4,
             label="passed (experiment)")
    ax_b.bar([runs[regular]], [failed[regular]], bottom=[passed[regular]],
             color=COLOR_FAIL, edgecolor="black", linewidth=0.3, alpha=0.4,
             label="failed (experiment)")

    for r, p, f in zip(runs, passed, failed):
        if f > 0:
            ax_b.text(r, p + f + 3, str(f), ha="center", va="bottom",
                      fontsize=8, color=COLOR_FAIL, fontweight="bold")

    ax_b.set_xticks(runs)
    ax_b.set_xlabel("Run #")
    ax_b.set_ylabel("Test count (attempted)")
    ax_b.set_title("Pass / Fail Absolute Counts by Run (1–16)\n"
                   "failure count labeled above each bar; Run 16 = CodeMode ON experiment")
    ax_b.legend(loc="upper left", fontsize=8.5, framealpha=0.95)
    ax_b.grid(axis="y", alpha=0.3, linestyle="--")

    fig.tight_layout()
    fig.savefig(OUT / "failure_modes.png", bbox_inches="tight")
    plt.close(fig)


# -------------------------------------------------------------------- #
# 6. NEW: Model comparison (2026-03-28 sonnet/haiku/opus sweep)        #
# -------------------------------------------------------------------- #
def model_comparison() -> None:
    models = ["haiku", "sonnet", "opus"]
    passed = [160, 170, 170]
    total = 180
    rates = [p / total * 100 for p in passed]
    cost = [11.21, 18.96, 32.23]
    duration_min = [79.6, 157.5, 184.6]

    # Per-tier breakdowns
    tiers = ["setup", "tier1", "tier2", "tier3", "tier4", "progressive"]
    sonnet_t = [100.0, 100.0, 89.2, 80.8, 100.0, 99.0]
    haiku_t  = [100.0, 100.0, 83.8, 73.1, 100.0, 93.3]
    opus_t   = [100.0, 100.0, 91.9, 73.1, 100.0, 100.0]

    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 6),
                                     gridspec_kw={"width_ratios": [1, 1.4]})

    # Left: overall pass rate + cost
    x = np.arange(len(models))
    w = 0.38
    ax_b2 = ax_a.twinx()
    bars_pass = ax_a.bar(x - w/2, rates, w, color=COLOR_PASS,
                         edgecolor="black", linewidth=0.4,
                         label="pass rate (left)")
    bars_cost = ax_b2.bar(x + w/2, cost, w, color=COLOR_LINE,
                          edgecolor="black", linewidth=0.4,
                          label="notional cost USD (right)")
    for bar, p, r in zip(bars_pass, passed, rates):
        ax_a.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                  f"{p}/{total}\n{r:.1f}%", ha="center", va="bottom",
                  fontsize=9, fontweight="bold")
    for bar, c, d in zip(bars_cost, cost, duration_min):
        ax_b2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                   f"${c:.2f}\n{d:.0f} min", ha="center", va="bottom",
                   fontsize=8.5)
    ax_a.set_xticks(x)
    ax_a.set_xticklabels(models)
    ax_a.set_ylabel("Pass rate (%)", color=COLOR_PASS)
    ax_a.tick_params(axis="y", labelcolor=COLOR_PASS)
    ax_b2.set_ylabel("Notional cost (USD)", color=COLOR_LINE)
    ax_b2.tick_params(axis="y", labelcolor=COLOR_LINE)
    ax_a.set_ylim(0, 115)
    ax_b2.set_ylim(0, max(cost) * 1.35)
    ax_a.set_title("Cross-Model Sweep — 2026-03-28\n"
                   "Same 180-test suite, retries=0, identical tool definitions")
    ax_a.grid(axis="y", alpha=0.3, linestyle="--")

    h1, l1 = ax_a.get_legend_handles_labels()
    h2, l2 = ax_b2.get_legend_handles_labels()
    ax_a.legend(h1 + h2, l1 + l2, loc="upper center",
                bbox_to_anchor=(0.5, -0.08), fontsize=9,
                framealpha=0.95, ncol=2)

    # Right: per-tier comparison
    x2 = np.arange(len(tiers))
    w2 = 0.26
    ax_b.bar(x2 - w2, haiku_t, w2, label="haiku",
             color="#90caf9", edgecolor="black", linewidth=0.3)
    ax_b.bar(x2,      sonnet_t, w2, label="sonnet",
             color=COLOR_LINE, edgecolor="black", linewidth=0.3)
    ax_b.bar(x2 + w2, opus_t, w2, label="opus",
             color=COLOR_ALT, edgecolor="black", linewidth=0.3)
    ax_b.axhline(95, color=COLOR_PASS, linestyle="--", alpha=0.5, label="95% target")
    ax_b.set_xticks(x2)
    ax_b.set_xticklabels(tiers, fontsize=9)
    ax_b.set_ylabel("Pass rate (%)")
    ax_b.set_ylim(0, 115)
    ax_b.set_title("Per-Tier Pass Rate by Model\n"
                   "(tier3 skill evals hit all 3 models — disambiguation gap)")
    ax_b.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08),
                fontsize=9, framealpha=0.95, ncol=4)
    ax_b.grid(axis="y", alpha=0.3, linestyle="--")

    fig.tight_layout()
    fig.savefig(OUT / "model_comparison.png", bbox_inches="tight")
    plt.close(fig)


# -------------------------------------------------------------------- #
# 7. NEW: CodeMode A/B experiment (2026-04-05)                         #
# -------------------------------------------------------------------- #
def codemode_ab() -> None:
    labels = ["CodeMode OFF\n(baseline)", "CodeMode ON\n(experiment)"]

    # Top-level
    passed = [123, 31]
    total = 129
    rates = [p / total * 100 for p in passed]

    # L1/L2/L3 breakdown
    l1_rates = [93.0, 18.6]
    l2_rates = [97.7, 27.9]
    l3_rates = [95.3, 25.6]

    # Cost / duration / ToolSearch
    cost = [9.29, 22.35]
    duration_min = [69, 168]
    toolsearch = [1.6, 5.8]
    output_tok = [127_859, 300_118]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5),
                             gridspec_kw={"width_ratios": [1, 1.4, 1.4]})

    # Left: overall pass rate
    ax = axes[0]
    colors = [COLOR_PASS, COLOR_FAIL]
    bars = ax.bar(labels, rates, color=colors, edgecolor="black", linewidth=0.5)
    for bar, p, r in zip(bars, passed, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                f"{p}/{total}\n{r:.1f}%", ha="center", va="bottom",
                fontsize=10, fontweight="bold")
    ax.axhline(95, color=COLOR_PASS, linestyle="--", alpha=0.5, label="95% target")
    ax.set_ylabel("Pass rate (%)")
    ax.set_ylim(0, 118)
    ax.set_title("Overall Pass Rate\n(same 129-test progressive suite)")
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    ax.legend(loc="upper right", fontsize=9, framealpha=0.95)

    # Middle: L1/L2/L3 by condition
    ax = axes[1]
    x = np.arange(2)
    w = 0.26
    ax.bar(x - w, l1_rates, w, label="L1 (vague)",
           color=COLOR_FAIL, edgecolor="black", linewidth=0.3)
    ax.bar(x,      l2_rates, w, label="L2 (moderate)",
           color=COLOR_WARN, edgecolor="black", linewidth=0.3)
    ax.bar(x + w,  l3_rates, w, label="L3 (explicit)",
           color=COLOR_PASS, edgecolor="black", linewidth=0.3)
    for i, (a, b, c) in enumerate(zip(l1_rates, l2_rates, l3_rates)):
        ax.text(i - w, a + 1.5, f"{a:.0f}%", ha="center", fontsize=8)
        ax.text(i,      b + 1.5, f"{b:.0f}%", ha="center", fontsize=8)
        ax.text(i + w,  c + 1.5, f"{c:.0f}%", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Pass rate (%)")
    ax.set_ylim(0, 115)
    ax.set_title("Pass Rate by Specificity Level\n(CodeMode regresses ~70pp at every level)")
    ax.legend(loc="upper right", fontsize=8.5, framealpha=0.95)
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    # Right: cost / duration / toolsearch calls
    ax = axes[2]
    metrics = ["cost\n(USD)", "duration\n(min)", "ToolSearch\ncalls/test", "output\ntokens (k)"]
    off_vals = [9.29, 69, 1.6, 127.9]
    on_vals  = [22.35, 168, 5.8, 300.1]
    # Normalize each metric so bars are comparable on one axis
    off_norm = [1.0, 1.0, 1.0, 1.0]
    on_norm  = [o / f for o, f in zip(on_vals, off_vals)]
    x = np.arange(len(metrics))
    w = 0.38
    ax.bar(x - w/2, off_norm, w, color=COLOR_PASS,
           edgecolor="black", linewidth=0.3, label="CodeMode OFF (baseline = 1×)")
    bars_on = ax.bar(x + w/2, on_norm, w, color=COLOR_FAIL,
                     edgecolor="black", linewidth=0.3, label="CodeMode ON")
    for bar, on_v, off_v in zip(bars_on, on_vals, off_vals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                f"{bar.get_height():.2f}×\n({on_v:.0f} vs {off_v:.0f})",
                ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontsize=9)
    ax.set_ylabel("Relative to CodeMode OFF (= 1.0)")
    ax.set_title("Resource Cost Multipliers\n(CodeMode ON is worse on every metric)")
    ax.set_ylim(0, max(on_norm) * 1.4)
    ax.axhline(1, color="gray", linestyle=":", alpha=0.5)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax.grid(axis="y", alpha=0.3, linestyle="--")

    fig.suptitle("FastMCP CodeMode A/B Experiment — 2026-04-05 (sonnet, 129 progressive tests)",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "codemode_ab.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    run_history()
    progressive_l1_l2_l3()
    tier_pass_rates()
    token_profile()
    failure_modes()
    model_comparison()
    codemode_ab()
    print(f"Wrote 7 plots to {OUT}")


if __name__ == "__main__":
    main()
