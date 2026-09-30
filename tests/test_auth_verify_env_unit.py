"""Unit tests for MCP_JWT_VERIFY_* env parsing (mcp_server/auth_verify.py).

No server, no openstudio, no network: build_verifier_kwargs_from_env() only.
"""
from __future__ import annotations

import pytest

from mcp_server.auth_verify import build_verifier_kwargs_from_env

pytestmark = pytest.mark.unit


_ENV = ("MCP_JWT_VERIFY_URL", "MCP_JWT_VERIFY_FAIL_OPEN", "MCP_JWT_VERIFY_TIMEOUT", "MCP_JWT_VERIFY_CACHE_TTL")


def _clear_env(monkeypatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def test_env_defaults(monkeypatch):
    # Validates: unset env means portal check disabled, fail-closed, 3 s timeout and 30 s
    # cache — the defaults documented in docs/remote-multi-user.md.
    _clear_env(monkeypatch)

    assert build_verifier_kwargs_from_env() == {
        "verify_url": None, "fail_open": False, "timeout": 3.0, "cache_ttl": 30.0,
    }


def test_env_overrides(monkeypatch):
    # Validates: explicit env values override every default; surrounding whitespace is tolerated.
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_JWT_VERIFY_URL", "  https://portal.test/.well-known/verify-token ")
    monkeypatch.setenv("MCP_JWT_VERIFY_FAIL_OPEN", "true")
    monkeypatch.setenv("MCP_JWT_VERIFY_TIMEOUT", "5")
    monkeypatch.setenv("MCP_JWT_VERIFY_CACHE_TTL", "0")

    assert build_verifier_kwargs_from_env() == {
        "verify_url": "https://portal.test/.well-known/verify-token",
        "fail_open": True, "timeout": 5.0, "cache_ttl": 0.0,
    }


@pytest.mark.parametrize(("raw", "expected"), [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("off", False), ("no", False), ("", False),
])
def test_env_fail_open_spellings(monkeypatch, raw, expected):
    # Validates: the documented true/false spellings for MCP_JWT_VERIFY_FAIL_OPEN, case-insensitive.
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_JWT_VERIFY_FAIL_OPEN", raw)

    assert build_verifier_kwargs_from_env()["fail_open"] is expected


@pytest.mark.parametrize(("name", "raw"), [
    ("MCP_JWT_VERIFY_TIMEOUT", "abc"),
    ("MCP_JWT_VERIFY_TIMEOUT", "0"),
    ("MCP_JWT_VERIFY_TIMEOUT", "-1"),
    ("MCP_JWT_VERIFY_CACHE_TTL", "-5"),
    ("MCP_JWT_VERIFY_CACHE_TTL", "soon"),
    ("MCP_JWT_VERIFY_URL", "portal.example.com/verify"),
    ("MCP_JWT_VERIFY_FAIL_OPEN", "maybe"),
    ("MCP_JWT_VERIFY_CACHE_TTL", "nan"),
    ("MCP_JWT_VERIFY_CACHE_TTL", "inf"),
    ("MCP_JWT_VERIFY_TIMEOUT", "nan"),
    ("MCP_JWT_VERIFY_TIMEOUT", "inf"),
    ("MCP_JWT_VERIFY_URL", "http://"),
    ("MCP_JWT_VERIFY_URL", "https:///.well-known/verify-token"),
    ("MCP_JWT_VERIFY_URL", "ftp://portal.test/.well-known/verify-token"),
])
def test_env_invalid_values_fail_fast_naming_the_variable(monkeypatch, name, raw):
    # Validates: a bad value raises ValueError naming the variable so startup fails with a
    # clear message (same contract as MCP_TOKENS) instead of a traceback on the first request.
    # nan/inf and host-less URLs are included because they pass naive `< 0` / prefix checks
    # (Copilot review of PR #163): a nan/inf TTL would cache a "valid" answer forever.
    _clear_env(monkeypatch)
    monkeypatch.setenv(name, raw)

    with pytest.raises(ValueError, match=name):
        build_verifier_kwargs_from_env()


def test_require_issuer_audience_rejects_unscoped_jwt(monkeypatch):
    # Validates: JWT mode refuses to start without issuer+audience (tokens minted for
    # other services would otherwise be accepted); MCP_JWT_ALLOW_UNSCOPED opts out.
    from mcp_server.auth_verify import require_issuer_audience

    monkeypatch.delenv("MCP_JWT_ALLOW_UNSCOPED", raising=False)
    require_issuer_audience("iss", "aud")
    for iss, aud, missing in [(None, "aud", "MCP_JWT_ISSUER"), ("iss", None, "MCP_JWT_AUDIENCE"),
                              (None, None, "MCP_JWT_ISSUER and MCP_JWT_AUDIENCE")]:
        with pytest.raises(ValueError, match=missing):
            require_issuer_audience(iss, aud)
    monkeypatch.setenv("MCP_JWT_ALLOW_UNSCOPED", "true")
    require_issuer_audience(None, None)


@pytest.mark.parametrize(("host", "warns"), [
    ("portal.internal", True), ("10.0.0.5", True),
    ("localhost:8080", False), ("127.0.0.2", False), ("[::1]", False), ("[0:0:0:0:0:0:0:1]", False),
])
def test_plain_http_verify_url_warns_off_loopback(monkeypatch, host, warns):
    # Validates: the verify URL carries the bearer token, so plain http off loopback warns.
    _clear_env(monkeypatch)
    monkeypatch.setenv("MCP_JWT_VERIFY_URL", f"http://{host}/.well-known/verify-token")
    from mcp_server import auth_verify

    seen = []
    # fastmcp's logger does not propagate to caplog; record calls directly.
    monkeypatch.setattr(auth_verify.logger, "warning", lambda msg, *a, **_: seen.append(msg % a))
    build_verifier_kwargs_from_env()
    assert any("plain http" in m for m in seen) is warns
