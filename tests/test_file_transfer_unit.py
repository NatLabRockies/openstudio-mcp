"""Unit tests for the file-transfer channel: signing, filename safety, archive
guards, upload finalization, and route behavior (via fake ASGI requests).
No server, no openstudio — pure logic.
"""
import asyncio
import base64
import hashlib
import io
import json
import logging
import zipfile
from pathlib import Path

import pytest

from mcp_server.skills.file_transfer import operations, routes, signing
from mcp_server.skills.file_transfer.archive import guarded_extract

pytestmark = pytest.mark.unit

_MB = 1 << 20


def _http_request(method: str, query: str, path_params: dict, messages=None):
    """Build a real starlette Request driven by a canned ASGI message list."""
    from starlette.requests import Request

    msgs = iter(messages or [])

    async def receive():
        return next(msgs)

    scope = {
        "type": "http", "method": method, "scheme": "http", "http_version": "1.1",
        "server": ("test", 80), "client": ("127.0.0.1", 1), "root_path": "",
        "path": "/files/x", "raw_path": b"/files/x",
        "query_string": query.encode(), "headers": [], "path_params": path_params,
    }
    return Request(scope, receive)


def test_signed_token_roundtrip():
    # Validates: a token minted for (user, file, op) verifies and carries identity
    tok = signing.make_token("alice", "abc123", "u", 60)
    payload = signing.verify_token(tok, op="u")
    assert payload["u"] == "alice"
    assert payload["f"] == "abc123"
    assert payload["op"] == "u"


def test_tampered_signature_rejected():
    # Regression: route authorization IS the HMAC — a flipped sig must not verify
    tok = signing.make_token("alice", "abc", "u", 60)
    body, _sig = tok.split(".", 1)
    forged = f"{body}.{'A' * 43}"
    with pytest.raises(ValueError, match="signature"):
        signing.verify_token(forged)


def test_tampered_payload_rejected():
    # Regression: swapping the user in the body must invalidate the signature,
    # so a leaked token can't be edited to impersonate another tenant.
    tok = signing.make_token("alice", "abc", "u", 60)
    _body, sig = tok.split(".", 1)
    evil_body = base64.urlsafe_b64encode(
        json.dumps({"u": "bob", "f": "abc", "op": "u", "exp": 9_999_999_999},
                   separators=(",", ":"), sort_keys=True).encode(),
    ).decode().rstrip("=")
    with pytest.raises(ValueError, match="signature"):
        signing.verify_token(f"{evil_body}.{sig}")


def test_expired_token_rejected():
    # Validates: short-TTL URLs must stop working once expired
    tok = signing.make_token("alice", "abc", "u", -1)
    with pytest.raises(ValueError, match="expired"):
        signing.verify_token(tok)


def test_wrong_op_token_rejected():
    # Regression: an upload URL must not be replayable against the download route
    tok = signing.make_token("alice", "abc", "u", 60)
    with pytest.raises(ValueError, match="op"):
        signing.verify_token(tok, op="d")


@pytest.mark.parametrize(("raw", "expected"), [
    ("../../etc/passwd", "passwd"),
    ("/abs/model.osm", "model.osm"),
    ("..\\..\\win.osm", "win.osm"),
    ("", "upload.bin"),
    ("a b;c.osm", "a_b_c.osm"),
])
def test_sanitize_filename(raw, expected):
    # Regression: client filename must never become a path component
    out = operations._sanitize_filename(raw)
    assert out == expected
    assert "/" not in out and "\\" not in out and ".." not in out


@pytest.mark.parametrize(("base", "host", "scheme", "expected"), [
    # operator override always wins (e.g. pinned behind a TLS reverse proxy)
    ("https://api.example.com", "10.0.0.5:8000", "http", "https://api.example.com"),
    # direct LAN/VPN: trust the Host the caller reached us on
    ("", "192.168.4.29:8000", "http", "http://192.168.4.29:8000"),
    ("", "localhost:8000", "http", "http://localhost:8000"),
    # scheme from the request is honored when no override
    ("", "api.example.com", "https", "https://api.example.com"),
    # off-request / no Host header -> relative (caller stitches its own host)
    ("", None, "http", None),
])
def test_resolve_base_url(base, host, scheme, expected):
    # Regression: request_upload/download returned a RELATIVE url; the model never
    # sees the client's .mcp.json host, so the agent couldn't PUT/GET. Resolve the
    # absolute origin server-side: env override, else request Host, else relative.
    assert operations._resolve_base_url(base, host, scheme) == expected


