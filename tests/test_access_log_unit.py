"""RedactSignedUrlFilter: the signed ?t= token must not reach the uvicorn access log.

Issue #170: after a client fetched a request_download URL the server log held the full
request line including the token, replayable until it expired.
"""
import logging

import pytest

pytestmark = pytest.mark.unit

TOKEN = "eyJleHAiOjE3OTE4NTYwLCJmIjoiLSJ9.c2lnbmF0dXJl"  # noqa: S105 - shape only, not a secret


def _access_record(path: str, method: str = "GET") -> logging.LogRecord:
    # uvicorn: access_logger.info('%s - "%s %s HTTP/%s" %d', client, method, path, ver, status)
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, "h11_impl.py", 1,
        '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:1234", method, path, "1.1", 200), None,
    )


@pytest.mark.parametrize(("method", "path", "expected"), [
    ("GET", f"/files/d/model.osm?t={TOKEN}", "/files/d/model.osm?[redacted]"),
    ("PUT", f"/files/u/abc123?t={TOKEN}", "/files/u/abc123?[redacted]"),
    # Starlette decodes parameter names, so %74= reaches the route as t=; the log is raw
    ("GET", f"/files/d/model.osm?%74={TOKEN}", "/files/d/model.osm?[redacted]"),
    ("GET", f"/files/d/model.osm?t=a&t={TOKEN}", "/files/d/model.osm?[redacted]"),
    ("GET", f"/files/d/run_abc.zip?t={TOKEN}&x=1", "/files/d/run_abc.zip?[redacted]"),
])
def test_signed_file_routes_lose_their_query(method, path, expected):
    # Regression: the full ?t=<token> of /files/ requests was written to the access log (#170)
    from mcp_server.access_log import RedactSignedUrlFilter
    rec = _access_record(path, method)
    assert RedactSignedUrlFilter().filter(rec) is True
    assert rec.args[2] == expected, rec.args
    assert TOKEN not in rec.getMessage(), rec.getMessage()
    assert rec.args[0] == "127.0.0.1:1234" and rec.args[4] == 200, "other fields untouched"


@pytest.mark.parametrize("path", [
    "/mcp?x=1",
    "/files/d/model.osm",
    "/healthz",
    "/filesystem/d/x?t=abc",
])
def test_other_routes_untouched(path):
    # Validates: only /files/ routes carry signed tokens; nothing else is rewritten
    from mcp_server.access_log import RedactSignedUrlFilter
    rec = _access_record(path)
    assert RedactSignedUrlFilter().filter(rec) is True
    assert rec.args[2] == path


def test_non_access_records_pass_through():
    # Validates: records without uvicorn's five-arg shape are left alone and still logged
    from mcp_server.access_log import RedactSignedUrlFilter
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, "plain %s", ("msg",), None)
    assert RedactSignedUrlFilter().filter(rec) is True
    assert rec.args == ("msg",)
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, "no args", None, None)
    assert RedactSignedUrlFilter().filter(rec) is True
