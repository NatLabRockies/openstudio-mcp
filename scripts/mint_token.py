#!/usr/bin/env python3
"""Mint RSA-signed JWTs for an openstudio-mcp HTTP server running ``MCP_AUTH=jwt``.

You become a tiny token issuer: generate one RSA key pair, hand the PUBLIC key
to the server (``MCP_JWT_PUBLIC_KEY``), and keep the PRIVATE key here on your
admin machine. Issue one token per user with ``issue`` — adding or rotating a
user needs NO server restart, because the server stores only the public key,
never a roster.

The token carries the username in the ``sub`` claim and nothing else that the
server treats as identity. openstudio-mcp scopes each user's run directory by
that identity (``/runs/<user>/``), so two users stay isolated. Do NOT add a
``client_id`` or ``azp`` claim: FastMCP's JWTVerifier prefers those over ``sub``,
which would collapse every user onto one identity.

Usage
-----
One-time, generate a key pair (writes private.pem + public.pem to the cwd)::

    python scripts/mint_token.py keygen

Per user (prints a ready-to-paste Authorization header)::

    python scripts/mint_token.py issue --user alice
    python scripts/mint_token.py issue --user bob --days 7

Server side (give it the PUBLIC key only)::

    MCP_AUTH=jwt
    MCP_JWT_PUBLIC_KEY="$(cat public.pem)"
    MCP_JWT_ISSUER=urn:openstudio-mcp
    MCP_JWT_AUDIENCE=openstudio-mcp

Revocation: tokens are stateless and valid until they expire. To kill ONE token
early you must either wait out its TTL or rotate the key pair (keygen again +
update the server's public key + re-issue everyone). Keep TTLs short enough that
"wait it out" is acceptable, or move to a managed IdP if you need instant revoke.
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_ISSUER = "urn:openstudio-mcp"
DEFAULT_AUDIENCE = "openstudio-mcp"
DEFAULT_DAYS = 30


def generate_keypair(key_size: int = 2048) -> tuple[str, str]:
    """Return (private_pem, public_pem) as PEM strings for an RSA key pair."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return private_pem, public_pem


def issue_token(
    private_pem: str,
    subject: str,
    *,
    issuer: str = DEFAULT_ISSUER,
    audience: str = DEFAULT_AUDIENCE,
    days: int = DEFAULT_DAYS,
    now: datetime | None = None,
) -> str:
    """Sign an RS256 JWT carrying ``sub=subject`` and an expiry ``days`` out.

    Deliberately sets only sub/iss/aud/iat/exp — no client_id/azp, so the
    server's identity (and thus the per-user run dir) resolves to ``subject``.
    """
    import jwt  # PyJWT

    if not subject or not subject.strip():
        raise ValueError("subject (username) must be a non-empty string")
    subject = subject.strip()  # normalize: " alice " and "alice" must be one identity
    issued = now or datetime.now(UTC)
    payload = {
        "sub": subject,
        "iss": issuer,
        "aud": audience,
        "iat": issued,
        "exp": issued + timedelta(days=days),
    }
    return jwt.encode(payload, private_pem, algorithm="RS256")


def _cmd_keygen(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    priv_path = out_dir / args.private_name
    pub_path = out_dir / args.public_name
    if priv_path.exists() and not args.force:
        print(
            f"refusing to overwrite existing {priv_path} (use --force to replace; "
            f"replacing the key invalidates every token already issued)",
            file=sys.stderr,
        )
        return 1
    private_pem, public_pem = generate_keypair(key_size=args.key_size)
    priv_path.write_text(private_pem, encoding="ascii")
    pub_path.write_text(public_pem, encoding="ascii")
    with contextlib.suppress(OSError):  # best effort; a no-op on Windows
        priv_path.chmod(0o600)
    print(f"wrote {priv_path}  (PRIVATE — keep secret, never commit, never bake into an image)")
    print(f"wrote {pub_path}   (PUBLIC — give to the server via MCP_JWT_PUBLIC_KEY)")
    print()
    print("Start the server with:")
    print("  MCP_AUTH=jwt \\")
    print(f'  MCP_JWT_PUBLIC_KEY="$(cat {pub_path})" \\')
    print(f"  MCP_JWT_ISSUER={DEFAULT_ISSUER} \\")
    print(f"  MCP_JWT_AUDIENCE={DEFAULT_AUDIENCE}")
    return 0


def _cmd_issue(args: argparse.Namespace) -> int:
    priv_path = Path(args.private)
    if not priv_path.exists():
        print(f"private key not found: {priv_path} (run `keygen` first?)", file=sys.stderr)
        return 1
    token = issue_token(
        priv_path.read_text(encoding="ascii"),
        args.user,
        issuer=args.issuer,
        audience=args.audience,
        days=args.days,
    )
    expires = (datetime.now(UTC) + timedelta(days=args.days)).date().isoformat()
    print(f"# user={args.user}  expires={expires}  (in {args.days} days)")
    print(f"Authorization: Bearer {token}")
    print()
    print("Put it in the user's .mcp.json header:")
    print(f'  "headers": {{ "Authorization": "Bearer {token}" }}')
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("keygen", help="generate an RSA key pair (one-time)")
    g.add_argument("--out-dir", default=".", help="directory to write the keys (default: cwd)")
    g.add_argument("--private-name", default="private.pem")
    g.add_argument("--public-name", default="public.pem")
    g.add_argument("--key-size", type=int, default=2048)
    g.add_argument("--force", action="store_true", help="overwrite an existing private key")
    g.set_defaults(func=_cmd_keygen)

    i = sub.add_parser("issue", help="mint a bearer token for a user")
    i.add_argument("--user", required=True, help="username -> token subject -> /runs/<user>/")
    i.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"TTL in days (default: {DEFAULT_DAYS})")
    i.add_argument("--private", default="private.pem", help="path to the private key")
    i.add_argument("--issuer", default=DEFAULT_ISSUER)
    i.add_argument("--audience", default=DEFAULT_AUDIENCE)
    i.set_defaults(func=_cmd_issue)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
