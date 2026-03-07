---
name: openstudio-patterns
description: OpenStudio model object relationships, tool dependencies, and common error patterns. Use when building or modifying models to ensure correct tool ordering.
user-invocable: false
---

# OpenStudio Modeling Patterns

## Object Dependency Graph

Objects must be created in dependency order. Arrows mean "must exist before."

```
Materials
  └─> Constructions
        └─> assign_construction_to_surface (needs Surface + Construction)

Spaces (geometry)
  ├─> Surfaces (auto-created by create_space_from_floor_print)
  │     └─> SubSurfaces (windows/doors on walls)
  └─> ThermalZones (assign spaces to zones)
        ├─> HVAC Systems (zones must exist before add_baseline_system)
        │     ├─> AirLoopHVAC (systems 3-8)
        │     ├─> ZoneHVACEquipment (systems 1-2, 9-10)
        │     └─> PlantLoops (systems 5, 7-8: HW/CHW/condenser)
        └─> Loads (people, lights, equipment → assigned to spaces in zones)

Schedules (referenced by loads, thermostats)

Weather (EPW + design days, needed before simulation)
```

## Typical Model Build Order

1. **Create or load model** — `create_example_osm` / `create_baseline_osm` / `load_osm_model`
2. **Geometry** — `create_space_from_floor_print` (preferred) or `create_space` + `create_surface`
3. **Match surfaces** — `match_surfaces` after all spaces created (finds shared walls)
4. **Thermal zones** — `create_thermal_zone` with `space_names`
5. **Envelope** — `create_standard_opaque_material` → `create_construction` → `assign_construction_to_surface`
6. **Glazing** — `set_window_to_wall_ratio` or `create_subsurface`
7. **Schedules** — `create_schedule_ruleset` (needed by loads)
8. **Loads** — `create_people_definition`, `create_lights_definition`, `create_electric_equipment`
9. **HVAC** — `add_baseline_system` / `add_doas_system` / `add_vrf_system`
10. **Weather** — `change_building_location` (sets EPW + design days + climate zone in one call)
11. **Simulation control** — `set_run_period`, `set_simulation_control`
12. **Save & simulate** — `save_osm_model` → `run_simulation`
13. **Results** — `extract_summary_metrics`, `extract_end_use_breakdown`, etc.

## Model Object Relationships

### Space
- Belongs to: ThermalZone (optional), BuildingStory (optional), SpaceType (optional)
- Contains: Surfaces, People, Lights, ElectricEquipment, GasEquipment, Infiltration
- Key: A space without a ThermalZone won't participate in simulation

### ThermalZone
- Contains: 1+ Spaces
- Connected to: AirLoopHVAC (optional), ZoneHVACEquipment (optional)
- Has: ThermostatSetpointDualSetpoint (heating + cooling schedules)
- Key: A zone without HVAC equipment gets no conditioning

### Surface
- Belongs to: Space
- Has: Construction (optional), AdjacentSurface (for interior walls)
- Contains: SubSurfaces (windows, doors)
- Types: Wall, Floor, RoofCeiling
- Boundary conditions: Outdoors, Ground, Surface (interior)

### Construction
- Ordered list of Material layers (outside to inside)
- Referenced by: Surfaces, SubSurfaces, DefaultConstructionSets

### AirLoopHVAC
- Supply side: Fan, Cooling Coil, Heating Coil, OutdoorAirSystem
- Demand side: AirTerminals (one per zone), zone connections
- Serves: 1+ ThermalZones

### PlantLoop
- Types: Hot Water, Chilled Water, Condenser
- Supply: Boiler/Chiller/CoolingTower + Pump
- Demand: Coils from air loops or zone equipment

## When to Use Which Creation Tool

| Goal | Tool | Notes |
|------|------|-------|
| Quick test model (1 zone) | `create_example_osm` | Minimal geometry, no HVAC |
| Baseline with HVAC (10 zones) | `create_baseline_osm` | Includes ASHRAE system, geometry, schedules |
| Custom geometry | `create_space_from_floor_print` | Preferred — auto-creates walls, floor, ceiling from polygon |
| Explicit surfaces | `create_surface` | Use only when floor print extrusion won't work |
| Typical building (standards-based) | `create_typical_building` | ComStock measure, adds constructions + loads + HVAC + schedules |

## Common Error Patterns

| Error | Cause | Fix |
|-------|-------|-----|
| `"No model loaded"` | Called a query/creation tool before loading | `load_osm_model` or `create_example_osm` first |
| `"Space 'X' not found"` | Typo or space not yet created | Check `list_spaces` for exact names |
| `"Thermal zone 'X' not found"` | Zone name mismatch in HVAC tool | Check `list_thermal_zones` for exact names |
| `"Material 'X' not found"` | Creating construction with nonexistent material | `create_standard_opaque_material` first |
| `"system_type must be 1-10"` | Invalid system number | Check `list_baseline_systems` |
| Simulation fails, no results | Missing weather file or design days | `change_building_location` (sets EPW + DDY + climate zone) |
| EUI = 0 or unreasonable | No loads, no HVAC, or no run period | Check `inspect_osm_summary` for missing objects |
| `"Output directory is not allowed"` | Path outside mounted volumes | Use `/runs/` for output, `/inputs/` for input files |

## Save vs Simulate

- `save_osm_model` — persists model to disk (`.osm` file)
- `run_simulation` — takes an OSM path + optional EPW, runs EnergyPlus in a background process
- The in-memory model and the on-disk file are separate — save before simulating if you've made changes
- Simulation results go to `/runs/<run_id>/`
