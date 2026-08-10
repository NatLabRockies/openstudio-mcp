"""Build Fig 4 v2 + Table 4 v2 images for the revised section 3.2.

Panel (a): outcome vs routing pass per model, full arm, with Wilson CIs on
outcome and the routing-outcome gap annotated (the H6 picture).
Panel (b): outcome pass by prompt-specificity level L1/L2/L3, full arm.
Table 4: outcome [CI] vs routing per model/arm (matches the draft table).

Data is computed live from results/prod-2026-08b/*.json so the figure can
never drift from the leg data. Outputs to paper/figures/*_v2.{png,svg}.
"""
from __future__ import annotations

import glob
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results" / "prod-2026-08b"
OUT = Path(__file__).resolve().parent / "figures"

MODELS = [  # (file prefix, display name, bar color) — blues=Claude, greens=OpenAI
    ("claude-opus-4-6", "Opus 4.6", "#08306b"),
    ("claude-sonnet-4-6", "Sonnet 4.6", "#2b7bba"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5", "#a8cbe4"),
    ("gpt-5.4", "GPT-5.4", "#1a7d43"),
    ("gpt-5.4-mini", "GPT-5.4-mini", "#8fd0a8"),
]


def wilson(s: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = s / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def cell(prefix: str, arm: str) -> dict:
    """Pooled outcome/routing counts + per-level outcome for one (model, arm)."""
    s = n = r = 0
    lv = {L: [0, 0] for L in ("L1", "L2", "L3")}
    for f in glob.glob(str(RESULTS / f"{prefix}_{arm}_r*.json")):
        for t in json.load(open(f, encoding="utf-8"))["tests"]:
            if t.get("skipped"):
                continue
            n += 1
            s += int(t["passed"])
            if t["passed"] or t.get("failure_mode") == "outcome_mismatch":
                r += 1
            tid = t["test_id"]
            if "[" in tid and t.get("tier") == "progressive":
                level = tid.rsplit("_", 1)[-1].rstrip("]")
                if level in lv:
                    lv[level][1] += 1
                    lv[level][0] += int(t["passed"])
    return {"s": s, "n": n, "r": r, "levels": lv}


def build_figure() -> None:
    cells = {name: cell(pref, "full") for pref, name, _c in MODELS}
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(12.5, 5.0))
    fig.subplots_adjust(left=0.06, right=0.99, top=0.82, bottom=0.14, wspace=0.18)

    # ── (a) outcome vs routing, full arm ────────────────────────────────
    xs = range(len(MODELS))
    for i, (_pref, name, color) in enumerate(MODELS):
        c = cells[name]
        out_p = c["s"] / c["n"] * 100
        rou_p = c["r"] / c["n"] * 100
        lo, hi = wilson(c["s"], c["n"])
        ax_a.bar(i - 0.2, rou_p, width=0.38, color="white", edgecolor=color,
                 linewidth=1.4, hatch="//", zorder=2)
        ax_a.bar(i + 0.2, out_p, width=0.38, color=color, zorder=2)
        ax_a.errorbar(i + 0.2, out_p, yerr=[[out_p - lo * 100], [hi * 100 - out_p]],
                      fmt="none", ecolor="#444444", capsize=3, linewidth=1.1,
                      zorder=3)
        ax_a.annotate(f"gap {rou_p - out_p:.1f}", (i, max(rou_p, hi * 100) + 2.5),
                      ha="center", fontsize=9.5, color="#333333")
    ax_a.set_xticks(list(xs))
    ax_a.set_xticklabels([name for _p, name, _c in MODELS], fontsize=10)
    ax_a.set_ylim(0, 112)
    ax_a.set_yticks([0, 25, 50, 75, 100])
    ax_a.set_ylabel("Pass rate (%)", fontsize=12)
    ax_a.set_title("(a) Routing vs outcome pass, full configuration",
                   loc="left", fontsize=13)

    # ── (b) outcome by prompt-specificity level, full arm ───────────────
    levels = ["L1", "L2", "L3"]
    width = 0.15
    for i, (_pref, name, color) in enumerate(MODELS):
        lv = cells[name]["levels"]
        rates = [lv[L][0] / lv[L][1] * 100 for L in levels]
        pos = [j + (i - 2) * width for j in range(len(levels))]
        ax_b.bar(pos, rates, width=width * 0.92, color=color, zorder=2)
        for x, v in zip(pos, rates):
            ax_b.annotate(f"{v:.0f}", (x, v + 1.5), ha="center", fontsize=8,
                          color="#333333")
    ax_b.set_xticks(range(len(levels)))
    ax_b.set_xticklabels(["L1\n(vague)", "L2\n(moderate)", "L3\n(tool named)"],
                         fontsize=10)
    ax_b.set_ylim(0, 112)
    ax_b.set_yticks([0, 25, 50, 75, 100])
    ax_b.set_title("(b) Outcome pass by prompt specificity",
                   loc="left", fontsize=13)

    for ax in (ax_a, ax_b):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", color="#d9e2ec", linewidth=0.8, zorder=0)

    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _p, _n, c in MODELS]
    handles.append(plt.Rectangle((0, 0), 1, 1, facecolor="white",
                                 edgecolor="#555555", hatch="//"))
    labels = [name for _p, name, _c in MODELS] + ["routing gate only"]
    fig.legend(handles, labels, loc="upper center", ncol=6, frameon=False,
               fontsize=10.5, bbox_to_anchor=(0.5, 0.995))

    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "fig4_benchmark_v2.png", dpi=170)
    fig.savefig(OUT / "fig4_benchmark_v2.svg")
    plt.close(fig)


