# Geometry Workflows Research

Research on how to create building models from scratch using OpenStudio measures.
Two major workflows exist, both converging at `create_typical_building_from_model`.

## Workflow 1: Bar Geometry (ComStock)

Creates rectangular bar geometry from high-level parameters. Best for quick
parametric studies, stock modeling, and when custom geometry isn't needed.

### Measure Chain

```
1. ChangeBuildingLocation          -- weather file + climate zone
2. simulation_settings             -- timestep, run period
3. create_bar_from_building_type_ratios  -- geometry + space types
4. create_typical_building_from_model    -- constructions, loads, HVAC, SWH, schedules
5. set_*_template measures         -- (optional) baseline overrides
6. hardsize_model                  -- (optional) autosize then hardsize
```

### create_bar_from_building_type_ratios

Source: `openstudio-model-articulation-gem`, bundled in ComStock at
`/opt/comstock-measures/create_bar_from_building_type_ratios/`

**What it creates:** Spaces, surfaces, fenestration, thermal zones, building
stories, space types with `standardsBuildingType` and `standardsSpaceType` set.

**What it does NOT create:** Constructions, loads, HVAC, SWH, schedules.

**Delegates to:** `OpenstudioStandards::Geometry.create_bar_from_building_type_ratios(model, args)`

#### Key Arguments (~35 total, most have smart defaults)

| Argument | Type | Default | Notes |
|----------|------|---------|-------|
| `bldg_type_a` | Choice | SmallOffice | Primary building type (DOE prototypes) |
| `bldg_type_b/c/d` | Choice | SmallOffice | Up to 4 mixed types |
| `bldg_type_b/c/d_fract_bldg_area` | Double | 0.0 | Fraction of area per type |
| `total_bldg_floor_area` | Double (ft^2) | 10000 | Total building area |
| `single_floor_area` | Double (ft^2) | 0 | 0 = derive from total/stories |
| `num_stories_above_grade` | Double | 1.0 | Fractional stories OK |
| `num_stories_below_grade` | Integer | 0 | |
| `floor_height` | Double (ft) | 0 | 0 = smart default by bldg type |
| `ns_to_ew_ratio` | Double | 0 | 0 = smart default |
| `wwr` | Double | 0 | 0 = smart default by bldg type |
| `building_rotation` | Double (deg) | 0 | Clockwise from north |
| `template` | Choice | 90.1-2004 | Standards template |
| `climate_zone` | Choice | Lookup From Stat File | ASHRAE zone or CEC zone |
| `bar_width` | Double (ft) | 0 | Overrides perim_mult if nonzero |
| `bar_division_method` | Choice | "Multiple Space Types - Individual Stories Sliced" | |
| `story_multiplier` | Choice | "Basements Ground Mid Top" | |
| `party_wall_fraction` | Double | 0 | Fraction of ext wall area |
| `party_wall_stories_north/south/east/west` | Integer | 0 | Party walls by direction |
| `neighbor_height_north/south/east/west` | Double (ft) | 0 | Shading surfaces |
| `bottom_story_ground_exposed_floor` | Bool | true | |
| `top_story_exterior_exposed_roof` | Bool | true | |
| `double_loaded_corridor` | Choice | "Primary Space Type" | |
| `use_upstream_args` | Bool | true | Read args from prior OSW steps |

#### Supported Building Types

SmallOffice, MediumOffice, LargeOffice, SmallHotel, LargeHotel, Warehouse,
RetailStandalone, RetailStripmall, QuickServiceRestaurant, FullServiceRestaurant,
MidriseApartment, HighriseApartment, Hospital, Outpatient, SuperMarket,
SecondarySchool, PrimarySchool

### create_typical_building_from_model

Source: `openstudio-model-articulation-gem`, bundled in ComStock at
`/opt/comstock-measures/create_typical_building_from_model/`

**What it expects:** Model with geometry + space types that have
`standardsBuildingType` and `standardsSpaceType` set.

**What it creates:** Constructions, internal loads (people, lights, equipment),
schedules, HVAC, SWH, thermostats, elevators, exhaust fans, refrigeration,
exterior lights, internal mass.

**Delegates to:** `OpenstudioStandards::CreateTypical.create_typical_building_from_model(model, template, ...)`

