"""Token auth over HTTP.

MCP_AUTH=token must reject missing/invalid bearer tokens and accept valid ones.
The authenticated principal (client_id) also scopes the caller's run dir.
"""
import asyncio
import uuid

import pytest
from conftest import http_server, http_session, integration_enabled, unwrap


def _uniq(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:8]}"


@pytest.mark.integration
def test_http_token_auth_accepts_valid_rejects_invalid():
    # Validates: token auth rejects missing/invalid bearer tokens, accepts valid
    # ones, and the authenticated principal (client_id) scopes the run dir.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    tokens = '{"good-secret-abc": "alice"}'
    with http_server({"MCP_AUTH": "token", "MCP_TOKENS": tokens}) as (url, _proc):
        async def _run():
            # Valid token works, and the principal "alice" scopes the run dir.
            async with http_session(url, token="good-secret-abc") as s:  # noqa: S106 - test token
                res = unwrap(await s.call_tool("create_example_osm", {"name": _uniq("authok")}))
                assert res["ok"] is True, res
                assert "/alice/" in res["out_dir"], \
                    f"run dir must be scoped to the authenticated principal: {res['out_dir']}"

            # Missing token: rejected (connection/handshake fails).
            missing_rejected = False
            try:
                async with http_session(url) as s:
                    await s.call_tool("create_example_osm", {"name": "x"})
            except Exception:
                missing_rejected = True
            assert missing_rejected, "connection without a token must be rejected"

            # Invalid token: rejected.
            bad_rejected = False
            try:
                async with http_session(url, token="wrong-token") as s:  # noqa: S106 - test token
                    await s.call_tool("create_example_osm", {"name": "x"})
            except Exception:
                bad_rejected = True
            assert bad_rejected, "connection with an invalid token must be rejected"

        asyncio.run(_run())


@pytest.mark.integration
def test_http_jwt_auth_accepts_signed_rejects_unsigned():
    # Validates: MCP_AUTH=jwt accepts a token signed by the configured public key
    # (issuer/audience enforced) and rejects connections without one.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    from fastmcp.server.auth.providers.jwt import RSAKeyPair

    kp = RSAKeyPair.generate()
    issuer, audience = "https://issuer.test", "openstudio-mcp"
    good = kp.create_token(subject="carol", issuer=issuer, audience=audience)
    env = {
        "MCP_AUTH": "jwt",
        "MCP_JWT_PUBLIC_KEY": kp.public_key,
        "MCP_JWT_ISSUER": issuer,
        "MCP_JWT_AUDIENCE": audience,
    }
    with http_server(env) as (url, _proc):
        async def _run():
            # A token signed by the configured key is accepted.
            async with http_session(url, token=good) as s:
                res = unwrap(await s.call_tool("create_example_osm", {"name": _uniq("jwtok")}))
                assert res["ok"] is True, res

            # No token: rejected.
            rejected = False
            try:
                async with http_session(url) as s:
                    await s.call_tool("create_example_osm", {"name": "x"})
            except Exception:
                rejected = True
            assert rejected, "JWT mode must reject connections without a token"

        asyncio.run(_run())


# --- Self-signed JWT: restart-free user onboarding (scripts/mint_token.py) ------
# These exercise the SAME minting code an operator runs to add a user, then prove
# the server accepts tokens it never saw at startup and keeps users isolated.
import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402

# Load scripts/mint_token.py by path without mutating sys.path (no global shadowing).
_mint_spec = importlib.util.spec_from_file_location(
    "mint_token", Path(__file__).resolve().parent.parent / "scripts" / "mint_token.py",
)
mint_token = importlib.util.module_from_spec(_mint_spec)
_mint_spec.loader.exec_module(mint_token)

JWT_ISSUER = "urn:openstudio-mcp"
JWT_AUDIENCE = "openstudio-mcp"


def _jwt_env(public_pem: str) -> dict:
    return {
        "MCP_AUTH": "jwt",
        "MCP_JWT_PUBLIC_KEY": public_pem,
        "MCP_JWT_ISSUER": JWT_ISSUER,
        "MCP_JWT_AUDIENCE": JWT_AUDIENCE,
    }


def _mint(private_pem: str, user: str, **kw) -> str:
    kw.setdefault("issuer", JWT_ISSUER)
    kw.setdefault("audience", JWT_AUDIENCE)
    return mint_token.issue_token(private_pem, user, **kw)


