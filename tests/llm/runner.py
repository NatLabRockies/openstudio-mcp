"""LLM test runner — wraps Claude Code CLI for agent testing.

Runs `claude -p` with MCP config pointing at openstudio-mcp Docker server,
parses NDJSON output, and extracts tool calls for assertions.

Output format:
  --output-format stream-json --verbose → newline-delimited JSON messages
  including assistant messages with tool_use content blocks.

  NOTE: --output-format json only returns a final result object (no tool
  calls visible). stream-json is required for tool_use block extraction.
  The --verbose flag is required with stream-json.

Message types in NDJSON output:
  - type=system → initialization messages (MCP server connected, etc.)
  - type=assistant → Claude's responses, including tool_use content blocks
  - type=user → tool results (tool_result content blocks)
  - type=result → final result object with cost, turn count, etc.

CLAUDECODE env var:
  Claude Code sets CLAUDECODE env var to detect nesting. Since these tests
  run FROM Claude Code, we strip CLAUDECODE from the subprocess env to
  allow nested `claude -p` calls.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

# Built-in tools used by Claude Code internally (not MCP tools).
# "PowerShell" is the Windows shell tool — omitting it counted PowerShell
# calls as MCP tool names on Windows legs (misclassified no_mcp_tool
# failures as wrong_tool). "LocalShell" is our synthetic name for codex
# command_execution items.
BUILTIN_TOOLS = frozenset({
    "ToolSearch", "Task", "TaskOutput", "TaskStop",
    "Bash", "PowerShell", "LocalShell", "Glob", "Grep", "Read", "Edit",
    "Write", "NotebookEdit", "WebFetch", "WebSearch", "TodoWrite",
    "AskUserQuestion", "Skill", "EnterPlanMode", "ExitPlanMode",
    "EnterWorktree", "LSP", "ListMcpResourcesTool", "ReadMcpResourceTool",
    "Agent",
})

# Tools that touch the HOST machine (shell, filesystem, network) — the
# harness-escape metric counts these. Excludes ToolSearch (client-side
# schema discovery, no host access) and bookkeeping tools (TodoWrite etc).
# Harness-escape evidence (pilot-5a): haiku read server source and authored
# its own out-of-band MCP client via Bash/Write; codex agents rg'd the repo.
HOST_TOOLS = frozenset({
    "Bash", "PowerShell", "LocalShell", "Glob", "Grep", "Read", "Edit",
    "Write", "NotebookEdit", "WebFetch", "WebSearch", "Agent", "Task",
    "EnterWorktree", "LSP",
})


DEFAULT_SYSTEM_PROMPT = (
    "You are an OpenStudio building energy modeling assistant. "
    "Use the MCP tools for all building energy modeling tasks. "
    "For multi-step tasks, complete ALL steps in the prompt before stopping."
)


class AgentResult:
    """Normalized result from an agent CLI invocation (provider-agnostic).

    Built today from Claude Code stream-json; the codex adapter maps its
    JSONL events into the same shape (messages with tool_use/tool_result
    blocks + a result object). Usage fields are 0 when a provider does not
    report them.
    """

    def __init__(self, messages: list[dict], result: dict, raw_ndjson: str = ""):
        self.messages = messages
        self.result = result
        self.raw_ndjson = raw_ndjson
        # Sandbox working directory the agent CLI ran in (set by the
        # backend). None for results built outside a backend (unit fixtures).
        self.agent_cwd: str | None = None

    @property
    def tool_calls(self) -> list[dict]:
        """All tool_use blocks from assistant messages (including built-in)."""
        calls = []
        for msg in self.messages:
            if msg.get("type") == "assistant":
                for block in msg.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        calls.append({
                            "tool": block["name"],
                            "input": block.get("input", {}),
                        })
        return calls

    @property
    def mcp_tool_calls(self) -> list[dict]:
        """Only MCP tool calls (excluding ToolSearch, Bash, etc.)."""
        return [c for c in self.tool_calls if c["tool"] not in BUILTIN_TOOLS]

    @property
    def code_mode_tool_calls(self) -> list[str]:
        """Extract tool names from CodeMode execute calls."""
        names = []
        for c in self.mcp_tool_calls:
            stripped = c["tool"].removeprefix("mcp__openstudio__")
            if stripped == "execute":
                code = c["input"].get("code", "")
                for m in re.finditer(r'call_tool\(["\'](\w+)["\']', code):
                    names.append(m.group(1))
        return names

    @property
    def tool_names(self) -> list[str]:
        """MCP tool names with mcp__openstudio__ prefix stripped.

        Includes tools called inside CodeMode execute blocks.
        """
        prefix = "mcp__openstudio__"
        # CodeMode meta-tools (search, get_schema, execute) excluded from
        # domain tool list — only the real tools they invoke count.
        code_mode_meta = frozenset({"search", "get_schema", "execute"})
        direct = [
            c["tool"].removeprefix(prefix)
            for c in self.mcp_tool_calls
            if c["tool"].removeprefix(prefix) not in code_mode_meta
        ]
        return direct + self.code_mode_tool_calls

    @property
    def all_tool_names(self) -> list[str]:
        """All tool names (including built-in), no prefix stripping."""
        return [c["tool"] for c in self.tool_calls]

    @property
    def tool_results(self) -> dict[str, dict]:
        """tool_use id -> parsed tool_result JSON (or {"_raw": text}).

        tool_result blocks arrive in type=user messages; content is either a
        plain string or a list of text blocks. Non-JSON results are preserved
        under "_raw" so callers can still inspect them.
        """
        results: dict[str, dict] = {}
        for msg in self.messages:
            if msg.get("type") != "user":
                continue
            content = msg.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                    continue
                text = _tool_result_text(block.get("content"))
                try:
                    parsed = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    parsed = {"_raw": text}
                if not isinstance(parsed, dict):
                    parsed = {"_raw": text}
                results[block.get("tool_use_id", "")] = parsed
        return results

    def results_for(self, name: str) -> list[dict]:
        """Parsed results of every call to `name` (prefix-stripped), in call order.

        Calls whose result never arrived (e.g. cut off by timeout) are skipped.
        """
        prefix = "mcp__openstudio__"
        results = self.tool_results
        out = []
        for msg in self.messages:
            if msg.get("type") != "assistant":
                continue
            for block in msg.get("message", {}).get("content", []):
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block["name"].removeprefix(prefix) == name
                ):
                    res = results.get(block.get("id", ""))
                    if res is not None:
                        out.append(res)
        return out

    def tool_ok(self, name: str) -> bool | None:
        """ok flag of the FIRST call to `name` (prefix-stripped match).

        Returns None if the tool was never called or its result carries no
        boolean ok flag — asserts should use `is not False` so undeterminable
        results don't fail.
        """
        results = self.results_for(name)
        if not results:
            return None
        ok = results[0].get("ok")
        return ok if isinstance(ok, bool) else None

    @property
    def final_text(self) -> str:
        """Final text result."""
        return self.result.get("result", "") or ""

    @property
    def is_error(self) -> bool:
        return self.result.get("is_error", False)

    @property
    def cost_usd(self) -> float:
        return self.result.get("total_cost_usd", 0.0)

    @property
    def num_turns(self) -> int:
        return self.result.get("num_turns", 0)

    @property
    def duration_ms(self) -> int:
        return self.result.get("duration_ms", 0)

    @property
    def input_tokens(self) -> int:
        usage = self.result.get("usage", {})
        return usage.get("input_tokens", 0)

    @property
    def output_tokens(self) -> int:
        usage = self.result.get("usage", {})
        return usage.get("output_tokens", 0)

    @property
    def cache_read_tokens(self) -> int:
        usage = self.result.get("usage", {})
        return usage.get("cache_read_input_tokens", 0)

    @property
    def toolsearch_count(self) -> int:
        """Number of ToolSearch calls — proxy for tool discovery overhead."""
        return sum(1 for c in self.tool_calls if c["tool"] == "ToolSearch")

    @property
    def toolsearch_queries(self) -> list[str]:
        """Raw ToolSearch query strings, in call order.

        Discovery-substitution evidence for the ablation: Claude Code models
        fetch schemas by name ("select:mcp__openstudio__x,...") instead of
        consulting the server's knowledge layer — WHICH tools they reach for
        (and whether that differs between arms) is the mechanism the paper
        reports alongside knowledge-call counts.
        """
        return [
            str(c["input"].get("query", ""))
            for c in self.tool_calls if c["tool"] == "ToolSearch"
        ]

    @property
    def host_tool_counts(self) -> dict[str, int]:
        """Host-touching tool calls by name (Bash, Read, Write, ...).

        The harness-escape metric: an agent that solves (or fails) a task
        with zero MCP calls but nonzero host calls did not disengage — it
        went around the MCP layer (pilot-5a: haiku authored its own MCP
        client from our server source and fabricated a success report).
        """
        counts: dict[str, int] = {}
        for c in self.tool_calls:
            if c["tool"] in HOST_TOOLS:
                counts[c["tool"]] = counts.get(c["tool"], 0) + 1
        return counts

    @property
    def dropped_files(self) -> list[str]:
        """Files the agent left in its sandbox cwd (relative paths).

        Empty when the sandbox is clean or agent_cwd is unset. Forensic
        evidence for escape analysis — a benchmark agent has no legitimate
        reason to write host files.
        """
        if not self.agent_cwd:
            return []
        roots = [Path(self.agent_cwd)]
        # Windows Git-Bash /tmp asymmetry (live smoke, 2026-08-06): the Bash
        # tool presents a cwd under %TEMP% as /tmp/..., which Git Bash
        # resolves to C:\tmp\... — Bash-created files land in that MIRROR of
        # the sandbox, not the sandbox itself. Scan both.
        temp_root = Path(tempfile.gettempdir())
        try:
            rel = roots[0].relative_to(temp_root)
            roots.append(Path(temp_root.anchor) / "tmp" / rel)
        except ValueError:
            pass  # sandbox not under %TEMP% — no mirror
        found = set()
        for root in roots:
            if root.is_dir():
                found.update(
                    str(p.relative_to(root))
                    for p in root.rglob("*") if p.is_file()
                )
        return sorted(found)

    @property
    def stats(self) -> dict:
        """Summary stats for benchmarking."""
        return {
            "num_turns": self.num_turns,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "tool_calls": self.tool_names,
            "num_tool_calls": len(self.tool_names),
            "all_tool_calls": self.all_tool_names,
            "toolsearch_count": self.toolsearch_count,
            "toolsearch_queries": self.toolsearch_queries,
            "host_tool_counts": self.host_tool_counts,
            "host_tool_call_count": sum(self.host_tool_counts.values()),
            "agent_cwd": self.agent_cwd,
            "dropped_files": self.dropped_files,
            "is_timeout": self.is_error and "Timed out" in self.final_text,
            "code_mode_active": bool(self.code_mode_tool_calls),
            "code_executions": sum(
                1 for c in self.mcp_tool_calls
                if c["tool"].removeprefix("mcp__openstudio__") == "execute"
            ),
        }


def _agent_cwd() -> str:
    """Fresh EMPTY working directory for one agent CLI invocation.

    Before 2026-08-06 the agent inherited pytest's cwd — the SERVER'S OWN
    REPO. Agents read our source to learn tool internals, grepped the
    grading tests (answer leakage), and dropped artifacts that persisted
    across sweep legs on the host (haiku authored an out-of-band MCP client
    and left a model in repo runs/). An empty per-test dir closes the
    starting-point leak; dirs are kept (not cleaned) under the leg's runs
    dir as forensic evidence for the dropped_files metric.
    """
    base = Path(os.environ.get("LLM_TESTS_RUNS_DIR",
                               str(Path(tempfile.gettempdir()) / "llm-test-runs")))
    cwd_root = base / "agent_cwd"
    cwd_root.mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(prefix="t", dir=cwd_root)


def _claude_env() -> dict:
    """Env for the claude subprocess.

    Strips CLAUDECODE (a nested claude CLI refuses to run). Arms containing
    "nodiscovery" set ENABLE_TOOL_SEARCH=false: Claude Code then loads every
    MCP tool schema up-front instead of discovering via ToolSearch — removes
    the client-side discovery that substitutes for the server's knowledge
    layer, making the claude-side ablation symmetric with codex (which has
    no client discovery). Composes with the server-side ablation as
    "nodiscovery-noskills".
    """
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    if "nodiscovery" in os.environ.get("LLM_TESTS_ARM", ""):
        env["ENABLE_TOOL_SEARCH"] = "false"
    return env


def _tool_result_text(content) -> str:
    """Flatten a tool_result content field (string or text-block list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


# Back-compat alias — tests written against the Claude-only runner still work
ClaudeResult = AgentResult

# Last result from run_agent — used by conftest benchmark tracking
_last_result: AgentResult | None = None


def run_agent(
    prompt: str,
    model: str | None = None,
    timeout: int = 120,
    allowed_tools: str = "mcp__openstudio__*",
    system_prompt: str | None = None,
    max_turns: int | None = None,
    use_mcp: bool = True,
) -> AgentResult:
    """Run the configured agent backend and return a normalized AgentResult.

    Backend selected by LLM_TESTS_PROVIDER (default "claude"). use_mcp=False
    omits the MCP server entirely (Arm C codegen baseline — the agent gets
    only shell/file tools and must script the SDK itself).
    """
    provider = os.environ.get("LLM_TESTS_PROVIDER", "claude")
    backend = _BACKENDS.get(provider)
    if backend is None:
        raise ValueError(
            f"Unknown LLM_TESTS_PROVIDER '{provider}' — known: {sorted(_BACKENDS)}")
    return backend(
        prompt, model=model, timeout=timeout, allowed_tools=allowed_tools,
        system_prompt=system_prompt, max_turns=max_turns, use_mcp=use_mcp,
    )


def run_claude(
    prompt: str,
    model: str | None = None,
    timeout: int = 120,
    allowed_tools: str = "mcp__openstudio__*",
    system_prompt: str | None = None,
    max_turns: int | None = None,
    use_mcp: bool = True,
) -> AgentResult:
    """Compat wrapper — existing tests call run_claude; dispatches run_agent."""
    return run_agent(
        prompt, model=model, timeout=timeout, allowed_tools=allowed_tools,
        system_prompt=system_prompt, max_turns=max_turns, use_mcp=use_mcp,
    )


def _run_claude(
    prompt: str,
    model: str | None = None,
    timeout: int = 120,
    allowed_tools: str = "mcp__openstudio__*",
    system_prompt: str | None = None,
    max_turns: int | None = None,
    use_mcp: bool = True,
) -> AgentResult:
    """Claude Code CLI backend.

    Uses stream-json --verbose to capture tool_use blocks.
    ToolSearch calls (deferred tool loading) consume turns, so max_turns
    should be set generously (default 5 for simple queries).
    """
    global _last_result
    model = model or os.environ.get("LLM_TESTS_MODEL", "sonnet")
    system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--allowedTools", allowed_tools,
        "--system-prompt", system_prompt,
    ]
    # Arm "nohost": remove host-touching tools entirely — tests whether the
    # harness-escape behavior is STOPPABLE, and what the agent does when the
    # MCP layer is the only route. ToolSearch stays (discovery, not host).
    if "nohost" in os.environ.get("LLM_TESTS_ARM", ""):
        cmd += ["--disallowedTools", ",".join(sorted(HOST_TOOLS))]
    if use_mcp:
        cmd += ["--mcp-config", str(_write_mcp_config())]
    if max_turns:
        cmd.extend(["--max-turns", str(max_turns)])

    env = _claude_env()
    agent_cwd = _agent_cwd()

    try:
        # encoding: claude emits UTF-8; without it Windows decodes cp1252 —
        # mojibake in every transcript and a hard UnicodeDecodeError on bytes
        # like 0x90 (killed a pilot-5 test as a fake failure). codex path
        # already had this.
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
            env=env, cwd=agent_cwd, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        # Parse whatever output we got before timeout
        partial = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        parsed = _parse_stream_json(partial)
        # Mark as error so tests can assert on it
        parsed.result["is_error"] = True
        parsed.result["result"] = f"Timed out after {timeout}s"
        parsed.agent_cwd = agent_cwd
        _last_result = parsed
        return parsed

    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (rc={result.returncode}):\n"
            f"stderr: {result.stderr[:2000]}\n"
            f"stdout tail: {(result.stdout or '')[-2000:]}",
        )

    _last_result = _parse_stream_json(result.stdout)
    _last_result.agent_cwd = agent_cwd
    return _last_result


