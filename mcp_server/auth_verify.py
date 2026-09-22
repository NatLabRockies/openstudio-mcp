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

When the portal is unreachable (connection error, timeout, or 5xx) the
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

import hashlib
import os
import time
from typing import Any

import httpx
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 3.0
DEFAULT_CACHE_TTL = 30.0
DEFAULT_CACHE_MAX_SIZE = 1024

# Monotonic clock, indirected so tests can advance it without touching the
# global ``time`` module (asyncio's event loop uses time.monotonic too).
_now = time.monotonic


def _cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _json_object(response: httpx.Response) -> dict[str, Any]:
    """The response body as a dict, or {} if it is not a JSON object."""
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class RevocationAwareJWTVerifier(JWTVerifier):
    """``JWTVerifier`` plus an optional revocation check against the auth portal.

    With ``verify_url`` unset this is exactly the base verifier. See the module
    docstring for the ordering, fail-open/fail-closed, and caching contracts.
    """

    def __init__(
        self,
        *args: Any,
        verify_url: str | None = None,
        fail_open: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        cache_max_size: int = DEFAULT_CACHE_MAX_SIZE,
        http_client: httpx.AsyncClient | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.verify_url = verify_url or None
        self.fail_open = bool(fail_open)
        self.timeout = float(timeout)
        self.cache_ttl = float(cache_ttl)
        self.cache_max_size = max(int(cache_max_size), 1)
        self._http_client = http_client
        self._owns_client = http_client is None
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
            allowed = await self._portal_allows(token, access_token.client_id)
        except httpx.HTTPError as exc:
            if self.fail_open:
                logger.warning(
                    "verify-token endpoint unreachable (%s); accepting locally "
                    "valid token for client %s because MCP_JWT_VERIFY_FAIL_OPEN=true",
                    exc, access_token.client_id,
                )
                return access_token
            logger.warning(
                "verify-token endpoint unreachable (%s); rejecting request for "
                "client %s (fail-closed; set MCP_JWT_VERIFY_FAIL_OPEN=true to "
                "accept locally valid tokens during a portal outage)",
                exc, access_token.client_id,
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
        """
        response = await self._client().post(
            self.verify_url, headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code >= 500:
            raise httpx.HTTPStatusError(
                f"verify-token returned HTTP {response.status_code}",
                request=response.request, response=response,
            )
        body = _json_object(response)
        if response.status_code == 200 and body.get("valid") is True:
            return True
        reason = body.get("reason") or f"HTTP {response.status_code}"
        if response.status_code in (404, 405):
            reason += " (check MCP_JWT_VERIFY_URL)"
        logger.warning("verify-token rejected token for client %s: %s", client_id, reason)
        return False

    # --- http client -------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        """One shared client (keep-alive) created lazily inside the event loop."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)
        return self._http_client

    async def aclose(self) -> None:
        """Close the client this verifier created; an injected client is the caller's."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

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
    if value < 0 or (value == 0 and not allow_zero):
        bound = ">= 0" if allow_zero else "> 0"
        raise ValueError(f"{name} must be {bound}, got {raw!r}")
    return value


def build_verifier_kwargs_from_env() -> dict[str, Any]:
    """Read ``MCP_JWT_VERIFY_*`` into ``RevocationAwareJWTVerifier`` kwargs.

    Raises ``ValueError`` with the offending variable's name so a bad value
    fails server startup with a clear message instead of a traceback later.
    """
    verify_url = os.environ.get("MCP_JWT_VERIFY_URL", "").strip() or None
    if verify_url is not None and not verify_url.startswith(("http://", "https://")):
        raise ValueError(f"MCP_JWT_VERIFY_URL must be an http(s) URL, got {verify_url!r}")
    return {
        "verify_url": verify_url,
        "fail_open": _env_flag("MCP_JWT_VERIFY_FAIL_OPEN"),
        "timeout": _env_number("MCP_JWT_VERIFY_TIMEOUT", DEFAULT_TIMEOUT, allow_zero=False),
        "cache_ttl": _env_number("MCP_JWT_VERIFY_CACHE_TTL", DEFAULT_CACHE_TTL, allow_zero=True),
    }
