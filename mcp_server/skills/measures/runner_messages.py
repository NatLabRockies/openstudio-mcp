"""Parse and bound runner messages from an OSW run's out.osw.

Pure stdlib (no openstudio import) so the message caps are unit-testable
without the SDK installed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_server.util import read_file_bounded

# Caps keep runner_messages small enough that a tool response can never
# approach JSON-RPC framing limits: generic_qaqc on a 27-zone model emitted
# 18.9MB of step_warnings (one message alone 9.45MB), which killed the stdio
# session mid-call (#98). Errors/warnings carry the debugging signal; info is
# mostly progress noise.
MAX_MESSAGE_CHARS = 500
MESSAGE_LIMITS = {"info": 10, "warnings": 20, "errors": 20}

# out.osw is written by the confined-but-untrusted measure subprocess; the
# unconfined server reads it back with read_file_bounded (O_NOFOLLOW — a
# symlink swap must not redirect the read; PR #105). Cap well above the
# largest real out.osw seen (#98 bson-repro fixture: 20.7MB) — the message
# caps below do the response-size work, this only bounds server memory.
OSW_MAX_BYTES = 50_000_000


def _clip(msg: Any) -> str:
    text = str(msg)
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[:MAX_MESSAGE_CHARS] + f"... [truncated, {len(text)} chars total]"


def _step_messages(step: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Extract one OSW step's runner messages, bounded by the caps.

    Returns (msgs, truncated) — msgs has no "truncated"/"note" fields yet;
    callers add those once, scoped to whatever they're reporting (a single
    step vs. a whole multi-step run).
    """
    result = step.get("result", {}) or {}
    msgs: dict[str, Any] = {
        "result": result.get("step_result", ""),
    }
    truncated = False
    for key in ("step_initial_condition", "step_final_condition"):
        val = result.get(key)
        if val:
            clipped = _clip(val)
            truncated = truncated or clipped != str(val)
            # Strip "step_" prefix for cleaner output
            msgs[key.replace("step_", "")] = clipped
    for key, osw_key, count_key in (
        ("info", "step_info", "info_count"),
        ("warnings", "step_warnings", "warning_count"),
        ("errors", "step_errors", "error_count"),
    ):
        items = result.get(osw_key, [])
        if not items:
            continue
        limit = MESSAGE_LIMITS[key]
        kept = [_clip(m) for m in items[:limit]]
        if len(items) > limit or any(len(str(m)) > MAX_MESSAGE_CHARS for m in items[:limit]):
            truncated = True
        msgs[key] = kept
        msgs[count_key] = len(items)
    return msgs, truncated


def parse_runner_messages(out_osw_path: Path) -> dict[str, Any] | None:
    """Extract runner messages from out.osw step results, bounded by the caps.

    Returns dict with result, initial_condition, final_condition, clipped
    info/warnings/errors lists plus *_count totals (and truncated + a note
    pointing at out.osw when anything was cut) — or None on parse failure.

    Only looks at the FIRST step — correct for apply_measure's single-measure
    OSW. For a multi-step workflow, use parse_all_step_messages instead.
    """
    try:
        if not out_osw_path.is_file():
            return None
        osw = json.loads(read_file_bounded(out_osw_path, OSW_MAX_BYTES).decode("utf-8", errors="replace"))
        steps = osw.get("steps", [])
        if not steps:
            return None
        msgs, truncated = _step_messages(steps[0])
        if truncated:
            msgs["truncated"] = True
            msgs["note"] = f"Messages clipped to keep the response small; full log in {out_osw_path}"
        return msgs
    except Exception:
        return None


def parse_all_step_messages(out_osw_path: Path) -> dict[str, Any] | None:
    """Per-step runner messages across every step of a multi-step OSW run.

    A multi-step workflow (e.g. gbxml_import's ChangeBuildingLocation ->
    gbxml_import -> gbxml_import_advanced -> gbxml_import_hvac ->
    set_simulation_control -> gbxml_postprocess chain) can raise errors or
    warnings from ANY step, not just the first — so every step needs its own
    attribution. Applies the same per-step MAX_MESSAGE_CHARS/MESSAGE_LIMITS
    caps as parse_runner_messages, so a 6-step run's response stays as small
    as a single-step one (see #98 in the module docstring above).
    """
    try:
        if not out_osw_path.is_file():
            return None
        osw = json.loads(read_file_bounded(out_osw_path, OSW_MAX_BYTES).decode("utf-8", errors="replace"))
        steps = osw.get("steps", [])
        if not steps:
            return None
        step_results = []
        total_errors = 0
        total_warnings = 0
        truncated = False
        for step in steps:
            msgs, step_truncated = _step_messages(step)
            msgs["measure"] = step.get("measure_dir_name", "")
            step_results.append(msgs)
            total_errors += msgs.get("error_count", 0)
            total_warnings += msgs.get("warning_count", 0)
            truncated = truncated or step_truncated
        out: dict[str, Any] = {
            "steps": step_results,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
        }
        if truncated:
            out["truncated"] = True
            out["note"] = f"Messages clipped to keep the response small; full log in {out_osw_path}"
        return out
    except Exception:
        return None