def _find_codex() -> str:
    """Locate the codex CLI: env override, PATH, then the Windows install dir."""
    override = os.environ.get("LLM_TESTS_CODEX_CMD")
    if override:
        return override
    import shutil as _shutil
    found = _shutil.which("codex") or _shutil.which("codex.exe")
    if found:
        return found
    default = (Path(os.environ.get("LOCALAPPDATA", ""))
               / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe")
    if default.is_file():
        return str(default)
    raise RuntimeError(
        "codex CLI not found — install it or set LLM_TESTS_CODEX_CMD")


def _run_codex(
    prompt: str,
    model: str | None = None,
    timeout: int = 120,
    allowed_tools: str = "mcp__openstudio__*",
    system_prompt: str | None = None,
    max_turns: int | None = None,
    use_mcp: bool = True,
) -> AgentResult:
    """codex exec backend (SPIKE-1 verified 2026-08-05, codex-cli 0.146.0).

    - MCP server injected via -c mcp_servers.openstudio overrides;
      --ignore-user-config keeps the user's config out while CODEX_HOME auth
      still applies.
    - --dangerously-bypass-approvals-and-sandbox is required: exec mode
      auto-cancels MCP tool calls otherwise ("user cancelled MCP tool call");
      approval_policy=never does NOT cover MCP calls. Mirrors claude's
      --dangerously-skip-permissions role in this harness.
    - No --system-prompt equivalent: system prompt is PREPENDED to the user
      prompt (footnoted in the paper). allowed_tools/max_turns have no codex
      equivalent and are ignored.
    """
    global _last_result
    if "nohost" in os.environ.get("LLM_TESTS_ARM", ""):
        raise ValueError(
            "arm 'nohost' is claude-only: codex exec has no per-tool disable "
            "(its sandbox flags cancel MCP calls too) — drop the arm or the "
            "codex leg")
    model = model or os.environ.get("LLM_TESTS_MODEL") or None
    system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    full_prompt = f"{system_prompt}\n\n{prompt}"

    cmd = [
        _find_codex(), "exec", "--json", "--ephemeral",
        "--skip-git-repo-check", "--ignore-user-config",
        "--dangerously-bypass-approvals-and-sandbox",
        "--color", "never",
    ]
    if use_mcp:
        docker_args_toml = json.dumps(_docker_mcp_args())  # JSON array is valid TOML
        cmd += [
            "-c", 'mcp_servers.openstudio.command="docker"',
            "-c", f"mcp_servers.openstudio.args={docker_args_toml}",
        ]
    if model:
        cmd += ["-m", model]
    cmd.append(full_prompt)

    agent_cwd = _agent_cwd()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
            cwd=agent_cwd,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout if isinstance(exc.stdout, str) else (
            exc.stdout.decode("utf-8", "replace") if exc.stdout else "")
        parsed = _parse_codex_jsonl(partial)
        parsed.result["is_error"] = True
        parsed.result["result"] = f"Timed out after {timeout}s"
        parsed.agent_cwd = agent_cwd
        _last_result = parsed
        return parsed

    if result.returncode != 0:
        raise RuntimeError(
            f"codex CLI failed (rc={result.returncode}):\n"
            f"stderr: {result.stderr[:2000]}\n"
            f"stdout tail: {(result.stdout or '')[-2000:]}",
        )

    _last_result = _parse_codex_jsonl(result.stdout)
    _last_result.agent_cwd = agent_cwd
    return _last_result


def _parse_codex_jsonl(raw: str | None) -> AgentResult:
    """Map codex exec --json events onto the claude-shaped AgentResult.

    Each completed mcp_tool_call item is synthesized into an assistant
    tool_use block + a user tool_result block (result text preferred,
    structured_content fallback), so every AgentResult accessor —
    tool_names, tool_ok, results_for — works identically across backends.
    """
    messages: list[dict] = []
    final_text = ""
    usage: dict = {}
    is_error = False

    for line in (raw or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = obj.get("type", "")
        if etype == "item.completed":
            item = obj.get("item", {})
            itype = item.get("type")
            if itype == "mcp_tool_call":
                item_id = item.get("id", "")
                name = f"mcp__{item.get('server', 'openstudio')}__{item.get('tool', '')}"
                messages.append({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": item_id, "name": name,
                     "input": item.get("arguments") or {}},
                ]}})
                res = item.get("result") or {}
                text = _tool_result_text(res.get("content"))
                if not text and item.get("error"):
                    text = json.dumps(
                        {"ok": False, "error": item["error"].get("message", "")})
                if not text and res.get("structured_content") is not None:
                    text = json.dumps(res["structured_content"])
                messages.append({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": item_id,
                     "content": text},
                ]}})
            elif itype == "command_execution":
                # Codex host-shell calls — synthesized as builtin "LocalShell"
                # tool_use blocks so host_tool_counts sees codex escapes the
                # same way it sees claude Bash/PowerShell calls. Excluded
                # from tool_names via BUILTIN_TOOLS.
                item_id = item.get("id", "")
                messages.append({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": item_id, "name": "LocalShell",
                     "input": {"command": item.get("command", "")}},
                ]}})
                messages.append({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": item_id,
                     "content": json.dumps({
                         "exit_code": item.get("exit_code"),
                         "output": item.get("aggregated_output", "")})},
                ]}})
            elif itype == "agent_message":
                final_text = item.get("text", "") or final_text
        elif etype == "turn.completed":
            u = obj.get("usage", {})
            usage = {
                "input_tokens": u.get("input_tokens", 0),
                "output_tokens": u.get("output_tokens", 0),
                "cache_read_input_tokens": u.get("cached_input_tokens", 0),
            }
        elif etype in ("turn.failed", "error"):
            is_error = True

    result_obj = {
        "result": final_text,
        "is_error": is_error,
        "usage": usage,
        # codex reports tokens, not dollars — cost stays 0 and the paper
        # reports token counts for cross-provider comparisons
        "total_cost_usd": 0.0,
        "num_turns": sum(1 for m in messages if m["type"] == "assistant"),
    }
    return AgentResult(messages=messages, result=result_obj, raw_ndjson=raw or "")


