"""One sentence telling the agent how to get a server-side file to the user.

Shared by the report wrappers (common_measures) and the response-size guard.
The old text named a host path ("find it on the host at runs/exports/...") on
every transport; over HTTP the agent has no mount and gave up on the report
(issue #167).
"""
from __future__ import annotations

from pathlib import Path

from mcp_server.identity import _is_http_transport


def export_hint(path: Path, what: str = "File") -> str:
    """stdio: copy_file (the host usually bind-mounts the run root). HTTP: a signed URL."""
    if _is_http_transport():
        from mcp_server.config import OSMCP_DOWNLOAD_URL_TTL
        return (
            f'{what} written to {path}. Call request_download(path="{path}") and give the '
            f"user the download_url. The URL is valid for {OSMCP_DOWNLOAD_URL_TTL} s."
        )
    return (
        f'{what} written to {path}. Call copy_file(file_path="{path}") to export it; '
        "copy_file returns the exported path."
    )