ARMS = [  # (model prefix, display, arm key, arm display)
    ("claude-opus-4-6", "Opus 4.6", "full", "full"),
    ("claude-opus-4-6", "Opus 4.6", "nodiscovery", "no tool search"),
    ("claude-opus-4-6", "Opus 4.6", "nodiscovery-noskills", "no search, no skills"),
    ("claude-sonnet-4-6", "Sonnet 4.6", "full", "full"),
    ("claude-sonnet-4-6", "Sonnet 4.6", "nodiscovery", "no tool search"),
    ("claude-sonnet-4-6", "Sonnet 4.6", "noskills", "no skills"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5", "full", "full"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5", "nodiscovery", "no tool search"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5", "noskills", "no skills"),
    ("gpt-5.4", "GPT-5.4", "full", "full (native schema load)"),
    ("gpt-5.4", "GPT-5.4", "noskills", "no skills"),
    ("gpt-5.4-mini", "GPT-5.4-mini", "full", "full (native schema load)"),
    ("gpt-5.4-mini", "GPT-5.4-mini", "noskills", "no skills"),
]


def build_table() -> None:
    rows = []
    for pref, disp, arm, armdisp in ARMS:
        c = cell(pref, arm)
        lo, hi = wilson(c["s"], c["n"])
        rows.append([disp, armdisp,
                     f"{c['s'] / c['n'] * 100:.1f} [{lo * 100:.1f}, {hi * 100:.1f}]",
                     f"{c['r'] / c['n'] * 100:.1f}",
                     f"{c['n']}"])
    header = ["Model", "Assistance arm", "Outcome pass % [95% CI]",
              "Routing pass %", "n"]

    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    ax.axis("off")
    tbl = ax.table(cellText=rows, colLabels=header, loc="center",
                   cellLoc="center",
                   colWidths=[0.16, 0.28, 0.28, 0.16, 0.07])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.scale(1, 1.45)
    for (r, c0), cellobj in tbl.get_celld().items():
        cellobj.set_edgecolor("#c8c8c8")
        if r == 0:
            cellobj.set_facecolor("#eef2f7")
            cellobj.set_text_props(weight="bold")
        elif rows[r - 1][1].startswith("full"):
            cellobj.set_facecolor("#f7fafc")
    ax.set_title("Table 4. Outcome-graded vs routing-only pass rates, "
                 "18 tasks x 3 repeats per cell, over attempted tasks.",
                 fontsize=11, loc="left", pad=14)
    fig.tight_layout()
    fig.savefig(OUT / "table4_v2.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    build_figure()
    build_table()
    print(f"wrote {OUT / 'fig4_benchmark_v2.png'}, .svg, {OUT / 'table4_v2.png'}")
