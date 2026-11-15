"""Sweep panel: a form for a measure's sweepable arguments, checked by the server.

One HTML panel (panel.html) reaches the user two ways:
- MCP Apps hosts (Claude Desktop, VS Code, ...) render it inline from ui://sweep/panel.html,
  over any transport, stdio included. The panel calls submit_measure_sweep through the host.
- Over HTTP only, the tool also returns a signed, single-submit browser link to the same
  panel, for clients that can't render MCP Apps (terminal clients). Same trust model as
  file_transfer: the token binds (user key, link id, op "p", expiry); results are stored
  under that user's run root, so get_panel_result only reads the caller's own links.

The panel's own min/max are a convenience. validate_values() is the trust boundary.
"""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any

from mcp_server.config import OSMCP_DOWNLOAD_URL_TTL, run_root_for
from mcp_server.skills.analysis.operations import _read_measure_metadata
from mcp_server.skills.sweep_panel.measure_bounds import measure_limits

OP = "p"
SUBMIT_TOOL = "submit_measure_sweep"
MAX_STEPS = 20
_LINK_RE = re.compile(r"^[0-9a-f]{12}$")
PANEL_HTML = Path(__file__).parent / "panel.html"


def panel_schema(measure_dir: str) -> dict[str, Any]:
    """Numeric arguments with a known range become panel fields; nothing else is sweepable."""
    meta = _read_measure_metadata(measure_dir)
    limits = measure_limits(meta["measure_path"])
    schema = {}
    for arg in meta["arguments"]:
        spec = limits.get(arg["name"])
        if spec is None or arg["value_type"] not in ("double", "integer"):
            continue
        schema[arg["name"]] = {
            "type": "number", "units": spec["units"], "min": spec["min"], "max": spec["max"],
            "default": arg["default_value"], "label": spec.get("label", arg["display_name"]),
        }
    return {"measure_name": meta["name"], "measure_dir": str(meta["measure_path"]), "schema": schema}


def validate_values(schema: dict[str, Any], values: Any) -> dict[str, Any]:
    """Each value is a number or [low, high, steps]. Returns ok, or every error found."""
    if not isinstance(values, dict) or not values:
        return {"ok": False, "errors": ["values must be a non-empty object"]}
    errors, n_points = [], 1
    for name, v in values.items():
        spec = schema.get(name)
        if spec is None:
            errors.append(f"{name}: not a sweepable argument (choose from {sorted(schema)})")
            continue
        is_range = isinstance(v, list)
        if is_range and len(v) != 3:
            errors.append(f"{name}: a range is [low, high, steps]")
            continue
        units = f" {spec['units']}" if spec["units"] else ""
        mine = []
        for x in v[:2] if is_range else [v]:
            if isinstance(x, bool) or not isinstance(x, (int, float)):
                mine.append(f"{name}: {x!r} is not a number")
            elif not spec["min"] <= x <= spec["max"]:
                mine.append(f"{name}: {x}{units} outside [{spec['min']}, {spec['max']}]")
        if is_range:
            steps = v[2]
            if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= MAX_STEPS:
                mine.append(f"{name}: steps {steps!r} must be a whole number from 1 to {MAX_STEPS}")
            elif not mine and v[0] > v[1]:
                mine.append(f"{name}: low {v[0]} is above high {v[1]}")
            else:
                n_points *= steps
        errors += mine
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "n_points": n_points}


def next_osa_call(measure_dir: str, values: dict[str, Any]) -> dict[str, Any]:
    """The openstudio_analysis_add_measure_to_osa_json arguments for validated values."""
    arguments, variables = {}, []
    for name, v in values.items():
        if isinstance(v, list):
            lo, hi = v[0], v[1]
            variables.append({"argument_name": name, "distribution": {
                "type": "uniform", "minimum": lo, "maximum": hi, "mode": (lo + hi) / 2}})
        else:
            arguments[name] = v
    call: dict[str, Any] = {"tool": "openstudio_analysis_add_measure_to_osa_json", "measure_dir": measure_dir}
    if arguments:
        call["arguments"] = arguments
    if variables:
        call["variables"] = variables
    return call