#### Key Arguments (~30 total)

| Argument | Type | Default | Notes |
|----------|------|---------|-------|
| `template` | Choice | 90.1-2010 | Standards year |
| `system_type` | Choice | Inferred | 155+ HVAC options |
| `hvac_delivery_type` | Choice | Forced Air | Forced Air, Hydronic, Inferred |
| `htg_src` | Choice | NaturalGas | Electricity, DistrictHeating, DistrictAmbient, Inferred |
| `clg_src` | Choice | Electricity | DistrictCooling, DistrictAmbient, Inferred |
| `swh_src` | Choice | Inferred | NaturalGas, Electricity, HeatPump |
| `climate_zone` | Choice | Lookup From Model | ASHRAE zone string |
| `add_constructions` | Bool | true | |
| `wall_construction_type` | Choice | Inferred | Mass, Metal Building, SteelFramed, WoodFramed |
| `add_space_type_loads` | Bool | true | People, lights, equipment |
| `add_hvac` | Bool | true | (NOTE: default varies by gem version) |
| `add_swh` | Bool | true | |
| `add_thermostat` | Bool | true | |
| `add_elevators` | Bool | true | |
| `add_internal_mass` | Bool | true | |
| `add_exterior_lights` | Bool | true | |
| `add_exhaust` | Bool | true | Kitchen/restroom fans |
| `add_refrigeration` | Bool | true | |
| `kitchen_makeup` | Choice | Adjacent | None, Largest Zone |
| `exterior_lighting_zone` | Choice | "3 - All Other Areas" | 0-4 zones |
| `onsite_parking_fraction` | Double | 1.0 | |
| `modify_wkdy_op_hrs` | Bool | false | Custom weekday schedule |
| `wkdy_op_hrs_start_time` | Double | 8.0 | |
| `wkdy_op_hrs_duration` | Double | 8.0 | |
| `modify_wknd_op_hrs` | Bool | false | Custom weekend schedule |
| `unmet_hours_tolerance` | Double | 1.0 | Degrees Rankine |
| `remove_objects` | Bool | true | Clean non-geometry objects first |
| `use_upstream_args` | Bool | true | Read args from prior OSW steps |

### use_upstream_args Behavior

When both measures run in the same OSW with `use_upstream_args=true`,
`create_typical` auto-reads `template` and `climate_zone` from `create_bar`'s
registered values. In our MCP tool approach (separate `apply_measure` calls),
this won't work — must pass args explicitly to both.

---

## Workflow 2: FloorspaceJS (Custom Geometry)

User draws geometry in FloorspaceJS editor, exports JSON, then populates
with standards-based systems. Best for custom building shapes, real projects.

### Measure Chain

```
1. merge_floorspace_js_with_model  -- import geometry from JSON
2. ChangeBuildingLocation          -- weather file + climate zone
3. create_typical_building_from_model  -- constructions, loads, HVAC, SWH, schedules
```

Only 3 measures needed. `merge_floorspace_js_with_model` is a do-everything
geometry measure that handles:
- FloorspaceJS JSON → OSM geometry translation
- Surface intersection and matching
- Thermal zone creation for unzoned spaces
- Space type `standardsSpaceType` assignment from FloorspaceJS names
- Duplicate vertex cleanup

### What is FloorspaceJS?

A free, open-source 2D floor-plan editor built as a JavaScript widget.
Developed by Devetry, debuted in OpenStudio 2.3.0. Replaces the deprecated
SketchUp plugin. Runs in web browsers or embedded in OpenStudio Application.

Source: https://github.com/NatLabRockies/floorspace.js
DOE article: https://www.energy.gov/cmei/buildings/articles/openstudio-world-flat

Key features:
- Grid-based drawing, story-by-story floor plan definition + extrusion
- Space/zone/space-type awareness for energy modeling
- Interior spaces, windows, doors, shades, daylighting sensors
- Import floor-plan images or maps as drawing underlay
- "Import-merge" model: save JSON, OpenStudio imports + merges without losing
  non-geometry data (schedules, HVAC) during iterative editing

### FloorspaceJS JSON Schema

Source: `NatLabRockies/floorspace.js/schema/geometry_schema.json`

