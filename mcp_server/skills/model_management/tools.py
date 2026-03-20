"""MCP tool definitions for OSM model management."""
from __future__ import annotations

from mcp_server.skills.model_management.operations import (
    create_baseline_osm,
    create_example_osm,
    inspect_osm_summary,
    list_files,
    load_osm_model,
    save_osm_model,
)


def register(mcp):
    @mcp.tool(name="load_osm_model", tags={"core"})
    def load_osm_model_tool(osm_path: str, version_translate: bool = True):
        """Load an OpenStudio model (.osm) and set as current model for all
        query and modification tools. Supports version translation for older
        models. After loading, use get_building_info, list_spaces,
        list_thermal_zones, etc. to inspect the model.

        Args:
            osm_path: Path to the OSM file to load (absolute or relative)
            version_translate: Use VersionTranslator to upgrade older OSM files (default True)
        """
        return load_osm_model(osm_path=osm_path, version_translate=version_translate)

    @mcp.tool(name="save_osm_model", tags={"core"})
    def save_osm_model_tool(osm_path: str | None = None):
        """Save the currently loaded model to disk as an OSM file.
        IMPORTANT: call after making changes to persist the model. Changes
        are lost if you don't save before loading a different model.

        Args:
            osm_path: Optional path to save to. If not provided, saves to original load path.
        """
        return save_osm_model(osm_path=osm_path)

    @mcp.tool(name="create_example_osm", tags={"geometry"})
    def create_example_osm_tool(name: str | None = None, out_dir: str | None = None):
        """Create a minimal single-zone OpenStudio example model for testing
        and demos. Auto-loads into memory. Saved under /runs/.
        For multi-zone baseline, use create_baseline_osm. For production
        models with DOE prototypes, use create_new_building.
        """
        return create_example_osm(name=name, out_dir=out_dir)

    @mcp.tool(name="create_baseline_osm", tags={"geometry"})
    def create_baseline_osm_tool(
        name: str | None = None,
        num_floors: int = 2,
        floor_to_floor_height: float = 4.0,
        perimeter_zone_depth: float = 3.0,
        ashrae_sys_num: str | None = None,
        wwr: float | None = None,
    ):
        """Create a baseline 10-zone, 2-story commercial building with perimeter
        and core zones, schedules, loads, constructions, and thermostats.
        Optionally adds ASHRAE HVAC system 01-10 and windows. Auto-loads into
        memory. For testing/demos only — for production models use create_new_building.

        Args:
            name: Model name (used for output directory)
            num_floors: Number of stories (default 2)
            floor_to_floor_height: Height per floor in meters (default 4.0)
            perimeter_zone_depth: Perimeter zone depth in meters (default 3.0, 0=single zone/floor)
            ashrae_sys_num: ASHRAE system "01"-"10", None = no HVAC
            wwr: Window-to-wall ratio 0-1, None = no windows
        """
        return create_baseline_osm(
            name=name,
            num_floors=num_floors,
            floor_to_floor_height=floor_to_floor_height,
            perimeter_zone_depth=perimeter_zone_depth,
            ashrae_sys_num=ashrae_sys_num,
            wwr=wwr,
        )

    @mcp.tool(name="list_files", tags={"core"})
    def list_files_tool(
        directory: str | None = None,
        pattern: str = "*",
        max_depth: int = 2,
        max_results: int = 10,
    ):
        """List files in /inputs and /runs only. Default 10 results.
        /inputs contains user-provided models, weather files, and data files.
        /runs contains simulation outputs. Both are inside the MCP container.

        Only call if you need to discover files. Do not call repeatedly
        for the same directory. For weather files, use list_weather_files instead.

        Args:
            directory: Directory under /inputs or /runs (e.g. "/runs/my_run"). If omitted, scans both.
            pattern: Glob pattern (e.g. "*.osm"). Default "*".
            max_depth: Max directory depth (1 = top-level only). Default 2.
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_files(directory=directory, pattern=pattern, max_depth=max_depth,
                         max_results=mr)

    @mcp.tool(name="inspect_osm_summary", tags={"core"})
    def inspect_osm_summary_tool(osm_path: str):
        """Quick structural summary of an OSM file without loading it into
        memory. Returns object counts, floor area, and zone info. Use to
        preview a model before loading.
        If model is already loaded, use get_model_summary instead.
        """
        return inspect_osm_summary(osm_path=osm_path)
