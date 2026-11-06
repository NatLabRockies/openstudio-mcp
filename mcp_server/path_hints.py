"""Guidance for a file that is on the user's machine, not on the server.

Over HTTP the server runs on another machine than the user. The instructions said "If a file
path is given, use it directly" and then "call list_files once" on every transport, so an
agent asked about a file in the user's local folder searched the server for it, got a bare
"not allowed", and parsed the model with local scripts instead of uploading it. On stdio the
user's folder is mounted into the server, so looking there first is right and stays.

The client-path check only picks the wording of a hint. It never decides whether a path is
allowed: that stays with config.is_path_allowed at each call site.
"""
from __future__ import annotations

import os
import re

from mcp_server.identity import _is_http_transport
from mcp_server.tool_policy import tool_enabled

# A drive path is the server's own path when the server runs natively on Windows.
_SERVER_IS_WINDOWS = os.name == "nt"

# Drive letter (C:\ or C:/), UNC (\\server\share) or home (~/, ~\). None of these can name a
# file on a Linux server; a leading "/" can, so "/Users/..." and "/home/..." are not listed.
_CLIENT_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|~[\\/])")

_STDIO_INSTRUCTIONS = (
    "If a file path is given, use it directly. If a file operation fails, "
    "you may call list_files once to find the right path, then retry — "
    "do not call list_files more than once for the same file. "
)
_SERVER_FILE_INSTRUCTIONS = (
    "Call list_files only for a file already on the server, and not more than once for "
    "the same file. "
)
_UPLOAD_STEPS = "with request_upload, then use the path get_upload returns."
_NO_UPLOAD = "File upload is disabled on this server; ask the server operator to stage the file."


def looks_like_client_path(raw: str) -> bool:
    """Whether `raw` is shaped like a path on the user's machine rather than the server's."""
    if _SERVER_IS_WINDOWS:
        return False
    return _CLIENT_PATH.match(str(raw).strip()) is not None


def _upload_available() -> bool:
    return tool_enabled("request_upload") and tool_enabled("get_upload")


def path_hint(raw: str) -> str:
    """The `hint` for a file-path argument the server refused or could not find."""
    client = looks_like_client_path(raw)
    lead = (
        f"{raw} looks like a path on the user's machine; the server cannot read it."
        if client else "Paths are on the server, not the user's machine."
    )
    if not _is_http_transport():
        from mcp_server.config import INPUT_ROOT
        return (
            f"{lead} Files from the user's mounted folder are under {INPUT_ROOT}; "
            "list_files shows them."
        )
    if not _upload_available():
        return f"{lead} {_NO_UPLOAD}"
    if client:
        return f"{lead} Upload the file {_UPLOAD_STEPS}"
    return f"{lead} If this file is on the user's machine, upload it {_UPLOAD_STEPS}"


def no_match_hint() -> str | None:
    """The `hint` for a server file listing that matched nothing; None on stdio.

    On stdio the listing already covers the user's mounted folder, so an empty one says all
    there is to say. Over HTTP the file is most likely on the user's machine.
    """
    if not _is_http_transport():
        return None
    if not _upload_available():
        return f"No matching file on the server. {_NO_UPLOAD}"
    return (
        "No matching file on the server. If the file is on the user's machine, upload it "
        f"{_UPLOAD_STEPS}"
    )


def file_location_instructions() -> str:
    """The server-instructions sentence on where a file the user names is to be found.

    Over HTTP the default is the user's machine: a wording that only covered "a file on
    their own machine" left an agent treating /assets/x.osm (a folder on the user's
    machine) as a server path.
    """
    if not _is_http_transport():
        return _STDIO_INSTRUCTIONS
    from mcp_server.config import INPUT_ROOT, RUN_ROOT
    lead = (
        "This server is remote: path arguments are paths on the server, and a file the user "
        "names is usually on the user's machine instead"
    )
    if _upload_available():
        local = (
            ". Unless the path came from a tool result, starts with "
            f"{RUN_ROOT.as_posix()}/ or {INPUT_ROOT.as_posix()}/, or the user says it is on "
            "the server, look for it on the user's machine with your own file tools first "
            "(ask the user if you have none), then upload it with request_upload and use the "
            "path get_upload returns. "
        )
    else:
        local = f", where the server cannot read it. {_NO_UPLOAD} "
    return lead + local + _SERVER_FILE_INSTRUCTIONS
