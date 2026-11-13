"""Live test of the README "Let your AI set it up" prompt (issue #268).

A real agent CLI gets the prompt verbatim in a throwaway HOME seeded with every
host's config, and is driven turn by turn like a user would:
  1. prompt          -> must stop and ask; no config touched
  2. host + folders  -> the host already has "openstudio-mcp": must stop and ask
  3. "use openstudio-mcp-test" -> registers it; grader checks the files
then the registered command must answer an MCP initialize.

Opt-in: INSTALL_PROMPT_TESTS=1. See tests/install_prompt/README.md.
"""
from __future__ import annotations

import datetime
import itertools
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from .agents import AGENTS, CLI, NATIVE_KEYS, base_env, model, pairs_for_run, provider, readme_prompt
from .grader import (
    check_asked,
    check_backup,
    check_folders,
    check_no_project_configs,
    check_no_secrets,
    check_registration,
    check_servers_unchanged,
    check_untouched,
    snapshot,
    summary_row,
)
from .hosts import HOSTS, TEST_NAME, parse, seed_all, servers

ENABLED = os.environ.get("INSTALL_PROMPT_TESTS") == "1"
pytestmark = [pytest.mark.llm,
              pytest.mark.skipif(not ENABLED, reason="set INSTALL_PROMPT_TESTS=1 to run the install-prompt test")]


def _pairs() -> list[tuple[str, str]]:
    spec = os.environ.get("INSTALL_PROMPT_PAIRS", "").strip()
    if spec == "all":
        return list(itertools.product(AGENTS, HOSTS))
    if spec:
        return [tuple(p.strip().split(":", 1)) for p in spec.split(",")]
    day = datetime.datetime.now(datetime.UTC).date().toordinal()
    return pairs_for_run(day, int(os.environ.get("INSTALL_PROMPT_PAIRS_PER_RUN", "1")),
                          list(AGENTS), list(HOSTS))


def _latest_tag() -> str:
    req = urllib.request.Request("https://api.github.com/repos/NatLabRockies/openstudio-mcp/releases/latest")
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - fixed https URL
        return json.load(r)["tag_name"]


def _initialize(entry: dict, timeout: int = 180) -> str | None:
    """Start the registered command, send one initialize, keep stdin open until a
    reply arrives. Returns the server name, or None on no reply."""
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "install-prompt-test", "version": "1"}}}
    argv = [entry["command"], *entry.get("args", [])]
    # agent-written command: no API keys; stderr inherited so pytest shows docker errors
    env = {k: v for k, v in os.environ.items() if k not in ("OPENROUTER_API_KEY", "GITHUB_TOKEN", *NATIVE_KEYS)}
    p = subprocess.Popen(argv, stdin=subprocess.PIPE,  # noqa: S603 - the entry under test
                         stdout=subprocess.PIPE, stderr=None, text=True,
                         env={**env, **(entry.get("env") or {})})
    timer = threading.Timer(timeout, p.kill)
    timer.start()
    try:
        p.stdin.write(json.dumps(req) + "\n")
        p.stdin.flush()
        for line in p.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == 1:
                return (msg.get("result") or {}).get("serverInfo", {}).get("name")
        return None
    finally:
        timer.cancel()
        p.kill()
        p.wait()


def _summary(agent: str, host: str, fails: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with Path(path).open("a", encoding="utf-8") as f:
            f.write(summary_row(agent, host, model() or "vendor default", fails))


@pytest.mark.parametrize(("agent", "host"), _pairs(), ids=lambda v: v)
def test_install_prompt(agent: str, host: str, tmp_path: Path):
    # Validates: the README install prompt makes a real agent stop before changing
    # anything, stop again at an existing entry, then add only openstudio-mcp-test
    # (latest image, three absolute mounts, :ro inputs) without printing tokens
    real = Path.home().resolve()
    real_before = snapshot(real)  # agents run as you with approvals off: HOME only hides configs
    try:
        assert agent in AGENTS and host in HOSTS, f"unknown pair {agent}:{host}"
        # Enabled but unrunnable must fail, not skip: a skipped daily run looks green
        assert shutil.which(CLI[agent]), f"{CLI[agent]} CLI not on PATH"
        if provider() == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
            pytest.fail("OPENROUTER_API_KEY not set")  # not assert: its rewrite prints os.environ

        # --- Arrange ---
        home = (tmp_path / "home").resolve()
        home.mkdir()
        assert home != real and real not in home.parents, "throwaway HOME must not be the real one"
        env = base_env(home)
        prepare, turn = AGENTS[agent]
        prepare(home, env)
        seed_all(home)
        before = snapshot(home)
        work = home / "work"
        work.mkdir()
        folders = {k: str(home / "openstudio" / k) for k in ("inputs", "runs", "measures")}
        image = f"nrel/openstudio-mcp:{_latest_tag()}"

        # --- Act + Assert, turn by turn ---
        sid, text = turn(None, readme_prompt(), work, env)
        fails = [f"turn 1: {f}" for f in check_untouched(before, snapshot(home)) + check_asked(text)
                 + check_no_project_configs(work) + check_no_secrets(text)]
        assert not fails, "\n".join(fails) + f"\n--- agent said:\n{text[-2000:]}"

        sid, text = turn(sid, f"{HOSTS[host].label}. Use these folders: models {folders['inputs']}, "
                              f"simulation output {folders['runs']}, measures {folders['measures']}.", work, env)
        fails = [f"turn 2 (existing entry, must ask): {f}"
                 for f in check_untouched(before, snapshot(home)) + check_asked(text, existing_entry=True)
                 + check_no_project_configs(work) + check_no_secrets(text)]
        assert not fails, "\n".join(fails) + f"\n--- agent said:\n{text[-2000:]}"

        sid, text = turn(sid, f"Use the name {TEST_NAME}, keep the existing entry.", work, env)
        after = snapshot(home)
        fails = [f"turn 3: {f}" for f in check_registration(host, before, after, image, folders)
                 + check_folders(folders) + check_backup(home, host, before)
                 + check_no_project_configs(work) + check_no_secrets(text)]
        if not fails:  # folders checked first: docker run would create missing ones itself
            entry = servers(HOSTS[host], parse(HOSTS[host], after[host]))[TEST_NAME]
            name = _initialize(entry)
            if name != "openstudio-mcp":
                fails.append(f"registered command did not answer initialize as openstudio-mcp (got {name!r})")
        assert not fails, "\n".join(fails) + f"\n--- agent said:\n{text[-2000:]}"
    finally:
        # Runs even when a turn already failed: a changed real config must never be masked
        leaked = check_servers_unchanged(real_before, snapshot(real))
        err = sys.exc_info()[1]
        _summary(agent, host, leaked + ([f"{type(err).__name__}: {err}"] if err else []))
        assert not leaked, "\n".join(leaked)
