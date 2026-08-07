# Example 24: Guaranteed Climate Zone & Conditioned-Zone Volume Checks on gbXML Import

`import_gbxml` now always returns a valid ASHRAE climate zone (or a clear reason it couldn't) and
flags conditioned zones with zero or missing volume — automatically, with no extra tool call.

## Scenario

A modeler imports a real Revit gbXML export and its project EPW. The vendored
`ChangeBuildingLocation` measure tries to set the model's ASHRAE climate zone by regexing the
project's `.stat` file — but on a regex miss it doesn't fail, it silently writes the literal string
`"Lookup From Stat File"` into the model as if it were a real value. Nothing used to catch this, so
a gbXML import could quietly produce a model with a garbage "climate zone" that corrupts every
downstream ASHRAE 90.1 baseline comparison. Separately, gbXML/Revit zone-enclosure defects can leave
a conditioned thermal zone with zero or uncomputable volume, silently corrupting autosized equipment
capacities.

## Prompt

> Import this gbXML file with its project weather file, and make sure the model actually has a
> correct climate zone before I do a 90.1 baseline comparison.

## Tool Call Sequence

```
1. import_gbxml(gbxml_path="/inputs/gbxml.xml",
                 epw_path="/inputs/USA_TX_Austin-Camp.Mabry.ANGB.722544_TMYx.2009-2023.epw")
   → { ok: true,
       climate_zone: "2A",
       climate_zone_source: "stat_file",
       climate_zone_resolved: true,
       climate_zone_prior_invalid_value: "Lookup From Stat File",
       conditioned_zone_count: 74,
       zero_volume_zone_count: 0,
       zero_volume_zones: [],
       zero_volume_warning: null,
       total_errors: 0, total_warnings: 1,
       osm_path: "...", run_dir: "..." }
```

One call — the same call already needed to do the import. Contrast with Example 22, where a second
`repair_and_validate_gbxml_geometry()` call was needed for its diagnostic.

## Why `climate_zone_prior_invalid_value` is set here

This fixture's `.stat` file is from Climate.OneBuilding.org, which phrases the climate-zone line
differently from the older EnergyPlus-generated format the vendored measure's own regex expects:

```
- Climate Zone "2A" (ASHRAE Standard 169-2021)
```

No `"Climate type"` label, no trailing `**`. The measure's regex misses this entirely — it still
registers `"Can't find ASHRAE climate zone in stat file."` as a step warning (visible in
`total_warnings: 1` above) and leaves the model's `ClimateZones` object holding the literal string
`"Lookup From Stat File"`. `import_gbxml` catches this: it re-validates whatever the measure chain
left behind, and since `"Lookup From Stat File"` doesn't match a real ASHRAE code
(`[0-8][ABC]?`), it re-resolves in order:

1. Re-parse the same `.stat` file directly, with a broadened regex that accepts both the older
   `"Climate type ...**"` phrasing and this newer `"Climate Zone ..."` phrasing — succeeds here,
   `climate_zone_source: "stat_file"`.
2. If that also missed: an ASHRAE-zone-by-WMO-station lookup over a bundled ~2,560-station reference
   table — exact hash match by WMO number first, Haversine nearest-station by lat/lon second —
   `climate_zone_source: "wmo_or_geographic_lookup"`.
3. If every tier misses: `climate_zone_resolved: false` and a `climate_zone_warning` explaining why —
   `ok` stays `true`, but the zone needs `change_building_location` called explicitly before any
   90.1 baseline work.

On a `.stat` file whose climate-zone line the vendored measure's regex already handles (e.g. the
Boston fixture from Example 21), none of this triggers — `climate_zone_source: "gbxml_measure"`,
model untouched.

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `import_gbxml` | Translate gbXML -> OSM (Example 21); now also guarantees climate zone + reports zone-volume warnings |
| `change_building_location` | Manual override/retry if `climate_zone_resolved` comes back `false` |
| `repair_and_validate_gbxml_geometry` | The Space-level counterpart to the zero-volume zone check — same defect family, different unit |

## Common Pitfalls

- **`climate_zone_resolved: false` doesn't mean the import failed** — `ok` is still `true`. It means
  no tier could support a real value; fabricating one instead of flagging it would be worse, since a
  wrong climate zone silently corrupts every downstream load calc.
- **A large `zero_volume_zone_count` isn't the tool guessing wrong** — like
  `non_enclosed_spaces_count` in Example 22, it's a real signal that the source gbXML/Revit export
  has zone-enclosure gaps. Fix flagged zones the same way as any other non-enclosed-space finding:
  `repair_missing_roof_ceiling`, then re-check.
- **`climate_zone_prior_invalid_value` is absent, not `null`, on the already-valid path** — check
  with `.get("climate_zone_prior_invalid_value")` if you need to distinguish "already correct" from
  "corrected."

## Integration Test

See `tests/test_gbxml_import.py::test_import_gbxml_climate_zone_already_valid_from_measure`,
`::test_import_gbxml_resolves_climate_zone_from_stat_file_on_austin_fixture` (also covers the
conditioned-zone volume fields on the same import — the Austin fixture is large enough that it's
worth amortizing across both assertions rather than importing it twice), and
`::test_import_gbxml_falls_back_to_wmo_lookup_when_stat_file_unusable`. The WMO-hash/Haversine
lookup and `.stat`-regex logic also have direct pure-Python unit coverage in
`tests/test_gbxml_climate_zone_lookup.py`, and the zero-volume flagging branch (not reproduced by
any real fixture on hand) has lightweight-fake unit coverage in `tests/test_gbxml_zone_checks.py`.
