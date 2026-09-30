"""Tool exposure policy and remote-mode sandbox fail-closed check (issue #180).

Tools that author or install executable content (measures, Python plugins,
pip packages) are the prompt-injection blast radius on a multi-user server:
injected text in an uploaded model can steer an agent into writing and running
code. In HTTP mode they are hidden unless the operator opts in.

Env:
  OSMCP_TOOLS_ALLOW   comma list; when set, ONLY these tools are registered
  OSMCP_TOOLS_DENY    comma list of tools to hide (any transport)
  OSMCP_ENABLE_CODE_TOOLS=true  expose CODE_AUTHORING_TOOLS in HTTP mode
  OSMCP_ALLOW_UNSANDBOXED=true  let the HTTP server start without full confinement
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

CODE_AUTHORING_TOOLS = frozenset({
    "create_measure",
    "edit_measure",
    "create_python_plugin",
    "edit_python_plugin",
    "install_plugin_packages",
})


def _csv(name: str) -> set[str]:
    return {t.strip() for t in os.environ.get(name, "").split(",") if t.strip()}


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _http() -> bool:
    return os.environ.get("MCP_TRANSPORT", "stdio").lower() in ("http", "streamable-http")


def tool_enabled(name: str) -> bool:
    """Whether `name` should be registered under the current environment."""
    allow = _csv("OSMCP_TOOLS_ALLOW")
    if allow and name not in allow:
        return False
    if name in _csv("OSMCP_TOOLS_DENY"):
        return False
    return not (_http() and name in CODE_AUTHORING_TOOLS and not _flag("OSMCP_ENABLE_CODE_TOOLS"))


def enforce_http_sandbox() -> None:
    """Refuse to serve remote users without full kernel confinement.

    Uploaded measures/OSWs/plugins are attacker-controlled code; without
    Landlock+seccomp they would run as the server's own user.
    """
    if not _http():
        return
    from mcp_server import sandbox

    tier = sandbox.active_tier()
    if tier == "landlock":
        return
    msg = (
        f"HTTP transport requires full sandbox confinement but the active tier is '{tier}'. "
        "Use the Docker image on Linux with OSMCP_SANDBOX=auto, or set "
        "OSMCP_ALLOW_UNSANDBOXED=true to accept the risk."
    )
    if _flag("OSMCP_ALLOW_UNSANDBOXED"):
        logger.warning("%s (overridden)", msg)
        return
    raise RuntimeError(msg)