def test_issue_token_normalizes_subject_whitespace():
    # Regression: issue_token validated subject.strip() but signed the UNstripped
    # subject, so "  alice  " and "alice" minted different identities -> different
    # /runs/<user>/ dirs. The subject must be normalized before signing. Unit-level
    # (no server, no openstudio import): mint and decode without verifying.
    import jwt as pyjwt

    private_pem, _ = mint_token.generate_keypair()
    token = mint_token.issue_token(private_pem, "  alice  ", issuer=JWT_ISSUER, audience=JWT_AUDIENCE)
    claims = pyjwt.decode(token, options={"verify_signature": False, "verify_aud": False})
    assert claims["sub"] == "alice", f"subject must be stripped before signing: {claims!r}"


@pytest.mark.integration
def test_jwt_add_user_after_startup_needs_no_restart_and_scopes_run_dir():
    # Validates: the headline property. The server boots holding only the public
    # key (no roster). A token minted AFTER startup for a never-seen subject is
    # accepted with no restart, and the subject (sub claim) scopes its run dir.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    private_pem, public_pem = mint_token.generate_keypair()
    with http_server(_jwt_env(public_pem)) as (url, _proc):
        async def _run():
            # First user.
            tok_a = _mint(private_pem, "alice_jwt")
            async with http_session(url, token=tok_a) as s:
                res = unwrap(await s.call_tool("create_example_osm", {"name": _uniq("jwtA")}))
                assert res["ok"] is True, res
                assert "/alice_jwt/" in res["out_dir"], \
                    f"JWT sub must scope the run dir: {res['out_dir']}"

            # Second user minted now — server is NOT restarted between the two.
            tok_b = _mint(private_pem, "bob_jwt")
            async with http_session(url, token=tok_b) as s:
                res = unwrap(await s.call_tool("create_example_osm", {"name": _uniq("jwtB")}))
                assert res["ok"] is True, res
                assert "/bob_jwt/" in res["out_dir"], \
                    f"a user added after startup must get its own scoped dir: {res['out_dir']}"

        asyncio.run(_run())


@pytest.mark.integration
def test_jwt_users_cannot_read_each_others_files():
    # Validates: two distinct JWT subjects are isolated — one cannot load a file
    # under the other's run root (path scoping), same guarantee as token mode.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    private_pem, public_pem = mint_token.generate_keypair()
    with http_server(_jwt_env(public_pem)) as (url, _proc):
        async def _run():
            tok_a = _mint(private_pem, "alice_jwt")
            tok_b = _mint(private_pem, "bob_jwt")
            async with http_session(url, token=tok_a) as sa, http_session(url, token=tok_b) as sb:
                cr = unwrap(await sa.call_tool("create_example_osm", {"name": _uniq("ua")}))
                assert cr["ok"] is True, cr
                alice_osm = cr["osm_path"]
                assert "/alice_jwt/" in alice_osm, alice_osm

                # bob must not read a file under alice's run root.
                ld = unwrap(await sb.call_tool("load_osm_model", {"osm_path": alice_osm}))
                assert ld["ok"] is False, f"bob must not read alice's file: {ld}"
                assert "not allowed" in ld["error"].lower(), ld

        asyncio.run(_run())


@pytest.mark.integration
def test_jwt_client_id_claim_overrides_sub_identity():
    # Validates (guardrail): FastMCP resolves identity as client_id || azp || sub.
    # A token carrying azp/client_id therefore scopes the run dir to THAT claim,
    # not sub — the footgun that collapses many users onto one identity if an IdP
    # stamps a shared azp. mint_token omits these claims on purpose; this locks in
    # the precedence so a regression (or a misconfigured IdP) is caught loudly.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    private_pem, public_pem = mint_token.generate_keypair()
    now = datetime.now(UTC)
    token = pyjwt.encode(
        {
            "sub": "real_user",
            "azp": "shared_app",  # an IdP's application id, NOT the human
            "iss": JWT_ISSUER, "aud": JWT_AUDIENCE,
            "iat": now, "exp": now + timedelta(days=1),
        },
        private_pem, algorithm="RS256",
    )
    with http_server(_jwt_env(public_pem)) as (url, _proc):
        async def _run():
            async with http_session(url, token=token) as s:
                res = unwrap(await s.call_tool("create_example_osm", {"name": _uniq("azp")}))
                assert res["ok"] is True, res
                assert "/shared_app/" in res["out_dir"], \
                    f"azp/client_id must win over sub (documented footgun): {res['out_dir']}"
                assert "/real_user/" not in res["out_dir"], res["out_dir"]

        asyncio.run(_run())


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["expired", "wrong_issuer", "wrong_audience"])
def test_jwt_rejects_bad_tokens(kind):
    # Validates: signature is necessary but not sufficient — expired tokens and
    # tokens with the wrong issuer/audience are rejected even though they are
    # signed by the configured key.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    private_pem, public_pem = mint_token.generate_keypair()
    if kind == "expired":
        bad = _mint(private_pem, "alice_jwt", days=-1)
    elif kind == "wrong_issuer":
        bad = _mint(private_pem, "alice_jwt", issuer="urn:evil")
    else:
        bad = _mint(private_pem, "alice_jwt", audience="not-this-server")

    with http_server(_jwt_env(public_pem)) as (url, _proc):
        async def _run():
            rejected = False
            try:
                async with http_session(url, token=bad) as s:
                    await s.call_tool("create_example_osm", {"name": "x"})
            except Exception:
                rejected = True
            assert rejected, f"{kind} token must be rejected by the server"

        asyncio.run(_run())


