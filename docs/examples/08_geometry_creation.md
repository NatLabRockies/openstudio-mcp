# Example 8: Geometry Creation from Scratch

Build a multi-zone model from floor plans, add windows, and configure simulation settings.

## Scenario

An engineer wants to model a two-zone office from scratch: a west and east zone, each 10x10m, 3m floor-to-ceiling. They match shared walls, add 40% glazing on exterior walls, and configure the simulation run period.

## Prompt

> Create a two-zone office building. Each zone is 10m x 10m, 3m tall, side by side along the X axis. Match the shared wall, add 40% glazing on south walls, and set run period to January only.

## Tool Call Sequence

```
1.  create_example_osm(name="my_office")
2.  load_osm_model(osm_path="...")
3.  create_thermal_zone(name="Zone West")
4.  create_thermal_zone(name="Zone East")
5.  create_space_from_floor_print(
      name="West Office",
      floor_vertices=[[0,0], [10,0], [10,10], [0,10]],
      floor_to_ceiling_height=3.0,
      thermal_zone_name="Zone West")
6.  create_space_from_floor_print(
      name="East Office",
      floor_vertices=[[10,0], [20,0], [20,10], [10,10]],
      floor_to_ceiling_height=3.0,
      thermal_zone_name="Zone East")
7.  match_surfaces()                              -- shared wall → interior
8.  list_surfaces()                               -- find exterior wall names
9.  set_window_to_wall_ratio(
      surface_name="<south wall>", ratio=0.4)     -- 40% glazing
10. set_simulation_control(
      do_zone_sizing=true, do_system_sizing=true,
      run_for_sizing_periods=true)
11. set_run_period(begin_month=1, begin_day=1,
      end_month=1, end_day=31, name="January Only")
12. save_osm_model(save_path="/runs/two_zone_office.osm")
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `create_space_from_floor_print` | Extrude floor polygon into space with walls, floor, ceiling |
| `match_surfaces` | Pair shared walls between adjacent spaces as interior boundaries |
| `set_window_to_wall_ratio` | Add glazing by ratio (e.g. 0.4 = 40%) — no vertex math needed |
| `create_subsurface` | Add window/door with explicit vertices (when precise placement needed) |
| `create_surface` | Add individual surfaces with explicit vertices (advanced) |
| `set_simulation_control` | Enable/disable sizing calculations, weather file run |
| `set_run_period` | Set begin/end month/day for annual simulation |

## Geometry Tips

**`create_space_from_floor_print`** is the easiest approach — provide a 2D floor polygon and height, and OpenStudio generates all 6 surfaces (4 walls + floor + ceiling) automatically. Vertex winding order is auto-corrected.

**`match_surfaces`** is essential after creating multiple adjacent spaces. Without it, shared walls are treated as exterior "Outdoors" and heat transfer is wildly overestimated. Always call this after creating geometry.

**`set_window_to_wall_ratio`** is the practical way to add fenestration — just say "40% glazing" instead of computing vertex coordinates. Use `create_subsurface` only when you need precise window placement.

**`create_surface`** is for advanced cases: non-rectangular surfaces, skylights, or explicit control over boundary conditions.

## Integration Test

See `tests/test_example_workflows.py::test_workflow_geometry_from_scratch`
