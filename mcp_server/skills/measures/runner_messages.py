"""Parse and bound runner messages from an OSW run's out.osw.

Pure stdlib (no openstudio import) so the message caps are unit-testable
without the SDK installed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Caps keep runner_messages small enough that a tool response can never
# approach JSON-RPC framing limits: generic_qaqc on a 27-zone model emitted
# 18.9MB of step_warnings (one message alone 9.45MB), which killed the stdio
# session mid-call (#98). Errors/warnings carry the debugging signal; info is
# mostly progress noise.
MAX_MESSAGE_CHARS = 500
MESSAGE_LIMITS = {"info": 10, "warnings": 20, "errors": 20}


def _clip(msg: Any) -> str:
    text = str(msg)
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[:MAX_MESSAGE_CHARS] + f"... [truncated, {len(text)} chars total]"


def parse_runner_messages(out_osw_path: Path) -> dict[str, Any] | None:
    """Extract runner messages from out.osw step results, bounded by the caps.

    Returns dict with result, initial_condition, final_condition, clipped
    info/warnings/errors lists plus *_count totals (and truncated + a note
    pointing at out.osw when anything was cut) — or None on parse failure.
    """
    try:
        if not out_osw_path.is_file():
            return None
        osw = json.loads(out_osw_path.read_text(encoding="utf-8", errors="replace"))
        steps = osw.get("steps", [])
        if not steps:
            return None
        step = steps[0]
        result = step.get("result", {})
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
        if truncated:
            msgs["truncated"] = True
            msgs["note"] = f"Messages clipped to keep the response small; full log in {out_osw_path}"
        return msgs
    except Exception:
        return None
