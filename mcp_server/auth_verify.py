"""Revocation-aware JWT verification backed by the auth portal.

FastMCP's ``JWTVerifier`` checks a bearer token statelessly: signature against
``MCP_JWT_PUBLIC_KEY``/``MCP_JWT_JWKS_URI``, expiry, and the configured
issuer/audience. Nothing in that path can learn that an admin revoked a token
before its natural expiry, and nobody learns which tokens are in use.

``RevocationAwareJWTVerifier`` keeps that local check as the first and
authoritative step, then (opt-in via ``MCP_JWT_VERIFY_URL``) asks the auth
portal's ``POST /.well-known/verify-token`` endpoint whether the token is still
allowed. The portal answers ``200 {"valid": true}`` or ``401 {"valid": false,
"reason": ...}`` and records ``usage_count`` / ``last_usage_at`` for the token's
``jti`` as a side effect. The portal is a gate, never a source of identity: the
request's ``AccessToken`` (and therefore ``client_id``, which scopes the user's
run dir) always comes from the locally verified token.

Ordering matters for two reasons. A token that fails the local check never
reaches the portal, so unauthenticated callers cannot drive portal traffic or
pollute its usage counters. And the server's own issuer/audience policy stays
enforced even if the portal is misconfigured or compromised.

When the portal is unreachable (connection error, 5xx, or no complete answer
within ``timeout`` seconds, which bounds the whole call, not each read) the
``fail_open`` policy decides: fail-closed (default) rejects the request;
fail-open accepts the locally valid token and logs a warning. A definitive
portal answer (200/401/4xx) is never treated as unreachable.

A small in-memory cache keyed by the SHA-256 of the exact token bytes skips the
portal round trip for ``cache_ttl`` seconds after a "valid" answer. The local
check still runs on every request, so an expired token is rejected even while
cached; only revocation is delayed by up to the TTL. The cache is bounded by
``cache_max_size`` entries (oldest evicted first).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 3.0
DEFAULT_CACHE_TTL = 30.0
DEFAULT_CACHE_MAX_SIZE = 1024
# A verify-token reply is a small JSON object; anything bigger is a broken or
# hostile portal and is rejected without being buffered.
MAX_PORTAL_RESPONSE_BYTES = 64 * 1024

# Monotonic clock, indirected so tests can advance it without touching the
# global ``time`` module (asyncio's event loop uses time.monotonic too).
_now = time.monotonic


def _cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _json_object(raw: bytes) -> dict[str, Any]:
    """The body as a dict, or {} if it is not a JSON object."""
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        # RecursionError: nesting deeper than the parser's limit fits well under the size cap.
        return {}
    return body if isinstance(body, dict) else {}


class RevocationAwareJWTVerifier(JWTVerifier):
    """``JWTVerifier`` plus an optional revocation check against the auth portal.

    With ``verify_url`` unset this is exactly the base verifier. See the module
    docstring for the ordering, fail-open/fail-closed, and caching contracts.

    ``verify_http_client`` is the client for the portal call only. The base
    class's ``http_client`` (JWKS fetches) is a separate object with its own
    timeout; the two are never shared.
    """

    def __init__(
        self,
        *args: Any,
        verify_url: str | None = None,
        fail_open: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        cache_max_size: int = DEFAULT_CACHE_MAX_SIZE,
        verify_http_client: httpx.AsyncClient | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.verify_url = verify_url or None
        self.fail_open = bool(fail_open)
        self.timeout = float(timeout)
        self.cache_ttl = float(cache_ttl)
        # nan/inf would make a cached "valid" answer never expire (nan never
        # compares elapsed, inf never arrives), silently disabling revocation.
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError(f"timeout must be a finite number > 0, got {timeout!r}")
        if not math.isfinite(self.cache_ttl) or self.cache_ttl < 0:
            raise ValueError(f"cache_ttl must be a finite number >= 0, got {cache_ttl!r}")
        self.cache_max_size = max(int(cache_max_size), 1)
        # Deliberately NOT ``_http_client``: that is the base verifier's JWKS client.
        self._verify_http_client = verify_http_client
        self._owns_verify_client = verify_http_client is None
        # sha256(token) -> monotonic time at which the cached "valid" answer expires.
        self._cache: dict[str, float] = {}

    # --- verification ------------------------------------------------------

    async def verify_token(self, token: str) -> AccessToken | None:
        # Local signature/expiry/issuer/audience/scope check first; it is the
        # only thing that ever produces the request's identity.
        access_token = await super().verify_token(token)
        if access_token is None or self.verify_url is None:
            return access_token

        key = _cache_key(token)
        if self._cache_hit(key):
            return access_token

        try:
            # httpx's timeout is per phase (connect, each read), so a portal that drips its
            # reply could outlast it indefinitely; this caps the whole call.
            async with asyncio.timeout(self.timeout):
                allowed = await self._portal_allows(token, access_token.client_id)
        except (httpx.HTTPError, TimeoutError) as exc:
            detail = str(exc) or f"no answer within {self.timeout:g} s"
            if self.fail_open:
                logger.warning(
                    "verify-token endpoint unreachable (%s); accepting locally "
                    "valid token for client %s because MCP_JWT_VERIFY_FAIL_OPEN=true",
                    detail, access_token.client_id,
                )
                return access_token
            logger.warning(
                "verify-token endpoint unreachable (%s); rejecting request for "
                "client %s (fail-closed; set MCP_JWT_VERIFY_FAIL_OPEN=true to "
                "accept locally valid tokens during a portal outage)",
                detail, access_token.client_id,
            )
            return None

        if not allowed:
            return None
        self._cache_put(key)
        return access_token

    async def _portal_allows(self, token: str, client_id: str) -> bool:
        """Ask the portal. True = valid, False = definitive reject.

        Raises ``httpx.HTTPError`` (transport error, timeout, or a 5xx wrapped
        as ``HTTPStatusError``) so the caller can apply the fail-open policy.
        The body is read incrementally and capped at MAX_PORTAL_RESPONSE_BYTES;
        an oversized reply is a broken portal and counts as a reject.
        """
        async with self._client().stream(
            "POST", self.verify_url, headers={"Authorization": f"Bearer {token}"},
        ) as response:
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"verify-token returned HTTP {response.status_code}",
                    request=response.request, response=response,
                )
            raw = b""
            async for chunk in response.aiter_bytes():
                raw += chunk
                if len(raw) > MAX_PORTAL_RESPONSE_BYTES:
                    logger.warning(
                        "verify-token reply exceeded %d bytes; rejecting token for client %s",
                        MAX_PORTAL_RESPONSE_BYTES, client_id,
                    )
                    return False
        body = _json_object(raw)
        if response.status_code == 200 and body.get("valid") is True:
            return True
        reason = body.get("reason") or f"HTTP {response.status_code}"
        if response.status_code in (404, 405):
            reason += " (check MCP_JWT_VERIFY_URL)"
        logger.warning("verify-token rejected token for client %s: %s", client_id, reason)
        return False

    # --- http client -------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        """One shared portal client (keep-alive) created lazily inside the event loop."""
        if self._verify_http_client is None:
            self._verify_http_client = httpx.AsyncClient(timeout=self.timeout)
        return self._verify_http_client

    async def aclose(self) -> None:
        """Close the portal client this verifier created; an injected one is the caller's."""
        if self._owns_verify_client and self._verify_http_client is not None:
            await self._verify_http_client.aclose()
            self._verify_http_client = None

    # --- cache -------------------------------------------------------------

    def _cache_hit(self, key: str) -> bool:
        if self.cache_ttl <= 0:
            return False
        expires_at = self._cache.get(key)
        if expires_at is None:
            return False
        if _now() >= expires_at:
            del self._cache[key]
            return False
        return True

    def _cache_put(self, key: str) -> None:
        if self.cache_ttl <= 0:
            return
        now = _now()
        if len(self._cache) >= self.cache_max_size:
            for stale in [k for k, exp in self._cache.items() if now >= exp]:
                del self._cache[stale]
        while len(self._cache) >= self.cache_max_size:
            # dicts iterate in insertion order, so this is the oldest entry.
            del self._cache[next(iter(self._cache))]
        self._cache[key] = now + self.cache_ttl


