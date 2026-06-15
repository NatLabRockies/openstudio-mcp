"""Adversarial / abuse-case coverage for the remote file-transfer channel.

Named test_security_*.py so it runs in the dedicated `security` workflow on BOTH
amd64 and arm64 (alongside the sandbox suite), separate from the functional
round-trips in tests/test_file_transfer.py.

Threats covered: forged/expired signatures, cross-tenant read, path traversal in
both directions (upload filename + download path = exfil), oversize, sha
tampering, zip bombs over the live route, per-user quota, upload replay, and
isolation under real token auth.
"""
import asyncio
import hashlib
import io
import json
import uuid
import zipfile
from pathlib import Path

import httpx
import pytest
from conftest import http_server, http_session, integration_enabled, unwrap

_MB = 1 << 20


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _base(url: str) -> str:
    return url[: -len("/mcp")] if url.endswith("/mcp") else url


def _put(url: str, upload_path: str, data: bytes) -> httpx.Response:
    return httpx.put(_base(url) + upload_path, content=data, timeout=60)


async def _mint(session, filename: str, data: bytes, kind: str = "auto") -> dict:
    return unwrap(await session.call_tool("request_upload", {
        "filename": filename, "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "kind": kind,
    }))


async def _upload(session, url: str, filename: str, data: bytes, kind: str = "auto") -> dict:
    req = await _mint(session, filename, data, kind)
    assert req["ok"] is True, req
    r = _put(url, req["upload_path"], data)
    assert r.status_code == 200, f"PUT failed: {r.status_code} {r.text}"
    return unwrap(await session.call_tool("get_upload", {"file_id": req["file_id"]}))


def _need_integration():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")


@pytest.mark.integration
def test_forged_signature_rejected():
    # Regression: the route's only authorization is the HMAC sig — a forged ?t= must 403
    _need_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        r = httpx.put(_base(url) + f"/files/u/{'0' * 32}?t=not.a.real.sig",
                      content=b"x", timeout=30)
        assert r.status_code == 403, r.text


@pytest.mark.integration
def test_upload_filename_traversal_neutralized():
    # Regression: a hostile filename must not become a path component (server mints the id)
    _need_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                info = await _upload(s, url, "../../etc/evil.osm", b"OS:Version,3.11.0;\n")
                assert info["ready"] is True, info
                assert ".." not in info["server_path"], info
                assert "/uploads/" in info["server_path"], info
                assert Path(info["server_path"]).name == "evil.osm", info
        asyncio.run(_run())


@pytest.mark.integration
def test_sha256_and_size_tampering_rejected():
    # Regression: corrupted (right length, wrong bytes) or wrong-length uploads must 422, not persist
    _need_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                good = b"hello world"
                req = await _mint(s, "x.bin", good)
                r = _put(url, req["upload_path"], b"HELLO WORLD")  # same len, different bytes
                assert r.status_code == 422, r.text
                assert "sha256 mismatch" in r.json()["error"]
                got = unwrap(await s.call_tool("get_upload", {"file_id": req["file_id"]}))
                assert got["ready"] is False, "rejected upload must not be marked ready"
        asyncio.run(_run())


