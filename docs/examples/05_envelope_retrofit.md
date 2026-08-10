# Example 3: Envelope Retrofit Analysis

Upgrade wall insulation by adding an insulation layer to the existing wall construction and assigning the upgraded assembly to exterior walls.

## Scenario

An energy auditor wants to evaluate the impact of upgrading wall insulation from R-11 to R-20 on an existing building. They load the model, review the current assembly, add insulation to it, and assign the upgraded construction to exterior walls.

## Prompt

> Load my existing model, show me the current wall constructions, then add R-20 insulation to the exterior walls.

## Tool Call Sequence

```
1. load_osm_model(osm_path="/inputs/my_building.osm")
2. list_surfaces()
3. get_construction_details(construction_name="Exterior Wall")
4. create_standard_opaque_material(name="R20_Insulation",
     thickness_m=0.089, conductivity_w_m_k=0.04,
     density_kg_m3=30, specific_heat_j_kg_k=1000)
5. add_layer_to_construction(construction_name="Exterior Wall",
     material_name="R20_Insulation")
   -- keeps all existing layers; response reports
      assembly_r_si_before / assembly_r_si_after for self-checking
6. assign_construction_to_surface(
     surface_name="Story 1 East Wall",
     construction_name="Exterior Wall + R20_Insulation")
   ... repeat for each exterior wall ...
7. save_osm_model(save_path="/runs/retrofitted.osm")
```

Do NOT rebuild the assembly with `create_construction(material_names=[...])` —
a hand-typed layer list silently drops the original membrane/finish layers and
can make the envelope worse. `assign_construction_to_surface` warns when the
assembly R of a surface decreases. Reserve `create_construction` for brand-new
assemblies where you specify every layer deliberately.

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `list_surfaces` | Find exterior walls by boundary condition |
| `get_construction_details` | Review existing layers and R-values |
| `create_standard_opaque_material` | Define insulation properties |
| `add_layer_to_construction` | Insert the layer, preserving the assembly |
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
