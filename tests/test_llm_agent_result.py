"""Unit tests for the LLM-bench runner: AgentResult parsing, backend seam,
image/arm plumbing. No network, no Docker, no openstudio import.
"""
import json

import pytest
from llm.runner import AgentResult, ClaudeResult, _parse_stream_json, _write_mcp_config, run_agent

pytestmark = pytest.mark.unit


def _ndjson(*objs) -> str:
    return "\n".join(json.dumps(o) for o in objs)


def _assistant(tool_id: str, name: str, tool_input: dict) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input},
    ]}}


def _tool_result(tool_id: str, content) -> dict:
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": content},
    ]}}


FIXTURE = _ndjson(
    {"type": "system", "subtype": "init"},
    _assistant("t1", "mcp__openstudio__list_spaces", {"max_results": 0}),
    _tool_result("t1", [{"type": "text", "text": '{"ok": true, "spaces": []}'}]),
    _assistant("t2", "mcp__openstudio__apply_measure", {"measure_dir": "/x"}),
    _tool_result("t2", '{"ok": false, "error": "boom"}'),
    _assistant("t3", "Bash", {"command": "ls"}),
    _tool_result("t3", "plain text, not JSON"),
    _assistant("t4", "mcp__openstudio__get_component_properties", {}),
    _tool_result("t4", '{"properties": {}}'),
    {"type": "result", "result": "done", "total_cost_usd": 0.5, "num_turns": 4,
     "usage": {"input_tokens": 10, "output_tokens": 20}},
)


def test_parse_stream_json_normalizes_tool_calls():
    # Validates: AgentResult strips the MCP prefix and excludes builtin tools —
    # the fields every benchmark assertion is built on
    r = _parse_stream_json(FIXTURE)
    assert r.tool_names == ["list_spaces", "apply_measure", "get_component_properties"]
    assert r.all_tool_names == [
        "mcp__openstudio__list_spaces", "mcp__openstudio__apply_measure",
        "Bash", "mcp__openstudio__get_component_properties",
    ]
    assert r.final_text == "done"
    assert r.cost_usd == pytest.approx(0.5)
    assert r.num_turns == 4


def test_tool_results_pairing_and_tool_ok():
    # Validates: tool_use ids pair to parsed results (list-of-text-blocks and
    # plain-string forms); tool_ok distinguishes True / False / undeterminable
    r = _parse_stream_json(FIXTURE)
    assert r.tool_results["t1"] == {"ok": True, "spaces": []}
    assert r.tool_results["t2"] == {"ok": False, "error": "boom"}
    assert r.tool_results["t3"] == {"_raw": "plain text, not JSON"}
    assert r.tool_ok("list_spaces") is True
    assert r.tool_ok("apply_measure") is False
    assert r.tool_ok("get_component_properties") is None  # no ok flag
    assert r.tool_ok("never_called") is None


def test_results_for_call_order():
    # Validates: results_for returns each call's parsed result in call order —
    # workflow EUI asserts index baseline vs retrofit by position
    raw = _ndjson(
        _assistant("a", "mcp__openstudio__extract_summary_metrics", {"run_id": "r1"}),
        _tool_result("a", '{"ok": true, "metrics": {"eui_kBtu_ft2": 28.2}}'),
        _assistant("b", "mcp__openstudio__extract_summary_metrics", {"run_id": "r2"}),
        _tool_result("b", '{"ok": true, "metrics": {"eui_kBtu_ft2": null}}'),
        {"type": "result", "result": ""},
    )
    r = _parse_stream_json(raw)
    results = r.results_for("extract_summary_metrics")
    assert [x["metrics"]["eui_kBtu_ft2"] for x in results] == [28.2, None]

    from llm.conftest import summary_metric_euis
    assert summary_metric_euis(r) == [pytest.approx(28.2)]


