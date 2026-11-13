"""Unit tests for the install-prompt agent adapters (tests/install_prompt/agents.py):
output parsing, pair rotation, environment isolation and README prompt extraction. Stdlib only.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from install_prompt import agents
from install_prompt.hosts import CANARY, HOSTS

pytestmark = pytest.mark.unit


def test_claude_text_keeps_every_assistant_message():
    # Regression: only the final `result` was kept, so a token printed mid-turn
    # escaped the secret check for claude but not for codex/opencode
    stream = "\n".join(json.dumps(e) for e in [
        {"type": "system", "subtype": "init", "session_id": "s"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": f"Bearer {CANARY}"},
                                                      {"type": "tool_use", "name": "Bash", "input": {}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Replace or rename?"}]}},
        {"type": "result", "result": "Replace or rename?"},
    ]) + "\nnot json"
    assert agents.claude_text(stream) == f"Bearer {CANARY}\nReplace or rename?"


@pytest.mark.parametrize("per_run", [0, -1, 29])
def test_rotation_rejects_bad_pairs_per_run(per_run):
    # Regression: 0 collected nothing and the daily job went green; >28 repeated pairs
    with pytest.raises(ValueError, match=r"INSTALL_PROMPT_PAIRS_PER_RUN must be 1\.\.28"):
        agents.pairs_for_run(0, per_run, list(agents.AGENTS), list(HOSTS))


def test_native_mode_leaves_model_to_each_cli(monkeypatch):
    # Regression: native mode passed the OpenRouter-only default model to opencode -m
    monkeypatch.setenv("INSTALL_PROMPT_PROVIDER", "native")
    monkeypatch.delenv("INSTALL_PROMPT_MODEL", raising=False)
    assert agents.model() == ""


def test_daily_rotation_covers_every_pair():
    # Validates: one pair a day still reaches every agent x host combination
    a, h = list(agents.AGENTS), list(HOSTS)
    seen = {p for w in range(len(a) * len(h)) for p in agents.pairs_for_run(w, 1, a, h)}
    assert seen == {(x, y) for x in a for y in h}
    assert agents.pairs_for_run(0, 2, ["a", "b"], ["x", "y"]) == [("a", "x"), ("a", "y")]


def test_env_hides_developer_secrets(tmp_path, monkeypatch):
    # Validates: agents see a throwaway HOME and only the provider key, not the
    # developer's other credentials
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic")
    monkeypatch.delenv("INSTALL_PROMPT_PROVIDER", raising=False)
    env = agents.base_env(tmp_path)
    assert env["HOME"] == str(tmp_path) and env["CODEX_HOME"] == str(tmp_path / ".codex")
    assert env["OPENROUTER_API_KEY"] == "or-key"
    assert "AWS_SECRET_ACCESS_KEY" not in env and "ANTHROPIC_API_KEY" not in env


def test_blank_model_and_provider_fall_back_to_defaults(monkeypatch):
    # Regression: the workflow passed INSTALL_PROMPT_MODEL="" so every agent got an empty
    # model (codex and copilot refused to start, claude silently used a paid default)
    monkeypatch.setenv("INSTALL_PROMPT_MODEL", "")
    monkeypatch.setenv("INSTALL_PROMPT_PROVIDER", "")
    assert agents.model() == "nvidia/nemotron-3.5-super-vl:free"
    assert agents.provider() == "openrouter"


@pytest.mark.parametrize("needle", [
    "If you have no way to ask me, stop there and list what you need",
    "api.github.com/repos/NatLabRockies/openstudio-mcp/releases/latest",
    "a web search can return an old cached page",
    "print no headers, env values or tokens",
    "copy the file to a timestamped backup first",
])
def test_readme_prompt_keeps_safeguards(needle):
    # Regression: client runs for #268 failed without each of these lines (no stop
    # when the agent can't ask, stale tag from a web search, printed tokens, no backup)
    prompt = " ".join(agents.readme_prompt().split())
    assert needle in prompt


def test_readme_prompt_skips_toc_link(tmp_path):
    # Regression: the prompt was found from the TOC line, so an earlier ```text example became the prompt
    readme = tmp_path / "README.md"
    readme.write_text("- [Let your AI set it up](#x)\n\n```text\nexample\n```\n\n"
                      "## Let your AI set it up\n\n```text\nthe prompt\n```\n")
    assert agents.readme_prompt(readme) == "the prompt\n"


def test_readme_prompt_extraction_fails_loudly(tmp_path):
    # Validates: a renamed section fails the harness instead of sending an empty prompt
    bad = tmp_path / "README.md"
    bad.write_text("# Let your AI set it up\n\nno code block\n")
    with pytest.raises(ValueError, match="no ```text block"):
        agents.readme_prompt(bad)


def test_jsonl_keeps_events_with_line_separators():
    # Regression: splitlines() cut an event at a raw U+2028 inside a JSON string and dropped it
    out = json.dumps({"type": "text", "part": {"text": "a\u2028b?"}}, ensure_ascii=False) + "\n"
    assert [e["part"]["text"] for e in agents._jsonl(out)] == ["a\u2028b?"]


def test_env_repr_hides_values(tmp_path, monkeypatch):
    # Regression: pytest prints every traceback frame's arguments, which included the env with the provider key
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-value")
    monkeypatch.delenv("INSTALL_PROMPT_PROVIDER", raising=False)
    env = agents.base_env(tmp_path)
    assert env["OPENROUTER_API_KEY"] == "sk-or-secret-value"
    assert "sk-or-secret-value" not in repr(env) and "OPENROUTER_API_KEY" in repr(env)


@pytest.mark.parametrize("value", ["OpenRouter", "openrouter ", "vendor"])
def test_unknown_provider_is_rejected(monkeypatch, value):
    # Regression: any value but "openrouter" meant native mode, handing every vendor key to the agent
    monkeypatch.setenv("INSTALL_PROMPT_PROVIDER", value)
    with pytest.raises(ValueError, match="INSTALL_PROMPT_PROVIDER must be one of"):
        agents.provider()


def test_timeout_kills_the_whole_process_group(tmp_path):
    # Regression: a timeout killed only the npm launcher, leaving the real agent (a grandchild) running
    pidfile = tmp_path / "pid"
    with pytest.raises(RuntimeError, match="timed out after 1 s"):
        agents._run(["sh", "-c", f"sleep 60 & echo $! > {pidfile}; wait"], tmp_path, {"PATH": os.environ["PATH"]},
                    timeout=1)
    pid = int(pidfile.read_text())
    time.sleep(0.2)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    # a killed orphan stays a zombie when container PID 1 doesn't reap (CI); dead all the same
    state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    assert state == "Z", f"grandchild {pid} still running (state {state}) after timeout"
