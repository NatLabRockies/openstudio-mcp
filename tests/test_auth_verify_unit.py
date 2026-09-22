"""Unit tests for RevocationAwareJWTVerifier (mcp_server/auth_verify.py).

No server, no openstudio, no network — the auth portal's verify-token
endpoint is simulated with an httpx MockTransport.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from mcp_server.auth_verify import RevocationAwareJWTVerifier, build_verifier_kwargs_from_env

pytestmark = pytest.mark.unit

ISSUER = "https://issuer.test"
AUDIENCE = "openstudio-mcp"


def _make_verifier(public_key: str, *, transport: httpx.MockTransport, **kwargs) -> RevocationAwareJWTVerifier:
    client = httpx.AsyncClient(transport=transport)
    return RevocationAwareJWTVerifier(
        public_key=public_key,
        issuer=ISSUER,
        audience=AUDIENCE,
        verify_url="https://portal.test/.well-known/verify-token",
        http_client=client,
        **kwargs,
    )



def test_verify_token_success_populates_claims_from_portal():
    asyncio.run(_test_verify_token_success_populates_claims_from_portal())


async def _test_verify_token_success_populates_claims_from_portal():
    # Validates: on 200 {"valid": true, "claims": {...}}, the AccessToken is
    # built from the portal's claims (the source of truth), not local JWKS decode.
    kp = RSAKeyPair.generate()
    token = kp.create_token(subject="alice", issuer=ISSUER, audience=AUDIENCE)

    portal_claims = {
        "sub": "alice", "iss": ISSUER, "aud": AUDIENCE,
        "iat": int(time.time()), "exp": int(time.time()) + 3600,
        "jti": "abc-123", "groups": ["engineers"], "role": "admin",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer " + token
        return httpx.Response(200, json={"valid": True, "claims": portal_claims})

    verifier = _make_verifier(kp.public_key, transport=httpx.MockTransport(handler))
    result = await verifier.verify_token(token)

    assert result is not None
    assert result.subject == "alice"
    assert result.claims["groups"] == ["engineers"]
    assert result.claims["role"] == "admin"
    assert result.claims["jti"] == "abc-123"



def test_verify_token_revoked_is_rejected():
    asyncio.run(_test_verify_token_revoked_is_rejected())


async def _test_verify_token_revoked_is_rejected():
    # Validates: a 401 {"valid": false, "reason": "Token has been revoked"}
    # response causes the request to be rejected outright (no JWKS fallback).
    kp = RSAKeyPair.generate()
    token = kp.create_token(subject="alice", issuer=ISSUER, audience=AUDIENCE)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"valid": False, "reason": "Token has been revoked"})

    verifier = _make_verifier(kp.public_key, transport=httpx.MockTransport(handler))
    result = await verifier.verify_token(token)

    assert result is None



def test_verify_token_unreachable_fails_closed_by_default():
    asyncio.run(_test_verify_token_unreachable_fails_closed_by_default())


async def _test_verify_token_unreachable_fails_closed_by_default():
    # Validates: default fail-closed behavior — when the portal is unreachable
    # (connection error), the request is rejected even though the token would
    # pass local JWKS validation.
    kp = RSAKeyPair.generate()
    token = kp.create_token(subject="alice", issuer=ISSUER, audience=AUDIENCE)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    verifier = _make_verifier(kp.public_key, transport=httpx.MockTransport(handler), fail_open=False)
    result = await verifier.verify_token(token)

    assert result is None



def test_verify_token_unreachable_falls_back_to_jwks_when_fail_open():
    asyncio.run(_test_verify_token_unreachable_falls_back_to_jwks_when_fail_open())


async def _test_verify_token_unreachable_falls_back_to_jwks_when_fail_open():
    # Validates: with fail_open=True, an unreachable portal falls back to
    # local JWKS-only validation, so a validly-signed token is still accepted.
    kp = RSAKeyPair.generate()
    token = kp.create_token(subject="alice", issuer=ISSUER, audience=AUDIENCE)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    verifier = _make_verifier(kp.public_key, transport=httpx.MockTransport(handler), fail_open=True)
    result = await verifier.verify_token(token)

    assert result is not None
    assert result.subject == "alice"



def test_verify_token_5xx_treated_as_unreachable():
    asyncio.run(_test_verify_token_5xx_treated_as_unreachable())


async def _test_verify_token_5xx_treated_as_unreachable():
    # Validates: a 500 from the portal (even with a JSON body, per its
    # documented "Internal error" response) is treated as "unreachable" and
    # goes through the fail-open/fail-closed policy, not an unconditional reject.
    kp = RSAKeyPair.generate()
    token = kp.create_token(subject="alice", issuer=ISSUER, audience=AUDIENCE)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"valid": False, "reason": "Internal error"})

    verifier = _make_verifier(kp.public_key, transport=httpx.MockTransport(handler), fail_open=True)
    result = await verifier.verify_token(token)

    assert result is not None, "fail-open must fall back to JWKS on 5xx"



def test_jwks_only_path_unaffected_when_verify_url_unset():
    asyncio.run(_test_jwks_only_path_unaffected_when_verify_url_unset())


async def _test_jwks_only_path_unaffected_when_verify_url_unset():
    # Validates: backward compatibility — with verify_url unset, behavior is
    # identical to the base JWTVerifier (no network call to any portal).
    kp = RSAKeyPair.generate()
    token = kp.create_token(subject="alice", issuer=ISSUER, audience=AUDIENCE)

    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"valid": True, "claims": {}})

    verifier = RevocationAwareJWTVerifier(
        public_key=kp.public_key, issuer=ISSUER, audience=AUDIENCE,
        verify_url=None, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await verifier.verify_token(token)

    assert result is not None
    assert result.subject == "alice"
    assert called is False, "verify-token endpoint must not be called when unset"



def test_verify_token_result_is_cached_within_ttl():
    asyncio.run(_test_verify_token_result_is_cached_within_ttl())


async def _test_verify_token_result_is_cached_within_ttl():
    # Validates: within the cache TTL, a second call for the same jti does not
    # hit the portal again (avoids a hard per-request network round trip).
    kp = RSAKeyPair.generate()
    token = kp.create_token(
        subject="alice", issuer=ISSUER, audience=AUDIENCE,
        additional_claims={"jti": "cache-test-jti"},
    )
    jti = "cache-test-jti"

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"valid": True, "claims": {"sub": "alice", "jti": jti}})

    verifier = _make_verifier(kp.public_key, transport=httpx.MockTransport(handler), cache_ttl=30.0)
    r1 = await verifier.verify_token(token)
    r2 = await verifier.verify_token(token)

    assert r1 is not None and r2 is not None
    assert calls == 1, "second call within TTL must be served from cache"


def test_build_verifier_kwargs_from_env_defaults(monkeypatch):
    # Validates: unset env vars produce the documented defaults (disabled,
    # fail-closed, 3s timeout, 30s cache).
    monkeypatch.delenv("MCP_JWT_VERIFY_URL", raising=False)
    monkeypatch.delenv("MCP_JWT_VERIFY_FAIL_OPEN", raising=False)
    monkeypatch.delenv("MCP_JWT_VERIFY_TIMEOUT", raising=False)
    monkeypatch.delenv("MCP_JWT_VERIFY_CACHE_TTL", raising=False)

    kwargs = build_verifier_kwargs_from_env()
    assert kwargs["verify_url"] is None
    assert kwargs["fail_open"] is False
    assert kwargs["timeout"] == 3.0
    assert kwargs["cache_ttl"] == 30.0


def test_build_verifier_kwargs_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("MCP_JWT_VERIFY_URL", "https://portal.test/.well-known/verify-token")
    monkeypatch.setenv("MCP_JWT_VERIFY_FAIL_OPEN", "true")
    monkeypatch.setenv("MCP_JWT_VERIFY_TIMEOUT", "5")
    monkeypatch.setenv("MCP_JWT_VERIFY_CACHE_TTL", "0")

    kwargs = build_verifier_kwargs_from_env()
    assert kwargs["verify_url"] == "https://portal.test/.well-known/verify-token"
    assert kwargs["fail_open"] is True
    assert kwargs["timeout"] == 5.0
    assert kwargs["cache_ttl"] == 0.0
