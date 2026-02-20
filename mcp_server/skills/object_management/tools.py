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

        Supports spaces, zones, stories, HVAC loops, coils, fans, pumps,
        plant equipment, loads, constructions, materials, schedules.

        Warning: deleting a Space also removes its surfaces and loads.
        Requires a model to be loaded via load_osm_model_tool first.
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

        Supports the same types as delete_object_tool.
        Requires a model to be loaded via load_osm_model_tool first.
        """
        return rename_object(
            object_name=object_name,
            new_name=new_name,
            object_type=object_type,
        )

    @mcp.tool(name="list_model_objects")
    def list_model_objects_tool(object_type: str):
        """List all objects of a given type in the loaded model.

        Args:
            object_type: Type to list (e.g. "Space", "ThermalZone",
                "BoilerHotWater", "ScheduleRuleset")

        Returns name and handle for each object of that type.
        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_model_objects(object_type=object_type)