@pytest.mark.integration
@pytest.mark.parametrize("bad_tokens", ["not-json", "[1, 2, 3]"])
def test_invalid_mcp_tokens_fails_fast_with_clear_error(bad_tokens):
    # Regression: invalid MCP_TOKENS crashed startup with a cryptic JSONDecodeError /
    # AttributeError. With MCP_AUTH=token (the HTTP default), it must fail fast with
    # an actionable message naming MCP_TOKENS.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with pytest.raises(RuntimeError) as exc:  # http_server raises if the server exits at startup
        with http_server({"MCP_AUTH": "token", "MCP_TOKENS": bad_tokens}):
            pass
    assert "MCP_TOKENS must be" in str(exc.value), str(exc.value)


# --- Portal-backed revocation (MCP_JWT_VERIFY_URL) ------------------------------
# The server keeps its local JWKS check and additionally asks the auth portal's
# verify-token endpoint. A tiny in-process HTTP server plays the portal; the MCP
# server is a subprocess on the same host, so 127.0.0.1 is reachable from it.
import json  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

import httpx  # noqa: E402
from conftest import _free_port  # noqa: E402


class _FakePortal:
    """Stand-in for openstudio-mcp-auth's POST /.well-known/verify-token."""

    def __init__(self):
        self.calls: list[str] = []
        self.revoked: set[str] = set()
        portal = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):  # keep pytest output clean
                pass

            def do_POST(self):
                token = self.headers.get("Authorization", "")[len("Bearer "):]
                portal.calls.append(token)
                if token in portal.revoked:
                    status, body = 401, {"valid": False, "reason": "Token has been revoked"}
                else:
                    status, body = 200, {"valid": True, "claims": {}}
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/.well-known/verify-token"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


async def _tool_call_rejected(url: str, token: str) -> bool:
    try:
        async with http_session(url, token=token) as s:
            await s.call_tool("create_example_osm", {"name": _uniq("rv_probe")})
    except Exception:
        return True
    return False


def _raw_status(url: str, token: str) -> int:
    """HTTP status of a bare MCP initialize POST with this bearer token (401 = rejected)."""
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "auth-probe", "version": "0"}},
    }
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    return httpx.post(url, json=body, headers=headers, timeout=15).status_code