```
Top-level properties:
  version, application, project
  stories          -- building stories with geometry + spaces
  building_units   -- grouping of spaces
  thermal_zones    -- zone definitions (id, name, color)
  space_types      -- space type definitions (id, name, color)
  construction_sets
  window_definitions
  door_definitions
  daylighting_control_definitions
  pitched_roofs

Story contains:
  id, name, geometry (vertices/edges/faces), spaces, shading, windows, doors
  below_floor_plenum_height, floor_to_ceiling_height, above_ceiling_plenum_height
  multiplier

Space contains:
  id, name, face_id, thermal_zone_id, space_type_id, construction_set_id
  building_type_id, template, open_to_below, floor_offset
  below_floor_plenum_height, floor_to_ceiling_height, above_ceiling_plenum_height
```

Default library ships with 32 space types (e.g. "189.1-2009 - Office - Vending"),
7 construction sets, 8 window definitions.

**Key limitation:** Space types in FloorspaceJS have names but NO standards
fields (`standardsBuildingType`, `standardsSpaceType`). The merge measure
sets `standardsSpaceType` from the FloorspaceJS space type name. These names
must match openstudio-standards space type names (e.g., "Office", "Corridor",
"Lobby") for `create_typical_building_from_model` to work correctly.

### SDK-Native Alternative (No Measure Needed)

FloorspaceJS import is available directly in the OpenStudio Python SDK:

```python
import openstudio

# Load FloorspaceJS JSON
rt = openstudio.model.FloorspaceReverseTranslator()
result = rt.modelFromFloorspace(json_string)
if result.is_initialized():
    new_model = result.get()

# Merge into existing model
mm = openstudio.model.ModelMerger()
mm.mergeModels(model, new_model, rt.handleMapping())
```

Confirmed available in OpenStudio 3.11.0 Python bindings:
- `openstudio.model.FloorspaceReverseTranslator` — `.modelFromFloorspace(json)`
- `openstudio.model.ModelMerger` — `.mergeModels(target, source, mapping)`
- `openstudio.FloorplanJS` — `.load(json)`, `.toThreeScene()`

The SDK-native approach means we could build a Python tool that imports
FloorspaceJS without needing the Ruby measure. But we'd need to replicate
the surface matching, thermal zone creation, and space type assignment that
the measure does.

### Standalone Measures (Not Needed in FloorspaceJS Workflow)

These exist in `openstudio-model-articulation-gem` but are NOT needed when
using `merge_floorspace_js_with_model` (it does all of this internally):

| Measure | What It Does | Notes |
|---------|-------------|-------|
| `create_and_assign_thermal_zones_for_unassigned_spaces` | Creates ThermalZone for each unzoned space | Zero arguments |
| `SurfaceMatching` | Intersects + matches surfaces | 1 arg: `intersect_surfaces` (bool) |
| `AssignSpaceTypeBySpaceName` | Maps name string → space type | Manual, one-at-a-time |
| `SpaceTypeAndConstructionSetWizard` | Creates DOE space types + construction sets | Not needed with create_typical |

We already have native SDK equivalents for some of these:
- `match_surfaces` tool (geometry skill) — surface matching
- `create_thermal_zone` tool (spaces skill) — zone creation

---

## Workflow 3: URBANopt (GeoJSON → OSM)

URBANopt starts from GeoJSON (urban-scale site layout) and creates individual
building models. This is a district-scale workflow.

### Key Repos

