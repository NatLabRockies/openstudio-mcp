"""Keep signed file-transfer tokens out of uvicorn's access log (issue #170).

The /files/u and /files/d routes authorize with a signed ``?t=<token>`` query
(see skills/file_transfer/routes.py). uvicorn logs every request line with its
raw query string, so anyone who could read the server log could replay a
download until the token expired. This filter drops the whole query from
/files/ paths in uvicorn's access and error records before they are
formatted (a refused WebSocket upgrade to a signed URL is logged by the error
logger with the full path). It cuts the query rather than
matching ``t=`` by name because Starlette percent-decodes parameter names
(``?%74=`` reaches the route as ``t``) while uvicorn logs the raw bytes.

A reverse proxy in front of the server writes its own access log; that is
outside this process.
"""
from __future__ import annotations

import logging

SIGNED_ROUTE_PREFIX = "/files/"
REDACTED = "?[redacted]"


def _redact(value: str) -> str:
    if value.startswith(SIGNED_ROUTE_PREFIX) and "?" in value:
        return value.split("?", 1)[0] + REDACTED
    return value


class RedactSignedUrlFilter(logging.Filter):
    """Redact every ``/files/...?...`` string argument of a log record.

    Shapes seen in uvicorn: the access line
    ``'%s - "%s %s HTTP/%s" %d', client, method, path, ver, status`` on
    ``uvicorn.access``, and the refused WebSocket upgrade
    ``'%s - "WebSocket %s" 403', client, path`` on ``uvicorn.error``. Matching
    by value rather than by position covers both and any future shape.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and any(isinstance(a, str) for a in args):
            record.args = tuple(_redact(a) if isinstance(a, str) else a for a in args)
        return True


def install() -> None:
    """Attach the filter to uvicorn's access and error loggers.

    Called before uvicorn starts. uvicorn's dictConfig replaces the loggers'
    handlers but leaves filters attached to the logger objects in place.
    """
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(RedactSignedUrlFilter())
