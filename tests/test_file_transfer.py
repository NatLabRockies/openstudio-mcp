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
                r = httpx.get(_base(url) + dl["download_path"], timeout=30)
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
