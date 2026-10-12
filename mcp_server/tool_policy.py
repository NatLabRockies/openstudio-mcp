"""Tool exposure policy and remote-mode sandbox fail-closed check (issue #180).

Tools that author or install executable content (measures, Python plugins,
pip packages) are the prompt-injection blast radius on a multi-user server:
injected text in an uploaded model can steer an agent into writing and running
code. In HTTP mode they are hidden unless the operator opts in.

Hiding them is a steering control, not an execution boundary: uploads still
auto-extract measure zips and ``apply_measure``/``run_osw``/``test_measure``
still run tenant code. The sandbox (``enforce_http_sandbox``) is the boundary.

Env:
  OSMCP_TOOLS_ALLOW   comma list; when set, ONLY these tools are registered
  OSMCP_TOOLS_DENY    comma list of tools to hide (any transport); deny wins
  OSMCP_ENABLE_CODE_TOOLS=true  expose CODE_AUTHORING_TOOLS in HTTP mode
  OSMCP_ALLOW_UNSANDBOXED=true  let the HTTP server start without full confinement

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


def code_tools_enabled() -> bool:
    """Whether the code-authoring tools are exposed under the current transport/flags."""
    return not _http() or _flag("OSMCP_ENABLE_CODE_TOOLS")


def tool_enabled(name: str) -> bool:
    """Whether `name` should be registered under the current environment.

    Order: allow-list narrows, deny-list hides (deny wins over allow), then the
    HTTP code-authoring hide applies regardless of the allow-list, so listing
    ``create_measure`` in OSMCP_TOOLS_ALLOW never implies OSMCP_ENABLE_CODE_TOOLS.
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
    included) plus, under OSMCP_CODE_MODE, the synthetic CodeMode names.
    Raises RuntimeError naming the variable and the bad entries.
    """
    known = {n.lower() for n in known_names}
    if _code_mode():
        known |= CODE_MODE_TOOLS
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
