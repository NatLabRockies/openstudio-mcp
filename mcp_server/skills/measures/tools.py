"""MCP tool definitions for measures."""
from __future__ import annotations

from typing import Any

from mcp_server.skills.measures.operations import (
    apply_measure,
    download_measure_archive,
    list_local_measures,
    list_measure_arguments,
)


def register(mcp):
    @mcp.tool(tags={"measures"}, name="list_local_measures")
    def list_local_measures_tool(
        root_dir: str | None = None,
        max_depth: int = 3,
        max_results: int = 200,
    ):
        """Find existing OpenStudio measures before considering BCL download.

        Use this first when the user asks for a measure by name or intent.
        Searches mounted/user measures plus bundled common measures and
        ComStock measures by default. Only ask the user about downloading from
        BCL if no suitable local match is found.

        Search order: /measures/custom, /measures, legacy /inputs measures,
        /opt/common-measures, /opt/comstock-measures, then local BCL caches.
        Pass root_dir to inspect one allowed measure folder.
        """
        return list_local_measures(root_dir=root_dir, max_depth=max_depth, max_results=max_results)

    @mcp.tool(tags={"measures"}, name="list_measure_arguments")
    def list_measure_arguments_tool(measure_dir: str):
        """List argument names, types, defaults, and choices for an OpenStudio measure.

        Args:
            measure_dir: Path to the measure directory (contains measure.rb)
        """
        return list_measure_arguments(measure_dir=measure_dir)

    @mcp.tool(tags={"measures"}, name="download_measure_from_bcl")
    def download_measure_from_bcl_tool(
        url: str,
        output_dir: str | None = None,
        measure_name: str | None = None,
        timeout_seconds: int = 300,
    ):
        """Download and extract a measure ZIP into the local BCL cache.

        Use only after list_local_measures finds no suitable local, common
        measures, or ComStock match and the user agrees to try BCL/download.
        Defaults to /measures/bcl so downloaded measures persist when
        /measures is host-mounted. Accepts HTTPS URLs from BCL/NREL and GitHub.
        Returns discovered measure_dir values for list_measure_arguments,
        apply_measure, and OSA generation tools.
        """
        return download_measure_archive(
            url=url,
            output_dir=output_dir,
            measure_name=measure_name,
            timeout_seconds=timeout_seconds,
        )

    @mcp.tool(tags={"measures"}, name="apply_measure")
    def apply_measure_tool(
        measure_dir: str,
        arguments: dict[str, Any] | None = None,
    ):
        """Run an existing local OpenStudio measure against the loaded model.

        Use to apply a measure after you have a measure_dir. When the user asks
        for a measure by name or intent, first call list_local_measures to find
        mounted, custom, common measures, or ComStock measures. If no local
        match exists, ask before using BCL/download. To create a new measure,
        use create_measure.

        Args:
            measure_dir: Path to the measure directory (contains measure.rb)
            arguments: Optional dict of argument_name -> value overrides

        """
        return apply_measure(measure_dir=measure_dir, arguments=arguments)
