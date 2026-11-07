"""Transport selection for the LLM harness: stdio (default) or shared HTTP server.

stdio spawns a fresh `docker run` per prompt and owns the whole /runs tree.
HTTP talks to one long-lived server authenticated as HTTP_USER, whose run and
measure areas are /runs/<user> and /measures/<user>; anything outside is denied.

Suite prompts hardcode the stdio layout, so run_agent rewrites them here rather
than at ~20 call sites. On the host, LLM_TESTS_RUNS_DIR points at the user's
subfolder of the leg, so conftest fixture checks and the outcome graders see
the same /runs-relative layout on both transports.
"""
from __future__ import annotations

import os
import re
import sys
import time
from collections.abc import Callable

HTTP_USER = "bench"

_RUNS_PATH = re.compile(r"(?<![\w/.-])/runs/")
_MEASURES_PATH = re.compile(r"(?<![\w/.-])/measures/local/")
_CAP_MESSAGE = re.compile(
    r"(hit your|usage|session|weekly|rate|credit)\W+(\w+\W+){0,2}limit"
    r"|limit reached|resets? (at )?\d|\b429\b",
    re.IGNORECASE,
)


def is_http() -> bool:
    transport = os.environ.get("LLM_TESTS_TRANSPORT", "stdio").lower()
    if transport not in ("stdio", "http"):
        raise ValueError(f"LLM_TESTS_TRANSPORT must be stdio or http, got {transport!r}")
    return transport == "http"


def transport_name() -> str:
    return "http" if is_http() else "stdio"


def measures_user() -> str:
    """Owner folder of authored measures under /measures."""
    return HTTP_USER if is_http() else "local"


def agent_prompt(prompt: str) -> str:
    """Point a prompt's server paths at the caller's area on this transport."""
    if not is_http():
        return prompt
    prompt = _RUNS_PATH.sub(f"/runs/{HTTP_USER}/", prompt)
    return _MEASURES_PATH.sub(f"/measures/{HTTP_USER}/", prompt)


def effective_timeout(timeout: int) -> int:
    """Raise a test's own timeout to LLM_TESTS_TIMEOUT_FLOOR when set.

    LLM_TESTS_TIMEOUT_BASE only reaches test_06; every other file hardcodes its
    timeout, so a suite-wide completion budget has to be applied here.
    """
    return max(timeout, int(os.environ.get("LLM_TESTS_TIMEOUT_FLOOR", "0")))


def http_server_config() -> dict:
    """Claude Code MCP entry for the shared server (name stays `openstudio`)."""
    return {
        "type": "http",
        "url": os.environ["LLM_TESTS_MCP_URL"],
        "headers": {"Authorization": f"Bearer {os.environ['LLM_TESTS_MCP_TOKEN']}"},
    }


def looks_like_usage_cap(text: str) -> bool:
    """True when a FAILED CLI call's error text reads as a usage or rate cap."""
    return bool(_CAP_MESSAGE.search(text or ""))


def wait_out_cap(
    attempt: Callable[[], tuple[bool, object]],
    *,
    budget_s: int | None = None,
    poll_s: int = 600,
    sleep: Callable[[float], None] = time.sleep,
) -> object:
    """Call attempt() until it is not capped, sleeping between tries.

    attempt returns (capped, value). A capped call did no work, so retrying it
    is not a test retry. A multi-hour leg would otherwise be invalidated whole
    by one cap, since a sweep can only resume at leg level. With no budget
    (the default outside sweeps) the first capped value is returned unchanged.
    """
    if budget_s is None:
        budget_s = int(os.environ.get("LLM_TESTS_CAP_WAIT_S", "0"))
    waited = 0
    while True:
        capped, value = attempt()
        if not capped or waited >= budget_s:
            return value
        print(f"[llm] usage cap, waited {waited}s, retrying in {poll_s}s",
              file=sys.stderr, flush=True)
        sleep(poll_s)
        waited += poll_s
