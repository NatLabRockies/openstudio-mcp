# Plan: MCP 2026-07-28 adoption (stateless protocol)

Tracking issue: [#111](https://github.com/NatLabRockies/openstudio-mcp/issues/111)
Status: WATCH. No migration work until trigger conditions fire. Guards landed now.

## What changed in the spec

Revision 2026-07-28 (announced 2026-07-28):

- Protocol sessions removed: no `Mcp-Session-Id`, no `initialize`/`notifications/initialized`
  handshake. Every request standalone; version + capabilities ride in `_meta`.
- Cross-call state must be "explicit, server-minted handles passed as ordinary tool
  arguments" (SEP-2567).
- New required `server/discover` RPC; `subscriptions/listen` replaces GET stream +
  `resources/subscribe`; `ping`/`logging/setLevel` removed.
- Deprecated (12-month window): MCP Sampling, Roots, Logging features. Migration =
  stderr logging (we already do this).
- Tasks moved to official extension (`io.modelcontextprotocol/tasks`, polling via
  `tasks/get`).
- Auth: aligned to production OAuth 2.0/OIDC; Dynamic Client Registration deprecated in
  favor of Client ID Metadata Documents.
- `tools/list` should be deterministic order + `ttlMs`/`cacheScope` for prompt caching.

Refs: [Claude blog](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude),
[spec changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)

## What we rely on today

| Dependency | Where | New-spec fate |
|---|---|---|
| Protocol session id keys current-model state | `identity.py::session_key()` -> `model_manager._sessions` | REMOVED. Only real exposure. |
| JWT `client_id` keys run dirs + path scope | `identity.py::user_key()` | Unaffected. Auth spec improves. |
| stdio single-user, collapses to `"local"` | `identity.py` | Unaffected. |
| stderr-only logging (stdout suppression) | `stdout_suppression.py` | Already matches spec migration advice. |
| MCP sampling/roots/logging/subscriptions | none used | No exposure. |

Impact is HTTP multi-user deployment only. stdio (primary deploy) unaffected in practice.

## Guards (verified 2026-07-29, no change needed)

Installed in test image: fastmcp 3.4.4, mcp 1.28.1. New-spec SDK is mcp 2.0.0
(released 2026-07-28, major rework); fastmcp 4.x not yet released.

Pin chain: pyproject `fastmcp>=3.1.0,<4.0` -> fastmcp 3.4.4 requires
`fastmcp-slim[client,server]==3.4.4` -> fastmcp-slim requires `mcp<2.0,>=1.24.0`.
The resolver therefore cannot install mcp 2.x in any env containing fastmcp. Dev extra
`"mcp"` (test client imports) is deliberately left unpinned: Docker installs runtime+dev
into one venv and local dev uses `-e .[dev]`, so it is always resolver-constrained to 1.x.
Residual risk only if someone installs `mcp` standalone outside the project extras.

## Migration design (when triggered)

1. `load_model` (and create tools) return a server-minted `model_id` handle.
2. Tools accept optional `model_id`; resolution order: explicit arg, else most recent
   model for `user_key()`. Keeps agent ergonomics (no id threading through 151 calls).
3. Trade-off: per-user fallback loses two-windows-same-user isolation that sessions gave;
   explicit `model_id` restores it. Document in tool descriptions.
4. Retire `session_key()` or delegate it to handle resolution. Prefer middleware/default
   resolution so per-tool churn stays near zero.
5. Refresh `docs/security-stdio-vs-http.md`: isolation analysis assumes `Mcp-Session-Id`.
6. Auth: RESOLVED, no work. JWT auth already shipped (PR #77, merged; `MCP_AUTH=jwt` +
   `scripts/mint_token.py`). It is resource-server bearer validation only; the spec's
   auth changes (DCR deprecated for Client ID Metadata Documents, RFC 9207 `iss`
   validation, credential-issuer binding) all concern the client/authorization-server
   OAuth flow we do not implement. New-spec auth work arises only if we later add
   interactive SSO (clients OAuth against Entra/Okta directly) — optional new scope.
7. Opportunity, separate PR: Tasks extension for `run_simulation`; `tasks/get` polling
   replaces `get_run_status` + "wait 1-2 min" instruction.
8. Verify `tools/list` deterministic ordering post-upgrade (151 tools, prompt cache).

## Trigger conditions (re-open migration work when any fires)

- fastmcp 4.x released with 2026-07-28 support.
- Official `mcp` SDK 2.x released.
- Claude clients default to 2026-07-28 negotiation.
- Deprecation window (12 months from 2026-07-28) half elapsed: check by 2027-01.

## Unresolved questions

- model_id fallback: most-recent-per-user OK, or require explicit id in multi-user HTTP?
- Track fastmcp 4.x early in a spike branch, or wait for stable?
- Tasks extension: bundle with migration or separate PR?
