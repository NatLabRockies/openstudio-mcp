"""Skills auto-discovery and registration.

Scans all sub-packages in this directory for a `tools` module
with a `register(mcp)` function, then calls it.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)


def register_all_skills(mcp) -> list[str]:
    """Discover and register all skill tools with the MCP server.

    Returns list of registered skill names.
    """
    registered = []
    package = importlib.import_module(__name__)

    for importer, modname, ispkg in pkgutil.iter_modules(package.__path__):
        if not ispkg:
            continue
        try:
            tools_mod = importlib.import_module(f"{__name__}.{modname}.tools")
            if hasattr(tools_mod, "register"):
                tools_mod.register(mcp)
                registered.append(modname)
                logger.info("Registered skill: %s", modname)
            else:
                logger.warning("Skill %s has no register() function", modname)
        except ImportError as e:
            logger.warning("Failed to import skill %s: %s", modname, e)

    return registered