| Repo | Purpose |
|------|---------|
| [urbanopt-geojson-gem](https://github.com/urbanopt/urbanopt-geojson-gem) | GeoJSON → OpenStudio model translation |
| [urbanopt-cli](https://github.com/urbanopt/urbanopt-cli) | CLI orchestrator, contains workflow OSW templates |
| [urbanopt-example-geojson-project](https://github.com/urbanopt/urbanopt-example-geojson-project) | Example project |

### URBANopt GeoJSON Workflow

```
GeoJSON (site) → Feature (building footprint) → OSW per building → OSM models
```

1. GeoJSON contains building footprints with metadata (building_type, stories,
   floor_area, construction_year, etc.)
2. `urbanopt-geojson-gem` translates each Feature into an OpenStudio model:
   - Extrudes 2D footprint to 3D geometry
   - Creates perimeter+core zoning
   - Assigns space types based on building_type
3. OSW runs measures on each building model

### URBANopt Createbar OSW (Actual)

Source: `urbanopt-cli/example_files/mappers/createbar_workflow.osw`

```json
steps:
  1. set_run_period                        -- timestep=4, begin/end dates
  2. ChangeBuildingLocation                -- weather_file_name, climate_zone
  3. create_bar_from_building_type_ratios  -- bldg_type_a, floor_area, stories, etc.
  4. create_typical_building_from_model    -- add_hvac=true, add_refrigeration=true
  5. PredictedMeanVote                     -- (reporting)
  6. IncreaseInsulationRValueForExteriorWalls  -- (SKIP=true, upgrade placeholder)
  7. ReduceElectricEquipmentLoadsByPercentage  -- (SKIP=true)
  8. ReduceLightingLoadsByPercentage            -- (SKIP=true)
  9. envelope_and_internal_load_breakdown  -- (reporting)
  10. generic_qaqc                          -- (reporting)
  11. default_feature_reports               -- (reporting)
  12. openstudio_results                    -- (reporting)
```

Simple workflow: set_run_period → location → create_bar → create_typical → reports.

### URBANopt FloorspaceJS OSW (Actual)

Source: `urbanopt-cli/example_files/mappers/floorspace_workflow.osw`

This OSW is a superset containing ALL workflow variants with `__SKIP__` flags.
The FloorspaceJS path enables only:

```json
steps (FloorspaceJS path):
  1. set_run_period
  2. ChangeBuildingLocation 1              -- (SKIP=true for floorspace)
  3. create_bar_from_building_type_ratios  -- (SKIP=true for floorspace)
  4. merge_floorspace_js_with_model        -- floorplan_path: "../files/office_floorplan.json"
  5. ChangeBuildingLocation 2              -- weather + climate_zone (AFTER merge)
  6. create_typical_building_from_model 1  -- add_hvac=false, add_refrigeration=false
  7. blended_space_type_from_model         -- blend_method: "Building Story"
  8. urban_geometry_creation               -- (SKIP=true for floorspace)
  9. create_typical_building_from_model 2  -- add_hvac=true, everything else false,
                                              use_upstream_args=false
  10. reporting measures...
```

**Key pattern:** URBANopt runs `create_typical` TWICE:
- Pass 1: loads/constructions only (`add_hvac=false`)
- `blended_space_type_from_model` — blends multi-zone space types per story
- Pass 2: HVAC only (`add_hvac=true`, `use_upstream_args=false`)

This handles blended space types correctly where HVAC sizing depends on
blended loads. Note `ChangeBuildingLocation` comes AFTER merge (the merge
can strip climate zone assignments).

### URBANopt Baseline (GeoJSON Footprint) OSW — Most Complex

Source: URBANopt agent research of `urbanopt-example-geojson-project`

This is the full pipeline where actual GeoJSON polygon footprints replace
bar geometry. It's the most complex workflow:

```
1. ChangeBuildingLocation 1              -- weather + climate zone
2. create_bar_from_building_type_ratios  -- temporary bar geometry + space types
3. create_typical_building_from_model 1  -- add_hvac=false (loads/constructions only)
4. blended_space_type_from_model         -- blend per-story space types
5. urban_geometry_creation               -- replace bar with GeoJSON footprint
     (creates spaces, zones, surface matching, shading, windows)
     (transfers blended space types from bar model to new geometry)
6. create_typical_building_from_model 2  -- add_hvac=true only
7. reporting measures
```

The `urban_geometry_creation_zoning` variant does core+perimeter zoning.
Both variants handle thermal zone creation, surface matching, and shading
surfaces internally in `building.rb`.

### Thermal Zone + Surface Matching Summary

| Workflow | Zone Creation | Surface Matching |
|----------|-------------|-----------------|
| CreateBar | `create_bar` does it internally | `create_bar` does it internally |
| FloorspaceJS | `merge_floorspace_js` does it | `merge_floorspace_js` does it (partially — may be commented out in some versions) |
| GeoJSON | `urban_geometry_creation` via `building.rb` | `urban_geometry_creation` internally |
| All | `create_and_assign_thermal_zones_for_unassigned_spaces` available as backup | `SurfaceMatching` available as backup |

### Relevance to openstudio-mcp

We won't build the URBANopt GeoJSON workflow in openstudio-mcp (it's
district-scale, not single-building). But the patterns are useful:
- Two-pass `create_typical` for blended space types (advanced use case)
- The FloorspaceJS variant is directly applicable
- Weather file should be set early in the workflow
- `blended_space_type_from_model` only needed when geometry is replaced
  after space types are assigned (GeoJSON workflow). Not needed for bar
  or FloorspaceJS workflows.

---

## Comparison: All Three Workflows

| Step | Bar (ComStock) | FloorspaceJS | URBANopt GeoJSON |
|------|---------------|-------------|-----------------|
| Input | Building type + area + stories | User-drawn JSON | GeoJSON footprints |
| Geometry | `create_bar` measure | `merge_floorspace_js` measure or SDK | `urban_geometry_creation` |
| Surface matching | Done by create_bar | Done by merge measure / SDK | Done by geometry creation |
| Thermal zones | Done by create_bar | Done by merge measure / SDK | Done by geometry creation |
| Space types | Done by create_bar (from ratios) | From FloorspaceJS names | From GeoJSON metadata |
| Weather | ChangeBuildingLocation | ChangeBuildingLocation | ChangeBuildingLocation |
| Systems | `create_typical` | `create_typical` | `create_typical` (2-pass) |
| Best for | Parametric studies, stock modeling | Custom buildings, real projects | District-scale analysis |

---

## Common Gotchas

1. **Climate zone must be set before create_typical.** Either via
   ChangeBuildingLocation, explicit `climate_zone` arg, or model's ClimateZones
   object. Our `create_typical_building` wrapper already handles this.

2. **`add_hvac` default varies.** ComStock version defaults to `true`. The
   articulation gem version may default to `false`. Always set explicitly.

3. **`use_upstream_args` irrelevant for MCP.** Since we call measures in
   separate OSW runs, upstream arg passing doesn't work. Pass all args explicitly.

4. **FloorspaceJS space type names must match standards names.** If the user
   names a space type "Conference Room" but standards expects "Conference", the
   mapping will fail silently.

5. **Units are imperial.** `create_bar` uses ft^2 for area and ft for heights.
   Wrapper tools should document this clearly or convert from metric.

6. **ChangeBuildingLocation must come AFTER merge_floorspace_js.** The merge
   can strip climate zone assignments from the model.

7. **Weather file path:** The measure needs to find the EPW file. In our
   `apply_measure` setup, the OSW's `file_paths` includes the EPW directory.

---

## Implementation Plan

### Phase A: Bar Workflow + Convenience Tool -- COMPLETE

**Tool 1: `create_bar_building`**
- Wraps `create_bar_from_building_type_ratios` measure
- Creates empty model internally, saves, applies measure, reloads
- `use_bundle=False` (same as create_typical)
- Expose args with smart defaults:
  - `building_type` (SmallOffice default)
  - `total_bldg_floor_area` (ft2, 10000 default)
  - `num_stories_above_grade` (1 default)
  - `num_stories_below_grade` (0 default)
  - `floor_height` (ft, 0=smart default)
  - `template` (90.1-2019 default)
  - `climate_zone` (Lookup From Stat File default)
  - `wwr` (0=smart default)
  - `ns_to_ew_ratio` (0=smart default)
  - `building_rotation` (0 default)
  - `bar_division_method` (expose)
  - `story_multiplier` (expose)
  - `bar_width` (ft, 0=auto)

**Tool 2: `create_typical_building`** (existing, no changes)

**Tool 3: `create_new_building`** (convenience, chains measures)
- Merges args from create_bar + create_typical into one call
- Calls `change_building_location` (already wrapped in common_measures) if
  `weather_file` provided (sets weather + climate zone). Uses common-measures
  version at `/opt/common-measures/ChangeBuildingLocation/` — NOT the ComStock
  version which has different args (grid_region, soil_conductivity).
- `weather_file` is optional. If omitted, `climate_zone` must be passed
  explicitly to create_bar (or user sets it later before create_typical).
- Flow: empty model → [ChangeBuildingLocation] → create_bar → create_typical
- Single tool for "I want a building from scratch"

**Also (cleanup):**
- [x] Deprioritize `create_baseline_osm` in prompts/skills (kept registered — 30+ tests use it via MCP)
- [x] Updated prompts to use create_new_building instead
- [x] Updated new-building SKILL.md with all 3 workflows (A/B/C)
- [x] Updated tool catalog resource with new tools
- [x] Update CLAUDE.md tool counts

**Integration tests:**
- create_bar standalone (verify spaces, zones, surfaces, space types)
- create_bar → create_typical chain (verify HVAC, constructions, loads)
- create_new_building end-to-end with weather file
- Multiple building types (SmallOffice, LargeOffice, RetailStandalone)
- Phase B preview: load SDDC Office seed.osm → create thermal zones (Python SDK)
  → create_typical_building → verify HVAC/loads populated on FloorspaceJS geometry
  (tests/assets/sddc_office/seed.osm already has 44 spaces, 328 surfaces,
  12 space types with standardsBuildingType=Office, zero zones/HVAC)

### Phase B: FloorspaceJS Import -- COMPLETE

**Tool 4: `import_floorspacejs`** (implemented SDK-native, no Ruby measure)
- Uses SDK FloorspaceReverseTranslator (no measure bundling needed)
- Creates thermal zones with dual-setpoint thermostats (required for
  create_typical to see "conditioned zones")
- Maps DOE prototype names to openstudio-standards internal names
  (e.g. SmallOffice -> Office + WholeBuilding - Sm Office)
- Runs surface intersection and matching
- Full workflow: import_floorspacejs -> set_weather -> create_typical

**Test assets (already downloaded to `tests/assets/sddc_office/`):**
- `floorplan.json` — 513KB FloorspaceJS, 2 stories, 12 space types, 44 spaces
- `seed.osm` — 930KB, geometry baked in (44 spaces, 328 surfaces, 14 windows,
  space types with standardsBuildingType=Office, NO thermal zones, NO HVAC)
- Source: https://github.com/DavidGoldwasser/PAT_projects/tree/master/pat_sddc_office

**FloorspaceJS creation UX — multiple approaches to explore:**
- Accept file path (user creates in hosted editor at
  https://natlabrockies.github.io/floorspace.js/)
- Template library: pre-built FloorspaceJS JSONs for common shapes
- Generate FloorspaceJS JSON from text description (LLM-generated geometry)
- Hybrid: start from create_bar, export to FloorspaceJS, user edits, re-import
- All need testing to see what actually works for users

### Phase C: URBANopt (out of scope)
Document only. District-scale workflow belongs in a separate project.

### Phase D: AEDG / Individual Measure Workflows (future)
The SDDC Office project shows an alternative to `create_typical`: applying
individual AEDG measures for high-performance design. The "Low Energy"
alternative skips `create_typical` entirely and applies 15+ individual AEDG
measures + `nze_hvac` for a custom high-performance building. These measures
are NOT currently bundled — would need to add from BCL or PAT projects.

---

## Reference Project: PAT SDDC Office

Source: https://github.com/DavidGoldwasser/PAT_projects/tree/master/pat_sddc_office

A Parametric Analysis Tool project for Small/Medium Office AEDG analysis.
Contains FloorspaceJS geometry, 26-measure chain, 3 design alternatives.
Good test case for both bar and FloorspaceJS workflows.

### Building Description
- 2-story, ~20,000 ft2, 125x80 ft rectangular footprint
- 12 space types: Open Office, Private Office, Conference, Corridor, Lobby,
  Restroom, Data, Elevator, Stairway, Lounge, Storage, Mech/Elec
- 44 total spaces (23 on Story 1, 21 on Story 2)
- Complex interior partitioning (not simple shoebox)
- Windows: WWR=0.30, sill height=3 ft
- No thermal zones in FloorspaceJS (created by measure)

### Test Assets
- `seeds/SDDC Office Example Plan seed/floorplan.json` — 513KB FloorspaceJS
- `seeds/SDDC Office Example Plan seed.osm` — 930KB seed model
- 19 weather files covering US climate zones 1A-8A + international

### Measure Chain (26 measures)

The FloorspaceJS workflow path (Low Energy alternative):

```
 1. ChangeBuildingLocation                    -- weather + climate_zone (from stat file)
 2. create_and_assign_thermal_zones           -- zones for all spaces
 3. surface_matching_diagnostic               -- intersect + match + cleanup
 4. SetSpaceInfiltrationByExteriorSurfaceArea -- 0.05 cfm/ft2
 5. AedgSmallToMediumOfficeElectricEquipment  -- AEDG equipment loads
 6. AedgSmallToMediumOfficeElectricEquipmentControls
 7. add_electric_equipment_instance_to_space  -- elevator in Space 109
 8. AedgSmallToMediumOfficeInteriorLighting   -- AEDG lighting
 9. AedgSmallToMediumOfficeInteriorLightingControls
10. AedgSmallToMediumOfficeFenestrationAndDaylightingControls
11. AedgSmallToMediumOfficeExteriorWallConstruction
12. AedgSmallToMediumOfficeExteriorDoorConstruction
13. AedgSmallToMediumOfficeRoofConstruction
14. AedgSmallToMediumOfficeInteriorFinishes
15. AedgSmallToMediumOfficeExteriorFloorConstruction
16. AedgSmallToMediumOfficeExteriorLighting
17. add_rooftop_pv                            -- (Low Energy+PV only: 75%, 18% eff)
18. AedgOfficeSwh                             -- SWH for 84 employees
19. SetThermostatSchedules                    -- heating/cooling setpoints
20. nze_hvac                                  -- DOAS with fan coil chiller+boiler
21. create_typical_doe_building_from_model    -- (SKIP in Low Energy, used in Baseline)
22. create_baseline_building                  -- (SKIP in all — placeholder for parametrics)
23-26. Reporting measures (view_model, tariff, openstudio_results, envelope breakdown)
```

### Key Pattern: Mutually Exclusive Strategies

- **"Typical 2004" alternative:** Uses `create_typical_doe_building_from_model`
  with template=90.1-2004. Skips all AEDG measures. Code-minimum baseline.
- **"Low Energy" alternative:** Skips `create_typical_doe_building_from_model`.
  Applies individual AEDG measures + `nze_hvac`. High-performance design.

This shows two valid approaches to populating a FloorspaceJS model:
1. `create_typical` for standards-based baseline (our Workflow 2)
2. Individual AEDG/ECM measures for custom high-performance design (advanced)

### Important: FloorspaceJS Needs Separate Zone + Surface Matching

Unlike `merge_floorspace_js_with_model` (which does everything internally),
this project uses the seed OSM directly (geometry already in the .osm from
FloorspaceJS) and runs zone creation + surface matching as separate measures:
- `create_and_assign_thermal_zones_for_unassigned_spaces` (step 2)
- `surface_matching_diagnostic` (step 3)

This confirms there are two FloorspaceJS sub-workflows:
- **Via merge measure:** merge_floorspace_js → ChangeBuildingLocation → create_typical
- **Via seed model:** Load OSM (with FloorspaceJS geometry baked in) → create_zones → surface_match → measures

---

## Sources

- [ComStock repo](https://github.com/NatLabRockies/ComStock) (tag 2025-3)
- [openstudio-model-articulation-gem](https://github.com/NREL/openstudio-model-articulation-gem)
- [URBANopt CLI](https://github.com/urbanopt/urbanopt-cli) — workflow OSWs
- [URBANopt Geometry Workflows](https://docs.urbanopt.net/workflows/geometry_workflows.html)
- [FloorspaceJS](https://github.com/NatLabRockies/floorspace.js)
- [DOE: OpenStudio World is Flat](https://www.energy.gov/cmei/buildings/articles/openstudio-world-flat)
- [UnmetHours: Create Typical Building](https://unmethours.com/question/71608/)
- [UnmetHours: Modeling a Typical Building](https://unmethours.com/question/100169/)
- [PAT SDDC Office Project](https://github.com/DavidGoldwasser/PAT_projects/tree/master/pat_sddc_office)
- [URBANopt createbar_workflow.osw](https://github.com/urbanopt/urbanopt-cli/blob/develop/example_files/mappers/createbar_workflow.osw)
- [URBANopt floorspace_workflow.osw](https://github.com/urbanopt/urbanopt-cli/blob/develop/example_files/mappers/floorspace_workflow.osw)