def test_archive_rejects_path_escape(tmp_path):
    # Regression: a `..` zip entry must not write outside the extract dir
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../escape.txt", "pwned")
    err = guarded_extract(z, tmp_path / "out", max_uncompressed_bytes=_MB, max_entries=100)
    assert err is not None and "escape" in err.lower()
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path.parent / "escape.txt").exists()


def test_archive_rejects_symlink_member(tmp_path):
    # Regression: a symlink entry (e.g. -> /etc/shadow) must be refused
    z = tmp_path / "link.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 & 0xFFFF) << 16  # S_IFLNK | 0777
        zf.writestr(info, "/etc/shadow")
    err = guarded_extract(z, tmp_path / "out", max_uncompressed_bytes=_MB, max_entries=100)
    assert err is not None and "symlink" in err.lower()


def test_archive_rejects_zip_bomb(tmp_path):
    # Validates: streamed uncompressed-size cap catches a high-ratio bomb
    z = tmp_path / "bomb.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.bin", b"\0" * (3 * _MB))
    err = guarded_extract(z, tmp_path / "out", max_uncompressed_bytes=_MB, max_entries=100)
    assert err is not None and "bomb" in err.lower()


def test_archive_rejects_too_many_entries(tmp_path):
    # Validates: entry-count cap bounds inode/CPU blowups
    z = tmp_path / "many.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for i in range(20):
            zf.writestr(f"f{i}.txt", "x")
    err = guarded_extract(z, tmp_path / "out", max_uncompressed_bytes=_MB, max_entries=5)
    assert err is not None and "too many" in err.lower()


def test_archive_extracts_clean_tree(tmp_path):
    # Validates: a well-formed archive extracts with files intact, no error
    z = tmp_path / "ok.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("m/measure.rb", "class M; end\n")
        zf.writestr("m/measure.xml", "<measure/>")
    out = tmp_path / "out"
    err = guarded_extract(z, out, max_uncompressed_bytes=_MB, max_entries=100)
    assert err is None
    assert (out / "m" / "measure.rb").read_text().startswith("class M")


def test_finalize_rejects_size_mismatch():
    # Regression: declared size must match streamed bytes (truncated/padded upload)
    req = operations.request_upload_op(filename="m.osm", size_bytes=10)
    assert req["ok"] is True
    fid = req["file_id"]
    entry = operations._entry_dir("local", fid)
    tmp = entry / ".incoming"
    tmp.write_bytes(b"short")  # 5 bytes, declared 10
    res = operations.finalize_upload("local", fid, tmp,
                                     hashlib.sha256(b"short").hexdigest(), 5)
    assert res["ok"] is False
    assert res["status"] == 422
    assert "size mismatch" in res["error"]
    operations.delete_upload_op(fid)


def test_finalize_rejects_sha_mismatch():
    # Regression: a corrupted upload (right size, wrong bytes) must be rejected
    data = b"0123456789"
    req = operations.request_upload_op(filename="m.osm", size_bytes=len(data),
                                       sha256="deadbeef")
    fid = req["file_id"]
    entry = operations._entry_dir("local", fid)
    tmp = entry / ".incoming"
    tmp.write_bytes(data)
    res = operations.finalize_upload("local", fid, tmp,
                                     hashlib.sha256(data).hexdigest(), len(data))
    assert res["ok"] is False
    assert res["status"] == 422
    assert "sha256 mismatch" in res["error"]
    operations.delete_upload_op(fid)


def test_reserved_filename_meta_json_preserved():
    # Regression: uploading a file literally named meta.json had its bytes silently
    # replaced by the entry's own metadata (finalize wrote both to the same path)
    data = b"the users actual file bytes"
    req = operations.request_upload_op(filename="meta.json", size_bytes=len(data))
    assert req["ok"] is True, req
    fid = req["file_id"]
    tmp = operations._entry_dir("local", fid) / ".incoming"
    tmp.write_bytes(data)
    res = operations.finalize_upload("local", fid, tmp,
                                     hashlib.sha256(data).hexdigest(), len(data))
    assert res["ok"] is True, res
    assert Path(res["server_path"]).read_bytes() == data, \
        "uploaded bytes must survive a filename that collides with internal files"
    info = operations.get_upload_op(fid)
    assert info["ok"] is True and info["ready"] is True, info
    operations.delete_upload_op(fid)


