"""MCP tool definitions for internal loads."""
from __future__ import annotations

from mcp_server.skills.loads.operations import (
    create_electric_equipment as create_electric_equipment_op,
)
from mcp_server.skills.loads.operations import (
    create_gas_equipment as create_gas_equipment_op,
)
from mcp_server.skills.loads.operations import (
    create_infiltration as create_infiltration_op,
)
from mcp_server.skills.loads.operations import (
    create_lights_definition,
    create_people_definition,
    get_load_details,
    list_electric_equipment,
    list_gas_equipment,
    list_infiltration,
    list_lighting_loads,
    list_people_loads,
)


def register(mcp):
    @mcp.tool(name="list_people_loads")
    def list_people_loads_tool(
        space_name: str | None = None,
        space_type_name: str | None = None,
        max_results: int = 10,
    ):
        """List people (occupancy) loads. Default 10 results.

        Common filters: space_name="Office 1", space_type_name="Office"

        Args:
            space_name: Filter by parent space
            space_type_name: Filter by parent space type
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_people_loads(space_name=space_name, space_type_name=space_type_name,
                                max_results=mr)

    @mcp.tool(name="list_lighting_loads")
    def list_lighting_loads_tool(
        space_name: str | None = None,
        space_type_name: str | None = None,
        max_results: int = 10,
    ):
        """List lighting loads. Default 10 results.

        Common filters: space_name="Office 1"

        Args:
            space_name: Filter by parent space
            space_type_name: Filter by parent space type
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_lighting_loads(space_name=space_name, space_type_name=space_type_name,
                                  max_results=mr)

    @mcp.tool(name="list_electric_equipment")
    def list_electric_equipment_tool(
        space_name: str | None = None,
        space_type_name: str | None = None,
        max_results: int = 10,
    ):
        """List electric equipment (plug loads). Default 10 results.

        Common filters: space_name="Office 1"

        Args:
            space_name: Filter by parent space
            space_type_name: Filter by parent space type
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_electric_equipment(space_name=space_name, space_type_name=space_type_name,
                                      max_results=mr)

    @mcp.tool(name="list_gas_equipment")
    def list_gas_equipment_tool(
        space_name: str | None = None,
        space_type_name: str | None = None,
        max_results: int = 10,
    ):
        """List gas equipment loads. Default 10 results.

        Common filters: space_name="Kitchen"

        Args:
            space_name: Filter by parent space
            space_type_name: Filter by parent space type
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_gas_equipment(space_name=space_name, space_type_name=space_type_name,
                                 max_results=mr)

    @mcp.tool(name="list_infiltration")
    def list_infiltration_tool(
        space_name: str | None = None,
        space_type_name: str | None = None,
        max_results: int = 10,
    ):
        """List infiltration objects. Default 10 results.

        Common filters: space_name="Office 1"

        Args:
            space_name: Filter by parent space
            space_type_name: Filter by parent space type
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_infiltration(space_name=space_name, space_type_name=space_type_name,
                                max_results=mr)

    @mcp.tool(name="get_load_details")
    def get_load_details_tool(load_name: str):
        """Get detailed info for any load object (people, lights, electric/gas equipment, infiltration).

        Tries each load type by name until found. Returns load_type + all fields.

        Args:
            load_name: Name of the load object
        """
        return get_load_details(load_name=load_name)

    # --- Creation tools ---

    @mcp.tool(name="create_people_definition")
    def create_people_definition_tool(
        name: str,
        space_name: str,
        people_per_area: float | None = None,
        num_people: float | None = None,
        schedule_name: str | None = None,
    ):
        """Create a people (occupancy) load and assign to a space.

        Args:
            name: Name for the people load
            space_name: Space to assign the load to
            people_per_area: People per m² of floor area (use this OR num_people)
            num_people: Absolute number of people (use this OR people_per_area)
            schedule_name: Optional ScheduleRuleset for occupancy fraction
        """
        return create_people_definition(
            name=name, space_name=space_name,
            people_per_area=people_per_area, num_people=num_people,
            schedule_name=schedule_name,
        )

    @mcp.tool(name="create_lights_definition")
    def create_lights_definition_tool(
        name: str,
        space_name: str,
        watts_per_area: float | None = None,
        lighting_level_w: float | None = None,
        schedule_name: str | None = None,
    ):
        """Create a lighting load and assign to a space.

        Args:
            name: Name for the lights load
            space_name: Space to assign the load to
            watts_per_area: Lighting power density in W/m² (use this OR lighting_level_w)
            lighting_level_w: Absolute lighting power in W (use this OR watts_per_area)
            schedule_name: Optional ScheduleRuleset for lighting fraction
        """
        return create_lights_definition(
            name=name, space_name=space_name,
            watts_per_area=watts_per_area, lighting_level_w=lighting_level_w,
            schedule_name=schedule_name,
        )

    @mcp.tool(name="create_electric_equipment")
    def create_electric_equipment_tool(
        name: str,
        space_name: str,
        watts_per_area: float | None = None,
        design_level_w: float | None = None,
        schedule_name: str | None = None,
    ):
        """Create an electric equipment (plug load) and assign to a space.

        Args:
            name: Name for the equipment
            space_name: Space to assign the load to
            watts_per_area: Equipment power density in W/m² (use this OR design_level_w)
            design_level_w: Absolute equipment power in W (use this OR watts_per_area)
            schedule_name: Optional ScheduleRuleset for equipment fraction
        """
        return create_electric_equipment_op(
            name=name, space_name=space_name,
            watts_per_area=watts_per_area, design_level_w=design_level_w,
            schedule_name=schedule_name,
        )

    @mcp.tool(name="create_gas_equipment")
    def create_gas_equipment_tool(
        name: str,
        space_name: str,
        watts_per_area: float | None = None,
        design_level_w: float | None = None,
        schedule_name: str | None = None,
    ):
        """Create a gas equipment load and assign to a space.

        Args:
            name: Name for the gas equipment
            space_name: Space to assign the load to
            watts_per_area: Gas equipment power density in W/m² (use this OR design_level_w)
            design_level_w: Absolute gas equipment power in W (use this OR watts_per_area)
            schedule_name: Optional ScheduleRuleset for equipment fraction
        """
        return create_gas_equipment_op(
            name=name, space_name=space_name,
            watts_per_area=watts_per_area, design_level_w=design_level_w,
            schedule_name=schedule_name,
        )

    @mcp.tool(name="create_infiltration")
    def create_infiltration_tool(
        name: str,
        space_name: str,
        flow_per_exterior_surface_area: float | None = None,
        ach: float | None = None,
        schedule_name: str | None = None,
    ):
        """Create an infiltration load and assign to a space.

        Args:
            name: Name for the infiltration object
            space_name: Space to assign the infiltration to
            flow_per_exterior_surface_area: Flow rate per exterior surface area in m³/s·m²
            ach: Air changes per hour
            schedule_name: Optional ScheduleRuleset for infiltration fraction
        """
        return create_infiltration_op(
            name=name, space_name=space_name,
            flow_per_exterior_surface_area=flow_per_exterior_surface_area,
            ach=ach, schedule_name=schedule_name,
        )
