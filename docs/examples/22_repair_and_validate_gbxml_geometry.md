# Example 22: Repairing & Validating gbXML-Imported Geometry

Catch overlapping surfaces and non-enclosed spaces from a gbXML import in one call, instead of a long manual diagnostic chain.

## Scenario

After `import_gbxml` (Example 21), a modeler wants to know whether the geometry Revit exported is
actually clean before doing anything else with it. The manual way to check this — `get_model_summary`,
`validate_model`, `list_surfaces`, `get_surface_details` per surface, `list_spaces(detailed=true)`,
`get_space_details` per space — is a long chain of separate tool calls, each a full round trip.
`repair_and_validate_gbxml_geometry` moves that whole diagnostic into one server-side call.

## Prompt

> I just imported a gbXML file. Check the geometry for overlapping surfaces and spaces that aren't
> fully enclosed before I do anything else with it.

## Tool Call Sequence

```
1. import_gbxml(gbxml_path="/inputs/25_SpacesOneZE.xml",
                 epw_path="/inputs/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
2. repair_and_validate_gbxml_geometry()
   → runs match_surfaces() internally first (fixes cross-space shared walls —
     156 surfaces matched on this model), then reports what that can't fix:
   { ok: false,
     cross_space_surfaces_matched: 156,
     space_count: 25, surface_count: 228,
     overlapping_surfaces_count: 0, overlapping_surfaces: [],
     non_enclosed_spaces_count: 14,
     non_enclosed_spaces: [
       {"space": "aim2860", "floor_area_m2": 7.46, "has_floor": true, "has_roofceiling": true},
       ... ] }
```

Two calls total, replacing what would otherwise be dozens.

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `import_gbxml` | Translate gbXML -> OSM (Example 21) |
| `repair_and_validate_gbxml_geometry` | Fix cross-space shared walls (`match_surfaces()`, internal), then report same-space overlaps and non-enclosed spaces in one call |
| `get_surface_details` | Only needed afterward, for a specific flagged surface pair, if the summary isn't enough to act on |

## Why Two Separate Checks

- **Same-space overlaps** (e.g. an accidental duplicate Floor surface): OpenStudio's own
  `intersectSurfaces()`/`matchSurfaces()` — what `match_surfaces()` calls — explicitly refuse to
  touch two surfaces within the *same* space; they only reconcile shared walls *between* adjacent
  spaces. There's no SDK method for same-space duplicate detection, so this is computed directly:
  coincident-plane surfaces (`Plane.equal`/`Plane.reverseEqual`) are checked for true 2D overlap
  area via `openstudio.intersect()` — not just `openstudio.intersects()`, which returns `True` even
  for two surfaces that merely *touch* along a shared edge (e.g. adjacent wall segments split at a
  window), which would otherwise flood the report with false positives.
- **Non-enclosed spaces**: `Space.volume()` never signals failure — on non-manifold geometry it
  silently falls back to `ceilingHeight() * floorArea()` and only logs a C++ warning. The robust
  check is the boolean `Space.isEnclosedVolume()`. On the fixture above, all 14 flagged spaces
  *do* have both a Floor and a RoofCeiling surface (`has_floor`/`has_roofceiling` both `true`) —
  the actual defect is small non-manifold gaps between wall surfaces, which a naive
  "does a Floor/RoofCeiling exist" check would have missed entirely.

## Common Pitfalls

- **`overlapping_surfaces_count == 0` doesn't mean the geometry is perfect** — it means no *same-space*
  duplicate overlaps were found. `non_enclosed_spaces_count` is a separate, independent signal.
- **The response has a side effect**: `repair_and_validate_gbxml_geometry()` mutates the model via
  `match_surfaces()` before reporting (by design — the majority "shared wall left as Outdoors" case
  gets fixed for free). If you need to inspect the model *before* any matching runs, call
  `match_surfaces()` yourself only after checking, or save a copy of the model first.
- **A large `non_enclosed_spaces_count` isn't necessarily a bug in the tool** — it's often a genuine
  property of the source gbXML/Revit export. Real CAD-to-gbXML translations frequently produce
  small sub-centimeter gaps between adjacent surfaces that a Floor/RoofCeiling presence check alone
  would never catch.

## Integration Test

See `tests/test_gbxml_import.py::test_repair_and_validate_gbxml_geometry_on_real_import`,
`::test_repair_and_validate_gbxml_geometry_detects_same_space_overlap`, and
`::test_repair_and_validate_gbxml_geometry_detects_non_enclosed_space`.
