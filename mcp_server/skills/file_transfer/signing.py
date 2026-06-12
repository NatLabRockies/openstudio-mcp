"""HMAC-signed URL tokens for the out-of-band file-transfer routes.

The file PUT/GET routes run OUTSIDE FastMCP request context (custom_route is not
behind the `auth=` verifier — empirically: a custom route serves 200 with no
token), so they cannot derive the caller from context. Instead the authenticated
`request_upload` / `request_download` MCP tools — which DO have context and know
`user_key()` — mint a short-lived token binding (user, file_id, op, expiry). The
route verifies the HMAC and trusts the embedded user key as the authorization.

This keeps the long-lived bearer token out of the URL (and out of the model's
context), and a leaked URL expires fast and is scoped to one file + one op.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from mcp_server.config import RUN_ROOT

_KEY_FILE = RUN_ROOT / ".file_signing_key"
_key_cache: bytes | None = None


def _load_or_create_key() -> bytes:
    """Resolve the HMAC key: env override > persisted file > generate+persist.

    Persisting (mode 0600) means URLs survive a restart and every worker derives
    the same signatures. Operators who want to rotate or share a key across boxes
    set OSMCP_FILE_SIGNING_KEY.
    """
    env = os.environ.get("OSMCP_FILE_SIGNING_KEY")
    if env:
        return hashlib.sha256(env.encode("utf-8")).digest()
    try:
        if _KEY_FILE.exists():
            data = _KEY_FILE.read_bytes()
            if len(data) >= 32:
                return data
    except OSError:
        pass
    key = secrets.token_bytes(32)
    try:
        # O_EXCL: born 0600 (no chmod window) and exactly one process wins the
        # create — concurrent cold-started workers all converge on the same key.
        fd = os.open(_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            data = _KEY_FILE.read_bytes()
            if len(data) >= 32:
                return data
        except OSError:
            pass
        return key
    except OSError:
        # Read-only RUN_ROOT (unusual): fall back to a process-lifetime key. URLs
        # then don't survive a restart, but signing still works within the run.
        return key
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def _key() -> bytes:
    global _key_cache
    if _key_cache is None:
        _key_cache = _load_or_create_key()
    return _key_cache


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user_key: str, file_id: str, op: str, ttl: int, **extra) -> str:
    """Mint a signed token. `op` is "u" (upload) or "d" (download)."""
    payload = {"u": user_key, "f": file_id, "op": op, "exp": int(time.time()) + int(ttl)}
    payload.update({k: v for k, v in extra.items() if v is not None})
    body = _b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64u(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str, *, op: str | None = None) -> dict:
    """Validate signature + expiry; return the payload. Raises ValueError if bad.

    Constant-time signature compare; explicit expiry check; optional op match so
    an upload URL can't be replayed against the download route or vice versa.
    """
    try:
        body, sig = token.split(".", 1)
    except ValueError as e:
        raise ValueError("malformed token") from e
    expected = _b64u(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise ValueError("bad signature")
    try:
        payload = json.loads(_b64u_decode(body))
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError("malformed payload") from e
    if not isinstance(payload, dict) or "exp" not in payload:
        raise ValueError("malformed payload")
    if time.time() > float(payload["exp"]):
        raise ValueError("token expired")
    if op is not None and payload.get("op") != op:
        raise ValueError("wrong token op")
    return payload
