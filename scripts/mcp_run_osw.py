#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import sys
import time
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# --- result normalization ----------------------------------------------------
# MCP tool calls can return different payload shapes depending on client
# version. The helpers below normalize these into predictable Python objects.


def _unwrap_mcp_result(res: Any) -> Any:
    """Normalize MCP tool results to plain Python types.

    Why this exists:
    - Different MCP client versions return tool results in slightly different
      shapes.
    - For ad-hoc usage and debugging, we want a predictable object (dict or
      string) to print and to inspect.
    """
    if isinstance(res, dict):
        return res
    content = getattr(res, "content", None)
    if not content:
        return res
    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        return str(first)
    t = text.strip()
    if not t:
        return t
    try:
        return json.loads(t)
    except Exception:
        return t


# --- MCP invocation helpers --------------------------------------------------
# Centralize tool invocation so timeouts and formatting are consistent.

# --- MCP calling convenience -------------------------------------------------
# Wrap `session.call_tool` with consistent unwrapping + nicer exception messages.


async def _call_tool(session: ClientSession, name: str, args: dict, timeout: float) -> Any:
    """Call an MCP tool with a timeout and normalize the response.

    This keeps the rest of the script readable and provides a single place to
    adjust timeout handling or result normalization.
    """
    raw = await asyncio.wait_for(session.call_tool(name, args), timeout=timeout)
    return _unwrap_mcp_result(raw)


# --- small parsing utilities -------------------------------------------------
# These help keep the main orchestration logic readable.

# --- run bookkeeping ---------------------------------------------------------
# Helper functions for interpreting run_osw responses.


def _pick_run_id(run_res: Any) -> str | None:
    """Extract the run_id from a run_osw response (best-effort)."""
    if isinstance(run_res, dict):
        return run_res.get("run_id") or run_res.get("id")
    if isinstance(run_res, str):
        try:
            j = json.loads(run_res)
            if isinstance(j, dict):
                return j.get("run_id") or j.get("id")
        except Exception:
            return None
    return None


def _extract_status(status_payload: Any) -> str:
    """Extract the run status string from get_run_status output."""
    """Server returns {"ok": True, "run": {"status": "..."}}."""
    if isinstance(status_payload, dict):
        run = status_payload.get("run")
        if isinstance(run, dict):
            return str(run.get("status") or "")
        return str(status_payload.get("status") or status_payload.get("state") or "")
    return str(status_payload)


def _extract_logs_text(logs: Any) -> str:
    """Extract a printable log tail from get_run_logs output."""
    if isinstance(logs, dict):
        return str(logs.get("logs") or logs.get("text") or "")
    if isinstance(logs, str):
        return logs
    return ""


# --- small UX helpers --------------------------------------------------------
# Used only for nicer run naming in output.


def _guess_name_from_osw(osw_path: str) -> str:
    """Derive a stable, readable run name from an OSW path."""
    base = os.path.basename(osw_path.rstrip("/"))
    if base.lower().endswith(".osw"):
        base = base[:-4]
    return base or "openstudio-run"


# --- CLI entrypoint ----------------------------------------------------------