def test_assert_sim_valid_gates():
    # Validates: the D6 verifier's assert gates — completion, fatal/severe,
    # unmet cap (None skips), and pinned-EUI tolerance — each fail correctly
    from llm.verify import assert_sim_valid

    good = {"run_id": "r", "completed": True, "fatal": 0, "severe": 0,
            "eui": 57.4, "unmet_heating": 100.0, "unmet_cooling": 0.0}
    assert_sim_valid(good, eui_ref=57.41, rel=0.05)

    with pytest.raises(AssertionError, match="did not terminate"):
        assert_sim_valid(good | {"completed": False})
    with pytest.raises(AssertionError, match="fatal"):
        assert_sim_valid(good | {"fatal": 1})
    with pytest.raises(AssertionError, match="severe"):
        assert_sim_valid(good | {"severe": 2})
    with pytest.raises(AssertionError, match="unmet hours"):
        assert_sim_valid(good | {"unmet_heating": 561.0})
    assert_sim_valid(good | {"unmet_heating": 561.0}, max_unmet=None)  # skip cap
    with pytest.raises(AssertionError, match="outside 5%"):
        assert_sim_valid(good, eui_ref=28.21, rel=0.05)
    with pytest.raises(AssertionError, match="no EUI"):
        assert_sim_valid(good | {"eui": None}, eui_ref=57.41)


def test_claude_result_alias_preserved():
    # Validates: pre-rename tests importing ClaudeResult keep working
    assert ClaudeResult is AgentResult


