"""Conftest for LLM agent tests — markers, guards, fixtures, retry, and benchmarks.

This conftest provides:
  1. Custom pytest markers (llm, tier1-4) for selective test execution
  2. Guard fixture that skips tests unless LLM_TESTS_ENABLED=1
  3. Prompt budget tracking to prevent runaway test runs
  4. Shared model paths (Docker-internal) used across all tiers
  5. Retry logic for non-deterministic LLM test failures
  6. Benchmark results written to LLM_TESTS_RUNS_DIR/benchmark.json

Environment variables:
  LLM_TESTS_ENABLED  — set to "1" to enable LLM tests (default: disabled)
  LLM_TESTS_MAX_PROMPTS — hard cap on Claude invocations per run (default: 50)
  LLM_TESTS_TIER — filter to run specific tier: "1", "2", "3", "4", or "all"
  LLM_TESTS_RETRIES — retry count for failed tests (default: 2)
  LLM_TESTS_MODEL — model to use: "sonnet", "haiku", "opus" (default: "sonnet")
  LLM_TESTS_RUNS_DIR — host path for /runs volume mount (default: /tmp/llm-test-runs)
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "llm: marks LLM agent tests (require Claude CLI + Docker)")
    config.addinivalue_line("markers", "tier1: tool selection tests")
    config.addinivalue_line("markers", "tier2: multi-step workflow tests")
    config.addinivalue_line("markers", "tier3: end-to-end simulation tests")
    config.addinivalue_line("markers", "tier4: guardrail regression tests")


def llm_enabled() -> bool:
    return os.environ.get("LLM_TESTS_ENABLED", "").lower() in ("1", "true")


def claude_cli_available() -> bool:
    return shutil.which("claude") is not None


# ---------------------------------------------------------------------------
# Model paths — shared across tiers
# ---------------------------------------------------------------------------
# These are Docker-internal paths (/runs/...). The host path is controlled
# by LLM_TESTS_RUNS_DIR env var (default /tmp/llm-test-runs).
# test_01_setup creates these models; all subsequent tests load them.
BASELINE_MODEL = "/runs/llm-test-baseline/model.osm"
EXAMPLE_MODEL = "/runs/llm-test-example/model.osm"


# ---------------------------------------------------------------------------
# Prompt budget tracking
# ---------------------------------------------------------------------------
# Prevents runaway test runs from burning through too many Claude invocations.
# Each test_* function consumes 1 prompt. Retries also consume prompts.
MAX_PROMPTS = int(os.environ.get("LLM_TESTS_MAX_PROMPTS", "50"))
_prompt_count = 0


@pytest.fixture(autouse=True)
def llm_test_guard():
    """Skip if LLM tests not enabled; enforce prompt budget.

    This fixture runs before every LLM test. It checks:
      1. LLM_TESTS_ENABLED is set (tests are opt-in, not default)
      2. claude CLI binary is available in PATH
      3. Prompt budget not exhausted (prevents runaway costs)
    """
    if not llm_enabled():
        pytest.skip("Set LLM_TESTS_ENABLED=1 to run LLM tests")
    if not claude_cli_available():
        pytest.skip("claude CLI not found in PATH")

    global _prompt_count
    _prompt_count += 1
    if _prompt_count > MAX_PROMPTS:
        pytest.skip(f"Prompt budget exhausted ({MAX_PROMPTS} max)")


def get_tier() -> str:
    """Get the tier filter from env. Returns 'all' or '1'/'2'/'3'/'4'."""
    return os.environ.get("LLM_TESTS_TIER", "all").lower()


# ---------------------------------------------------------------------------
# Retry logic for non-deterministic LLM tests
# ---------------------------------------------------------------------------
# LLM outputs vary between runs. A test that passes 80% of the time should
# not block the suite. The retry hook re-runs failed tests up to MAX_RETRIES
# times before reporting a final failure. This is similar to pytest-rerunfailures
# but implemented as a custom hook to avoid an extra dependency.
MAX_RETRIES = int(os.environ.get("LLM_TESTS_RETRIES", "2"))


def pytest_collection_modifyitems(config, items):
    """Tag all LLM-marked tests with retry count for the retry hook."""
    for item in items:
        if "llm" in [m.name for m in item.iter_markers()]:
            item._llm_retries = MAX_RETRIES


def pytest_runtest_protocol(item, nextitem):
    """Retry failed LLM tests up to MAX_RETRIES times.

    On failure, re-runs the full test protocol (setup → call → teardown).
    If any attempt passes, the test is reported as passed (with a note
    about which attempt succeeded). If all attempts fail, the final failure
    is reported with "FAILED after N attempts" prefix.

    Note: each retry consumes a prompt from the budget (_prompt_count).
    """
    retries = getattr(item, "_llm_retries", 0)
    if retries <= 0:
        return None  # defer to default protocol

    from _pytest.runner import runtestprotocol

    for attempt in range(1, retries + 1):
        reports = runtestprotocol(item, nextitem=nextitem, log=False)

        failed = any(r.failed for r in reports if r.when in ("call", "setup"))
        if not failed:
            # Test passed — report it (with retry note if not first attempt)
            for report in reports:
                if attempt > 1 and report.when == "call":
                    report.sections.append(
                        ("llm-retry", f"Passed on attempt {attempt}/{retries}"),
                    )
                item.ihook.pytest_runtest_logreport(report=report)
            return True

        if attempt == retries:
            # All attempts exhausted — report final failure
            for report in reports:
                if report.failed and report.when == "call":
                    original = str(report.longrepr) if report.longrepr else ""
                    report.longrepr = (
                        f"FAILED after {retries} attempts (LLM non-determinism)\n\n"
                        f"{original}"
                    )
                item.ihook.pytest_runtest_logreport(report=report)
            return True

    return True  # pragma: no cover


# ---------------------------------------------------------------------------
# Benchmark results tracking
# ---------------------------------------------------------------------------
# Collects per-test timing and pass/fail status, writes a JSON summary
# to LLM_TESTS_RUNS_DIR/benchmark.json at session end.
# Run with --durations=0 for pytest's built-in timing report too.

_benchmark_results: list[dict] = []
_test_start_times: dict[str, float] = {}


def pytest_runtest_setup(item):
    """Record test start time."""
    _test_start_times[item.nodeid] = time.monotonic()


def pytest_runtest_logreport(report):
    """Record test result after the call phase."""
    if report.when != "call":
        return
    start = _test_start_times.pop(report.nodeid, None)
    duration = time.monotonic() - start if start else report.duration

    # Extract tier from file path
    tier = "setup"
    if "test_02" in report.nodeid:
        tier = "tier1"
    elif "test_04" in report.nodeid:
        tier = "tier2"
    elif "test_03" in report.nodeid:
        tier = "tier3"
    elif "test_05" in report.nodeid:
        tier = "tier4"

    # Check for retry info
    attempt = 1
    for section_name, section_content in getattr(report, "sections", []):
        if section_name == "llm-retry":
            try:
                attempt = int(section_content.split("attempt ")[1].split("/")[0])
            except (IndexError, ValueError):
                pass

    # Pull token/cost stats from the last run_claude result
    from .runner import _last_result
    stats = _last_result.stats if _last_result else {}

    _benchmark_results.append({
        "test_id": report.nodeid,
        "passed": report.passed,
        "duration_s": round(duration, 1),
        "tier": tier,
        "attempt": attempt,
        **stats,
    })


def _fmt_tokens(n: int) -> str:
    """Format token count as compact string (e.g. 8.5k, 1.2M)."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _short_test_id(test_id: str) -> str:
    """Extract short test name from nodeid (e.g. 'test_foo[bar]' → 'bar')."""
    # "tests/llm/test_02_tool_selection.py::test_tool_selection[list_spaces]" → "list_spaces"
    # "tests/llm/test_04_workflows.py::test_workflow[bar_then_typical]" → "bar_then_typical"
    if "[" in test_id:
        return test_id.split("[")[-1].rstrip("]")
    # "tests/llm/test_01_setup.py::test_create_baseline" → "test_create_baseline"
    return test_id.split("::")[-1]


