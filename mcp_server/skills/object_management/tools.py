"""MCP tool definitions for object management."""
from __future__ import annotations

from mcp_server.skills.object_management.operations import (
    delete_object,
    list_model_objects,
    rename_object,
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
        """List objects of a given type. Default 10 results.

        Common types: Space, ThermalZone, AirLoopHVAC, PlantLoop,
        BoilerHotWater, ChillerElectricEIR, CoilHeatingWater, CoilCoolingWater,
        FanVariableVolume, PumpVariableSpeed, ScheduleRuleset, Construction,
        People, Lights, ElectricEquipment, ZoneHVACFourPipeFanCoil.

        Args:
            object_type: Type to list (see common types above)
            name_contains: Substring filter on object name (case-insensitive)
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_model_objects(object_type=object_type, name_contains=name_contains,
                                 max_results=mr)
