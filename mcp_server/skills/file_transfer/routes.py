"""Signed, out-of-band HTTP routes that carry file bytes beside the MCP protocol.

These are NOT behind FastMCP's `auth=` verifier (custom routes never are), so
authorization is the HMAC signature in the `?t=` token, minted by the
authenticated request_upload / request_download tools. The token binds the op,
the user key, and (for upload) the file_id; the route trusts nothing else.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from pathlib import Path

from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from mcp_server.audit import audit
from mcp_server.config import OSMCP_MAX_UPLOAD_MB
from mcp_server.skills.file_transfer import operations, signing

_MB = 1024 * 1024


async def upload_route(request: Request) -> JSONResponse:
    token = request.query_params.get("t", "")
    try:
        payload = signing.verify_token(token, op="u")
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=403)
    key, file_id = payload["u"], payload["f"]
    if request.path_params.get("file_id") != file_id:
        return JSONResponse({"ok": False, "error": "file_id mismatch"}, status_code=403)
    try:
        entry = operations._entry_dir(key, file_id)
    except ValueError:
        return JSONResponse({"ok": False, "error": "bad file_id"}, status_code=403)
    if not (entry / "meta.json").exists():
        return JSONResponse({"ok": False, "error": "unknown or expired upload"}, status_code=404)

    max_bytes = OSMCP_MAX_UPLOAD_MB * _MB
    tmp = entry / ".incoming"
    h = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > max_bytes:
                    f.close()
                    tmp.unlink(missing_ok=True)
                    return JSONResponse(
                        {"ok": False, "error": f"exceeds max upload size ({OSMCP_MAX_UPLOAD_MB} MB)"},
                        status_code=413)
                h.update(chunk)
                f.write(chunk)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return JSONResponse({"ok": False, "error": f"write failed: {e}"}, status_code=500)

    result = operations.finalize_upload(key, file_id, tmp, h.hexdigest(), size)
    status = 200 if result.get("ok") else result.pop("status", 422)
    audit("file_upload", user=key, file_id=file_id, size=size,
          sha256=h.hexdigest(), ok=result.get("ok"), error=result.get("error"))
    return JSONResponse(result, status_code=status)


async def download_route(request: Request):
    token = request.query_params.get("t", "")
    res = operations.verify_download(token)
    if not res["ok"]:
        return JSONResponse({"ok": False, "error": res["error"]}, status_code=res["status"])
    path: Path = res["path"]
    if res["bundle"]:
        audit("file_download", file=str(path), bundle=True)
        return _zip_bundle(path)
    audit("file_download", file=str(path), bundle=False)
    return FileResponse(path, filename=path.name)


def _zip_bundle(run_dir: Path) -> FileResponse:
    """Zip a run's reports (or the whole run dir if no reports/) to a temp file."""
    src = run_dir / "reports" if (run_dir / "reports").is_dir() else run_dir
    fd, tmp_name = tempfile.mkstemp(prefix="bundle_", suffix=".zip")
    os.close(fd)
    tmp_path = Path(tmp_name)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in src.rglob("*"):
            if p.is_file() and not p.is_symlink():
                zf.write(p, p.relative_to(src))
    return FileResponse(tmp_path, filename=f"{run_dir.name}.zip",
                        background=BackgroundTask(tmp_path.unlink, missing_ok=True))
