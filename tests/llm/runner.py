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
import subprocess
import tempfile
from pathlib import Path

# Built-in tools used by Claude Code internally (not MCP tools)
BUILTIN_TOOLS = frozenset({
    "ToolSearch", "Task", "TaskOutput", "TaskStop",
    "Bash", "Glob", "Grep", "Read", "Edit", "Write",
    "NotebookEdit", "WebFetch", "WebSearch", "TodoWrite",
    "AskUserQuestion", "Skill", "EnterPlanMode", "ExitPlanMode",
    "EnterWorktree", "LSP", "ListMcpResourcesTool", "ReadMcpResourceTool",
})


class ClaudeResult:
    """Parsed result from a Claude Code CLI invocation."""

    def __init__(self, messages: list[dict], result: dict):
        self.messages = messages
        self.result = result

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
    def tool_names(self) -> list[str]:
        """MCP tool names with mcp__openstudio__ prefix stripped."""
        prefix = "mcp__openstudio__"
        return [c["tool"].removeprefix(prefix) for c in self.mcp_tool_calls]

    @property
    def all_tool_names(self) -> list[str]:
        """All tool names (including built-in), no prefix stripping."""
        return [c["tool"] for c in self.tool_calls]

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


def run_claude(
    prompt: str,
    model: str | None = None,
    timeout: int = 120,
    allowed_tools: str = "mcp__openstudio__*",
    system_prompt: str | None = None,
    max_turns: int | None = None,
) -> ClaudeResult:
    """Run Claude Code CLI with MCP config and return parsed result.

    Uses stream-json --verbose to capture tool_use blocks.
    ToolSearch calls (deferred tool loading) consume turns, so max_turns
    should be set generously (default 5 for simple queries).
    """
    model = model or os.environ.get("LLM_TESTS_MODEL", "sonnet")
    mcp_config = _write_mcp_config()

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--mcp-config", str(mcp_config),
        "--model", model,
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--allowedTools", allowed_tools,
    ]

    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    if max_turns:
        cmd.extend(["--max-turns", str(max_turns)])

    # Strip CLAUDECODE env var so nested claude CLI doesn't refuse to run
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        # Parse whatever output we got before timeout
        partial = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        parsed = _parse_stream_json(partial)
        # Mark as error so tests can assert on it
        parsed.result["is_error"] = True
        parsed.result["result"] = f"Timed out after {timeout}s"
        return parsed

    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (rc={result.returncode}):\n"
            f"stderr: {result.stderr[:2000]}",
        )

    return _parse_stream_json(result.stdout)


def _parse_stream_json(raw: str) -> ClaudeResult:
    """Parse newline-delimited JSON from stream-json output."""
    messages = []
    result_obj = {}

    for line in raw.strip().splitlines():
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

    return ClaudeResult(messages=messages, result=result_obj)


def _write_mcp_config() -> Path:
    """Write temporary MCP config for Docker stdio transport."""
    runs_dir = os.environ.get("LLM_TESTS_RUNS_DIR", "/tmp/llm-test-runs")

    config = {
        "mcpServers": {
            "openstudio": {
                "command": "docker",
                "args": [
                    "run", "--rm", "-i",
                    "-v", f"{runs_dir}:/runs",
                    "-e", "OPENSTUDIO_MCP_MODE=prod",
                    "openstudio-mcp:dev",
                    "openstudio-mcp",
                ],
            },
        },
    }
    tmpdir = Path(tempfile.mkdtemp(prefix="llm-test-"))
    path = tmpdir / "mcp.json"
    path.write_text(json.dumps(config))
    return path
