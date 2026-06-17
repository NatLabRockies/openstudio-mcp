"""MCP tool definitions for measures."""
from __future__ import annotations

from typing import Any

from mcp_server.skills.measures.operations import (
    apply_measure,
    download_measure_archive,
    find_measure,
    list_local_measures,
    list_measure_arguments,
    search_bcl_measures,
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

    @mcp.tool(tags={"measures"}, name="find_measure")
    def find_measure_tool(
        query: str,
        download_if_bcl_match: bool = True,
        min_match_score: float = 0.72,
        max_results: int = 10,
        timeout_seconds: int = 300,
    ):
        """Find a measure by name or intent, searching local measures before BCL.

        This is the safest default when the user names an existing measure.
        It ranks local custom/mounted/common/ComStock/BCL-cache measures first.
        If no local result is a good match, it searches BCL. When the best BCL
        result is above min_match_score, it downloads the measure into
        /measures/bcl. On success, use the top-level measure_dir or
        selected_measure_dir with list_measure_arguments and apply_measure.
        The response also includes next.list_arguments and next.apply tool
        argument objects for easy chaining.

        Example: query="Replace Chiller with Air Source Heat Pumps Measure Details"

        Args:
            query: Measure name, BCL page title, or intent text to find.
            download_if_bcl_match: Download the best BCL match when it is good.
            min_match_score: Minimum score required before accepting a match.
            max_results: Number of local/BCL candidates to return.
            timeout_seconds: Network/download timeout for BCL requests.
        """
        return find_measure(
            query=query,
            download_if_bcl_match=download_if_bcl_match,
            min_match_score=min_match_score,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
        )

    @mcp.tool(tags={"measures"}, name="search_bcl_measures")
    def search_bcl_measures_tool(
        query: str,
        max_results: int = 10,
        timeout_seconds: int = 60,
        page: int = 0,
    ):
        """Search BCL for measures and rank likely matches.

        Prefer find_measure for normal user requests because it searches local
        measures first and can download a strong BCL match. Use this when you
        need to inspect BCL candidates without downloading. Uses BCL wildcard
        search with bundle:measure and page query parameters.
        """
        return search_bcl_measures(
            query=query,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
            page=page,
        )

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
        Returns top-level measure_dir and selected_measure_dir for the first
        discovered measure, plus next.list_arguments and next.apply tool
        argument objects for easy chaining.
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
        for a measure by name or intent, call find_measure first and pass its
        top-level measure_dir here. To create a new measure, use create_measure.

        Args:
            measure_dir: Path to the measure directory (contains measure.rb)
            arguments: Optional dict of argument_name -> value overrides

        """
        return apply_measure(measure_dir=measure_dir, arguments=arguments)
