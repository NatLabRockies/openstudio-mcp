"""MCP tool definitions for measures."""
from __future__ import annotations

from typing import Any

from mcp_server.skills.measures.operations import (
    apply_measure,
    list_measure_arguments,
)


def register(mcp):
    @mcp.tool(tags={"measures"}, name="list_measure_arguments")
    def list_measure_arguments_tool(measure_dir: str):
        """List argument names, types, defaults, and choices for an OpenStudio measure.

        Args:
            measure_dir: Path to the measure directory (contains measure.rb)
        """
        return list_measure_arguments(measure_dir=measure_dir)

    @mcp.tool(tags={"measures"}, name="apply_measure")
    def apply_measure_tool(
        measure_dir: str,
        arguments: dict[str, Any] | None = None,
    ):
        """Run an existing OpenStudio measure against the loaded model.
        Use to apply a measure that already exists. To create a new measure, use create_measure.

        Args:
            measure_dir: Path to the measure directory (contains measure.rb)
            arguments: Optional dict of argument_name -> value overrides

        """
        return apply_measure(measure_dir=measure_dir, arguments=arguments)
