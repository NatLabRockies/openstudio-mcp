"""MCP tool definitions for ComStock measures."""
from __future__ import annotations

from mcp_server.skills.comstock.operations import (
    create_typical_building,
    list_comstock_measures,
)


def register(mcp):
    @mcp.tool(name="list_comstock_measures")
    def list_comstock_measures_tool(category: str | None = None):
        """List available ComStock measures bundled in the server.

        Args:
            category: Optional filter — "baseline", "upgrade", "setup", "other",
                      or omit for all measures

        Returns categorized list of ~61 measures with names, descriptions,
        paths, and argument counts. Use paths with list_measure_arguments
        and apply_measure for full control.

        Does not require a model to be loaded.
        """
        return list_comstock_measures(category=category)

    @mcp.tool(name="create_typical_building")
    def create_typical_building_tool(
        template: str = "90.1-2019",
        building_type: str = "SmallOffice",
        system_type: str = "Inferred",
        climate_zone: str = "Lookup From Model",
        htg_src: str = "NaturalGas",
        clg_src: str = "Electricity",
        swh_src: str = "Inferred",
        add_constructions: bool = True,
        add_space_type_loads: bool = True,
        add_hvac: bool = True,
        add_swh: bool = True,
        add_exterior_lights: bool = True,
        add_thermostat: bool = True,
        remove_objects: bool = True,
    ):
        """Create a typical building from the loaded model using openstudio-standards.

        Adds constructions, loads, HVAC, schedules, and service water heating
        to a model that already has geometry and space types assigned.
        Wraps the ComStock create_typical_building_from_model measure.

        Automatically sets standardsBuildingType on the building and space types
        if not already set, using the building_type parameter.

        Args:
            template: ASHRAE standard — "90.1-2019", "90.1-2016", "90.1-2013", etc.
            building_type: DOE prototype type — "SmallOffice", "LargeOffice",
                "RetailStandalone", "PrimarySchool", "Hospital", etc. Used to set
                standardsBuildingType if missing from model.
            system_type: HVAC system — "Inferred" (auto-select), "VAV chiller with gas boiler reheat", etc.
            climate_zone: "Lookup From Model" or e.g. "ASHRAE 169-2013-4A"
            htg_src: Heating fuel — "NaturalGas", "Electricity", "DistrictHeating"
            clg_src: Cooling fuel — "Electricity" or "DistrictCooling"
            swh_src: SWH fuel — "Inferred", "NaturalGas", "Electricity"
            add_constructions: Add standard constructions to surfaces
            add_space_type_loads: Add people, lights, equipment per space type
            add_hvac: Add HVAC system
            add_swh: Add service water heating
            add_exterior_lights: Add exterior lighting
            add_thermostat: Add thermostat schedules
            remove_objects: Remove existing HVAC/loads before adding new ones

        Requires a model to be loaded via load_osm_model first.
        The model should have geometry (spaces with surfaces).
        """
        return create_typical_building(
            template=template,
            building_type=building_type,
            system_type=system_type,
            climate_zone=climate_zone,
            htg_src=htg_src,
            clg_src=clg_src,
            swh_src=swh_src,
            add_constructions=add_constructions,
            add_space_type_loads=add_space_type_loads,
            add_hvac=add_hvac,
            add_swh=add_swh,
            add_exterior_lights=add_exterior_lights,
            add_thermostat=add_thermostat,
            remove_objects=remove_objects,
        )