def pytest_sessionfinish(session, exitstatus):
    """Write benchmark JSON + detailed markdown report."""
    if not _benchmark_results:
        return

    runs_dir = Path(os.environ.get("LLM_TESTS_RUNS_DIR", "/tmp/llm-test-runs"))
    runs_dir.mkdir(parents=True, exist_ok=True)

    total = len(_benchmark_results)
    passed = sum(1 for r in _benchmark_results if r["passed"])
    total_time = sum(r["duration_s"] for r in _benchmark_results)

    # Per-tier stats
    tiers: dict[str, dict] = {}
    for r in _benchmark_results:
        t = r["tier"]
        if t not in tiers:
            tiers[t] = {"total": 0, "passed": 0, "duration_s": 0.0}
        tiers[t]["total"] += 1
        tiers[t]["passed"] += int(r["passed"])
        tiers[t]["duration_s"] = round(tiers[t]["duration_s"] + r["duration_s"], 1)

    for t in tiers.values():
        t["pass_rate"] = round(t["passed"] / t["total"] * 100, 1) if t["total"] else 0

    total_input = sum(r.get("input_tokens", 0) for r in _benchmark_results)
    total_output = sum(r.get("output_tokens", 0) for r in _benchmark_results)
    total_cache = sum(r.get("cache_read_tokens", 0) for r in _benchmark_results)
    total_cost = sum(r.get("cost_usd", 0) for r in _benchmark_results)
    model = os.environ.get("LLM_TESTS_MODEL", "sonnet")
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    summary = {
        "timestamp": ts,
        "model": model,
        "retries": MAX_RETRIES,
        "total_tests": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "total_duration_s": round(total_time, 1),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_read_tokens": total_cache,
        "total_cost_usd": round(total_cost, 4),
        "tiers": tiers,
        "tests": _benchmark_results,
    }

    # --- Write JSON ---
    json_out = runs_dir / "benchmark.json"
    json_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # --- Write detailed markdown report ---
    pass_rate = summary["pass_rate"]
    md = []
    md.append(f"# LLM Benchmark Report")
    md.append(f"")
    md.append(f"**Date:** {ts}  ")
    md.append(f"**Model:** {model} | **Retries:** {MAX_RETRIES}  ")
    md.append(f"**Result:** {passed}/{total} passed ({pass_rate}%) "
              f"in {total_time:.0f}s  ")
    md.append(f"**Tokens:** {_fmt_tokens(total_input)} in "
              f"+ {_fmt_tokens(total_output)} out "
              f"+ {_fmt_tokens(total_cache)} cache "
              f"| **Cost:** ${total_cost:.4f}")
    md.append("")

    # Tier summary table
    md.append("## Summary by Tier")
    md.append("")
    hdr = (f"| {'Tier':<6} | {'Passed':>7} | {'Rate':>6} "
           f"| {'Time':>6} | {'Avg':>6} |")
    sep = (f"|{'-'*8}|{'-'*9}|{'-'*8}"
           f"|{'-'*8}|{'-'*8}|")
    md.append(hdr)
    md.append(sep)
    for tier_name in ("setup", "tier1", "tier2", "tier3", "tier4"):
        if tier_name not in tiers:
            continue
        ts_ = tiers[tier_name]
        avg = ts_["duration_s"] / ts_["total"] if ts_["total"] else 0
        ratio = f"{ts_['passed']}/{ts_['total']}"
        rate = f"{ts_['pass_rate']}%"
        md.append(f"| {tier_name:<6} | {ratio:>7} | {rate:>6} "
                  f"| {ts_['duration_s']:>5.0f}s | {avg:>5.0f}s |")
    md.append("")

    # Detailed per-test tables, grouped by tier
    md.append("## Detailed Results")
    md.append("")

    for tier_name in ("setup", "tier1", "tier2", "tier3", "tier4"):
        tier_tests = [r for r in _benchmark_results if r["tier"] == tier_name]
        if not tier_tests:
            continue

        # Compute column widths from data
        rows = []
        for r in tier_tests:
            name = _short_test_id(r["test_id"])
            status = "PASS" if r["passed"] else "FAIL"
            dur = f"{r['duration_s']:.0f}s"
            turns = str(r.get("num_turns", "?"))
            tools = ", ".join(r.get("tool_calls", [])) or "—"
            in_tok = _fmt_tokens(r.get("input_tokens", 0))
            out_tok = _fmt_tokens(r.get("output_tokens", 0))
            cache = _fmt_tokens(r.get("cache_read_tokens", 0))
            cost = f"${r.get('cost_usd', 0):.4f}"
            attempt = str(r.get("attempt", 1))
            rows.append((name, status, dur, turns, tools,
                         in_tok, out_tok, cache, cost, attempt))

        headers = ("Test", "Result", "Time", "Turns", "Tools",
                   "In Tok", "Out Tok", "Cache", "Cost", "Att")
        # Right-align numeric columns (index 2-9), left-align name+tools
        right_align = {1, 2, 3, 5, 6, 7, 8, 9}
        widths = [max(len(h), max(len(r[i]) for r in rows))
                  for i, h in enumerate(headers)]

        def _fmt_row(vals):
            cells = []
            for i, (v, w) in enumerate(zip(vals, widths)):
                cells.append(f" {v:>{w}} " if i in right_align else f" {v:<{w}} ")
            return "|" + "|".join(cells) + "|"

        md.append(f"### {tier_name}")
        md.append("")
        md.append(_fmt_row(headers))
        md.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
        for row in rows:
            md.append(_fmt_row(row))
        md.append("")

    # Failed tests detail
    failed_tests = [r for r in _benchmark_results if not r["passed"]]
    if failed_tests:
        md.append("## Failed Tests")
        md.append("")
        for r in failed_tests:
            name = _short_test_id(r["test_id"])
            tools = " -> ".join(r.get("tool_calls", [])) or "no tools called"
            md.append(f"- **{name}** ({r['tier']}): {r['duration_s']:.0f}s, "
                      f"{r.get('num_turns', '?')} turns, tools: {tools}")
        md.append("")

    md_out = runs_dir / "benchmark.md"
    md_out.write_text("\n".join(md), encoding="utf-8")

    # --- Append to history ---
    history_file = runs_dir / "benchmark_history.json"
    history: list = []
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text())
        except (json.JSONDecodeError, OSError):
            history = []
    # Keep last 50 runs
    history.append({k: v for k, v in summary.items() if k != "tests"})
    history = history[-50:]
    history_file.write_text(json.dumps(history, indent=2), encoding="utf-8")

    # --- Console summary ---
    print(f"\n{'='*70}")
    print(f"LLM Benchmark: {passed}/{total} passed ({pass_rate}%) | "
          f"Model: {model} | {total_time:.0f}s")
    print(f"Tokens: {_fmt_tokens(total_input)} in + "
          f"{_fmt_tokens(total_output)} out + "
          f"{_fmt_tokens(total_cache)} cache | Cost: ${total_cost:.4f}")
    for tier_name in ("setup", "tier1", "tier2", "tier3", "tier4"):
        if tier_name not in tiers:
            continue
        ts_ = tiers[tier_name]
        print(f"  {tier_name}: {ts_['passed']}/{ts_['total']} "
              f"({ts_['pass_rate']}%) in {ts_['duration_s']:.0f}s")
    if failed_tests:
        print(f"Failed: {', '.join(_short_test_id(r['test_id']) for r in failed_tests)}")
    print(f"Report: {md_out}")
    print(f"History: {history_file} ({len(history)} runs)")
    print(f"{'='*70}")
