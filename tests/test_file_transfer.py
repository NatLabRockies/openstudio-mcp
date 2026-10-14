"""Remote file transfer over HTTP — FUNCTIONAL round-trips (does the feature work).

Adversarial / abuse-case coverage lives in tests/test_security_file_transfer.py
(it runs in the dedicated security workflow on both amd64 and arm64).
"""
import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
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
    # url is http://127.0.0.1:<port>/mcp ; file routes live at the same host root
    return url[: -len("/mcp")] if url.endswith("/mcp") else url


def _put(url: str, upload_path: str, data: bytes) -> httpx.Response:
    return httpx.put(_base(url) + upload_path, content=data, timeout=60)


async def _upload(session, url: str, filename: str, data: bytes, kind: str = "auto") -> dict:
    """request_upload -> PUT bytes -> get_upload. Returns the get_upload dict."""
    req = unwrap(await session.call_tool("request_upload", {
        "filename": filename, "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "kind": kind,
    }))
    assert req["ok"] is True, req
    r = _put(url, req["upload_path"], data)
    assert r.status_code == 200, f"PUT failed: {r.status_code} {r.text}"
    return unwrap(await session.call_tool("get_upload", {"file_id": req["file_id"]}))


@pytest.mark.integration
def test_upload_rejects_bzip2_measure_archive():
    # Regression: request_upload auto-extracts measure zips through guarded_extract, so the
    # bzip2 memory bomb reached the server through the upload route as well as BCL downloads
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_BZIP2) as zf:
        zf.writestr("m/measure.rb", "class M; end\n")
    data = buf.getvalue()

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                req = unwrap(await s.call_tool("request_upload", {
                    "filename": "codec.zip", "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(), "kind": "measure",
                }))
                assert req["ok"] is True, req
                r = _put(url, req["upload_path"], data)
                assert r.status_code == 422, f"bzip2 member must be refused: {r.status_code} {r.text}"
                assert r.json() == {
                    "ok": False,
                    "error": "archive entry 'm/measure.rb' uses unsupported compression (bzip2); "
                             "only stored or deflated members are accepted",
                }
                info = unwrap(await s.call_tool("get_upload", {"file_id": req["file_id"]}))
                assert info["ok"] is True and info["status"] == "pending", info
                assert info["ready"] is False, info

        asyncio.run(_run())


@pytest.mark.integration
def test_upload_roundtrip_loads_model():
    # Validates: a model uploaded out-of-band becomes a server path that load_osm_model loads
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                # Make a real OSM on the server, then re-upload its bytes as if from a laptop.
                cr = unwrap(await s.call_tool("create_example_osm", {"name": _uniq("up")}))
                assert cr["ok"] is True, cr
                data = Path(cr["osm_path"]).read_bytes()

                info = await _upload(s, url, "client_model.osm", data, kind="osm")
                assert info["ok"] is True and info["ready"] is True, info
                assert info["sha256"] == hashlib.sha256(data).hexdigest()
                assert "/uploads/" in info["server_path"], info
                assert info["server_path"].endswith("client_model.osm")

                ld = unwrap(await s.call_tool("load_osm_model", {"osm_path": info["server_path"]}))
                assert ld["ok"] is True, f"uploaded model must load: {ld}"

        asyncio.run(_run())


@pytest.mark.integration
def test_request_upload_returns_absolute_url():
    # Regression: request_upload returned a RELATIVE upload_url. The MCP transport
    # never tells the model the server host (it lives only in the client's
    # .mcp.json), so the agent couldn't build `curl --upload-file ... <url>`. The
    # URL must be absolute, derived from the request Host, and work PUT'd directly.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                data = b"OS:Version,3.11.0;\nabs,url\n"
                req = unwrap(await s.call_tool("request_upload", {
                    "filename": "abs.osm", "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(), "kind": "osm",
                }))
                assert req["ok"] is True, req
                assert req["upload_url"].startswith("http://"), \
                    f"upload_url must be absolute so the agent can PUT it: {req['upload_url']}"
                assert req["upload_url"] == _base(url) + req["upload_path"], \
                    f"absolute upload_url must be host-base + relative path: {req}"
                # Works PUT'd directly — no client-side host stitching needed.
                r = httpx.put(req["upload_url"], content=data, timeout=60)
                assert r.status_code == 200, f"direct PUT to absolute url failed: {r.status_code} {r.text}"
                info = unwrap(await s.call_tool("get_upload", {"file_id": req["file_id"]}))
                assert info["ready"] is True, info
                assert info["sha256"] == hashlib.sha256(data).hexdigest(), info

        asyncio.run(_run())