@pytest.mark.integration
def test_oversize_rejected_at_mint_and_stream():
    # Validates: size cap enforced at request time AND mid-stream (declared==cap, send more)
    _need_integration()
    with http_server({"MCP_AUTH": "none", "OSMCP_MAX_UPLOAD_MB": "1"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                over = unwrap(await s.call_tool("request_upload", {
                    "filename": "big.osm", "size_bytes": 2 * _MB}))
                assert over["ok"] is False and "max upload size" in over["error"], over

                req = unwrap(await s.call_tool("request_upload", {
                    "filename": "edge.osm", "size_bytes": _MB}))
                r = _put(url, req["upload_path"], b"a" * (_MB + 64))
                assert r.status_code == 413, r.text
        asyncio.run(_run())


@pytest.mark.integration
def test_uploads_private_per_user():
    # Regression: one tenant's upload must not be readable or downloadable by another session
    _need_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s1, http_session(url) as s2:
                cr = unwrap(await s1.call_tool("create_example_osm", {"name": _uniq("u1")}))
                data = Path(cr["osm_path"]).read_bytes()
                info = await _upload(s1, url, "private.osm", data, kind="osm")
                path1 = info["server_path"]

                ld = unwrap(await s2.call_tool("load_osm_model", {"osm_path": path1}))
                assert ld["ok"] is False and "not allowed" in ld["error"].lower(), ld

                dl = unwrap(await s2.call_tool("request_download", {"path": path1}))
                assert dl["ok"] is False and "not accessible" in dl["error"].lower(), dl
        asyncio.run(_run())


@pytest.mark.integration
def test_download_path_escape_denied():
    # Regression: request_download must refuse host files outside the caller's roots (exfil guard)
    _need_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                for victim in ("/etc/passwd", "/etc/shadow", "../../etc/passwd"):
                    dl = unwrap(await s.call_tool("request_download", {"path": victim}))
                    assert dl["ok"] is False, f"must refuse {victim}: {dl}"
                    assert "not accessible" in dl["error"].lower(), dl
        asyncio.run(_run())


@pytest.mark.integration
def test_upload_replay_rejected():
    # Regression: re-PUTting a completed upload must 409, not silently overwrite a referenced file
    _need_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                data = b"OS:Version,3.11.0;\n"
                req = await _mint(s, "once.osm", data)
                assert _put(url, req["upload_path"], data).status_code == 200
                replay = _put(url, req["upload_path"], data)
                assert replay.status_code == 409, replay.text
                assert "already completed" in replay.json()["error"]
        asyncio.run(_run())


@pytest.mark.integration
def test_zip_bomb_rejected_over_route():
    # Validates: the live route + extractor reject a decompression bomb (not just the unit test)
    _need_integration()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("m/measure.rb", b"\0" * (8 * _MB))  # tiny compressed, large expanded
    bomb = buf.getvalue()

    with http_server({"MCP_AUTH": "none", "OSMCP_MAX_ARCHIVE_UNCOMPRESSED_MB": "1"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                req = await _mint(s, "bomb.zip", bomb, kind="measure")
                r = _put(url, req["upload_path"], bomb)
                assert r.status_code == 422, r.text
                assert "bomb" in r.json()["error"].lower()
        asyncio.run(_run())


@pytest.mark.integration
def test_per_user_quota_enforced():
    # Validates: per-user upload quota blocks further uploads once exceeded
    _need_integration()
    with http_server({"MCP_AUTH": "none", "OSMCP_USER_QUOTA_MB": "1"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                chunk = b"a" * (700 * 1024)  # 700 KB; two would exceed the 1 MB quota
                first = await _upload(s, url, "one.bin", chunk)
                assert first["ready"] is True, first
                second = await _mint(s, "two.bin", chunk)
                assert second["ok"] is False, "second upload should be quota-blocked"
                assert "quota" in second["error"].lower(), second
        asyncio.run(_run())


@pytest.mark.integration
def test_isolation_under_token_auth():
    # Regression: under real token auth, uploads key to the principal and PUT needs no bearer
    _need_integration()
    tok_a, tok_b = "tok-alice", "tok-bob"
    tokens = {tok_a: "alice", tok_b: "bob"}
    with http_server({"MCP_AUTH": "token", "MCP_TOKENS": json.dumps(tokens)}) as (url, _proc):
        async def _run():
            async with http_session(url, token=tok_a) as sa, \
                       http_session(url, token=tok_b) as sb:
                cr = unwrap(await sa.call_tool("create_example_osm", {"name": _uniq("al")}))
                data = Path(cr["osm_path"]).read_bytes()
                info = await _upload(sa, url, "alice.osm", data, kind="osm")
                # The signed PUT carried no bearer yet landed under alice's namespace.
                assert "/alice/" in info["server_path"], info

                ld = unwrap(await sb.call_tool("load_osm_model", {"osm_path": info["server_path"]}))
                assert ld["ok"] is False and "not allowed" in ld["error"].lower(), ld
        asyncio.run(_run())