# --- env wiring --------------------------------------------------------------

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("", "0", "false", "no", "off")


def _env_flag(name: str) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ValueError(f"{name} must be true/false, got {raw!r}")


def _env_number(name: str, default: float, *, allow_zero: bool) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number of seconds, got {raw!r}") from None
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        bound = ">= 0" if allow_zero else "> 0"
        raise ValueError(f"{name} must be a finite number {bound}, got {raw!r}")
    return value


def _env_url(name: str) -> str | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"{name} must be an absolute http(s) URL with a host, got {raw!r}")
    return raw


def build_verifier_kwargs_from_env() -> dict[str, Any]:
    """Read ``MCP_JWT_VERIFY_*`` into ``RevocationAwareJWTVerifier`` kwargs.

    Raises ``ValueError`` with the offending variable's name so a bad value
    fails server startup with a clear message instead of a traceback later.
    """
    return {
        "verify_url": _env_url("MCP_JWT_VERIFY_URL"),
        "fail_open": _env_flag("MCP_JWT_VERIFY_FAIL_OPEN"),
        "timeout": _env_number("MCP_JWT_VERIFY_TIMEOUT", DEFAULT_TIMEOUT, allow_zero=False),
        "cache_ttl": _env_number("MCP_JWT_VERIFY_CACHE_TTL", DEFAULT_CACHE_TTL, allow_zero=True),
    }
