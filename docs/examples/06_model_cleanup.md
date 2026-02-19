# Example 6: Model Cleanup and Organization

Rename and delete objects to clean up a model for documentation or handoff.

## Scenario

A modeler received a building model with auto-generated names ("Thermal Zone 1", "Space 1") and needs to clean it up before handing it off to a client. They also want to remove unused spaces.

## Prompt

> Rename "Thermal Zone 1" to "North Office Zone" and delete the unused "Storage Space" from the model.

## Tool Call Sequence

```
1. rename_object(object_name="Thermal Zone 1", new_name="North Office Zone")
2. delete_object(object_name="Storage Space")
3. list_spaces()        # verify deletion
4. list_thermal_zones() # verify rename
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `rename_object` | Rename any named model object |
| `delete_object` | Delete any named model object |
| `list_model_objects` | List all objects of a specific type |

## Supported Object Types (28+)

The object management tools support these types:

| Category | Types |
|----------|-------|
| **Spaces** | Space, ThermalZone, BuildingStory |
| **HVAC** | AirLoopHVAC, PlantLoop, all 15 component types |
| **Loads** | People, Lights, ElectricEquipment, GasEquipment, SpaceInfiltrationDesignFlowRate |
| **Constructions** | Construction, StandardOpaqueMaterial |
| **Schedules** | ScheduleRuleset |

## Cascade Warnings

Deleting a Space will also remove its child objects (surfaces, loads). The tool returns a warning with a count of affected children.

Use `object_type` parameter for disambiguation when multiple objects share a name:

```
delete_object(object_name="MySchedule", object_type="ScheduleRuleset")
```

## Integration Test

See `tests/test_example_workflows.py::test_workflow_model_cleanup`