async def main() -> int:
    """CLI entrypoint.

    This script is a *developer convenience*:
    - It demonstrates how an MCP client connects over stdio.
    - It validates an OSW, starts a run, polls status, and prints a log tail.
    - It optionally reads artifacts, like eplustbl.htm, for quick inspection.

    It is not intended to be the long-term user-facing interface. For real
    users, the goal is to expose higher-level MCP tools (and ultimately SDK
    tools) so a UI or agent can orchestrate workflows without needing bespoke
    scripts.
    """
    ap = argparse.ArgumentParser(description="Run an OpenStudio OSW via the openstudio-mcp stdio server.")
    ap.add_argument(
        "--osw",
        default=os.environ.get("MCP_OSW_PATH", ""),
        help=(
            "Path to OSW as seen by the MCP server process. "
            "If the server is a Docker container with your repo mounted to /repo, "
            "use /repo/tests/assets/..."
        ),
    )
    ap.add_argument(
        "--epw",
        default=os.environ.get("MCP_EPW_PATH", ""),
        help="Optional EPW path as seen by the MCP server process.",
    )
    ap.add_argument(
        "--name",
        default=os.environ.get("MCP_RUN_NAME", ""),
        help="Optional run name (defaults to OSW filename).",
    )
    ap.add_argument("--poll", type=float, default=float(os.environ.get("MCP_POLL_SECONDS", "2")))
    ap.add_argument("--tail", type=int, default=int(os.environ.get("MCP_LOG_TAIL", "80")))
    ap.add_argument("--tool-timeout", type=float, default=float(os.environ.get("MCP_TOOL_TIMEOUT", "20")))
    ap.add_argument("--hard-timeout", type=float, default=float(os.environ.get("MCP_HARD_TIMEOUT", str(60 * 30))))
    ap.add_argument(
        "--read-eplustbl",
        action="store_true",
        help="After completion, attempt to read run/eplustbl.htm via read_run_artifact (if present).",
    )
    args = ap.parse_args()

    # ---- MCP server process config ----
    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    osw_path = args.osw
    epw_path = args.epw.strip() or None
    run_name = args.name.strip() or _guess_name_from_osw(osw_path)

    server_params = StdioServerParameters(
        command=server_cmd,
        args=server_args,
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        server_status = await _call_tool(session, "get_server_status", {}, timeout=args.tool_timeout)
        print(f"Server status: {server_status}")

        val = await _call_tool(session, "validate_osw", {"osw_path": osw_path}, timeout=args.tool_timeout)
        print(f"Validate: {val}")
        if isinstance(val, dict) and not val.get("ok", True):
            print("ERROR: validate_osw returned ok=false", file=sys.stderr)
            return 2

        run_args: dict[str, Any] = {"osw_path": osw_path, "name": run_name}
        if epw_path:
            run_args["epw_path"] = epw_path

        run_res = await _call_tool(session, "run_osw", run_args, timeout=args.tool_timeout)
        if isinstance(run_res, dict) and run_res.get("ok") is False:
            err = run_res.get("error") or run_res
            print("ERROR: run_osw returned ok=false", file=sys.stderr)
            print(err, file=sys.stderr)
            return 2

        run_id = _pick_run_id(run_res)
        if not run_id:
            print("ERROR: Could not determine run_id from run_osw response:", file=sys.stderr)
            print(run_res, file=sys.stderr)
            return 2

        print(f"\nStarted run_id={run_id}")
        print("Polling status + printing logs...\n")

        started = time.time()
        terminal_states = {"success", "failed", "canceled", "cancelled"}
        last_fingerprint: dict[str, int] = {}

        while True:
            if time.time() - started > args.hard_timeout:
                print(f"\nERROR: timed out after {args.hard_timeout}s", file=sys.stderr)
                return 3

            status = await _call_tool(session, "get_run_status", {"run_id": run_id}, timeout=args.tool_timeout)
            state = _extract_status(status).lower()
            print(f"[status] {status}")

            for stream in ("openstudio", "energyplus"):
                logs = await _call_tool(
                    session,
                    "get_run_logs",
                    {"run_id": run_id, "stream": stream, "tail": args.tail},
                    timeout=args.tool_timeout,
                )
                txt = _extract_logs_text(logs).rstrip()
                fp = hash(txt)
                if txt and last_fingerprint.get(stream) != fp:
                    print(f"\n----- log tail ({stream}) -----")
                    print(txt)
                    print(f"----- end log tail ({stream}) -----\n")
                    last_fingerprint[stream] = fp

            if state in terminal_states:
                print(f"\nRun finished with state={state}\n")
                break

            await asyncio.sleep(args.poll)

        artifacts = await _call_tool(session, "get_run_artifacts", {"run_id": run_id}, timeout=args.tool_timeout)
        print("Artifacts:")
        print(json.dumps(artifacts, indent=2, sort_keys=True, default=str))

        metrics = await _call_tool(
            session,
            "extract_summary_metrics",
            {"run_id": run_id},
            timeout=args.tool_timeout,
        )
        print("\nSummary metrics:")
        print(json.dumps(metrics, indent=2, sort_keys=True, default=str))

        if args.read_eplustbl:
            candidate = "run/eplustbl.htm"
            try:
                tbl = await _call_tool(
                    session,
                    "read_run_artifact",
                    {"run_id": run_id, "path": candidate, "max_bytes": 200_000},
                    timeout=args.tool_timeout,
                )
                print(f"\nRead {candidate} (truncated):")
                if isinstance(tbl, dict):
                    print(json.dumps(tbl, indent=2, sort_keys=True, default=str))
                else:
                    print(str(tbl)[:2000])
            except Exception as e:
                print(f"\nNOTE: read_run_artifact failed for {candidate}: {e}", file=sys.stderr)

        return 0 if state == "success" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