def _checked(info: dict[str, Any], values: Any) -> dict[str, Any]:
    out = validate_values(info["schema"], values)
    out["values"] = values
    out["measure_name"] = info["measure_name"]
    if out["ok"]:
        out["next"] = next_osa_call(info["measure_dir"], values)
    return out


def submit_measure_sweep_op(measure_dir: str, values: Any) -> dict[str, Any]:
    """Validate values against the measure's limits. The result echoes what was submitted,
    so a host that forwards it to the model tells the model what the user chose."""
    try:
        info = panel_schema(measure_dir)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return _checked(info, values)


def _results_path(key: str, link_id: str) -> Path:
    if not _LINK_RE.match(link_id or ""):
        raise ValueError("bad link id")
    d = run_root_for(key) / "panels"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{link_id}.json"


def _mint_link(info: dict[str, Any]) -> dict[str, Any]:
    """Store the schema with the link: the browser routes carry no identity, so they must not
    re-read measure.xml through the caller's path checks."""
    from mcp_server.identity import user_key
    from mcp_server.skills.file_transfer import signing
    from mcp_server.skills.file_transfer.operations import _public_url

    key, link_id = user_key(), secrets.token_hex(6)
    _results_path(key, link_id).write_text(json.dumps({"info": info, "results": []}))
    token = signing.make_token(key, link_id, OP, OSMCP_DOWNLOAD_URL_TTL)
    return {"link_id": link_id, "panel_url": _public_url(f"/panel?t={token}"),
            "expires_in": OSMCP_DOWNLOAD_URL_TTL}


def open_measure_panel_op(measure_dir: str) -> dict[str, Any]:
    try:
        info = panel_schema(measure_dir)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not info["schema"]:
        return {"ok": False, "error": (
            f"Measure '{info['measure_name']}' has no sweepable arguments: no numeric argument has a valid "
            "range in its measure.xml or in openstudio-mcp's bounds files.")}
    out = {"ok": True, **info, "submit_tool": SUBMIT_TOOL, "submit_args": {"measure_dir": info["measure_dir"]}}
    from mcp_server.identity import _is_http_transport

    if _is_http_transport():
        out["fallback"] = _mint_link(info)
        out["note"] = ("If the panel didn't appear in the chat, give the user fallback.panel_url (single use, "
                       "short-lived), then call get_panel_result(link_id) after they submit.")
    return out


def record_submit(key: str, link_id: str, values: Any) -> tuple[int, dict[str, Any]]:
    """Handle a browser submit: (HTTP status, body). The first valid submit closes the link."""
    p = _results_path(key, link_id)
    if not p.exists():
        return 403, {"ok": False, "errors": ["unknown link"]}
    record = json.loads(p.read_text())
    if any(r["ok"] for r in record["results"]):
        return 409, {"ok": False, "errors": ["this link was already used; ask for a new panel"]}
    out = _checked(record["info"], values)
    # shortcut: read-modify-write without a lock; two racing submits could both pass. Add a lock for multi-user use.
    record["results"].append(out)
    p.write_text(json.dumps(record))
    return (200 if out["ok"] else 422), out


def link_schema(key: str, link_id: str) -> dict[str, Any] | None:
    p = _results_path(key, link_id)
    if not p.exists():
        return None
    return json.loads(p.read_text())["info"]["schema"]


def get_panel_result_op(link_id: str) -> dict[str, Any]:
    from mcp_server.identity import user_key

    try:
        p = _results_path(user_key(), link_id)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not p.exists():
        return {"ok": False, "error": "unknown link"}  # also what another user's link looks like
    results = json.loads(p.read_text())["results"]
    return {"ok": True, "submitted": bool(results), "results": results}
