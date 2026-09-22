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
])
def test_env_invalid_values_fail_fast_naming_the_variable(monkeypatch, name, raw):
    # Validates: a bad value raises ValueError naming the variable so startup fails with a
    # clear message (same contract as MCP_TOKENS) instead of a traceback on the first request.
    _clear_env(monkeypatch)
    monkeypatch.setenv(name, raw)

    with pytest.raises(ValueError, match=name):
        build_verifier_kwargs_from_env()