@pytest.mark.integration
def test_measure_zip_autoextract():
    # Validates: an uploaded measure .zip is extracted to a usable measure dir
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    measures_root = Path(os.environ.get("COMMON_MEASURES_DIR", "/opt/common-measures"))
    src = next((d for d in sorted(measures_root.iterdir())
                if (d / "measure.rb").is_file() and (d / "measure.xml").is_file()), None)
    if src is None:
        pytest.skip("no bundled measure with measure.rb+measure.xml found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in ("measure.rb", "measure.xml"):
            zf.write(src / f, f"{src.name}/{f}")
    zip_bytes = buf.getvalue()

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                info = await _upload(s, url, f"{src.name}.zip", zip_bytes, kind="measure")
                assert info["ready"] is True, info
                ep = info["extracted_path"]
                assert ep is not None, info
                assert (Path(ep) / "measure.rb").is_file(), f"extract should yield measure dir: {ep}"

                # The extracted measure is usable by the existing measure tooling.
                args = unwrap(await s.call_tool("list_measure_arguments", {"measure_dir": ep}))
                assert args["ok"] is True, f"extracted measure must be readable: {args}"

        asyncio.run(_run())


@pytest.mark.integration
def test_download_roundtrip():
    # Validates: a server file round-trips back out via a signed GET URL, bytes intact
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                data = b"OS:Version,3.11.0;\nsome,model,bytes\n"
                info = await _upload(s, url, "rt.osm", data)
                dl = unwrap(await s.call_tool("request_download", {"path": info["server_path"]}))
                assert dl["ok"] is True, dl
                # download_url is absolute too (same resolver as upload) — GET it directly.
                assert dl["download_url"] == _base(url) + dl["download_path"], dl
                r = httpx.get(dl["download_url"], timeout=30)
                assert r.status_code == 200, r.text
                assert r.content == data

        asyncio.run(_run())


@pytest.mark.integration
def test_download_bundle_roundtrip():
    # Validates: request_download(bundle=True) zips a dir under the caller's run
    # root and serves it with members byte-intact
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                data = b"OS:Version,3.11.0;\nbundle,me\n"
                info = await _upload(s, url, "bundle_me.osm", data)
                assert info["ready"] is True, info
                # uploads/ is itself a dir under the caller's run root — bundle it
                dl = unwrap(await s.call_tool("request_download",
                                              {"run_id": "uploads", "bundle": True}))
                assert dl["ok"] is True and dl["bundle"] is True, dl
                r = httpx.get(_base(url) + dl["download_path"], timeout=60)
                assert r.status_code == 200, r.text
                zf = zipfile.ZipFile(io.BytesIO(r.content))
                names = [n for n in zf.namelist() if n.endswith("bundle_me.osm")]
                assert len(names) == 1, f"uploaded file missing from bundle: {zf.namelist()}"
                assert zf.read(names[0]) == data

        asyncio.run(_run())


@pytest.mark.integration
def test_cli_put_get_roundtrip(tmp_path):
    # Regression: `osmcp put` crashed before moving any bytes — httpx AsyncClient
    # rejects a sync file object as content= (RuntimeError); CLI path had no test
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    data = b"OS:Version,3.11.0;\n" + b"x," * 5000
    src = tmp_path / "cli_model.osm"
    src.write_bytes(data)

    # Token auth (the documented CLI setup): put and get are separate MCP sessions,
    # so identity must come from the token, not the session, for get to see put's file.
    with http_server({"MCP_AUTH": "token",
                      "MCP_TOKENS": json.dumps({"tok-cli": "cliuser"})}) as (url, _proc):
        env = {**os.environ, "OSMCP_URL": url, "OSMCP_TOKEN": "tok-cli"}
        put = subprocess.run(  # noqa: S603 - args are sys.executable + test-owned paths
            [sys.executable, "-m", "mcp_server.tools.osmcp", "put", str(src), "--kind", "osm"],
            capture_output=True, text=True, env=env, timeout=180, check=False)
        assert put.returncode == 0, f"osmcp put failed:\n{put.stderr}"
        server_path = put.stdout.strip().splitlines()[-1]
        assert server_path.endswith("cli_model.osm"), put.stdout
        assert Path(server_path).read_bytes() == data

        out = tmp_path / "back.osm"
        get = subprocess.run(  # noqa: S603 - args are sys.executable + test-owned paths
            [sys.executable, "-m", "mcp_server.tools.osmcp", "get", server_path, "-o", str(out)],
            capture_output=True, text=True, env=env, timeout=180, check=False)
        assert get.returncode == 0, f"osmcp get failed:\n{get.stderr}"
        assert out.read_bytes() == data


def _token_exp(download_path: str) -> int:
    """Decode the signed token's expiry (payload is base64url JSON before the dot)."""
    import base64
    token = download_path.split("?t=", 1)[1]
    body = token.split(".", 1)[0]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))["exp"]


