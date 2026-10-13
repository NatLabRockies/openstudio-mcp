"""Keep signed file-transfer tokens out of uvicorn's access log (issue #170).

The /files/u and /files/d routes authorize with a signed ``?t=<token>`` query
(see skills/file_transfer/routes.py). uvicorn logs every request line with its
raw query string, so anyone who could read the server log could replay a
download until the token expired. This filter drops the whole query from
/files/ request lines before they are formatted. It cuts the query rather than
matching ``t=`` by name because Starlette percent-decodes parameter names
(``?%74=`` reaches the route as ``t``) while uvicorn logs the raw bytes.

A reverse proxy in front of the server writes its own access log; that is
outside this process.
"""
from __future__ import annotations

import logging

SIGNED_ROUTE_PREFIX = "/files/"
REDACTED = "?[redacted]"


class RedactSignedUrlFilter(logging.Filter):
    """uvicorn: ``access_logger.info('%s - "%s %s HTTP/%s" %d', client, method, path, ver, status)``."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path = args[2]
            if path.startswith(SIGNED_ROUTE_PREFIX) and "?" in path:
                record.args = (*args[:2], path.split("?", 1)[0] + REDACTED, *args[3:])
        return True


def install() -> None:
    """Attach the filter to uvicorn's access logger.

    Called before uvicorn starts. uvicorn's dictConfig replaces the logger's
    handlers but leaves filters attached to the logger object in place.
    """
    logging.getLogger("uvicorn.access").addFilter(RedactSignedUrlFilter())
