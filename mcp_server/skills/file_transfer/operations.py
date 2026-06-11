"""Business logic for remote file transfer. No MCP awareness; returns plain dicts.

Two call sites:
  * MCP tools (request_upload/get_upload/...) run in request context -> identity
    via user_key().
  * the signed PUT/GET routes run OUTSIDE context -> identity is the user key
    carried in the verified URL token, passed in explicitly.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from pathlib import Path

from mcp_server.config import (
    OSMCP_MAX_ARCHIVE_ENTRIES,
    OSMCP_MAX_ARCHIVE_UNCOMPRESSED_MB,
    OSMCP_MAX_UPLOAD_MB,
    OSMCP_PUBLIC_BASE_URL,
    OSMCP_UPLOAD_URL_TTL,
    OSMCP_USER_QUOTA_MB,
    is_path_allowed_for,
    run_root_for,
)
from mcp_server.skills.file_transfer import signing
from mcp_server.skills.file_transfer.archive import guarded_extract

_MB = 1024 * 1024
_FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _uploads_dir(key: str) -> Path:
    d = run_root_for(key) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _entry_dir(key: str, file_id: str) -> Path:
    if not _FILE_ID_RE.match(file_id):
        raise ValueError("bad file_id")  # server-minted; never a client path
    return _uploads_dir(key) / file_id


def _meta_path(key: str, file_id: str) -> Path:
    return _entry_dir(key, file_id) / "meta.json"


def _sanitize_filename(name: str) -> str:
    base = Path(str(name or "")).name  # strip any directory components
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", base).strip("._")
    return base or "upload.bin"


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file() and not p.is_symlink():
            total += p.stat().st_size
    return total


def _is_archive(filename: str, kind: str) -> bool:
    return kind in ("measure", "archive") or filename.lower().endswith(".zip")


def _public_url(path: str) -> str:
    return f"{OSMCP_PUBLIC_BASE_URL}{path}" if OSMCP_PUBLIC_BASE_URL else path


# --- MCP-context tools --------------------------------------------------------

def request_upload_op(filename: str, size_bytes: int, sha256: str = "", kind: str = "auto") -> dict:
    from mcp_server.identity import user_key

    key = user_key()
    try:
        size = int(size_bytes)
    except (TypeError, ValueError):
        return {"ok": False, "error": "size_bytes must be an integer"}
    if size <= 0:
        return {"ok": False, "error": "size_bytes must be > 0"}
    max_bytes = OSMCP_MAX_UPLOAD_MB * _MB
    if size > max_bytes:
        return {"ok": False, "error": f"file exceeds max upload size ({OSMCP_MAX_UPLOAD_MB} MB)"}
    if OSMCP_USER_QUOTA_MB > 0:
        used = _dir_size(_uploads_dir(key))
        if used + size > OSMCP_USER_QUOTA_MB * _MB:
            return {"ok": False, "error": (
                f"upload would exceed your {OSMCP_USER_QUOTA_MB} MB quota "
                f"(using {used // _MB} MB) — delete old uploads first")}

    file_id = secrets.token_hex(16)
    safe_name = _sanitize_filename(filename)
    entry = _entry_dir(key, file_id)
    entry.mkdir(parents=True, exist_ok=True)
    meta = {
        "file_id": file_id, "filename": safe_name, "kind": kind,
        "expected_size": size, "expected_sha256": (sha256 or "").lower(),
        "status": "pending", "created": int(time.time()),
    }
    _meta_path(key, file_id).write_text(json.dumps(meta), encoding="utf-8")
    token = signing.make_token(key, file_id, "u", OSMCP_UPLOAD_URL_TTL)
    path = f"/files/u/{file_id}?t={token}"
    return {
        "ok": True, "file_id": file_id, "method": "PUT",
        "upload_url": _public_url(path), "upload_path": path,
        "expires_in": OSMCP_UPLOAD_URL_TTL, "max_size_bytes": max_bytes,
        "hint": ("PUT the raw file bytes to upload_url (or upload_path on the same "
                 "host as /mcp), e.g. curl --upload-file <file> '<upload_url>', "
                 "then call get_upload(file_id) for the server path."),
    }


def get_upload_op(file_id: str) -> dict:
    from mcp_server.identity import user_key

    key = user_key()
    try:
        meta = json.loads(_meta_path(key, file_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": f"unknown file_id: {file_id}"}
    return {"ok": True, **_public_meta(key, meta)}


def list_uploads_op() -> dict:
    from mcp_server.identity import user_key

    key = user_key()
    uploads = []
    for meta_file in sorted(_uploads_dir(key).glob("*/meta.json")):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        uploads.append(_public_meta(key, meta))
    return {"ok": True, "count": len(uploads), "uploads": uploads}


def delete_upload_op(file_id: str) -> dict:
    from mcp_server.identity import user_key

    key = user_key()
    try:
        entry = _entry_dir(key, file_id)
    except ValueError:
        return {"ok": False, "error": f"unknown file_id: {file_id}"}
    if not (entry / "meta.json").exists():
        return {"ok": False, "error": f"unknown file_id: {file_id}"}
    shutil.rmtree(entry, ignore_errors=True)
    return {"ok": True, "file_id": file_id, "deleted": True}


def request_download_op(path: str | None = None, run_id: str | None = None,
                        bundle: bool = False) -> dict:
    from mcp_server.identity import user_key

    key = user_key()
    if bundle:
        if not run_id:
            return {"ok": False, "error": "bundle download requires run_id"}
        target = (run_root_for(key) / run_id).resolve()
        if not target.is_dir() or not is_path_allowed_for(key, target):
            return {"ok": False, "error": f"unknown run_id: {run_id}"}
        token = signing.make_token(key, "-", "d", OSMCP_UPLOAD_URL_TTL,
                                   p=str(target), b=1)
        url = f"/files/d/{run_id}.zip?t={token}"
        return {"ok": True, "method": "GET", "download_url": _public_url(url),
                "download_path": url, "expires_in": OSMCP_UPLOAD_URL_TTL, "bundle": True}
    if not path:
        return {"ok": False, "error": "provide a file path, or run_id + bundle=True"}
    target = Path(path).resolve()
    if not target.is_file() or not is_path_allowed_for(key, target):
        return {"ok": False, "error": f"file not accessible: {path}"}
    token = signing.make_token(key, "-", "d", OSMCP_UPLOAD_URL_TTL, p=str(target))
    url = f"/files/d/{target.name}?t={token}"
    return {"ok": True, "method": "GET", "download_url": _public_url(url),
            "download_path": url, "expires_in": OSMCP_UPLOAD_URL_TTL,
            "size_bytes": target.stat().st_size}


# --- signed-route helpers (no MCP context) ------------------------------------

def finalize_upload(key: str, file_id: str, tmp_path: Path, sha_hex: str, size: int) -> dict:
    """Verify a streamed upload against its pending meta, place it, auto-extract.

    Called by the PUT route after streaming bytes to `tmp_path`. Returns a result
    dict; on any failure the partial upload is removed.
    """
    meta_path = _meta_path(key, file_id)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tmp_path.unlink(missing_ok=True)
        return {"ok": False, "status": 404, "error": "unknown or expired upload"}
    if meta.get("status") == "ready":
        tmp_path.unlink(missing_ok=True)
        return {"ok": False, "status": 409, "error": "upload already completed"}
    if size != meta["expected_size"]:
        tmp_path.unlink(missing_ok=True)
        return {"ok": False, "status": 422,
                "error": f"size mismatch: got {size}, expected {meta['expected_size']}"}
    expected_sha = meta.get("expected_sha256") or ""
    if expected_sha and sha_hex != expected_sha:
        tmp_path.unlink(missing_ok=True)
        return {"ok": False, "status": 422, "error": "sha256 mismatch"}

    entry = _entry_dir(key, file_id)
    dest = entry / meta["filename"]
    tmp_path.replace(dest)
    server_path = str(dest)
    extracted_path = None
    if _is_archive(meta["filename"], meta.get("kind", "auto")):
        extract_dir = entry / "extracted"
        err = guarded_extract(
            dest, extract_dir,
            max_uncompressed_bytes=OSMCP_MAX_ARCHIVE_UNCOMPRESSED_MB * _MB,
            max_entries=OSMCP_MAX_ARCHIVE_ENTRIES,
        )
        if err:
            shutil.rmtree(extract_dir, ignore_errors=True)
            return {"ok": False, "status": 422, "error": err}
        extracted_path = _resolve_extracted(extract_dir)

    meta.update({"status": "ready", "sha256": sha_hex, "size": size,
                 "server_path": server_path, "extracted_path": extracted_path})
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return {"ok": True, "file_id": file_id, "sha256": sha_hex, "size": size,
            "server_path": server_path, "extracted_path": extracted_path}


def _resolve_extracted(extract_dir: Path) -> str:
    """Point measures at the actual measure dir even if zipped with a top folder.

    A measure zip is usually `my_measure/measure.rb,...`; if extraction produced a
    single top-level dir, return it so apply_measure(measure_dir=...) just works.
    """
    children = [p for p in extract_dir.iterdir() if p.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        return str(children[0])
    return str(extract_dir)


def verify_download(token: str) -> dict:
    """Validate a download token; return {ok, path, bundle} or {ok:False,...}."""
    try:
        payload = signing.verify_token(token, op="d")
    except ValueError as e:
        return {"ok": False, "status": 403, "error": str(e)}
    key = payload.get("u")
    path = payload.get("p")
    if not key or not path:
        return {"ok": False, "status": 403, "error": "bad token"}
    target = Path(path).resolve()
    if not is_path_allowed_for(key, target):
        return {"ok": False, "status": 403, "error": "not allowed"}
    if not target.exists():
        return {"ok": False, "status": 404, "error": "not found"}
    return {"ok": True, "path": target, "bundle": bool(payload.get("b"))}


def _public_meta(key: str, meta: dict) -> dict:
    return {
        "file_id": meta.get("file_id"), "filename": meta.get("filename"),
        "kind": meta.get("kind"), "status": meta.get("status"),
        "ready": meta.get("status") == "ready",
        "size_bytes": meta.get("size"), "sha256": meta.get("sha256"),
        "server_path": meta.get("server_path"),
        "extracted_path": meta.get("extracted_path"),
    }
