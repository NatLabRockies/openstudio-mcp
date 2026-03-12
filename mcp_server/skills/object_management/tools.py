"""MCP tool definitions for object management."""
from __future__ import annotations

from typing import Any

from mcp_server.skills.object_management.operations import (
    delete_object,
    get_object_fields,
    list_model_objects,
    rename_object,
    set_object_property,
)


def register(mcp):
    @mcp.tool(name="delete_object")
    def delete_object_tool(
        object_name: str,
        object_type: str | None = None,
    ):
        """Delete a named object from the loaded model.

        Args:
            object_name: Name of the object to delete
            object_type: Optional type hint (e.g. "Space", "BoilerHotWater")
                for disambiguation when multiple types share a name.

        Warning: deleting a Space also removes its surfaces and loads.
        """
        return delete_object(object_name=object_name, object_type=object_type)

    @mcp.tool(name="rename_object")
    def rename_object_tool(
        object_name: str,
        new_name: str,
        object_type: str | None = None,
    ):
        """Rename a named object in the loaded model.

        Args:
            object_name: Current name of the object
            new_name: New name to assign
            object_type: Optional type hint for disambiguation

        """
        return rename_object(
            object_name=object_name, new_name=new_name, object_type=object_type,
        )

    @mcp.tool(name="list_model_objects")
    def list_model_objects_tool(
        object_type: str,
        name_contains: str | None = None,
        max_results: int = 10,
    ):
        """List objects of a given type. Accepts ANY OpenStudio type. Default 10 results.

        Accepts type names in any format:
        - CamelCase: CoilCoolingFourPipeBeam
        - IDD colon: OS:Coil:Cooling:FourPipeBeam
        - IDD underscore: OS_Coil_Cooling_FourPipeBeam

        Common types: Space, ThermalZone, AirLoopHVAC, PlantLoop,
        BoilerHotWater, ChillerElectricEIR, CoilHeatingWater, CoilCoolingWater,
        FanVariableVolume, PumpVariableSpeed, ScheduleRuleset, Construction,
        People, Lights, ElectricEquipment, ZoneHVACFourPipeFanCoil,
        SizingSystem, SizingZone, ControllerOutdoorAir.

        Args:
            object_type: Type to list (any OpenStudio type name)
            name_contains: Substring filter on object name (case-insensitive)
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_model_objects(object_type=object_type, name_contains=name_contains,
                                 max_results=mr)

    @mcp.tool(name="get_object_fields")
    def get_object_fields_tool(
        object_type: str,
        object_name: str | None = None,
        object_handle: str | None = None,
    ):
        """Read all properties of ANY model object via introspection.

        Works with any OpenStudio type — no hardcoded type registry needed.
        Returns property values and available setter methods.

        Examples:
          get_object_fields("CoilCoolingFourPipeBeam", object_name="My Coil")
          get_object_fields("SizingSystem", object_name="VAV Sizing")
          get_object_fields("BoilerHotWater", object_name="Main Boiler")

        Args:
            object_type: CamelCase, IDD colon, or IDD underscore format
            object_name: Object name (provide name or handle)
            object_handle: Object UUID handle (alternative to name)
        """
        return get_object_fields(
            object_type=object_type, object_name=object_name,
            object_handle=object_handle,
        )

    @mcp.tool(name="set_object_property")
    def set_object_property_tool(
        object_type: str,
        property_name: str,
        value: Any,
        object_name: str | None = None,
        object_handle: str | None = None,
    ):
        """Set a property on ANY model object using its official setter.

        Use get_object_fields first to discover available setters.

        Examples:
          set_object_property("BoilerHotWater", "nominalCapacity", 50000.0,
                              object_name="Main Boiler")
          set_object_property("CoilCoolingWater", "setDesignInletAirTemperature",
                              26.0, object_name="Cooling Coil")

        Args:
            object_type: CamelCase, IDD colon, or IDD underscore format
            property_name: Setter name (e.g. "setEfficiency") or getter name
                (e.g. "efficiency" — auto-derives "setEfficiency")
            value: New value (auto-coerced to match property type)
            object_name: Object name (provide name or handle)
            object_handle: Object UUID handle (alternative to name)
        """
        return set_object_property(
            object_type=object_type, property_name=property_name, value=value,
            object_name=object_name, object_handle=object_handle,
        )