def test_reserved_filename_extracted_archive_finalizes():
    # Regression: a measure upload whose name sanitized to "extracted" collided with
    # the extraction dir — uncaught FileExistsError became an HTTP 500 from the route
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("m/measure.rb", "class M; end\n")
    data = buf.getvalue()
    req = operations.request_upload_op(filename="extracted", size_bytes=len(data),
                                       kind="measure")
    fid = req["file_id"]
    tmp = operations._entry_dir("local", fid) / ".incoming"
    tmp.write_bytes(data)
    res = operations.finalize_upload("local", fid, tmp,
                                     hashlib.sha256(data).hexdigest(), len(data))
    assert res["ok"] is True, res
    assert (Path(res["extracted_path"]) / "measure.rb").is_file(), res
    operations.delete_upload_op(fid)


def test_unknown_kind_rejected():
    # Validates: kind is validated against the documented enum, not silently stored
    req = operations.request_upload_op(filename="x.osm", size_bytes=10, kind="bogus")
    if req.get("ok"):  # red-run hygiene: don't leave an entry behind
        operations.delete_upload_op(req["file_id"])
    assert req["ok"] is False, req
    assert "kind" in req["error"].lower()


def test_disconnect_mid_put_cleans_partial():
    # Regression: a client disconnect mid-PUT raised ClientDisconnect through the
    # route and leaked the partial temp file, permanently counting toward quota
    req = operations.request_upload_op(filename="part.bin", size_bytes=8)
    fid = req["file_id"]
    token = signing.make_token("local", fid, "u", 60)
    request = _http_request("PUT", f"t={token}", {"file_id": fid}, [
        {"type": "http.request", "body": b"abcd", "more_body": True},
        {"type": "http.disconnect"},
    ])
    res = asyncio.run(routes.upload_route(request))  # must not raise
    assert res.status_code == 400, res.status_code
    entry = operations._entry_dir("local", fid)
    stray = [p.name for p in entry.iterdir() if p.name.startswith(".incoming")]
    assert stray == [], f"partial upload left behind: {stray}"
    assert operations.get_upload_op(fid)["ready"] is False
    operations.delete_upload_op(fid)


def test_concurrent_puts_same_token_keep_winner_intact():
    # Regression: two concurrent PUTs on one token shared the same temp file — the
    # losing request's interleaved writes corrupted the winner's finalized upload
    from starlette.requests import Request

    data_a, data_b = b"A" * 8, b"B" * 8
    req = operations.request_upload_op(filename="race.bin", size_bytes=8)
    fid = req["file_id"]
    token = signing.make_token("local", fid, "u", 60)

    async def _run():
        a_blocked, b_done = asyncio.Event(), asyncio.Event()
        calls = {"n": 0}

        async def receive_a():
            calls["n"] += 1
            if calls["n"] == 1:
                return {"type": "http.request", "body": data_a[:4], "more_body": True}
            a_blocked.set()
            await b_done.wait()
            return {"type": "http.request", "body": data_a[4:], "more_body": False}

        scope = {
            "type": "http", "method": "PUT", "scheme": "http", "http_version": "1.1",
            "server": ("test", 80), "client": ("127.0.0.1", 1), "root_path": "",
            "path": "/files/x", "raw_path": b"/files/x",
            "query_string": f"t={token}".encode(), "headers": [],
            "path_params": {"file_id": fid},
        }
        req_a = Request(scope, receive_a)
        req_b = _http_request("PUT", f"t={token}", {"file_id": fid}, [
            {"type": "http.request", "body": data_b, "more_body": False}])

        task_a = asyncio.create_task(routes.upload_route(req_a))
        await a_blocked.wait()                      # A mid-stream, holding its temp
        res_b = await routes.upload_route(req_b)    # B streams fully and finalizes
        b_done.set()
        res_a = await task_a                        # A resumes after B won
        return res_a, res_b

    res_a, res_b = asyncio.run(_run())
    assert res_b.status_code == 200, res_b.status_code
    assert res_a.status_code == 409, res_a.status_code
    info = operations.get_upload_op(fid)
    assert info["ready"] is True, info
    assert Path(info["server_path"]).read_bytes() == data_b, \
        "winner's finalized bytes were corrupted by the losing PUT"
    entry = operations._entry_dir("local", fid)
    stray = [p.name for p in entry.iterdir() if p.name.startswith(".incoming")]
    assert stray == [], f"losing PUT left a temp file: {stray}"
    operations.delete_upload_op(fid)