@pytest.mark.integration
def test_jwt_portal_revocation_end_to_end():
    # Validates: with MCP_JWT_VERIFY_URL set (cache off) a locally valid token is accepted only
    # while the portal says so — revoking it rejects the very next request, including on the
    # already-open connection; identity (run-dir scope) still comes from the token's sub; and
    # a token that fails the local signature check never reaches the portal.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    private_pem, public_pem = mint_token.generate_keypair()
    portal = _FakePortal()
    env = {**_jwt_env(public_pem), "MCP_JWT_VERIFY_URL": portal.url, "MCP_JWT_VERIFY_CACHE_TTL": "0"}
    try:
        with http_server(env) as (url, _proc):
            async def _run():
                tok = _mint(private_pem, "alice_rv")
                assert _raw_status(url, tok) != 401, "valid token must be accepted before revocation"
                before: dict = {}
                completed_after_revoke = False
                try:
                    async with http_session(url, token=tok) as s:
                        before["res"] = unwrap(await s.call_tool("create_example_osm", {"name": _uniq("rvA")}))
                        before["portal_calls"] = portal.calls.count(tok)

                        # Revoke mid-session: the next request on the SAME connection gets a
                        # 401, which the streamable-HTTP client raises out of the session
                        # context as an ExceptionGroup (after cancelling the in-flight call).
                        portal.revoked.add(tok)
                        await s.call_tool("create_example_osm", {"name": _uniq("rvB")})
                        completed_after_revoke = True
                except Exception:
                    pass
                assert "res" in before, "first tool call must succeed before revocation"
                assert before["res"]["ok"] is True, before["res"]
                assert "/alice_rv/" in before["res"]["out_dir"], \
                    f"identity must come from the token's sub, not the portal: {before['res']['out_dir']}"
                assert before["portal_calls"] >= 1, "portal must be consulted for a valid token"
                assert completed_after_revoke is False, \
                    "a revoked token must be rejected on its next request, even on an open session"
                assert _raw_status(url, tok) == 401, "server must answer 401 for a revoked token"

                # A fresh connection with the revoked token is rejected too.
                assert await _tool_call_rejected(url, tok), "revoked token must not open a new session"

                # Signed with the wrong key: rejected locally, never forwarded to the portal.
                other_private, _ = mint_token.generate_keypair()
                bad = _mint(other_private, "mallory_rv")
                assert await _tool_call_rejected(url, bad), "wrong-key token must be rejected"
                assert _raw_status(url, bad) == 401, "server must answer 401 for a wrong-key token"
                assert bad not in portal.calls, "locally invalid tokens must not reach the portal"

            asyncio.run(_run())
    finally:
        portal.close()


@pytest.mark.integration
@pytest.mark.parametrize("fail_open", ["false", "true"])
def test_jwt_portal_unreachable_applies_fail_policy(fail_open):
    # Validates: when the verify-token URL is unreachable the default (fail-closed) rejects a
    # locally valid token and MCP_JWT_VERIFY_FAIL_OPEN=true accepts it (JWKS-only fallback).
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    private_pem, public_pem = mint_token.generate_keypair()
    dead_url = f"http://127.0.0.1:{_free_port()}/.well-known/verify-token"
    env = {
        **_jwt_env(public_pem),
        "MCP_JWT_VERIFY_URL": dead_url,
        "MCP_JWT_VERIFY_FAIL_OPEN": fail_open,
        "MCP_JWT_VERIFY_CACHE_TTL": "0",
    }
    with http_server(env) as (url, _proc):
        tok = _mint(private_pem, "dana_rv")
        rejected = asyncio.run(_tool_call_rejected(url, tok))

    if fail_open == "true":
        assert rejected is False, "fail-open must accept a locally valid token during a portal outage"
    else:
        assert rejected is True, "fail-closed (default) must reject when the portal is unreachable"


@pytest.mark.integration
def test_build_auth_wires_portal_verifier_from_env(monkeypatch):
    # Validates: MCP_AUTH=jwt builds a RevocationAwareJWTVerifier carrying every MCP_JWT_VERIFY_*
    # setting plus the JWT issuer/audience, and a bad value fails startup naming the variable.
    # (Integration tier only because importing mcp_server.server loads openstudio.)
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    from mcp_server.auth_verify import RevocationAwareJWTVerifier
    from mcp_server.server import _build_auth

    _, public_pem = mint_token.generate_keypair()
    for name, value in _jwt_env(public_pem).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("MCP_JWT_VERIFY_URL", "https://portal.test/.well-known/verify-token")
    monkeypatch.setenv("MCP_JWT_VERIFY_FAIL_OPEN", "true")
    monkeypatch.setenv("MCP_JWT_VERIFY_TIMEOUT", "1.5")
    monkeypatch.setenv("MCP_JWT_VERIFY_CACHE_TTL", "5")

    verifier = _build_auth()

    assert isinstance(verifier, RevocationAwareJWTVerifier)
    assert verifier.verify_url == "https://portal.test/.well-known/verify-token"
    assert verifier.fail_open is True
    assert verifier.timeout == pytest.approx(1.5)
    assert verifier.cache_ttl == pytest.approx(5.0)
    assert verifier.issuer == JWT_ISSUER
    assert verifier.audience == JWT_AUDIENCE

    monkeypatch.setenv("MCP_JWT_VERIFY_TIMEOUT", "fast")
    with pytest.raises(ValueError, match="MCP_JWT_VERIFY_TIMEOUT"):
        _build_auth()
