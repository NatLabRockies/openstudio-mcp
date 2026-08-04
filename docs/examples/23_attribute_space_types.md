# Example 23: Attributing Space Types After gbXML Import

Give every conditioned space a standards SpaceType after `repair_and_validate_gbxml_geometry`,
either in one shot for a single-use building or through a guided, token-efficient wizard for a
mixed-use one.

## Scenario

A gbXML import produced clean geometry (Example 22) and real space-level lighting/equipment
loads translated from Revit, but no space has a standards SpaceType — nothing maps these
spaces onto OpenStudio's (Template / Building Type / Space Type) taxonomy yet.

## Prompt

> This building is mostly offices with a few conference rooms and corridors. Attribute space
> types to every conditioned space.

## Tool Call Sequence — mixed-use (wizard)

```
1. start_space_type_wizard()
   → { conditioned_space_count: 24, available_templates: ["90.1-2004", ..., "90.1-2019", ...] }

2. choose_space_type_templates(templates=["90.1-2019"])
   → { available_building_types: ["Office", "Hospital", "Warehouse", ...] }

3. choose_space_type_building_types(building_types=["Office"])
   → { valid_combo_count: 52,
       remaining_count: 24, page: 1, has_more: false,
       table_header: "idx|floor_area_m2|peak_people|lpd_w_m2|epd_w_m2|floor_elev_m|ext_wall_area_m2",
       table_rows: "0|92.3|8.0|8.0|5.0|0.0|38.1\n1|18.2|0.0|4.0|0.0|0.0|0.0\n..." }
   (Row 1's near-zero loads and small area read as a corridor; row 0 reads as open office.)

4. assign_space_type_batch(standards_template="90.1-2019", standards_building_type="Office",
                            standards_space_type="OpenOffice", space_indices=[0, 2, 5, 9, ...])
   → { space_type: "90.1-2019 - Office - OpenOffice", assigned_this_batch: 18, remaining_count: 6 }

5. assign_space_type_batch(standards_template="90.1-2019", standards_building_type="Office",
                            standards_space_type="Corridor", space_indices=[1, 4, 8, ...])
   → { remaining_count: 2 }

6. assign_space_type_batch(..., standards_space_type="Conference", space_indices=[3, 7])
   → { remaining_count: 0 }

7. finish_space_type_wizard()
   → { osm_path: "/runs/.../model.osm", spaces_assigned: 24, spaces_left_unassigned: 0,
       space_types_created: ["90.1-2019 - Office - Conference", "90.1-2019 - Office - Corridor",
                              "90.1-2019 - Office - OpenOffice"] }
```

## Tool Call Sequence — single-use (simple)

```
1. assign_space_type_simple(standards_template="90.1-2019", standards_building_type="Office",
                             standards_space_type="WholeBuilding - Sm Office")
   → { space_type: "90.1-2019 - Office - WholeBuilding - Sm Office",
       reused_existing: false, spaces_assigned: 24 }
2. save_osm_model()
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `assign_space_type_simple` | One combo, every conditioned space, one call |
| `start_space_type_wizard` | Scan conditioned spaces, list available templates |
| `choose_space_type_templates` | Narrow to templates, list their building types |
| `choose_space_type_building_types` | Narrow to building types, show the first table page |
| `get_space_type_wizard_status` | Progress + remaining table, any time |
| `assign_space_type_batch` | Assign one combo to a batch of space indices |
| `finish_space_type_wizard` | Save + end, once every space is assigned |
| `cancel_space_type_wizard` | Abandon wizard tracking (does not undo assignments) |

## Why the Table Is Compact

The space table is a pipe-delimited block keyed by a small integer index, not a list of JSON
objects with 7 repeated keys per row — and the full (template, building_type, space_type)
combo list is never sent to the caller at all, even after narrowing. `assign_space_type_batch`
validates combos server-side and only returns a short `did_you_mean` list on an actual
mismatch. Assigned indices drop out of the table automatically, so nothing needs to be
re-tracked across turns.

## Common Pitfalls

- **Building types are template-scoped**: call `choose_space_type_templates` before
  `choose_space_type_building_types` — the wizard rejects an out-of-scope building type.
- **A space type name typo** (e.g. "OpenOfice") returns `did_you_mean` suggestions rather than
  silently creating a bogus combo — use the suggestion, don't retry blindly.
- **`finish_space_type_wizard()` blocks** while any conditioned space is still unassigned;
  pass `force=True` only if some spaces are intentionally being left for later.

## Integration Test

See `tests/test_space_type_assignment.py`.
