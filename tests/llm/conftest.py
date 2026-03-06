"""Conftest for LLM agent tests — markers, guards, fixtures, and retry logic.

This conftest provides:
  1. Custom pytest markers (llm, tier1-4) for selective test execution
  2. Guard fixture that skips tests unless LLM_TESTS_ENABLED=1
  3. Prompt budget tracking to prevent runaway test runs
  4. Shared model paths (Docker-internal) used across all tiers
  5. Retry logic for non-deterministic LLM test failures

Environment variables:
  LLM_TESTS_ENABLED  — set to "1" to enable LLM tests (default: disabled)
  LLM_TESTS_MAX_PROMPTS — hard cap on Claude invocations per run (default: 50)
  LLM_TESTS_TIER — filter to run specific tier: "1", "2", "3", "4", or "all"
  LLM_TESTS_RETRIES — retry count for failed tests (default: 2)
  LLM_TESTS_MODEL — model to use: "sonnet", "haiku", "opus" (default: "sonnet")
  LLM_TESTS_RUNS_DIR — host path for /runs volume mount (default: /tmp/llm-test-runs)
"""
from __future__ import annotations

import os
import shutil

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

    return True