def test_parse_codex_jsonl_normalizes_to_agent_result():
    # Validates: codex exec --json events map onto the same AgentResult shape
    # as claude NDJSON — tool_names/tool_ok/results_for work cross-backend.
    # Fixture mirrors real codex-cli 0.146.0 output (SPIKE-1, 2026-08-05).
    from llm.runner import _parse_codex_jsonl
    raw = _ndjson(
        {"type": "thread.started", "thread_id": "t"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {
            "id": "item_0", "type": "agent_message", "text": "working"}},
        {"type": "item.started", "item": {
            "id": "item_1", "type": "mcp_tool_call", "server": "openstudio",
            "tool": "create_baseline_osm", "arguments": {"name": "x"},
            "result": None, "error": None, "status": "in_progress"}},
        {"type": "item.completed", "item": {
            "id": "item_1", "type": "mcp_tool_call", "server": "openstudio",
            "tool": "create_baseline_osm", "arguments": {"name": "x"},
            "result": {"content": [{"type": "text",
                                    "text": '{"ok": true, "osm_path": "/runs/x.osm"}'}],
                       "structured_content": {"ok": True}},
            "error": None, "status": "completed"}},
        {"type": "item.completed", "item": {
            "id": "item_2", "type": "mcp_tool_call", "server": "openstudio",
            "tool": "apply_measure", "arguments": {},
            "result": None,
            "error": {"message": "user cancelled MCP tool call"},
            "status": "failed"}},
        {"type": "item.completed", "item": {
            "id": "item_3", "type": "agent_message", "text": "Created x."}},
        {"type": "turn.completed", "usage": {
            "input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 20}},
    )
    r = _parse_codex_jsonl(raw)
    assert r.tool_names == ["create_baseline_osm", "apply_measure"]
    assert r.tool_ok("create_baseline_osm") is True
    assert r.tool_ok("apply_measure") is False  # cancelled -> synthesized ok:false
    assert r.results_for("create_baseline_osm")[0]["osm_path"] == "/runs/x.osm"
    assert r.final_text == "Created x."
    assert r.input_tokens == 100
    assert r.cache_read_tokens == 40
    assert r.is_error is False
    assert r.cost_usd == 0.0  # codex reports tokens, not dollars


def test_run_agent_rejects_unknown_provider(monkeypatch):
    # Validates: a typo'd LLM_TESTS_PROVIDER fails loudly instead of silently
    # benchmarking the wrong backend
    monkeypatch.setenv("LLM_TESTS_PROVIDER", "gpt5-typo")
    with pytest.raises(ValueError, match="gpt5-typo"):
        run_agent("hello")


def test_mcp_config_image_and_ablation_plumbing(monkeypatch, tmp_path):
    # Validates: LLM_TESTS_IMAGE pins the benchmark artifact and
    # LLM_TESTS_ARM=noskills injects the server-side ablation env (D3)
    monkeypatch.setenv("LLM_TESTS_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("LLM_TESTS_MEASURES_DIR", str(tmp_path / "measures"))
    monkeypatch.setenv("LLM_TESTS_IMAGE", "openstudio-mcp:v9.9.9")
    monkeypatch.setenv("LLM_TESTS_ARM", "noskills")
    args = json.loads(_write_mcp_config().read_text())["mcpServers"]["openstudio"]["args"]
    assert "openstudio-mcp:v9.9.9" in args
    assert "OSMCP_DISABLE_KNOWLEDGE_SKILLS=1" in args

    monkeypatch.setenv("LLM_TESTS_ARM", "full")
    monkeypatch.delenv("LLM_TESTS_IMAGE", raising=False)
    args = json.loads(_write_mcp_config().read_text())["mcpServers"]["openstudio"]["args"]
    assert "openstudio-mcp:dev" in args
    assert "OSMCP_DISABLE_KNOWLEDGE_SKILLS=1" not in args


def test_toolsearch_queries_captured_in_stats():
    # Validates: ToolSearch query strings land in stats/benchmark.json —
    # the ablation's discovery-substitution evidence (WHICH schemas Claude
    # Code fetches by name instead of consulting the knowledge layer)
    raw = _ndjson(
        {"type": "system", "subtype": "init"},
        _assistant("t1", "ToolSearch",
                   {"query": "select:mcp__openstudio__load_osm_model", "max_results": 1}),
        _tool_result("t1", "schemas loaded"),
        _assistant("t2", "mcp__openstudio__load_osm_model", {"osm_path": "/runs/x.osm"}),
        _tool_result("t2", '{"ok": true}'),
        _assistant("t3", "ToolSearch", {"query": "thermostat setpoint", "max_results": 5}),
        _tool_result("t3", "schemas loaded"),
        {"type": "result", "result": "done", "total_cost_usd": 0.0, "num_turns": 3,
         "usage": {"input_tokens": 1, "output_tokens": 1}},
    )
    result = _parse_stream_json(raw)
    assert result.toolsearch_count == 2
    assert result.toolsearch_queries == [
        "select:mcp__openstudio__load_osm_model", "thermostat setpoint"]
    assert result.stats["toolsearch_queries"] == result.toolsearch_queries


def test_leg_env_isolates_measures_dir(tmp_path):
    # Regression: pilot-4 — the shared default measures volume leaked a
    # previous leg's authored measure into later legs; gpt-5.4-mini found it
    # via list_custom_measures and reused it instead of authoring its own
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parents[1] / "scripts"))
    from benchmark_sweep import leg_env

    e1 = leg_env({}, model="haiku", provider="claude", arm="full",
                 image="img:dev", runs_dir=tmp_path / "leg_a", meta={"git": "x"},
                 repeat=1)
    e2 = leg_env({}, model="haiku", provider="claude", arm="noskills",
                 image="img:dev", runs_dir=tmp_path / "leg_b", meta={"git": "x"},
                 repeat=1)
    assert e1["LLM_TESTS_MEASURES_DIR"] == str(tmp_path / "leg_a" / "measures")
    assert e1["LLM_TESTS_MEASURES_DIR"] != e2["LLM_TESTS_MEASURES_DIR"]
    assert e1["LLM_TESTS_RUNS_DIR"] != e2["LLM_TESTS_RUNS_DIR"]
    assert e1["LLM_TESTS_RETRIES"] == "0"


def test_powershell_and_localshell_classified_builtin():
    # Regression: BUILTIN_TOOLS lacked "PowerShell" — on Windows legs the
    # agent's PowerShell calls were counted as MCP tool names, misclassifying
    # harness-escape failures as wrong_tool instead of no_mcp_tool
    raw = _ndjson(
        _assistant("t1", "PowerShell", {"command": "ls C:/"}),
        _tool_result("t1", "dir listing"),
        _assistant("t2", "mcp__openstudio__list_spaces", {}),
        _tool_result("t2", '{"ok": true, "spaces": []}'),
        {"type": "result", "result": "done"},
    )
    r = _parse_stream_json(raw)
    assert r.tool_names == ["list_spaces"]
    assert r.host_tool_counts == {"PowerShell": 1}
    assert r.stats["host_tool_call_count"] == 1


def test_codex_command_execution_visible_to_host_metrics():
    # Validates: codex command_execution items (host shell) surface as
    # builtin LocalShell calls — before this, codex host-side activity was
    # invisible to the harness-escape metric (pilot transcripts show codex
    # rg'ing the server repo with zero trace in benchmark.json)
    from llm.runner import _parse_codex_jsonl
    raw = _ndjson(
        {"type": "item.completed", "item": {
            "id": "c1", "type": "command_execution",
            "command": 'powershell.exe -Command "rg --files"',
            "aggregated_output": "mcp_server\\config.py\n",
            "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {
            "id": "m1", "type": "mcp_tool_call", "server": "openstudio",
            "tool": "list_spaces", "arguments": {},
            "result": {"content": [{"type": "text", "text": '{"ok": true}'}]},
            "error": None, "status": "completed"}},
        {"type": "turn.completed", "usage": {
            "input_tokens": 5, "cached_input_tokens": 0, "output_tokens": 5}},
    )
    r = _parse_codex_jsonl(raw)
    assert r.tool_names == ["list_spaces"]
    assert r.host_tool_counts == {"LocalShell": 1}
    assert r.tool_results["c1"] == {
        "exit_code": 0, "output": "mcp_server\\config.py\n"}


def test_agent_cwd_fresh_empty_unique(monkeypatch, tmp_path):
    # Validates: each agent invocation gets its own EMPTY sandbox dir under
    # the leg's runs dir — the anti-escape/anti-leak isolation boundary
    from llm.runner import _agent_cwd
    monkeypatch.setenv("LLM_TESTS_RUNS_DIR", str(tmp_path))
    a, b = _agent_cwd(), _agent_cwd()
    assert a != b
    from pathlib import Path
    for d in (a, b):
        assert Path(d).is_dir()
        assert list(Path(d).iterdir()) == [], "sandbox cwd must start empty"
        assert Path(d).parent == tmp_path / "agent_cwd"


def test_run_claude_uses_sandbox_cwd_and_reports_droppings(monkeypatch, tmp_path):
    # Regression: pilot-5a — agent CLI inherited pytest cwd (the server's own
    # repo); haiku read our source, authored an out-of-band MCP client, and
    # dropped artifacts that persisted across legs. cwd must be the sandbox.
    import llm.runner as runner
    monkeypatch.setenv("LLM_TESTS_RUNS_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_TESTS_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_TESTS_ARM", raising=False)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"], captured["cwd"] = cmd, kwargs.get("cwd")
        captured["encoding"] = kwargs.get("encoding")
        import subprocess
        return subprocess.CompletedProcess(
            cmd, 0, stdout='{"type": "result", "result": "ok"}', stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner.run_claude("hi", use_mcp=False)
    # Regression: no encoding -> cp1252 on Windows -> UnicodeDecodeError on
    # 0x90 killed a pilot-5 test as a fake failure (and mojibake'd transcripts)
    assert captured["encoding"] == "utf-8"

    from pathlib import Path
    cwd = Path(captured["cwd"])
    assert cwd.parent == tmp_path / "agent_cwd", \
        f"agent must run in the per-leg sandbox, got {cwd}"
    assert result.agent_cwd == str(cwd)
    assert result.stats["dropped_files"] == []
    (cwd / "escape.txt").write_text("dropped")
    assert result.stats["dropped_files"] == ["escape.txt"]


def test_dropped_files_sees_gitbash_tmp_mirror(monkeypatch, tmp_path):
    # Regression: live smoke 2026-08-06 — Claude Code's Bash tool presents a
    # %TEMP% sandbox cwd as /tmp/..., which Git Bash resolves to C:\tmp\...;
    # the agent's file landed in that mirror and dropped_files missed it
    import tempfile as _tempfile
    from pathlib import Path

    import llm.runner as runner

    temp_root = tmp_path / "temp"
    sandbox = temp_root / "agent_cwd" / "t123"
    sandbox.mkdir(parents=True)
    mirror = Path(temp_root.anchor) / "tmp" / "agent_cwd" / "t123"
    mirror.mkdir(parents=True, exist_ok=True)
    (mirror / "escaped.txt").write_text("via bash /tmp")
    monkeypatch.setattr(_tempfile, "gettempdir", lambda: str(temp_root))
    try:
        r = runner.AgentResult(messages=[], result={})
        r.agent_cwd = str(sandbox)
        assert r.dropped_files == ["escaped.txt"]
    finally:
        import contextlib
        import shutil
        shutil.rmtree(mirror, ignore_errors=True)
        with contextlib.suppress(OSError):
            mirror.parent.rmdir()  # only if we created it and it's now empty


def test_run_codex_uses_sandbox_cwd(monkeypatch, tmp_path):
    # Validates: the codex backend gets the same sandbox isolation as claude
    import llm.runner as runner
    monkeypatch.setenv("LLM_TESTS_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_TESTS_CODEX_CMD", "codex-fake")
    monkeypatch.delenv("LLM_TESTS_ARM", raising=False)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cwd"] = kwargs.get("cwd")
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner._run_codex("hi", use_mcp=False)
    from pathlib import Path
    assert Path(captured["cwd"]).parent == tmp_path / "agent_cwd"
    assert result.agent_cwd == captured["cwd"]


def test_nohost_arm_blocks_host_tools(monkeypatch, tmp_path):
    # Validates: arm "nohost" removes host-touching tools from claude
    # (stoppability lever for the harness-escape study) and fails loudly on
    # codex, which has no per-tool disable
    import llm.runner as runner
    monkeypatch.setenv("LLM_TESTS_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_TESTS_ARM", "nohost")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        import subprocess
        return subprocess.CompletedProcess(
            cmd, 0, stdout='{"type": "result", "result": "ok"}', stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner._run_claude("hi", use_mcp=False)
    flag = captured["cmd"].index("--disallowedTools")
    blocked = captured["cmd"][flag + 1]
    for tool in ("Bash", "PowerShell", "Read", "Write", "Edit"):
        assert tool in blocked, f"nohost arm must block {tool}"
    assert "ToolSearch" not in blocked, "discovery is not host access"

    monkeypatch.setenv("LLM_TESTS_CODEX_CMD", "codex-fake")
    with pytest.raises(ValueError, match=r"nohost.*claude-only"):
        runner._run_codex("hi")

    monkeypatch.setenv("LLM_TESTS_ARM", "full")
    captured.clear()
    runner._run_claude("hi", use_mcp=False)
    assert "--disallowedTools" not in captured["cmd"]


def test_nodiscovery_arm_plumbing(monkeypatch):
    # Validates: arm "nodiscovery" disables Claude Code's ToolSearch
    # (ENABLE_TOOL_SEARCH=false -> schemas load up-front, client discovery
    # removed) and "nodiscovery-noskills" composes with the server-side
    # knowledge ablation — the claude-side analogue of the codex ablation
    from llm.runner import _claude_env, _docker_mcp_args

    monkeypatch.setenv("LLM_TESTS_ARM", "nodiscovery-noskills")
    assert _claude_env()["ENABLE_TOOL_SEARCH"] == "false"
    assert "OSMCP_DISABLE_KNOWLEDGE_SKILLS=1" in _docker_mcp_args()

    monkeypatch.setenv("LLM_TESTS_ARM", "nodiscovery")
    assert _claude_env()["ENABLE_TOOL_SEARCH"] == "false"
    assert "OSMCP_DISABLE_KNOWLEDGE_SKILLS=1" not in _docker_mcp_args()

    monkeypatch.setenv("LLM_TESTS_ARM", "full")
    assert "ENABLE_TOOL_SEARCH" not in _claude_env()

    monkeypatch.setenv("LLM_TESTS_ARM", "noskills")
    assert "ENABLE_TOOL_SEARCH" not in _claude_env()
    assert "OSMCP_DISABLE_KNOWLEDGE_SKILLS=1" in _docker_mcp_args()

    monkeypatch.setenv("CLAUDECODE", "1")
    assert "CLAUDECODE" not in _claude_env()
