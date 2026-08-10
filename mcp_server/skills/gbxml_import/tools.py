"""MCP tools for translating gbXML files (e.g. Revit exports) into OSM models."""
from __future__ import annotations

from mcp_server.skills.gbxml_import.operations import (
    import_gbxml_op,
    repair_and_validate_gbxml_geometry_op,
)


def register(mcp):
    @mcp.tool(tags={"geometry", "core"}, name="import_gbxml")
    def import_gbxml_tool(
        gbxml_path: str,
        epw_path: str,
        osm_path: str | None = None,
        run_name: str | None = None,
    ):
        """Translate a Revit-exported gbXML file into an OpenStudio model, without running a simulation.

        Runs the gbxml-to-openstudio measures (location, geometry, HVAC, sim
        control, postprocess) via the OpenStudio CLI with --measures_only, so
        EnergyPlus never executes — only the model-building measures do. Any
        ERROR/WARNING messages the measures report are returned per-step. The
        project's own EPW is required so the resulting .osm has the real
        project location embedded, not a placeholder.

        The result always has a valid ASHRAE climate zone unless truly
        unresolvable: `climate_zone` + `climate_zone_source` ("gbxml_measure",
        "stat_file", or "wmo_or_geographic_lookup") report where it came from;
        if every resolution tier misses, `climate_zone_resolved` is false and
        `climate_zone_warning` explains why — the import still succeeds
        (`ok: true`), it just needs `change_building_location` called
        explicitly afterward. It also reports `zero_volume_zone_count` /
        `zero_volume_zones`: conditioned thermal zones with zero or missing
        volume, a sign of gbXML zone-enclosure defects that make autosized
        equipment capacities unreliable.

        Args:
            gbxml_path: Path to the gbXML file (e.g. under /inputs).
            epw_path: Path to the project's own EPW file (e.g. under /inputs).
                Its companion .stat and .ddy files must sit alongside it in the
                same directory, with the same filename stem — the user should
                place all three files (gbxml, epw, stat, ddy) under /inputs.
            osm_path: Where to save the resulting .osm. Defaults to a path
                inside a new run directory.
            run_name: Optional label for the run directory.
        """
        return import_gbxml_op(
            gbxml_path=gbxml_path,
            epw_path=epw_path,
            osm_path=osm_path,
            run_name=run_name,
        )

    @mcp.tool(tags={"geometry", "core"}, name="repair_and_validate_gbxml_geometry")
    def repair_and_validate_gbxml_geometry_tool():
        """Check the loaded model for surface overlaps and non-enclosed space volumes.

        Runs match_surfaces() first (fixes shared walls between adjacent
        spaces — the common case), then reports same-space duplicate/
        overlapping surfaces and spaces whose volume can't be computed as a
        closed manifold (usually a missing Floor or RoofCeiling surface) —
        problems match_surfaces() cannot fix. One call replaces the manual
        list_surfaces/get_surface_details/list_spaces/get_space_details
        diagnostic chain.
        """
        return repair_and_validate_gbxml_geometry_op()
