"""MCP tool registration for API reference skill."""
from __future__ import annotations

from .operations import search_api_op, search_wiring_patterns_op


def register(mcp):
    @mcp.tool(name="search_api", tags={"core"})
    def search_api_tool(
        class_pattern: str,
        method_pattern: str | None = None,
        max_classes: int = 10,
        include_base: bool = False,
    ) -> dict:
        """Search OpenStudio SDK classes and methods by pattern.

        Use this tool to discover real class names and method signatures
        before calling OpenStudio API methods. Catches hallucinated methods
        that don't exist on the actual class.

        Args:
            class_pattern: Regex to match class names (e.g. "CoilCooling",
                "FourPipeBeam"). Case-insensitive.
            method_pattern: Optional regex to filter methods (e.g. "Rated|COP").
            max_classes: Max classes to return (default 10).
            include_base: Include inherited ModelObject methods (default False).

        Returns setters, getters, and other methods grouped per class.
        """
        return search_api_op(
            class_pattern,
            method_pattern=method_pattern,
            max_classes=max_classes,
            include_base=include_base,
        )

    @mcp.tool(tags={"hvac"}, name="search_wiring_patterns")
    def search_wiring_patterns_tool(
        pattern: str,
        max_results: int = 3,
    ) -> dict:
        """Search HVAC wiring recipes showing how to connect components.

        Returns Ruby code snippets from openstudio-resources showing how to
        wire coils to loops, terminals to air loops, zone equipment to zones.
        Use before authoring measures that create or modify HVAC systems.

        Args:
            pattern: Component type or keyword (e.g. "four pipe beam",
                "DOAS", "boiler", "fan coil", "VRF", "PTAC", "unitary",
                "plant loop", "chiller", "heat pump")
            max_results: Max recipes to return (default 3)
        """
        return search_wiring_patterns_op(pattern, max_results=max_results)
