"""MCP tool definitions for ComStock measures."""
from __future__ import annotations

from mcp_server.skills.comstock.operations import (
    create_bar_building,
    create_new_building,
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

        """
        return list_comstock_measures(category=category)

    @mcp.tool(name="create_bar_building")
    def create_bar_building_tool(
        building_type: str = "SmallOffice",
        total_bldg_floor_area: float = 10000,
        num_stories_above_grade: float = 1.0,
        num_stories_below_grade: int = 0,
        floor_height: float = 0,
        template: str = "90.1-2019",
        climate_zone: str = "Lookup From Stat File",
        wwr: float = 0,
        ns_to_ew_ratio: float = 0,
        building_rotation: float = 0,
        bar_division_method: str = "Multiple Space Types - Individual Stories Sliced",
        story_multiplier: str = "Basements Ground Mid Top",
        bar_width: float = 0,
    ):
        """Create bar building geometry from building type and high-level parameters.

        Creates spaces, surfaces, fenestration, thermal zones, building stories,
        and space types. Does NOT add constructions, loads, HVAC, or schedules —
        use create_typical_building after this for a complete model.

        Creates an empty model if none is loaded. All units are imperial (ft, ft²).

        Args:
            building_type: DOE prototype — "SmallOffice", "MediumOffice", "LargeOffice",
                "SmallHotel", "LargeHotel", "Warehouse", "RetailStandalone",
                "RetailStripmall", "QuickServiceRestaurant", "FullServiceRestaurant",
                "MidriseApartment", "HighriseApartment", "Hospital", "Outpatient",
                "SuperMarket", "SecondarySchool", "PrimarySchool"
            total_bldg_floor_area: Total floor area in ft² (default 10000)
            num_stories_above_grade: Stories above grade, fractional OK (default 1)
            num_stories_below_grade: Basement stories (default 0)
            floor_height: Floor-to-floor height in ft (0 = smart default by type)
            template: Standards template — "90.1-2019", "90.1-2016", "90.1-2013", etc.
            climate_zone: ASHRAE climate zone or "Lookup From Stat File"
            wwr: Window-to-wall ratio 0-1 (0 = smart default by building type)
            ns_to_ew_ratio: Aspect ratio (0 = smart default)
            building_rotation: Clockwise rotation from north in degrees
            bar_division_method: "Multiple Space Types - Individual Stories Sliced"
                or "Multiple Space Types - Building Type Ratios"
            story_multiplier: "Basements Ground Mid Top" or "None"
            bar_width: Bar width in ft (0 = auto from perimeter multiplier)

        """
        return create_bar_building(
            building_type=building_type,
            total_bldg_floor_area=total_bldg_floor_area,
            num_stories_above_grade=num_stories_above_grade,
            num_stories_below_grade=num_stories_below_grade,
            floor_height=floor_height,
            template=template,
            climate_zone=climate_zone,
            wwr=wwr,
            ns_to_ew_ratio=ns_to_ew_ratio,
            building_rotation=building_rotation,
            bar_division_method=bar_division_method,
            story_multiplier=story_multiplier,
            bar_width=bar_width,
        )

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

    @mcp.tool(name="create_new_building")
    def create_new_building_tool(
        building_type: str = "SmallOffice",
        total_bldg_floor_area: float = 10000,
        num_stories_above_grade: float = 1.0,
        num_stories_below_grade: int = 0,
        floor_height: float = 0,
        wwr: float = 0,
        ns_to_ew_ratio: float = 0,
        building_rotation: float = 0,
        bar_division_method: str = "Multiple Space Types - Individual Stories Sliced",
        story_multiplier: str = "Basements Ground Mid Top",
        bar_width: float = 0,
        weather_file: str | None = None,
        climate_zone: str = "Lookup From Stat File",
        template: str = "90.1-2019",
        system_type: str = "Inferred",
        htg_src: str = "NaturalGas",
        clg_src: str = "Electricity",
        swh_src: str = "Inferred",
        add_hvac: bool = True,
        add_swh: bool = True,
    ):
        """Create a complete building from scratch in one call.

        Chains: empty model -> [change_building_location] -> create_bar -> create_typical.
        Creates geometry, space types, constructions, loads, HVAC, schedules, SWH.
        All geometry units are imperial (ft, ft²).

        Args:
            building_type: DOE prototype — "SmallOffice", "LargeOffice",
                "RetailStandalone", "PrimarySchool", "Hospital", etc.
            total_bldg_floor_area: Total floor area in ft² (default 10000)
            num_stories_above_grade: Stories above grade (default 1)
            num_stories_below_grade: Basement stories (default 0)
            floor_height: Floor-to-floor height in ft (0 = smart default)
            wwr: Window-to-wall ratio 0-1 (0 = smart default)
            ns_to_ew_ratio: Aspect ratio (0 = smart default)
            building_rotation: Rotation from north in degrees
            bar_division_method: Bar space division method
            story_multiplier: Story multiplier grouping
            bar_width: Bar width in ft (0 = auto)
            weather_file: Absolute path to EPW weather file (optional)
            climate_zone: ASHRAE climate zone or "Lookup From Stat File"
            template: ASHRAE standard — "90.1-2019", etc.
            system_type: HVAC system — "Inferred" or specific type
            htg_src: Heating fuel — "NaturalGas", "Electricity", etc.
            clg_src: Cooling fuel — "Electricity" or "DistrictCooling"
            swh_src: SWH fuel — "Inferred", "NaturalGas", "Electricity"
            add_hvac: Add HVAC system (default True)
            add_swh: Add service water heating (default True)

        """
        return create_new_building(
            building_type=building_type,
            total_bldg_floor_area=total_bldg_floor_area,
            num_stories_above_grade=num_stories_above_grade,
            num_stories_below_grade=num_stories_below_grade,
            floor_height=floor_height,
            wwr=wwr,
            ns_to_ew_ratio=ns_to_ew_ratio,
            building_rotation=building_rotation,
            bar_division_method=bar_division_method,
            story_multiplier=story_multiplier,
            bar_width=bar_width,
            weather_file=weather_file,
            climate_zone=climate_zone,
            template=template,
            system_type=system_type,
            htg_src=htg_src,
            clg_src=clg_src,
            swh_src=swh_src,
            add_hvac=add_hvac,
            add_swh=add_swh,
        )
