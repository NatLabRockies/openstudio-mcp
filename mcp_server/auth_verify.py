"""Revocation-aware JWT verification against the auth portal.

Wraps FastMCP's stateless ``JWTVerifier`` (signature/issuer/audience/expiry
checked purely against the published JWKS) with an *optional* extra hop to
the auth portal's ``/.well-known/verify-token`` endpoint. That endpoint does
everything the JWKS path does PLUS:

  - rejects tokens the portal admin has revoked before natural expiry
  - records usage_count / last_usage_at for the token's ``jti``, which
    populates the portal's /admin dashboard

This is opt-in via ``MCP_JWT_VERIFY_URL`` — when unset, verification is
exactly the original JWKS-only ``JWTVerifier`` behavior (fully backward
compatible).

Fail-safe behavior when the portal itself is unreachable (network error,
timeout, or 5xx) is controlled by ``MCP_JWT_VERIFY_FAIL_OPEN``:
  - fail-closed (default): reject the request. Prefer this — it's the only
    setting that never lets the server accept a revoked token because a
    single admin-facing service happened to be down.
  - fail-open (opt-in): fall back to local JWKS-only validation and log a
    warning. Revocation is not enforced during the outage, but the server
    stays available. Choose this only if availability matters more than
    "revoke this token now" for your deployment.

A definitive answer from the portal (200 valid/invalid, or 401 "revoked" /
"invalid token") is never treated as "unreachable" — those always reject
the request, regardless of the fail-open/fail-closed setting.

An optional short-lived in-memory cache (keyed by the token's ``jti``) can
avoid a network round trip on every single tool call. The trade-off: a
revoked token remains usable for up to the cache TTL after being revoked.
Keep the TTL short (default 30s) or set it to 0 to disable caching entirely
and always hit the portal.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


def _extract_scopes(claims: dict[str, Any]) -> list[str]:
    for claim in ("scope", "scp"):
        if claim in claims:
            value = claims[claim]
            if isinstance(value, str):
                return value.split()
            if isinstance(value, list):
                return value
    return []


def _access_token_from_claims(token: str, claims: dict[str, Any]) -> AccessToken:
    client_id = claims.get("client_id") or claims.get("azp") or claims.get("sub") or "unknown"
    exp = claims.get("exp")
    return AccessToken(
        token=token,
        client_id=str(client_id),
        scopes=_extract_scopes(claims),
        expires_at=int(exp) if exp is not None else None,
        subject=claims.get("sub"),
        claims=claims,
    )


def _with_subject_from_claims(access_token: AccessToken | None) -> AccessToken | None:
    """Backfill ``subject`` from the ``sub`` claim when the base verifier left it unset.

    The base ``JWTVerifier`` (JWKS-only path) populates ``client_id`` but not
    ``subject``. Callers of this verifier (portal path included) expect
    ``subject`` to reflect the token's ``sub`` claim, so normalize it here for
    any JWKS-only result (backward-compat / fail-open fallback paths).
    """
    if access_token is None or access_token.subject is not None:
        return access_token
    subject = access_token.claims.get("sub")
    if subject is None:
        return access_token
    return access_token.model_copy(update={"subject": str(subject)})


class RevocationAwareJWTVerifier(JWTVerifier):
    """JWTVerifier that additionally checks token revocation via the auth portal.

    Backward compatible: with ``verify_url`` unset, this behaves exactly like
    the base ``JWTVerifier`` (JWKS-only, stateless). See module docstring for
    the fail-open/fail-closed and caching trade-offs.
    """

    def __init__(
        self,
        *args: Any,
        verify_url: str | None = None,
        fail_open: bool = False,
        timeout: float = 3.0,
        cache_ttl: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.verify_url = verify_url or None
        self.fail_open = fail_open
        self.timeout = timeout
        self.cache_ttl = max(cache_ttl, 0.0)
        self._verify_http_client = http_client
        # jti -> (AccessToken, expiry_monotonic_seconds)
        self._cache: dict[str, tuple[AccessToken, float]] = {}

    def _cache_get(self, jti: str | None) -> AccessToken | None:
        if not jti or self.cache_ttl <= 0:
            return None
        entry = self._cache.get(jti)
        if entry is None:
            return None
        access_token, expires_at = entry
        if time.monotonic() >= expires_at:
            self._cache.pop(jti, None)
            return None
        return access_token

    def _cache_put(self, jti: str | None, access_token: AccessToken) -> None:
        if not jti or self.cache_ttl <= 0:
            return
        self._cache[jti] = (access_token, time.monotonic() + self.cache_ttl)

    async def _call_verify_token(self, token: str) -> AccessToken | None:
        """Call the portal's verify-token endpoint.

        Returns the resulting AccessToken on a definitive "valid" response.
        Returns None on a definitive "invalid/revoked" response (401/400).
        Raises httpx.HTTPError (or similar) when the portal is unreachable
        (network error, timeout, 5xx) so the caller can apply the
        fail-open/fail-closed policy.
        """
        client = self._verify_http_client or httpx.AsyncClient(timeout=self.timeout)
        owns_client = self._verify_http_client is None
        try:
            response = await client.post(
                self.verify_url,
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code >= 500:
            # Treat as "unreachable" — the portal is documented to return
            # {"valid": false, "reason": "Internal error"} here, but this
            # class of failure could be transient, so it goes through the
            # fail-open/fail-closed policy rather than an unconditional reject.
            raise httpx.HTTPStatusError(
                f"verify-token returned {response.status_code}",
                request=response.request,
                response=response,
            )

        try:
            body = response.json()
        except ValueError:
            body = {}

        if response.status_code == 200 and body.get("valid") is True:
            claims = body.get("claims") or {}
            return _access_token_from_claims(token, claims)

        reason = body.get("reason", f"HTTP {response.status_code}")
        logger.warning("verify-token rejected token: %s", reason)
        return None

    async def verify_token(self, token: str) -> AccessToken | None:
        if not self.verify_url:
            return _with_subject_from_claims(await super().verify_token(token))

        # Cheap local peek at the jti for cache lookup only; the claims are
        # NOT trusted for authorization until the portal (or JWKS fallback)
        # has verified the signature.
        cached_jti = self._peek_jti(token)
        cached = self._cache_get(cached_jti)
        if cached is not None:
            return cached

        try:
            access_token = await self._call_verify_token(token)
        except httpx.HTTPError as e:
            if self.fail_open:
                logger.warning(
                    "verify-token endpoint unreachable (%s); falling back to "
                    "JWKS-only validation because MCP_JWT_VERIFY_FAIL_OPEN=true",
                    e,
                )
                return _with_subject_from_claims(await super().verify_token(token))
            logger.warning(
                "verify-token endpoint unreachable (%s); rejecting request "
                "(fail-closed default; set MCP_JWT_VERIFY_FAIL_OPEN=true to "
                "fall back to JWKS-only validation instead)",
                e,
            )
            return None

        if access_token is not None:
            jti = access_token.claims.get("jti")
            self._cache_put(jti, access_token)
        return access_token

    def _peek_jti(self, token: str) -> str | None:
        """Best-effort, unverified peek at the `jti` claim for cache lookups only."""
        try:
            import base64
            import json as _json

            parts = token.split(".")
            if len(parts) < 2:
                return None
            padded = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = _json.loads(base64.urlsafe_b64decode(padded))
            jti = payload.get("jti")
            return str(jti) if jti is not None else None
        except Exception:
            return None


def build_verifier_kwargs_from_env() -> dict[str, Any]:
    """Read MCP_JWT_VERIFY_* env vars into RevocationAwareJWTVerifier kwargs."""
    verify_url = os.environ.get("MCP_JWT_VERIFY_URL") or None
    fail_open = os.environ.get("MCP_JWT_VERIFY_FAIL_OPEN", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    timeout = float(os.environ.get("MCP_JWT_VERIFY_TIMEOUT", "3.0") or 3.0)
    cache_ttl = float(os.environ.get("MCP_JWT_VERIFY_CACHE_TTL", "30") or 30)
    return {
        "verify_url": verify_url,
        "fail_open": fail_open,
        "timeout": timeout,
        "cache_ttl": cache_ttl,
    }