async def _view_model_report(s) -> dict:
    cr = unwrap(await s.call_tool("create_example_osm", {"name": _uniq("report")}))
    assert cr["ok"] is True, cr
    assert unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))["ok"] is True
    res = unwrap(await s.call_tool("view_model", {}))
    assert res["ok"] is True, res
    assert res["report_path"].endswith("reports/view_model_report.html"), res
    return res


@pytest.mark.integration
def test_view_model_hint_over_http():
    # Regression: over HTTP the report tools said "find it on the host at runs/exports/...";
    # the agent has no host mount there and gave up on the report (issue #167)
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                res = await _view_model_report(s)
                msg = res["user_message"]
                assert f'request_download(path="{res["report_path"]}")' in msg, msg
                assert "copy_file" not in msg and "runs/exports" not in msg, msg
                assert "valid for 900 s" in msg, msg

        asyncio.run(_run())


@pytest.mark.integration
def test_report_download_roundtrip_uses_download_ttl():
    # Regression: download URLs were minted with the upload TTL (300 s); the mint -> relay ->
    # click hop took longer and the user's link was dead (issue #167). Checks the signed
    # expiry, not just the reported expires_in, for a file and for a bundle; uploads keep
    # their own TTL.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")
    import time

    env = {"MCP_AUTH": "none", "OSMCP_DOWNLOAD_URL_TTL": "777", "OSMCP_UPLOAD_URL_TTL": "300"}
    with http_server(env) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                res = await _view_model_report(s)
                t0 = int(time.time())
                dl = unwrap(await s.call_tool("request_download", {"path": res["report_path"]}))
                assert dl["ok"] is True, dl
                assert dl["expires_in"] == 777, dl
                assert t0 + 777 - 2 <= _token_exp(dl["download_path"]) <= t0 + 777 + 5, dl
                r = httpx.get(dl["download_url"], timeout=30)
                assert r.status_code == 200, r.text
                assert r.content == Path(res["report_path"]).read_bytes()

                run_id = Path(res["run_dir"]).name  # apply_measure results carry run_dir only
                bundle = unwrap(await s.call_tool("request_download",
                                                  {"run_id": run_id, "bundle": True}))
                assert bundle["ok"] is True, bundle
                assert bundle["expires_in"] == 777, bundle
                assert t0 + 777 - 2 <= _token_exp(bundle["download_path"]) <= t0 + 777 + 10, bundle

                up = unwrap(await s.call_tool("request_upload", {"filename": "x.osm", "size_bytes": 3}))
                assert up["ok"] is True and up["expires_in"] == 300, up
                assert t0 + 300 - 2 <= _token_exp(up["upload_path"]) <= t0 + 300 + 15, up

        asyncio.run(_run())
