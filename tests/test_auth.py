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
