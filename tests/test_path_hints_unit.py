"""path_hints: what the server tells an agent about a file that is on the user's machine.

Session 2026-11-04 (remote HTTP server): asked about a model in the user's local folder, the
agent probed the server with list_files and load_osm_model, got bare "not allowed" errors, and
fell back to parsing the OSM with local scripts. The instructions told it to "use the path
directly" and then try list_files; nothing named request_upload.
"""
import pytest

pytestmark = pytest.mark.unit

STDIO_SENTENCE = (
    "If a file path is given, use it directly. If a file operation fails, "
    "you may call list_files once to find the right path, then retry — "
    "do not call list_files more than once for the same file. "
)
WIN_PATH = r"C:\projects\test\assets\SystemD_baseline.osm"


def _transport(monkeypatch, name):
    if name:
        monkeypatch.setenv("MCP_TRANSPORT", name)
    else:
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("OSMCP_TOOLS_ALLOW", raising=False)
    monkeypatch.delenv("OSMCP_TOOLS_DENY", raising=False)


@pytest.mark.parametrize(("raw", "expected"), [
    (WIN_PATH, True),
    ("d:/models/office.osm", True),
    (r"\\fileserver\share\office.osm", True),
    ("~/models/office.osm", True),
    ("/inputs/office.osm", False),
    ("/runs/brian/models/office.osm", False),
    ("/assets/office.osm", False),
    ("tests/assets/office.osm", False),
    ("~backup.osm", False),
    ("", False),
])
def test_client_path_detector(monkeypatch, raw, expected):
    # Validates: only shapes that cannot be a path on a Linux server (drive letter, UNC, ~/)
    # are called user-machine paths; server-style and relative paths are left alone
    from mcp_server import path_hints
    monkeypatch.setattr(path_hints, "_SERVER_IS_WINDOWS", False)
    assert path_hints.looks_like_client_path(raw) is expected, raw


def test_drive_path_is_a_server_path_on_a_windows_server(monkeypatch):
    # Validates: a server run natively on Windows takes C:\ paths as its own, so the hint
    # must not call them user-machine paths there
    from mcp_server import path_hints
    monkeypatch.setattr(path_hints, "_SERVER_IS_WINDOWS", True)
    assert path_hints.looks_like_client_path(WIN_PATH) is False


@pytest.mark.parametrize("transport", ["http", "streamable-http"])
def test_http_hint_names_the_upload_tools(monkeypatch, transport):
    # Regression: over HTTP "OSM path is not allowed: /assets/x.osm" gave the agent no next
    # step; the hint must name request_upload and get_upload
    from mcp_server import path_hints
    _transport(monkeypatch, transport)
    assert path_hints.path_hint("/assets/SystemD_baseline.osm") == (
        "Paths are on the server, not the user's machine. If this file is on the user's "
        "machine, upload it with request_upload, then use the path get_upload returns."
    )


def test_http_hint_calls_out_a_windows_path(monkeypatch):
    # Regression: load_osm_model("C:\...") answered "OSM file not found: /repo/C:\...", the
    # Windows path glued onto the server's working directory, with no word that the file is
    # on the user's machine
    from mcp_server import path_hints
    _transport(monkeypatch, "http")
    monkeypatch.setattr(path_hints, "_SERVER_IS_WINDOWS", False)
    assert path_hints.path_hint(WIN_PATH) == (
        f"{WIN_PATH} looks like a path on the user's machine; the server cannot read it. "
        "Upload the file with request_upload, then use the path get_upload returns."
    )


@pytest.mark.parametrize("transport", ["stdio", ""])
def test_stdio_hint_points_at_the_mounted_folder_not_upload(monkeypatch, transport):
    # Validates: on stdio the user's folder is mounted into the server, so the hint sends the
    # agent to list_files and never to request_upload (there is no upload host to PUT to)
    from mcp_server import path_hints
    from mcp_server.config import INPUT_ROOT
    _transport(monkeypatch, transport)
    hint = path_hints.path_hint("/assets/SystemD_baseline.osm")
    assert hint == (
        "Paths are on the server, not the user's machine. Files from the user's mounted "
        f"folder are under {INPUT_ROOT}; list_files shows them."
    )
    assert "request_upload" not in hint


@pytest.mark.parametrize("hidden", ["request_upload", "get_upload"])
def test_http_hint_never_names_an_upload_tool_the_policy_hides(monkeypatch, hidden):
    # Validates: with either upload tool hidden by OSMCP_TOOLS_DENY the hint must not send the
    # agent to a tool it cannot call
    from mcp_server import path_hints
    _transport(monkeypatch, "http")
    monkeypatch.setenv("OSMCP_TOOLS_DENY", hidden)
    hint = path_hints.path_hint("/assets/SystemD_baseline.osm")
    assert hint == (
        "Paths are on the server, not the user's machine. File upload is disabled on this "
        "server; ask the server operator to stage the file."
    )
    assert "request_upload" not in path_hints.file_location_instructions()


@pytest.mark.parametrize("transport", ["stdio", ""])
def test_stdio_instructions_keep_the_use_it_directly_sentence(monkeypatch, transport):
    # Validates: stdio instructions are unchanged, byte for byte; there the mounted folder is
    # the right place to look for the user's file
    from mcp_server import path_hints
    _transport(monkeypatch, transport)
    assert path_hints.file_location_instructions() == STDIO_SENTENCE


@pytest.mark.parametrize("transport", ["http", "streamable-http"])
def test_http_instructions_send_local_files_to_upload(monkeypatch, transport):
    # Regression: the instructions said "If a file path is given, use it directly ... call
    # list_files once" on every transport, so HTTP agents searched the server for a file that
    # was on the user's machine. A first rewording that only covered "a file on their own
    # machine" still failed a replay: asked about /assets/SystemD*osm (a local folder), the
    # agent took it for a server path and called list_files twice. The default must be local.
    from mcp_server import path_hints
    from mcp_server.config import INPUT_ROOT, RUN_ROOT
    _transport(monkeypatch, transport)
    assert path_hints.file_location_instructions() == (
        "This server is remote: path arguments are paths on the server, and a file the user "
        "names is usually on the user's machine instead. Unless the path came from a tool "
        f"result, starts with {RUN_ROOT.as_posix()}/ or {INPUT_ROOT.as_posix()}/, or the user "
        "says it is on the server, look for it on the user's machine with your own file "
        "tools first (ask the user if you have none), then upload it with request_upload "
        "and use the path get_upload returns. "
        "Call list_files only for a file already on the server, and not more than once for "
        "the same file. "
    )


def test_http_empty_listing_hints_at_upload(monkeypatch):
    # Regression: in the replay list_files(pattern="SystemD*osm") succeeded with zero files,
    # so no error hint fired and the agent gave up without looking on the user's machine
    from mcp_server import path_hints
    _transport(monkeypatch, "http")
    assert path_hints.no_match_hint() == (
        "No matching file on the server. If the file is on the user's machine, upload it "
        "with request_upload, then use the path get_upload returns."
    )
    monkeypatch.setenv("OSMCP_TOOLS_DENY", "request_upload")
    assert path_hints.no_match_hint() == (
        "No matching file on the server. File upload is disabled on this server; ask the "
        "server operator to stage the file."
    )


@pytest.mark.parametrize("transport", ["stdio", ""])
def test_stdio_empty_listing_has_no_hint(monkeypatch, transport):
    # Validates: on stdio list_files already covers the user's mounted folder, so an empty
    # listing means the file is not there; no upload hint is added
    from mcp_server import path_hints
    _transport(monkeypatch, transport)
    assert path_hints.no_match_hint() is None
