# Example 9: Fenestration by Orientation

Apply different window-to-wall ratios per cardinal direction — the most common way to add glazing to a building model.

## Scenario

A designer wants to optimize glazing for energy performance: 40% south (maximize daylight), 25% north (minimize heat loss), 30% east/west (balance). They start from a baseline model that already has geometry.

## Prompt

> Load my baseline model and add windows: 40% glazing on south walls, 25% on north, 30% on east and west.

## Tool Call Sequence

```
1. create_baseline_osm(name="fenestration_study", ashrae_sys_num="03")
2. load_osm_model(osm_path="...")
3. list_surfaces()                    -- get all surfaces with azimuth
4. # Bin exterior walls by azimuth:
   #   South: 135-225°, North: 315-360° or 0-45°
   #   East: 45-135°, West: 225-315°
5. set_window_to_wall_ratio(surface_name="Story 1 South Wall", ratio=0.4)
6. set_window_to_wall_ratio(surface_name="Story 1 North Wall", ratio=0.25)
7. set_window_to_wall_ratio(surface_name="Story 1 East Wall", ratio=0.3)
8. set_window_to_wall_ratio(surface_name="Story 1 West Wall", ratio=0.3)
   ... repeat for all exterior walls ...
9. list_subsurfaces()                 -- verify all windows created
10. save_osm_model(save_path="/runs/with_fenestration.osm")
```

## Key Tools Used

| Tool                       | Purpose                                             |
| -------------------------- | --------------------------------------------------- |
| `list_surfaces`            | Find exterior walls and their azimuth (orientation) |
| `set_window_to_wall_ratio` | Add centered window by glazing ratio                |
| `get_surface_details`      | Verify net vs gross area after glazing              |
| `list_subsurfaces`         | Confirm all windows were created                    |

## Orientation Bins

| Direction | Azimuth Range | Typical WWR                            |
| --------- | ------------- | -------------------------------------- |
| South     | 135° - 225°   | 30-40% (maximize daylight/solar gain)  |
| North     | 315° - 45°    | 15-25% (minimize heat loss)            |
| East      | 45° - 135°    | 20-30% (morning sun, reduce glare)     |
| West      | 225° - 315°   | 20-30% (afternoon sun, reduce cooling) |

## Verification

After applying WWR, check via `get_surface_details`:

- `gross_area_m2` = total wall area (unchanged)
- `net_area_m2` = wall area minus window area
- Actual ratio = `1 - (net_area / gross_area)`

## Integration Test

See `tests/test_example_workflows.py::test_workflow_fenestration_by_orientation`
