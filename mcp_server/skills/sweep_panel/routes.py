"""Signed browser routes for the sweep panel, HTTP deployments only.

Not behind FastMCP's auth verifier (custom routes never are): the HMAC token in
?t=, minted by the authenticated open_measure_panel tool, is the only authority.
"""
from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from mcp_server.skills.file_transfer import signing
from mcp_server.skills.sweep_panel import operations

_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _payload(request: Request) -> dict | None:
    try:
        return signing.verify_token(request.query_params.get("t", ""), op=operations.OP)
    except ValueError:
        return None


def _link_schema(payload: dict | None) -> dict | None:
    try:
        return operations.link_schema(payload["u"], payload["f"]) if payload else None
    except ValueError:  # bad link id
        return None


async def page_route(request: Request):
    if _link_schema(_payload(request)) is None:
        return HTMLResponse("link expired or invalid", status_code=403)
    return HTMLResponse(operations.PANEL_HTML.read_text(), headers=_HEADERS)


async def schema_route(request: Request):
    schema = _link_schema(_payload(request))
    if schema is None:
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    return JSONResponse({"schema": schema}, headers=_HEADERS)


async def submit_route(request: Request):
    payload = _payload(request)
    if not payload:
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    try:
        body = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"ok": False, "errors": ["invalid JSON"]}, status_code=400)
    values = body.get("values") if isinstance(body, dict) else None
    try:
        status, out = operations.record_submit(payload["u"], payload["f"], values)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=403)
    return JSONResponse(out, status_code=status, headers=_HEADERS)
