"""Tool exposure policy and remote-mode sandbox fail-closed check (issue #180).

Tools that author or install executable content (measures, Python plugins,
pip packages) are the prompt-injection blast radius on a multi-user server:
injected text in an uploaded model can steer an agent into writing and running
code. They are exposed by default (measure authoring is a core workflow); a
deployment that must not let agents write code opts out explicitly with
OSMCP_ENABLE_CODE_TOOLS=false, on any transport.

Hiding them is a steering control, not an execution boundary: uploads still
auto-extract measure zips and ``apply_measure``/``run_osw``/``test_measure``
still run tenant code. The sandbox (``enforce_http_sandbox``) is the boundary.

Env:
  OSMCP_TOOLS_ALLOW   comma list; when set, ONLY these tools are registered
  OSMCP_TOOLS_DENY    comma list of tools to hide (any transport); deny wins
  OSMCP_ENABLE_CODE_TOOLS=false hide CODE_AUTHORING_TOOLS (default true, any transport)
  OSMCP_ALLOW_UNSANDBOXED=true  let the HTTP server start without full confinement
  OSMCP_TOOL_SEARCH=1 list only `core` tools plus search_tools/call_tool (see tool_search_transform)

Every ALLOW/DENY entry must name a registered tool (case-insensitive); an
unknown entry or an empty ALLOW refuses startup (``validate_policy``), so a
typo can never fail open.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterable

logger = logging.getLogger(__name__)

CODE_AUTHORING_TOOLS = frozenset({
    "create_measure",
    "edit_measure",
    "create_python_plugin",
    "edit_python_plugin",
    "install_plugin_packages",
})

# Synthetic tools FastMCP's CodeMode transform exposes instead of the roster
# (OSMCP_CODE_MODE=1). They are policy-checked like any other name.
CODE_MODE_SEARCH = "search"
CODE_MODE_GET_SCHEMA = "get_schema"
CODE_MODE_EXECUTE = "execute"
CODE_MODE_TOOLS = frozenset({CODE_MODE_SEARCH, CODE_MODE_GET_SCHEMA, CODE_MODE_EXECUTE})

# Synthetic tools FastMCP's BM25 search transform exposes (OSMCP_TOOL_SEARCH=1).
TOOL_SEARCH_SEARCH = "search_tools"
TOOL_SEARCH_CALL = "call_tool"
TOOL_SEARCH_TOOLS = frozenset({TOOL_SEARCH_SEARCH, TOOL_SEARCH_CALL})
TOOL_SEARCH_MAX_RESULTS = 8


def _csv(name: str) -> set[str]:
    """Entries of a comma-list env var, lower-cased and stripped (tool names are snake_case)."""
    return {t.strip().lower() for t in os.environ.get(name, "").split(",") if t.strip()}


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _http() -> bool:
    return os.environ.get("MCP_TRANSPORT", "stdio").lower() in ("http", "streamable-http")


def _code_mode() -> bool:
    # Mirrors config.ENABLE_CODE_MODE without importing config (which reads much more env).
    return os.environ.get("OSMCP_CODE_MODE", "").lower() in ("1", "true")


def _tool_search() -> bool:
    # Mirrors config.ENABLE_TOOL_SEARCH, like _code_mode above.
    return os.environ.get("OSMCP_TOOL_SEARCH", "").lower() in ("1", "true")


_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def code_tools_enabled() -> bool:
    """Whether the code-authoring tools are exposed: on unless OSMCP_ENABLE_CODE_TOOLS
    is explicitly false. An unrecognised value is rejected by ``validate_policy``;
    here it counts as the default (on) so registration never hides on a typo alone.
    """
    return os.environ.get("OSMCP_ENABLE_CODE_TOOLS", "true").strip().lower() not in _FALSE


def tool_enabled(name: str) -> bool:
    """Whether `name` should be registered under the current environment.

    Order: allow-list narrows, deny-list hides (deny wins over allow), then the
    code-authoring opt-out applies regardless of the allow-list, so listing
    ``create_measure`` in OSMCP_TOOLS_ALLOW never overrides OSMCP_ENABLE_CODE_TOOLS=false.
    """
    key = name.lower()
    allow = _csv("OSMCP_TOOLS_ALLOW")
    if allow and key not in allow:
        return False
    if key in _csv("OSMCP_TOOLS_DENY"):
        return False
    return code_tools_enabled() or key not in CODE_AUTHORING_TOOLS


def validate_policy(known_names: Iterable[str]) -> None:
    """Refuse a policy that names tools which do not exist.

    ``known_names`` is the full roster seen at registration (hidden tools
    included) plus, under OSMCP_CODE_MODE / OSMCP_TOOL_SEARCH, the synthetic names.
    Raises RuntimeError naming the variable and the bad entries.
    """
    if _code_mode() and _tool_search():
        raise RuntimeError(
            "OSMCP_CODE_MODE and OSMCP_TOOL_SEARCH both replace the tool list; turn one off.",
        )
    known = {n.lower() for n in known_names}
    if _code_mode():
        known |= CODE_MODE_TOOLS
    if _tool_search():
        known |= TOOL_SEARCH_TOOLS
    raw_code = os.environ.get("OSMCP_ENABLE_CODE_TOOLS")
    if raw_code is not None and raw_code.strip().lower() not in _TRUE + _FALSE:
        raise RuntimeError(
            f"OSMCP_ENABLE_CODE_TOOLS={raw_code!r} is not a boolean; use true or false "
            "(unset means true).",
        )
    raw_allow = os.environ.get("OSMCP_TOOLS_ALLOW")
    if raw_allow is not None and not _csv("OSMCP_TOOLS_ALLOW"):
        raise RuntimeError(
            "OSMCP_TOOLS_ALLOW is set but empty; unset it to expose every tool, "
            "or list the tools to expose.",
        )
    for var in ("OSMCP_TOOLS_ALLOW", "OSMCP_TOOLS_DENY"):
        unknown = sorted(_csv(var) - known)
        if unknown:
            raise RuntimeError(
                f"{var} names tools that do not exist: "
                + ", ".join(repr(u) for u in unknown)
                + ". Entries are matched case-insensitively against the registered roster"
                + (" and the CodeMode tools search/get_schema/execute" if _code_mode() else "")
                + (" and the tool-search tools search_tools/call_tool" if _tool_search() else "")
                + ".",
            )


def code_mode_transform():
    """Build the CodeMode transform with the exposure policy applied to its synthetic tools.

    The transform replaces the roster with discovery tools plus ``execute``;
    it is added after registration, so the CollectingMCP hook never sees these
    names. Discovery tools hidden by policy are simply not built; a hidden
    ``execute`` is a contradiction (nothing would be callable) and refuses startup.
    """
    from fastmcp.experimental.transforms.code_mode import CodeMode, GetSchemas, Search

    if not tool_enabled(CODE_MODE_EXECUTE):
        raise RuntimeError(
            f"OSMCP_CODE_MODE is on but the tool policy hides '{CODE_MODE_EXECUTE}'; "
            "every tool is called through it, so list it in OSMCP_TOOLS_ALLOW / drop it "
            "from OSMCP_TOOLS_DENY, or turn code mode off.",
        )
    discovery = []
    if tool_enabled(CODE_MODE_SEARCH):
        discovery.append(Search(name=CODE_MODE_SEARCH))
    else:
        logger.info("Tool hidden by policy: %s", CODE_MODE_SEARCH)
    if tool_enabled(CODE_MODE_GET_SCHEMA):
        discovery.append(GetSchemas(name=CODE_MODE_GET_SCHEMA))
    else:
        logger.info("Tool hidden by policy: %s", CODE_MODE_GET_SCHEMA)
    return CodeMode(discovery_tools=discovery, execute_tool_name=CODE_MODE_EXECUTE)


def tool_search_transform():
    """Build the search transform: ``core`` tools stay listed, the rest sit behind
    ``search_tools`` (BM25 over name/description/params) and ``call_tool``.

    For hosts that load every schema up front (~52K tokens for the full roster) or cap
    tools per request (VS Code Copilot: 128). Hosts with their own deferred loading
    (Claude Code) should leave it off: the CodeMode A/B (docs/archived/
    codemode-benchmark-2026-04-05.md) showed a second discovery layer hurts accuracy.
    Proxied calls re-enter FastMCP.call_tool with middleware, so identity, audit and
    response-size guards see the real tool name. Policy-hidden tools are never
    registered, so search cannot surface them.
    """
    from fastmcp.server.transforms.search import BM25SearchTransform

    from mcp_server.tool_registry import descriptors, ensure_collected

    hidden = sorted(n for n in TOOL_SEARCH_TOOLS if not tool_enabled(n))
    if hidden:
        raise RuntimeError(
            f"OSMCP_TOOL_SEARCH is on but the tool policy hides {', '.join(map(repr, hidden))}; "
            "unlisted tools are reachable only through search_tools and call_tool, so "
            "expose both or turn tool search off.",
        )
    ensure_collected()
    pinned = sorted(d.name for d in descriptors().values() if "core" in d.tags)
    return BM25SearchTransform(
        max_results=TOOL_SEARCH_MAX_RESULTS,
        always_visible=pinned,
        search_tool_name=TOOL_SEARCH_SEARCH,
        call_tool_name=TOOL_SEARCH_CALL,
    )


PROXY_READ_TIMEOUT_BUDGET_SECONDS = 55  # nginx proxy_read_timeout defaults to 60 s


def wait_cap_proxy_warning(cap_seconds: int) -> str | None:
    """Operator warning when the get_run_status wait cap would outlive a default proxy.

    A held `wait_seconds` call is one HTTP response. nginx closes an idle upstream
    response at 60 s by default (Cloudflare 100 s, Caddy/Traefik unbounded), so a
    cap above 55 s under HTTP transport needs the proxy's read timeout raised too.
    Returns the message, or None when nothing needs saying (stdio has no proxy).
    """
    if not _http() or cap_seconds <= PROXY_READ_TIMEOUT_BUDGET_SECONDS:
        return None
    return (
        f"OSMCP_WAIT_MAX_SECONDS={cap_seconds} exceeds the {PROXY_READ_TIMEOUT_BUDGET_SECONDS} s "
        "budget for a default reverse-proxy read timeout (nginx: 60 s). A held "
        "get_run_status call will be cut by the proxy unless its read timeout is raised "
        "above the cap."
    )


def enforce_http_sandbox() -> None:
    """Refuse to serve remote users without full kernel confinement.

    Uploaded measures/OSWs/plugins are attacker-controlled code; without
    Landlock+seccomp they would run as the server's own user. This checks the
    configured tier (OSMCP_SANDBOX / OSMCP_SANDBOX_NET on Linux); the exec shim
    then refuses each subprocess if the kernel backend is missing at run time.
    """
    if not _http():
        return
    from mcp_server import sandbox
    from mcp_server.config import SANDBOX_NET

    tier = sandbox.active_tier()
    if tier == "landlock" and SANDBOX_NET != "allow":
        return
    if tier == "landlock":
        tier = "landlock with OSMCP_SANDBOX_NET=allow (no network deny)"
    msg = (
        f"HTTP transport requires full sandbox confinement but the configured tier is '{tier}'. "
        "Use the Docker image on Linux with OSMCP_SANDBOX=auto, or set "
        "OSMCP_ALLOW_UNSANDBOXED=true to accept the risk."
    )
    if _flag("OSMCP_ALLOW_UNSANDBOXED"):
        logger.warning("%s (overridden)", msg)
        return
    raise RuntimeError(msg)
