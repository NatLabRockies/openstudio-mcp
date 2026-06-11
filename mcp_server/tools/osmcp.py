"""Thin CLI for the remote file-transfer channel — for clients without a shell.

The agent-driven path (request_upload tool -> curl -> get_upload) is the default;
this is the fallback for shell-less or human-driven use. It calls the same MCP
tools over the same authenticated endpoint, then moves bytes out-of-band.

    python -m mcp_server.tools.osmcp put model.osm --kind osm
    python -m mcp_server.tools.osmcp put my_measure.zip --kind measure
    python -m mcp_server.tools.osmcp get /runs/<user>/<run>/exports/model.osm -o out.osm

Endpoint + token come from --url/--token or OSMCP_URL / OSMCP_TOKEN.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


def _base_url(mcp_url: str) -> str:
    parts = urlsplit(mcp_url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _abs(mcp_url: str, url_or_path: str) -> str:
    return url_or_path if url_or_path.startswith("http") else _base_url(mcp_url) + url_or_path


# Long, explicit timeout for moving large model files (not None — bandit S113).
_XFER_TIMEOUT = 3600


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def _call(client: Client, name: str, args: dict) -> dict:
    res = await client.call_tool(name, args)
    data = getattr(res, "data", None)
    if isinstance(data, dict):
        return data
    sc = getattr(res, "structured_content", None)
    return sc if isinstance(sc, dict) else {}


async def _put(url: str, token: str, mcp_url: str, kind: str) -> int:
    src = Path(url)
    if not src.is_file():
        print(f"not a file: {src}", file=sys.stderr)
        return 2
    transport = StreamableHttpTransport(mcp_url, headers={"Authorization": f"Bearer {token}"})
    async with Client(transport) as client:
        req = await _call(client, "request_upload", {
            "filename": src.name, "size_bytes": src.stat().st_size,
            "sha256": _sha256(src), "kind": kind,
        })
        if not req.get("ok"):
            print(f"request_upload failed: {req.get('error')}", file=sys.stderr)
            return 1
        put_url = _abs(mcp_url, req.get("upload_url") or req["upload_path"])
        async with httpx.AsyncClient(timeout=_XFER_TIMEOUT) as http:
            with src.open("rb") as f:
                r = await http.put(put_url, content=f)
        if r.status_code != 200:
            print(f"upload failed ({r.status_code}): {r.text}", file=sys.stderr)
            return 1
        info = await _call(client, "get_upload", {"file_id": req["file_id"]})
        path = info.get("extracted_path") or info.get("server_path")
        print(path)  # stdout = the server path to feed to load_osm_model/apply_measure
        return 0


async def _get(server_path: str, token: str, mcp_url: str, out: str | None) -> int:
    transport = StreamableHttpTransport(mcp_url, headers={"Authorization": f"Bearer {token}"})
    async with Client(transport) as client:
        req = await _call(client, "request_download", {"path": server_path})
        if not req.get("ok"):
            print(f"request_download failed: {req.get('error')}", file=sys.stderr)
            return 1
        get_url = _abs(mcp_url, req.get("download_url") or req["download_path"])
        dest = Path(out) if out else Path(Path(server_path).name)
        async with httpx.AsyncClient(timeout=_XFER_TIMEOUT) as http:
            r = await http.get(get_url)
        if r.status_code != 200:
            print(f"download failed ({r.status_code}): {r.text}", file=sys.stderr)
            return 1
        dest.write_bytes(r.content)
        print(str(dest))
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="osmcp", description="openstudio-mcp file transfer")
    p.add_argument("--url", default=os.environ.get("OSMCP_URL"), help="MCP endpoint, e.g. http://box:8000/mcp")
    p.add_argument("--token", default=os.environ.get("OSMCP_TOKEN"), help="bearer token")
    sub = p.add_subparsers(dest="cmd", required=True)
    pu = sub.add_parser("put", help="upload a local file")
    pu.add_argument("file")
    pu.add_argument("--kind", default="auto")
    pg = sub.add_parser("get", help="download a server file")
    pg.add_argument("server_path")
    pg.add_argument("-o", "--out", default=None)
    a = p.parse_args(argv)
    if not a.url or not a.token:
        p.error("--url/--token (or OSMCP_URL/OSMCP_TOKEN) required")
    if a.cmd == "put":
        return asyncio.run(_put(a.file, a.token, a.url, a.kind))
    return asyncio.run(_get(a.server_path, a.token, a.url, a.out))


if __name__ == "__main__":
    raise SystemExit(main())
