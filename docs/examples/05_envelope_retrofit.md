# Example 3: Envelope Retrofit Analysis

Upgrade wall insulation by creating new materials, building a construction, and assigning it to exterior walls.

## Scenario

An energy auditor wants to evaluate the impact of upgrading wall insulation from R-11 to R-20 on an existing building. They load the model, create new insulation, and assign it to exterior walls.

## Prompt

> Load my existing model, show me the current wall constructions, then create a new R-20 wall and assign it to all exterior walls.

## Tool Call Sequence

```
1. load_osm_model(osm_path="/inputs/my_building.osm")
2. list_model_objects(object_type="Construction")
3. list_surfaces()
4. create_standard_opaque_material(name="R20_Insulation",
     thickness_m=0.089, conductivity_w_m_k=0.04,
     density_kg_m3=30, specific_heat_j_kg_k=1000)
5. create_construction(name="High_R_Wall",
     material_names=["Exterior Finish", "R20_Insulation", "Gypsum Board"])
6. assign_construction_to_surface(
     surface_name="Story 1 East Wall", construction_name="High_R_Wall")
   ... repeat for each exterior wall ...
7. save_osm_model(save_path="/runs/retrofitted.osm")
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `list_model_objects` | See existing wall assemblies |
| `list_surfaces` | Find exterior walls by boundary condition |
| `create_standard_opaque_material` | Define insulation properties |
| `create_construction` | Stack material layers |
| `assign_construction_to_surface` | Apply to each wall surface |

## Common Material Properties

| Material | Conductivity (W/m-K) | Density (kg/m3) | Specific Heat (J/kg-K) |
|----------|---------------------|-----------------|----------------------|
| Concrete | 1.7 | 2400 | 900 |
| Insulation (fiberglass) | 0.04 | 30 | 1000 |
| Gypsum board | 0.16 | 800 | 1090 |
| Wood | 0.15 | 600 | 1600 |
| Steel | 50.0 | 7800 | 500 |

## Integration Test

See `tests/test_example_workflows.py::test_workflow_envelope_retrofit`
