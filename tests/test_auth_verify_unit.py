"""Unit tests for RevocationAwareJWTVerifier (mcp_server/auth_verify.py).

No server, no openstudio, no network. Every token is RS256-signed with a
throwaway key so the local JWKS step runs for real; the portal's verify-token
endpoint is an httpx.MockTransport handler that scripts revocations, outages
and malformed replies.
"""
from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest
from fastmcp.server.auth.providers.jwt import RSAKeyPair

from mcp_server import auth_verify
from mcp_server.auth_verify import RevocationAwareJWTVerifier

pytestmark = pytest.mark.unit

ISSUER = "https://issuer.test"
AUDIENCE = "openstudio-mcp"
VERIFY_URL = "https://portal.test/.well-known/verify-token"


class FakePortal:
    """Scripted stand-in for the auth portal's POST /.well-known/verify-token.

    Records every bearer token it is asked about. Default answer: 200 valid,
    or 401 revoked for tokens in ``revoked``. ``reply`` overrides the answer:
    an ``httpx.Response`` to return, or an ``httpx`` exception class to raise
    as a transport failure.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.revoked: set[str] = set()
        self.reply: httpx.Response | type[Exception] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("authorization", "")[len("Bearer "):]
        self.calls.append(token)
        if isinstance(self.reply, type) and issubclass(self.reply, Exception):
            raise self.reply("simulated portal failure", request=request)
        if self.reply is not None:
            return self.reply
        if token in self.revoked:
            return httpx.Response(401, json={"valid": False, "reason": "Token has been revoked"})
        return httpx.Response(200, json={"valid": True, "claims": {"sub": "alice"}})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def _verifier(kp: RSAKeyPair, portal: FakePortal, **kwargs) -> RevocationAwareJWTVerifier:
    return RevocationAwareJWTVerifier(
        public_key=kp.public_key, issuer=ISSUER, audience=AUDIENCE,
        verify_url=VERIFY_URL, http_client=portal.client(), **kwargs,
    )


def _token(kp: RSAKeyPair, subject: str = "alice", **kwargs) -> str:
    kwargs.setdefault("issuer", ISSUER)
    kwargs.setdefault("audience", AUDIENCE)
    return kp.create_token(subject=subject, **kwargs)


def _unsigned(payload: dict) -> str:
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(payload)}.notasignature"


# --- construction ---------------------------------------------------------------

@pytest.mark.parametrize(("kwarg", "value"), [
    ("cache_ttl", float("nan")), ("cache_ttl", float("inf")), ("cache_ttl", -1),
    ("timeout", float("nan")), ("timeout", float("inf")), ("timeout", 0),
])
def test_constructor_rejects_non_finite_or_out_of_range_numbers(kwarg, value):
    # Regression: Copilot review of PR #163 — a nan or inf cache_ttl produces an expiry that
    # never elapses, so a cached "valid" answer would outlive any revocation; an inf timeout
    # would let a hung portal block requests forever. Reject at construction, not on first use.
    kp = RSAKeyPair.generate()
    with pytest.raises(ValueError, match=kwarg):
        RevocationAwareJWTVerifier(
            public_key=kp.public_key, issuer=ISSUER, audience=AUDIENCE,
            verify_url=VERIFY_URL, **{kwarg: value},
        )


# --- gate ordering ------------------------------------------------------------

def test_valid_token_passes_local_check_then_portal():
    # Validates: happy path — locally valid + portal "valid" yields an AccessToken whose
    # client_id is the token's sub (that is what scopes /runs/<user>/), and the portal saw
    # the token exactly once.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    token = _token(kp)

    result = asyncio.run(_verifier(kp, portal).verify_token(token))

    assert result is not None
    assert result.client_id == "alice"
    assert result.claims["iss"] == ISSUER
    assert portal.calls == [token]


def test_revoked_token_rejected_with_no_fallback():
    # Validates: a definitive 401 {"valid": false, "reason": "Token has been revoked"}
    # rejects the request even though the token is locally valid; there is no
    # JWKS-only fallback for a definitive answer.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    token = _token(kp)
    portal.revoked.add(token)

    result = asyncio.run(_verifier(kp, portal).verify_token(token))

    assert result is None
    assert portal.calls == [token]


@pytest.mark.parametrize("kind", ["wrong_key", "wrong_audience", "wrong_issuer", "expired", "unsigned"])
def test_locally_invalid_token_never_reaches_portal(kind):
    # Validates: the local signature/issuer/audience/expiry check runs FIRST. A token that
    # fails it is rejected without a portal call, so the server's own policy stays enforced
    # and unauthenticated callers cannot drive portal traffic or usage counters.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    if kind == "wrong_key":
        token = _token(RSAKeyPair.generate())
    elif kind == "wrong_audience":
        token = _token(kp, audience="other-service")
    elif kind == "wrong_issuer":
        token = _token(kp, issuer="https://someone-else")
    elif kind == "expired":
        token = _token(kp, expires_in_seconds=-60)
    else:
        token = _unsigned({"sub": "alice", "iss": ISSUER, "aud": AUDIENCE})

    result = asyncio.run(_verifier(kp, portal).verify_token(token))

    assert result is None, f"{kind} token must be rejected locally"
    assert portal.calls == [], f"{kind} token must not be sent to the portal"


def test_verify_url_unset_is_plain_jwks_verification():
    # Validates: backward compatibility — without verify_url a locally valid token is
    # accepted and no portal is ever contacted, exactly like the base JWTVerifier.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    verifier = RevocationAwareJWTVerifier(
        public_key=kp.public_key, issuer=ISSUER, audience=AUDIENCE,
        verify_url=None, http_client=portal.client(),
    )

    result = asyncio.run(verifier.verify_token(_token(kp)))

    assert result is not None
    assert result.client_id == "alice"
    assert portal.calls == []


# --- portal answers -----------------------------------------------------------

@pytest.mark.parametrize("fail_open", [False, True])
@pytest.mark.parametrize("failure", ["connect_error", "timeout", "http_500", "http_503"])
def test_unreachable_portal_applies_fail_policy(failure, fail_open):
    # Validates: transport errors, timeouts and 5xx all mean "portal unreachable":
    # fail-closed (default) rejects a locally valid token, fail-open accepts it.
    # Neither is treated as a definitive verdict on the token.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    token = _token(kp)
    portal.reply = {
        "connect_error": httpx.ConnectError,
        "timeout": httpx.ReadTimeout,
        "http_500": httpx.Response(500, json={"valid": False, "reason": "Internal error"}),
        "http_503": httpx.Response(503, text="upstream down"),
    }[failure]

    result = asyncio.run(_verifier(kp, portal, fail_open=fail_open).verify_token(token))

    if fail_open:
        assert result is not None and result.client_id == "alice", "fail-open must accept"
    else:
        assert result is None, "fail-closed must reject"
    assert portal.calls == [token]


@pytest.mark.parametrize("reply", [
    pytest.param(httpx.Response(200, text="<html>login</html>"), id="html_body"),
    pytest.param(httpx.Response(200, json=["valid"]), id="json_array"),
    pytest.param(httpx.Response(200, json={"claims": {"sub": "alice"}}), id="missing_valid_flag"),
    pytest.param(httpx.Response(200, json={"valid": "true"}), id="valid_not_bool"),
    pytest.param(httpx.Response(404, text="not found"), id="wrong_url_404"),
    pytest.param(httpx.Response(400, json={"valid": False, "reason": "Missing header"}), id="portal_400"),
])
def test_non_valid_portal_answer_rejects_without_raising(reply):
    # Validates: anything short of 200 {"valid": true} is a definitive reject: None, never an
    # exception out of verify_token, and never a fail-open fallback (2xx/4xx are answers, not outages).
    kp, portal = RSAKeyPair.generate(), FakePortal()
    portal.reply = reply

    result = asyncio.run(_verifier(kp, portal, fail_open=True).verify_token(_token(kp)))

    assert result is None


# --- cache ----------------------------------------------------------------------

def test_cache_skips_portal_within_ttl():
    # Validates: with a TTL, repeated requests with the same token consult the portal once.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    token = _token(kp)
    verifier = _verifier(kp, portal, cache_ttl=30)

    async def _run():
        for _ in range(3):
            assert (await verifier.verify_token(token)) is not None

    asyncio.run(_run())
    assert portal.calls == [token]


def test_cache_disabled_calls_portal_every_request():
    # Validates: cache_ttl=0 (MCP_JWT_VERIFY_CACHE_TTL=0) makes revocation immediate by
    # consulting the portal on every request.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    token = _token(kp)
    verifier = _verifier(kp, portal, cache_ttl=0)

    async def _run():
        for _ in range(3):
            assert (await verifier.verify_token(token)) is not None

    asyncio.run(_run())
    assert portal.calls == [token, token, token]


def test_cache_entry_expires_after_ttl(monkeypatch):
    # Validates: once the TTL elapses the next request re-checks with the portal.
    clock = [1000.0]
    monkeypatch.setattr(auth_verify, "_now", lambda: clock[0])
    kp, portal = RSAKeyPair.generate(), FakePortal()
    token = _token(kp)
    verifier = _verifier(kp, portal, cache_ttl=30)

    async def _run():
        await verifier.verify_token(token)
        clock[0] += 29
        await verifier.verify_token(token)  # still cached
        clock[0] += 2
        await verifier.verify_token(token)  # expired -> portal again

    asyncio.run(_run())
    assert portal.calls == [token, token]


def test_revocation_takes_effect_within_one_ttl(monkeypatch):
    # Validates: the documented trade-off — a token revoked while cached stays usable until
    # the TTL lapses, then the next request hits the portal and is rejected.
    clock = [1000.0]
    monkeypatch.setattr(auth_verify, "_now", lambda: clock[0])
    kp, portal = RSAKeyPair.generate(), FakePortal()
    token = _token(kp)
    verifier = _verifier(kp, portal, cache_ttl=30)

    async def _run():
        assert (await verifier.verify_token(token)) is not None
        portal.revoked.add(token)
        clock[0] += 10
        assert (await verifier.verify_token(token)) is not None, "cached answer still honored"
        clock[0] += 25
        assert (await verifier.verify_token(token)) is None, "rejected once the cache lapses"

    asyncio.run(_run())
    assert portal.calls == [token, token]


def test_cache_hit_is_bound_to_exact_token_bytes():
    # Regression: PR #162's first cut keyed the cache on the UNVERIFIED jti, so an unsigned
    # token carrying a cached jti was handed the cached user's identity. The key is now
    # sha256(token) and the local check runs first, so neither a forged token nor a
    # different valid token sharing the jti can reuse another token's cached answer.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    verifier = _verifier(kp, portal, cache_ttl=30)
    real = _token(kp, additional_claims={"jti": "shared-jti"})
    forged = _unsigned({"sub": "mallory", "jti": "shared-jti", "iss": ISSUER, "aud": AUDIENCE})
    twin = _token(kp, additional_claims={"jti": "shared-jti", "n": 2})

    async def _run():
        assert (await verifier.verify_token(real)).client_id == "alice"
        assert (await verifier.verify_token(forged)) is None, "forged token must not hit the cache"
        assert (await verifier.verify_token(twin)) is not None

    asyncio.run(_run())
    assert portal.calls == [real, twin], "each distinct token needs its own portal answer"


def test_cache_is_bounded_and_evicts_oldest():
    # Validates: the cache never grows past cache_max_size and drops the oldest entry, so a
    # long-running server seeing many distinct tokens has bounded memory.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    verifier = _verifier(kp, portal, cache_ttl=30, cache_max_size=2)
    t1, t2, t3 = (_token(kp, additional_claims={"n": i}) for i in range(3))

    async def _run():
        for t in (t1, t2, t3):
            await verifier.verify_token(t)
        assert len(verifier._cache) == 2
        await verifier.verify_token(t3)  # newest: served from cache
        await verifier.verify_token(t1)  # oldest was evicted: portal again

    asyncio.run(_run())
    assert portal.calls == [t1, t2, t3, t1]


def test_cache_purges_expired_entries_before_evicting(monkeypatch):
    # Validates: at capacity, expired entries are dropped before any live entry is evicted.
    clock = [1000.0]
    monkeypatch.setattr(auth_verify, "_now", lambda: clock[0])
    kp, portal = RSAKeyPair.generate(), FakePortal()
    verifier = _verifier(kp, portal, cache_ttl=30, cache_max_size=2)
    t1, t2, t3 = (_token(kp, additional_claims={"n": i}) for i in range(3))

    async def _run():
        await verifier.verify_token(t1)
        await verifier.verify_token(t2)
        clock[0] += 31
        await verifier.verify_token(t3)

    asyncio.run(_run())
    assert set(verifier._cache) == {auth_verify._cache_key(t3)}


# --- http client lifecycle -------------------------------------------------------

def test_production_path_creates_one_shared_client(monkeypatch):
    # Validates: with no injected client (the server.py path) the verifier builds ONE
    # httpx.AsyncClient with the configured timeout and reuses it for every request
    # (keep-alive), rather than a new client and TLS handshake per request.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    token = _token(kp)
    timeouts: list = []

    class Counting(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            timeouts.append(kwargs.get("timeout"))
            kwargs["transport"] = httpx.MockTransport(portal.handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(auth_verify.httpx, "AsyncClient", Counting)
    verifier = RevocationAwareJWTVerifier(
        public_key=kp.public_key, issuer=ISSUER, audience=AUDIENCE,
        verify_url=VERIFY_URL, timeout=7.5, cache_ttl=0,
    )

    async def _run():
        for _ in range(3):
            assert (await verifier.verify_token(token)) is not None
        await verifier.aclose()

    asyncio.run(_run())
    assert timeouts == [7.5], f"expected one client built with timeout=7.5, got {timeouts}"
    assert portal.calls == [token, token, token]
    assert verifier._http_client is None, "aclose() must release the owned client"


def test_aclose_leaves_injected_client_open():
    # Validates: an injected http_client belongs to the caller; aclose() must not close it.
    kp, portal = RSAKeyPair.generate(), FakePortal()
    client = portal.client()
    verifier = RevocationAwareJWTVerifier(
        public_key=kp.public_key, issuer=ISSUER, audience=AUDIENCE,
        verify_url=VERIFY_URL, http_client=client,
    )

    asyncio.run(verifier.aclose())

    assert client.is_closed is False
