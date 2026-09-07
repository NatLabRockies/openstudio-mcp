"""Skills auto-discovery and registration.

Scans all sub-packages in this directory for a `tools` module
with a `register(mcp)` function, then calls it.
"""
from __future__ import annotations

import importlib
import logging
import os
import pkgutil

logger = logging.getLogger(__name__)

# Knowledge-layer skills (list_skills/get_skill + recommend_tools) — excluded
# when OSMCP_DISABLE_KNOWLEDGE_SKILLS=1. Benchmark ablation arm only: the
# tools must be truly absent from the roster, because client-side blocking
# leaves them visible and the refusals contaminate agent behavior. See
# docs/plans/plan-benchmark-reviewer-response.md D3.
_KNOWLEDGE_SKILLS = {"skill_discovery", "tool_router"}


def register_all_skills(mcp) -> list[str]:
    """Discover and register all skill tools with the MCP server.

    Returns list of registered skill names.
    """
    from mcp_server.tool_registry import CollectingMCP, reset_descriptors

    registered = []
    package = importlib.import_module(__name__)
    ablate = os.environ.get("OSMCP_DISABLE_KNOWLEDGE_SKILLS") == "1"
    # Fresh descriptor collection per full registration (tests re-register)
    reset_descriptors()

    for _importer, modname, ispkg in pkgutil.iter_modules(package.__path__):
        if not ispkg:
            continue
        if ablate and modname in _KNOWLEDGE_SKILLS:
            logger.info("Skipping knowledge skill (ablation arm): %s", modname)
            continue
        try:
            tools_mod = importlib.import_module(f"{__name__}.{modname}.tools")
            if hasattr(tools_mod, "register"):
                # Collecting facade: delegates to the real MCP while recording
                # ToolDescriptors — catalog/router derive from that registry
                tools_mod.register(CollectingMCP(mcp, modname))
                registered.append(modname)
                logger.info("Registered skill: %s", modname)
            else:
                logger.warning("Skill %s has no register() function", modname)
        except ImportError as e:
            logger.warning("Failed to import skill %s: %s", modname, e)

    return registered