def _parse_stream_json(raw: str | None) -> AgentResult:
    """Parse newline-delimited JSON from stream-json output."""
    messages = []
    result_obj = {}

    for line in (raw or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if obj.get("type") == "result":
            result_obj = obj
        else:
            messages.append(obj)

    return AgentResult(messages=messages, result=result_obj, raw_ndjson=raw)


def _docker_mcp_args() -> list[str]:
    """Docker args for the openstudio MCP server — shared by every backend.

    /measures is a persistent volume: every agent call spawns a fresh --rm
    container, so without it custom measures and seeded fixtures (my_measure,
    EMS plugins) would vanish between tests.
    """
    _default_runs = str(Path(tempfile.gettempdir()) / "llm-test-runs")
    runs_dir = os.environ.get("LLM_TESTS_RUNS_DIR", _default_runs)
    _default_measures = str(Path(tempfile.gettempdir()) / "llm-test-measures")
    measures_dir = os.environ.get("LLM_TESTS_MEASURES_DIR", _default_measures)
    Path(measures_dir).mkdir(parents=True, exist_ok=True)
    assets_dir = str(Path(__file__).resolve().parents[1] / "assets")

    # Benchmark sweeps pin the exact image (LLM_TESTS_IMAGE=openstudio-mcp:v1.2.0)
    # so every benchmark.json can carry the artifact identity; dev default keeps
    # local iteration unchanged.
    image = os.environ.get("LLM_TESTS_IMAGE", "openstudio-mcp:dev")
    code_mode = os.environ.get("LLM_TESTS_CODE_MODE", "0")
    args = [
        "run", "--rm", "-i",
        "-v", f"{runs_dir}:/runs",
        "-v", f"{measures_dir}:/measures",
        "-v", f"{assets_dir}:/test-assets:ro",
        "-v", f"{assets_dir}:/inputs:ro",
        "-e", "OPENSTUDIO_MCP_MODE=prod",
        "-e", f"OSMCP_CODE_MODE={code_mode}",
    ]
    # Ablation arm: the knowledge-layer tools are absent server-side (refusals
    # from client-side blocking would contaminate behavior) — see
    # docs/plans/plan-benchmark-reviewer-response.md D3. Substring match so
    # the composite arm "nodiscovery-noskills" gets the server flag too.
    if "noskills" in os.environ.get("LLM_TESTS_ARM", ""):
        args += ["-e", "OSMCP_DISABLE_KNOWLEDGE_SKILLS=1"]
    args += [image, "openstudio-mcp"]
    return args


def _write_mcp_config() -> Path:
    """Write temporary MCP config for Docker stdio transport (claude backend)."""

    config = {"mcpServers": {"openstudio": {"command": "docker",
                                            "args": _docker_mcp_args()}}}
    tmpdir = Path(tempfile.mkdtemp(prefix="llm-test-"))
    path = tmpdir / "mcp.json"
    path.write_text(json.dumps(config))
    return path


# Provider name -> backend callable (same signature as run_agent)
_BACKENDS = {"claude": _run_claude, "codex": _run_codex}
