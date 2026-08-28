"""Collected ToolDescriptor registry — runtime source of truth for discovery.

Every skill's ``register(mcp)`` is invoked through :class:`CollectingMCP`,
which delegates to the real MCP object while recording one
:class:`ToolDescriptor` per ``@mcp.tool`` registration. The tool-catalog
resource and the router index are built from these descriptors, so they can
never drift from what is actually registered (including under the
OSMCP_DISABLE_KNOWLEDGE_SKILLS ablation flag, where the skipped packages
simply produce no descriptors).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDescriptor:
    name: str                # MCP-visible tool name
    package: str             # owning mcp_server/skills/<package>
    tags: frozenset[str]
    description: str         # first line of the tool docstring


_DESCRIPTORS: dict[str, ToolDescriptor] = {}


def descriptors() -> dict[str, ToolDescriptor]:
    """Snapshot of the collected descriptors (name -> ToolDescriptor)."""
    return dict(_DESCRIPTORS)


def reset_descriptors() -> None:
    """Clear the registry — called at the start of each full registration."""
    _DESCRIPTORS.clear()


def ensure_collected() -> None:
    """Populate descriptors if no registration has happened yet.

    Consumers that can run outside a live server (router index in unit
    contexts) call this; it registers all skills into a no-op MCP purely for
    the collection side effect.
    """
    if _DESCRIPTORS:
        return

    class _NullMCP:
        def tool(self, name=None, **kwargs):
            return lambda fn: fn

        def prompt(self, **kwargs):
            return lambda fn: fn

        def resource(self, *args, **kwargs):
            return lambda fn: fn

    from mcp_server.skills import register_all_skills
    register_all_skills(_NullMCP())


class CollectingMCP:
    """Facade handed to each skill's register().

    Delegates every call to the real MCP object — never monkeypatches the
    shared FastMCP instance — while capturing a ToolDescriptor per tool.
    """

    def __init__(self, mcp, package: str):
        self._mcp = mcp
        self._package = package

    def tool(self, name=None, tags=None, **kwargs):
        real_decorator = self._mcp.tool(name=name, tags=tags, **kwargs)
        package = self._package

        def decorator(fn):
            tool_name = name or fn.__name__
            if tool_name in _DESCRIPTORS:
                raise ValueError(
                    f"duplicate MCP tool name '{tool_name}' "
                    f"({_DESCRIPTORS[tool_name].package} and {package})",
                )
            doc = (fn.__doc__ or "").strip()
            _DESCRIPTORS[tool_name] = ToolDescriptor(
                name=tool_name,
                package=package,
                tags=frozenset(tags or ()),
                description=doc.split("\n")[0] if doc else "",
            )
            return real_decorator(fn)

        return decorator

    def __getattr__(self, attr):
        return getattr(self._mcp, attr)
