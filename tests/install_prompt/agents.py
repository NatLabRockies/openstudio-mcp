"""Headless agent CLIs that run the README install prompt, one turn at a time.

Every agent runs with HOME pointed at a throwaway directory, so no real config
or login is visible: auth comes only from env vars. Provider "openrouter"
(default, what CI uses) points each CLI at OpenRouter with INSTALL_PROMPT_MODEL;
provider "native" passes the developer's own vendor key through instead
(ANTHROPIC_API_KEY / OPENAI_API_KEY / COPILOT_GITHUB_TOKEN).

Cursor and Antigravity aren't here: their CLIs need an account login that a
throwaway HOME doesn't have. They stay a manual check (see README.md in this dir).
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OPENROUTER = "https://openrouter.ai/api"
DEFAULT_MODEL = "thinkingmachines/inkling-2-small:free"
TURN_TIMEOUT = int(os.environ.get("INSTALL_PROMPT_TURN_TIMEOUT", "900"))

_PASSTHROUGH = ("PATH", "LANG", "LC_ALL", "TERM", "DOCKER_HOST", "SSL_CERT_FILE")
_NATIVE_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "COPILOT_GITHUB_TOKEN", "GH_TOKEN")


def readme_prompt(readme: Path = REPO / "README.md") -> str:
    """The ```text block under "Let your AI set it up", verbatim."""
    text = readme.read_text(encoding="utf-8")
    section = text[text.index("Let your AI set it up"):]
    m = re.search(r"^```text\n(.*?)^```", section, re.S | re.M)
    if not m:
        raise ValueError("no ```text block after 'Let your AI set it up' in README.md")
    return m.group(1)


def provider() -> str:
    return os.environ.get("INSTALL_PROMPT_PROVIDER", "openrouter")


def model() -> str:
    return os.environ.get("INSTALL_PROMPT_MODEL", DEFAULT_MODEL)


def base_env(home: Path) -> dict[str, str]:
    """Minimal env: nothing from the developer's environment but PATH-like basics
    and, for the chosen provider, the one key it needs."""
    env = {k: os.environ[k] for k in _PASSTHROUGH if k in os.environ}
    env.update(HOME=str(home), TMPDIR=str(home / "tmp"), CI="1",
               XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local/share"),
               XDG_CACHE_HOME=str(home / ".cache"), XDG_STATE_HOME=str(home / ".local/state"),
               CODEX_HOME=str(home / ".codex"))
    (home / "tmp").mkdir(exist_ok=True)
    keys = ("OPENROUTER_API_KEY",) if provider() == "openrouter" else _NATIVE_KEYS
    env.update({k: os.environ[k] for k in keys if k in os.environ})
    return env


def _run(cmd: list[str], cwd: Path, env: dict) -> str:
    r = subprocess.run(cmd, cwd=cwd,  # noqa: S603 - fixed agent argv, no shell
                       env=env, stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, timeout=TURN_TIMEOUT, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited {r.returncode}: {(r.stderr or r.stdout)[-1500:]}")
    return r.stdout


def _jsonl(out: str):
    for line in out.splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


# --- Claude Code ------------------------------------------------------------
def _claude_prepare(home: Path, env: dict) -> None:
    if provider() == "openrouter":
        env.update(ANTHROPIC_BASE_URL=OPENROUTER, ANTHROPIC_AUTH_TOKEN=env.get("OPENROUTER_API_KEY", ""),
                   ANTHROPIC_API_KEY="", ANTHROPIC_MODEL=model(),
                   # default asks for 128k; OpenRouter rejects requests the key's limit can't cover
                   CLAUDE_CODE_MAX_OUTPUT_TOKENS="16000")


def _claude_turn(session: str | None, msg: str, cwd: Path, env: dict) -> tuple[str, str]:
    sid = session or str(uuid.uuid4())
    flag = "--resume" if session else "--session-id"
    out = _run(["claude", "-p", msg, flag, sid, "--dangerously-skip-permissions",
                "--output-format", "json"], cwd, env)
    return sid, json.loads(out).get("result") or ""


# --- Codex ------------------------------------------------------------------
def _codex_prepare(home: Path, env: dict) -> None:
    if provider() != "openrouter":
        return
    cfg = home / ".codex/config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(f'model_provider = "openrouter"\nmodel = "{model()}"\n\n'
                   '[model_providers.openrouter]\nname = "OpenRouter"\n'
                   f'base_url = "{OPENROUTER}/v1"\nenv_key = "OPENROUTER_API_KEY"\n'
                   'wire_api = "responses"\n', encoding="utf-8")


def _codex_turn(session: str | None, msg: str, cwd: Path, env: dict) -> tuple[str, str]:
    flags = ["--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", "--json"]
    cmd = ["codex", "exec", "resume", *flags, session, msg] if session else ["codex", "exec", *flags, msg]
    sid, texts = session, []
    for e in _jsonl(_run(cmd, cwd, env)):
        if e.get("type") == "thread.started":
            sid = e.get("thread_id")
        item = e.get("item") or {}
        if e.get("type") == "item.completed" and item.get("type") == "agent_message":
            texts.append(item.get("text") or "")
    return sid, "\n".join(texts)


# --- Copilot CLI --------------------------------------------------------------
def _copilot_prepare(home: Path, env: dict) -> None:
    if provider() == "openrouter":
        env.update(COPILOT_PROVIDER_BASE_URL=f"{OPENROUTER}/v1", COPILOT_MODEL=model(),
                   COPILOT_PROVIDER_API_KEY=env.get("OPENROUTER_API_KEY", ""))


def _copilot_turn(session: str | None, msg: str, cwd: Path, env: dict) -> tuple[str, str]:
    sid = session or str(uuid.uuid4())  # --session-id both creates and resumes
    out = _run(["copilot", "-p", msg, "--session-id", sid, "--allow-all", "--silent",
                "--no-auto-update"], cwd, env)
    return sid, out


# --- opencode (proposed client, discussion #269) -------------------------------
def _opencode_turn(session: str | None, msg: str, cwd: Path, env: dict) -> tuple[str, str]:
    m = model() if provider() != "openrouter" else f"openrouter/{model()}"
    cmd = ["opencode", "run", "--auto", "-m", m, "--format", "json", "--archived"]
    sid, texts = session, []
    for e in _jsonl(_run([*cmd, *(["--session", session] if session else []), msg], cwd, env)):
        sid = sid or e.get("sessionID")
        part = e.get("part") or {}
        if e.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
    return sid, "\n".join(texts)


AGENTS = {
    "claude": (_claude_prepare, _claude_turn),
    "codex": (_codex_prepare, _codex_turn),
    "copilot": (_copilot_prepare, _copilot_turn),
    "opencode": (lambda _home, _env: None, _opencode_turn),
}
CLI = {"claude": "claude", "codex": "codex", "copilot": "copilot", "opencode": "opencode"}


def pairs_for_run(run: int, per_run: int, agents: list[str], hosts: list[str]) -> list[tuple[str, str]]:
    """Rotate through the agent x host matrix, per_run pairs a run (one run a day). Index i maps
    to (agents[i % A], hosts[i % H]); with coprime A and H (4 and 7) that visits
    every pair once per A*H indices, so with one pair a day each host comes up weekly
    and the whole matrix in A*H days."""
    a, h = len(agents), len(hosts)
    if math.gcd(a, h) != 1:  # diagonal walk would skip pairs; fall back to row order
        order = [(x, y) for x in agents for y in hosts]
    else:
        order = [(agents[i % a], hosts[i % h]) for i in range(a * h)]
    return [order[(run * per_run + k) % len(order)] for k in range(per_run)]
