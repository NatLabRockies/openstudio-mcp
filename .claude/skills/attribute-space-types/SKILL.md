---
name: attribute-space-types
description: Attribute OpenStudio standards space types (Template/Building Type/Space Type) to conditioned spaces, typically after a gbXML import. Use when a model has geometry but no space types, or when asked to "attribute space types", "assign standards space types", or "run the space type wizard".
---

# Attribute Space Types

Run after `repair_and_validate_gbxml_geometry` (see the `gbxml-import` skill for that workflow)
or `import_floorspacejs`, when spaces have real geometry — and often real space-level
People/Lights/ElectricEquipment loads translated from the source file — but no `SpaceType`.
Only spaces in a **conditioned** zone (a ThermalZone with a heating+cooling thermostat) are
ever touched.

## Decide: simple or wizard

Ask the user (or infer from context) which building this is:

- **Single-use building** (all conditioned spaces are one type, e.g. an all-office building) →
  simple path, one tool call.
- **Mixed-use building** (offices + conference rooms + corridors + retail, etc.) → wizard path.

## Simple path

```
assign_space_type_simple(
    standards_template="90.1-2019",
    standards_building_type="Office",
    standards_space_type="WholeBuilding - Sm Office",
)
```

Creates one new `SpaceType` (no loads attached) and assigns it to every space in a
conditioned zone. Reuses an existing matching `SpaceType` if one already exists. Save
afterward with `save_osm_model`.

## Wizard path

Token-efficient by design: the space table and full combo list are never dumped in one shot —
the server tracks progress and only shows what's still unassigned.

1. `start_space_type_wizard()` — scans the model, returns the conditioned space count and the
   list of available standards templates (e.g. `["90.1-2004", ..., "90.1-2019", ...]`).
2. `choose_space_type_templates(templates=[...])` — one or more templates. Returns the union
   of available standards building types across them.
3. `choose_space_type_building_types(building_types=[...])` — one or more building types.
   Returns a `valid_combo_count` (sanity check only — the full list is never shown) plus the
   first page of the remaining space table: a compact pipe-delimited block, one row per space,
   keyed by a small stable `idx` (see `table_header` for column order — floor area, peak
   people, LPD, EPD, floor elevation, exterior wall area).
4. Match groups of `idx` values to a standards space type using the table's numbers (e.g. high
   LPD + high peak-people density often reads as open office; low loads + small area often
   reads as corridor/storage), then:
   `assign_space_type_batch(standards_template=..., standards_building_type=..., standards_space_type=..., space_indices=[0, 3, 7])`
   Repeat with different combos for different groups of indices. An invalid space type name
   returns `did_you_mean` suggestions rather than failing silently.
5. `get_space_type_wizard_status(page=..., page_size=...)` any time to see progress —
   `remaining_count` and a page of what's left. Already-assigned indices are removed from the
   table, so you never need to re-track which spaces are done.
6. Once `remaining_count == 0`, `finish_space_type_wizard()` saves the model and ends the
   wizard. If some spaces are intentionally left unassigned, pass `force=True`.

`cancel_space_type_wizard()` abandons the wizard's tracking only — it does not undo any
`assign_space_type_batch` calls already made (those are live model edits).

## Notes

- "Conditioned" means the zone has a dual-setpoint thermostat — the same definition used by
  `get_building_info`'s `conditioned_floor_area_m2`.
- Standards data comes directly from the OpenStudio SDK (`SpaceType.suggestedStandards*()`),
  not a file — always current with the installed OpenStudio version.
- A new `SpaceType` created by either path has zero loads. Follow up with `create_typical_building`
  or manual `create_people_definition`/`create_lights_definition`/etc. if loads are needed.