def test_download_audit_attributes_user():
    # Regression: file_download audit lines carried no user attribution — the
    # exfiltration direction was the one place audit couldn't say who
    probe = operations._uploads_dir("local") / "audit_probe.txt"
    probe.write_text("x")
    token = signing.make_token("local", "-", "d", 60, p=str(probe))
    records = []

    class _Capture(logging.Handler):
        def emit(self, rec):
            records.append(json.loads(rec.getMessage()))

    logger = logging.getLogger("openstudio-mcp.audit")
    cap = _Capture()
    logger.addHandler(cap)
    try:
        res = asyncio.run(routes.download_route(
            _http_request("GET", f"t={token}", {"name": "audit_probe.txt"})))
        assert res.status_code == 200, res.status_code
    finally:
        logger.removeHandler(cap)
        probe.unlink(missing_ok=True)
    dl = [r for r in records if r.get("event") == "file_download"]
    assert len(dl) == 1, records
    assert dl[0].get("user") == "local", f"download audit must say who: {dl[0]}"


def test_chmod_failure_does_not_crash_route():
    # Regression: tmp.chmod() ran outside the stream try/except — an OSError on an
    # exotic mount crashed the route and leaked the temp instead of finalizing
    data = b"chmod-resilient"
    req = operations.request_upload_op(filename="c.bin", size_bytes=len(data))
    fid = req["file_id"]
    token = signing.make_token("local", fid, "u", 60)
    request = _http_request("PUT", f"t={token}", {"file_id": fid}, [
        {"type": "http.request", "body": data, "more_body": False}])

    real_chmod = Path.chmod

    def _boom(self, *a, **k):
        # only sabotage the .incoming temp's chmod, not unrelated chmods
        if self.name.startswith(".incoming"):
            raise OSError("chmod not supported on this mount")
        return real_chmod(self, *a, **k)

    orig = Path.chmod
    Path.chmod = _boom
    try:
        res = asyncio.run(routes.upload_route(request))  # must not raise
    finally:
        Path.chmod = orig
    assert res.status_code == 200, res.status_code
    info = operations.get_upload_op(fid)
    assert info["ready"] is True, info
    entry = operations._entry_dir("local", fid)
    stray = [p.name for p in entry.iterdir() if p.name.startswith(".incoming")]
    assert stray == [], f"chmod failure leaked a temp: {stray}"
    operations.delete_upload_op(fid)


def test_finalize_concurrent_claim_rejects_second():
    # Regression: two concurrent PUTs both passed the status!="ready" check before
    # either wrote ready, both finalized -> double 200, nondeterministic bytes. An
    # exclusive finalize claim must reject the loser even while status is "pending".
    data = b"0123456789"
    req = operations.request_upload_op(filename="r.bin", size_bytes=len(data))
    fid = req["file_id"]
    entry = operations._entry_dir("local", fid)
    # Simulate PUT-A having claimed but not yet flipped status to ready:
    (entry / ".finalized").write_bytes(b"")
    tmp = entry / ".incoming"
    tmp.write_bytes(data)
    res = operations.finalize_upload("local", fid, tmp,
                                     hashlib.sha256(data).hexdigest(), len(data))
    assert res["ok"] is False and res["status"] == 409, res
    assert not tmp.exists(), "loser's temp must be cleaned up"
    operations.delete_upload_op(fid)


def test_finalize_enforces_quota_post_extraction(monkeypatch, tmp_path):
    # Regression: quota was only checked at mint (compressed size); a small archive
    # expanding past OSMCP_USER_QUOTA_MB on extraction, or raced concurrent mints,
    # could exceed the on-disk cap. finalize must re-check and roll back.
    monkeypatch.setattr(operations, "OSMCP_USER_QUOTA_MB", 1)  # 1 MB cap
    monkeypatch.setattr(operations, "_uploads_dir", lambda _key: tmp_path)  # isolate
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("m/big.bin", b"\0" * (3 * _MB))  # expands to 3 MB > 1 MB cap
    data = buf.getvalue()
    req = operations.request_upload_op(filename="x.zip", size_bytes=len(data), kind="measure")
    assert req["ok"] is True, req  # tiny compressed size passes the mint check
    fid = req["file_id"]
    tmp = operations._entry_dir("local", fid) / ".incoming"
    tmp.write_bytes(data)
    res = operations.finalize_upload("local", fid, tmp,
                                     hashlib.sha256(data).hexdigest(), len(data))
    assert res["ok"] is False and res["status"] == 413, res
    assert "quota" in res["error"].lower()
    assert not operations._entry_dir("local", fid).exists(), \
        "over-quota upload must roll back the whole entry"
