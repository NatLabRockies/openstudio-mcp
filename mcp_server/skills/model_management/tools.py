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
    @mcp.tool(name="load_osm_model")
    def load_osm_model_tool(osm_path: str, version_translate: bool = True):
        """Load an OSM file and set it as the current model for all query tools.

        Once loaded, you can use other tools like list_spaces, get_building_info,
        list_thermal_zones, etc. to query the model without passing the path each time.

        Args:
            osm_path: Path to the OSM file to load (absolute or relative)
            version_translate: Use VersionTranslator to upgrade older OSM files (default True)

        Returns:
            Dict with ok=True and model summary (spaces, zones, building name) on success
        """
        return load_osm_model(osm_path=osm_path, version_translate=version_translate)

    @mcp.tool(name="save_osm_model")
    def save_osm_model_tool(save_path: str | None = None):
        """Save the currently loaded model to disk.

        Args:
            save_path: Optional path to save to. If not provided, saves to original load path.

        Returns:
            Dict with ok=True and saved path on success
        """
        return save_osm_model(save_path=save_path)

    @mcp.tool(name="create_example_osm")
    def create_example_osm_tool(name: str | None = None, out_dir: str | None = None):
        """Create the built-in OpenStudio example model and save it as an OSM.

        This is intended as a zero-input demo for Claude Desktop / MCP clients.
        The model is written under /runs by default so it is persisted via the /runs mount.
        """
        return create_example_osm(name=name, out_dir=out_dir)

    @mcp.tool(name="create_baseline_osm")
    def create_baseline_osm_tool(
        name: str | None = None,
        num_floors: int = 2,
        floor_to_floor_height: float = 4.0,
        perimeter_zone_depth: float = 3.0,
        ashrae_sys_num: str | None = None,
        wwr: float | None = None,
    ):
        """Create a baseline 10-zone, 2-story commercial building model.

        Produces a perimeter+core zoned building with detailed schedules, loads,
        constructions, and thermostats. Optionally adds ASHRAE HVAC and windows.

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

    @mcp.tool(name="list_files")
    def list_files_tool(directory: str | None = None, pattern: str = "*"):
        """List files in the mounted directories (/inputs and /runs).

        Use this to discover what OSM models, EPW weather files, and simulation
        outputs are available. Scans both /inputs and /runs by default.

        Args:
            directory: Specific directory to list (e.g. "/inputs", "/runs"). If omitted, scans both.
            pattern: Glob pattern to filter (e.g. "*.epw", "*.osm"). Default "*" returns all files.

        Returns:
            Dict with file list including name, path, size, and extension.
        """
        return list_files(directory=directory, pattern=pattern)

    @mcp.tool(name="inspect_osm_summary")
    def inspect_osm_summary_tool(osm_path: str):
        """Inspect an OSM (no simulation) and return a simple summary."""
        return inspect_osm_summary(osm_path=osm_path)
