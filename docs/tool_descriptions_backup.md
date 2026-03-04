# MCP Tool Descriptions Backup

Extracted from all `mcp_server/skills/*/tools.py` files.

---

## server_info

### server_info/get_server_status
Return basic server health and configuration.

### server_info/get_versions
Return OpenStudio and EnergyPlus versions detected in this container.

---

## model_management

### model_management/load_osm_model
Load an OSM file and set it as the current model for all query tools.

Once loaded, you can use other tools like list_spaces, get_building_info,
list_thermal_zones, etc. to query the model without passing the path each time.

Args:
    osm_path: Path to the OSM file to load (absolute or relative)
    version_translate: Use VersionTranslator to upgrade older OSM files (default True)

Returns:
    Dict with ok=True and model summary (spaces, zones, building name) on success

### model_management/save_osm_model
Save the currently loaded model to disk.

Args:
    save_path: Optional path to save to. If not provided, saves to original load path.

Returns:
    Dict with ok=True and saved path on success

### model_management/create_example_osm
Create the built-in OpenStudio example model and save it as an OSM.

This is intended as a zero-input demo for Claude Desktop / MCP clients.
The model is written under /runs by default so it is persisted via the /runs mount.

### model_management/create_baseline_osm
Create a baseline 10-zone, 2-story commercial building model.

Produces a perimeter+core zoned building with detailed schedules, loads,
constructions, and thermostats. Optionally adds ASHRAE HVAC and windows.

Args:
    name: Model name (used for output directory)
    num_floors: Number of stories (default 2)
    floor_to_floor_height: Height per floor in meters (default 4.0)
    perimeter_zone_depth: Perimeter zone depth in meters (default 3.0, 0=single zone/floor)
    ashrae_sys_num: ASHRAE system "01"-"10", None = no HVAC
    wwr: Window-to-wall ratio 0-1, None = no windows

### model_management/list_files
List files in the mounted directories (/inputs and /runs).

Use this to discover what OSM models, EPW weather files, and simulation
outputs are available. Scans both /inputs and /runs by default.

Args:
    directory: Specific directory to list (e.g. "/inputs", "/runs"). If omitted, scans both.
    pattern: Glob pattern to filter (e.g. "*.epw", "*.osm"). Default "*" returns all files.

Returns:
    Dict with file list including name, path, size, and extension.

### model_management/inspect_osm_summary
Inspect an OSM (no simulation) and return a simple summary.

---

## simulation

### simulation/validate_osw
Validate OSW JSON and referenced files (best-effort).

If an `epw_path` override is supplied, the OSW's `weather_file` is treated
as optional during validation (the override path must exist).

### simulation/run_osw
Start an OpenStudio run asynchronously.

By default, this performs the same checks as `validate_osw_tool` before
starting a run. Set `validate_first=False` to skip validation.

### simulation/run_simulation
Run an EnergyPlus simulation from an OSM model file.

Creates a minimal OSW workflow automatically and starts the simulation.
This is the simplest way to run a simulation -- just provide an OSM path
and optionally an EPW weather file.

Use `get_run_status_tool` to poll for completion, then
`extract_summary_metrics_tool` to get results.

### simulation/get_run_status
Get current status for a run.

### simulation/get_run_logs
Return tail of logs for a run (openstudio/energyplus).

### simulation/get_run_artifacts
List important output artifacts for a run.

### simulation/cancel_run
Attempt to cancel a running job.

---

## results

### results/read_run_artifact
Read a run artifact file (text or base64 for binary).

Args:
    run_id: Run identifier
    path: Relative path within the run directory
    max_bytes: Max bytes to read (default 400KB)
    offset: Byte offset for chunked reading (default 0)

### results/extract_summary_metrics
Extract summary metrics (EUI + unmet hours) from outputs.

Args:
    run_id: Run identifier
    include_raw: Include full raw extraction dicts (default False)

### results/copy_run_artifact
Copy a run artifact to an accessible path, bypassing the MCP size limit.

Args:
    run_id: Run identifier
    path: Relative path within the run directory
    destination: Target directory (default /runs/exports/)

### results/extract_end_use_breakdown
Extract end-use energy breakdown by fuel type (heating, cooling, lighting, etc.).

Args:
    run_id: Run identifier
    units: "IP" (kBtu) or "SI" (GJ). Default "IP".

### results/extract_envelope_summary
Extract envelope U-values and areas (opaque + fenestration).

### results/extract_hvac_sizing
Extract autosized zone and system HVAC capacities/airflows.

### results/extract_zone_summary
Extract per-zone areas, conditions, and multipliers.

### results/extract_component_sizing
Extract autosized values for HVAC components (coils, fans, pumps, etc.).

Args:
    run_id: Run identifier
    component_type: Optional filter (e.g. "Coil", "Fan", "Pump", "Chiller")

### results/query_timeseries
Query time-series output variable data for a date range.

Requires output variables added via add_output_variable before simulation.

Args:
    run_id: Run identifier
    variable_name: Variable name (e.g. "Electricity:Facility")
    key_value: Key filter ("*" for all, or zone/surface name)
    start_month: Start month (1-12)
    start_day: Start day (1-31)
    end_month: End month (1-12)
    end_day: End day (1-31)
    frequency: "Zone Timestep", "Hourly", "Daily", "Monthly"
    max_points: Cap on returned data points (default 10000)

---

## building

### building/get_building_info
Get detailed information about the building object.

Returns building-level attributes including:
- Floor area (total and conditioned)
- Exterior surface and wall areas
- People density and count
- Lighting power density
- Equipment power density
- Infiltration rates
- North axis orientation
- Standards building type and number of stories

Requires a model to be loaded via load_osm_model_tool first.

### building/get_model_summary
Get a high-level summary of the entire model.

Returns counts of major object types:
- Building info (name, floor area)
- Spaces, zones, and stories
- Geometry (surfaces, subsurfaces, shading)
- Constructions and materials
- Loads (space types, people, lights, equipment)
- Schedules
- HVAC systems (air loops, plant loops, zone equipment)

Useful for understanding model scope and complexity.

Requires a model to be loaded via load_osm_model_tool first.

### building/list_building_stories
List all building stories in the model.

Returns an array of building story objects with:
- Name
- Z-coordinate (elevation)
- Floor-to-floor height
- Floor-to-ceiling height
- Number of spaces on the story
- Default construction and schedule sets

Requires a model to be loaded via load_osm_model_tool first.

---

## spaces

### spaces/list_spaces
List all spaces. Default brief: name, floor_area_m2, thermal_zone. Use get_space_details for full info.

Args:
    detailed: Return all fields (handle, volume, origin, loads counts, etc.)

### spaces/get_space_details
Get detailed information about a specific space.

Args:
    space_name: Name of the space to retrieve

Returns detailed space attributes including geometry, loads,
and assignments.

Requires a model to be loaded via load_osm_model_tool first.

### spaces/list_thermal_zones
List all thermal zones. Default brief: name, floor_area_m2, num_equipment. Use get_thermal_zone_details for full info.

Args:
    detailed: Return all fields (thermostat, schedules, equipment list, air_loop, etc.)

### spaces/get_thermal_zone_details
Get detailed information about a specific thermal zone.

Args:
    zone_name: Name of the thermal zone to retrieve

Returns detailed zone attributes including spaces, equipment,
thermostats, and HVAC connections.

Requires a model to be loaded via load_osm_model_tool first.

### spaces/create_space
Create a new space in the loaded OpenStudio model.

Args:
    name: Name for the new space
    building_story_name: Optional name of building story to assign
    space_type_name: Optional name of space type to assign

Returns the created space object with handle, name, geometry,
and assigned relationships.

Note: Newly created spaces will have zero floor area and volume
until surfaces are added. Use save_osm_model_tool to persist changes.

Requires a model to be loaded via load_osm_model_tool first.

### spaces/create_thermal_zone
Create a new thermal zone in the loaded OpenStudio model.

Args:
    name: Name for the new thermal zone
    space_names: Optional list of space names to assign to this zone

Returns the created thermal zone object with handle, name,
assigned spaces, and calculated floor area/volume.

Note: If spaces are already assigned to another zone, they will
be reassigned to this new zone. Use save_osm_model_tool to persist.

Requires a model to be loaded via load_osm_model_tool first.

---

## geometry

### geometry/list_surfaces
List all surfaces. Default brief: name, surface_type, gross_area_m2, space. Use get_surface_details for full info.

Args:
    detailed: Return all fields (boundary conditions, construction, orientation, vertices, subsurfaces)

### geometry/get_surface_details
Get detailed information about a specific surface.

Args:
    surface_name: Name of the surface to retrieve

Returns detailed surface attributes including geometry,
construction, boundary conditions, and orientation.

Requires a model to be loaded via load_osm_model_tool first.

### geometry/list_subsurfaces
List all subsurfaces (windows/doors) in the currently loaded model.

Returns array of subsurface objects with:
- Name, type (FixedWindow, OperableWindow, Door, etc.)
- Construction assignment
- Parent surface
- Multiplier
- Gross area
- Number of vertices

Requires a model to be loaded via load_osm_model_tool first.

### geometry/create_surface
Create a surface with explicit vertices in a space.

Args:
    name: Surface name
    vertices: List of [x,y,z] vertex coordinates (at least 3)
    space_name: Name of existing space to contain the surface
    surface_type: "Wall", "Floor", or "RoofCeiling" (auto-detected from tilt if omitted)
    outside_boundary_condition: "Outdoors", "Ground", or "Surface" (default "Outdoors")

Requires a model to be loaded via load_osm_model first.

### geometry/create_subsurface
Create a subsurface (window/door) on a parent surface.

Args:
    name: Subsurface name
    vertices: List of [x,y,z] vertex coordinates (coplanar with parent)
    parent_surface_name: Name of existing parent surface
    subsurface_type: "FixedWindow", "OperableWindow", "Door", or "GlassDoor"

Requires a model to be loaded via load_osm_model first.

### geometry/create_space_from_floor_print
Create a space by extruding a floor polygon to a given height.

Automatically creates floor, ceiling, and wall surfaces from the
polygon outline and height. This is the easiest way to create
geometry for a rectangular or polygonal zone.

Args:
    name: Space name
    floor_vertices: List of [x,y] or [x,y,z] floor polygon vertices
    floor_to_ceiling_height: Extrusion height in meters
    building_story_name: Optional existing building story to assign
    thermal_zone_name: Optional existing thermal zone to assign

Requires a model to be loaded via load_osm_model first.

### geometry/match_surfaces
Intersect and match surfaces across all spaces in the model.

Finds shared walls between adjacent spaces and sets them as
interior "Surface" boundaries pointing to each other. Essential
after creating multiple adjacent spaces -- without this, shared
walls are treated as exterior "Outdoors" boundaries.

Calls intersectSurfaces() then matchSurfaces() on all spaces.
Requires a model to be loaded via load_osm_model first.

### geometry/set_window_to_wall_ratio
Add a centered window to a wall surface by glazing ratio.

Much easier than specifying vertex coordinates -- just provide
the desired window-to-wall ratio (e.g. 0.4 for 40% glazing).

Args:
    surface_name: Name of the wall surface
    ratio: Window-to-wall ratio (0.0 to 1.0)
    sill_height_m: Sill height above floor in meters (default 0.9m)

Requires a model to be loaded via load_osm_model first.

---

## constructions

### constructions/list_materials
List all materials in the currently loaded model.

Returns array of material objects with:
- Name, handle, type (StandardOpaque, MasslessOpaque, AirGap, Glazing, etc.)
- Type-specific properties:
  * Opaque: thickness, conductivity, density, specific heat
  * Massless/AirGap: thermal resistance
  * Glazing: U-factor, SHGC, transmittance

Requires a model to be loaded via load_osm_model_tool first.

### constructions/list_constructions
List all constructions in the currently loaded model.

Returns array of construction objects with:
- Name, handle
- Number of layers
- List of layer material names (outside to inside)

Requires a model to be loaded via load_osm_model_tool first.

### constructions/list_construction_sets
List all construction sets in the currently loaded model.

Returns array of construction set objects with:
- Name, handle
- Default constructions for:
  * Exterior surfaces (walls, floors, roofs)
  * Interior surfaces (walls, floors, ceilings)
  * Ground contact surfaces (walls, floors)
  * Subsurfaces (windows, doors)

Construction sets define default construction assignments
for buildings, stories, space types, or spaces.

Requires a model to be loaded via load_osm_model_tool first.

### constructions/create_standard_opaque_material
Create a standard opaque material with thermal properties.

Args:
    name: Name for the material
    roughness: Surface roughness - "VeryRough", "Rough", "MediumRough", "MediumSmooth", "Smooth", "VerySmooth" (default: "Smooth")
    thickness_m: Thickness in meters (default: 0.1 = 10cm)
    conductivity_w_m_k: Thermal conductivity in W/m-K (default: 0.5)
    density_kg_m3: Density in kg/m3 (default: 800.0)
    specific_heat_j_kg_k: Specific heat in J/kg-K (default: 1000.0)

Creates a material with specified thermal properties. Common examples:
- Concrete: conductivity ~1.7, density ~2400, specific_heat ~900
- Insulation: conductivity ~0.04, density ~50, specific_heat ~800
- Wood: conductivity ~0.15, density ~600, specific_heat ~1600

Use save_osm_model_tool to persist changes.

Requires a model to be loaded via load_osm_model_tool first.

### constructions/create_construction
Create a layered construction from materials.

Args:
    name: Name for the construction
    material_names: List of material names, ordered from outside to inside

Creates a construction by stacking materials in layers.
Order matters: first material is outermost layer, last is innermost.

Example for wall: ["Exterior Finish", "Insulation", "Concrete", "Interior Finish"]

Use save_osm_model_tool to persist changes.

Requires a model to be loaded via load_osm_model_tool first.

### constructions/assign_construction_to_surface
Assign a construction to a surface.

Args:
    surface_name: Name of the surface to modify
    construction_name: Name of the construction to assign

Modifies a surface to use the specified construction.
The construction determines the thermal and optical properties
of the surface for simulation.

Use save_osm_model_tool to persist changes.

Requires a model to be loaded via load_osm_model_tool first.

---

## schedules

### schedules/list_schedule_rulesets
List all schedule rulesets in the currently loaded model.

Returns array of schedule ruleset objects with:
- Name, handle
- Schedule type limits
- Default day schedule
- Summer and winter design day schedules
- Number of schedule rules

Schedule rulesets define time-varying values (temperatures,
occupancy, lighting levels, etc.) with day-of-week and
date-range rules.

Requires a model to be loaded via load_osm_model_tool first.

### schedules/get_schedule_details
Get detailed information about a specific schedule ruleset.

Args:
    schedule_name: Name of the schedule ruleset to retrieve

Returns detailed schedule attributes including:
- Basic info (type limits, default schedules)
- All schedule rules with day-of-week applicability
- Date ranges for each rule

Requires a model to be loaded via load_osm_model_tool first.

### schedules/create_schedule_ruleset
Create a new schedule ruleset with a constant default day schedule.

Args:
    name: Name for the new schedule
    schedule_type: Type of schedule - "Fractional" (0-1), "Temperature", or "OnOff" (default: "Fractional")
    default_value: Constant value for all hours of the day (default: 1.0)

Returns the created schedule with appropriate type limits and
default day/design day schedules set to the constant value.

Useful for creating always-on schedules, constant setpoints,
or simple baseline schedules that can be refined with rules later.

Use save_osm_model_tool to persist changes.

Requires a model to be loaded via load_osm_model_tool first.

---

## hvac

### hvac/list_air_loops
List all air loops. Default brief: name, num_thermal_zones. Use get_air_loop_details for full info.

Args:
    detailed: Return all fields (thermal_zones list, supply_components, OA system, setpoint managers)

### hvac/get_air_loop_details
Get detailed information about a specific air loop HVAC system.

Args:
    air_loop_name: Name of the air loop to retrieve

Returns detailed air loop attributes including:
- Thermal zones served
- Supply components with types and names
- Detailed components (fans, coils with specs) - NEW Phase 4D
- Outdoor air system details (economizer settings) - NEW Phase 4D
- Setpoint managers - NEW Phase 4D

Enhanced in Phase 4D for component validation testing.

Requires a model to be loaded via load_osm_model_tool first.

### hvac/list_plant_loops
List all plant loops. Default brief: name, component counts. Use get_plant_loop_details for full info.

Args:
    detailed: Return all fields (supply/demand component lists with types and names)

### hvac/get_plant_loop_details
Get detailed information about a specific plant loop.

NEW in Phase 4D for component validation testing.

Args:
    plant_loop_name: Name of the plant loop to retrieve

Returns detailed plant loop attributes including:
- Loop type (Heating/Cooling)
- Supply temperature setpoint (C)
- Design loop exit temperature (C)
- Loop design temperature difference (C)
- Supply and demand components

Use for validating plant loop setpoints in baseline HVAC systems.

Requires a model to be loaded via load_osm_model_tool first.

### hvac/list_zone_hvac_equipment
List all zone HVAC equipment in the currently loaded model.

Returns array of zone HVAC component objects with:
- Type, name, handle
- Associated thermal zone (if applicable)

Zone HVAC equipment serves individual zones directly without
ductwork, e.g., PTACs, fan coil units, baseboards, VRF terminals.

Requires a model to be loaded via load_osm_model_tool first.

### hvac/add_air_loop
Add a new air loop HVAC system to the loaded OpenStudio model.

Args:
    name: Name for the new air loop
    thermal_zone_names: Optional list of thermal zone names to serve

Returns the created air loop object with handle, name, thermal zones,
and supply components.

Note: Creates basic air loop with uncontrolled terminals for each zone.
Additional components (fans, coils, etc.) should be added separately.
Use save_osm_model_tool to persist changes.

Requires a model to be loaded via load_osm_model_tool first.

### hvac/get_zone_hvac_details
Get detailed information about specific zone HVAC equipment.

NEW in Phase 4D for component validation testing.

Args:
    equipment_name: Name of the zone HVAC equipment to retrieve

Returns detailed equipment attributes including:
- Equipment type and thermal zone
- Heating coil (type, name)
- Cooling coil (type, name)
- Supply air fan (type, name)

Use for validating zone equipment like PTACs, PTHPs, unit heaters.

Requires a model to be loaded via load_osm_model_tool first.

---

## loads

### loads/list_people_loads
List all people (occupancy) loads in the currently loaded model.

Returns array of people objects with:
- Name, handle, space
- Number of people (or density metrics)
- Activity level schedule
- Number of people schedule
- Multiplier

People loads represent occupants and their heat gain, moisture
generation, and ventilation requirements.

Requires a model to be loaded via load_osm_model_tool first.

### loads/list_lighting_loads
List all lighting loads in the currently loaded model.

Returns array of lights objects with:
- Name, handle, space
- Lighting level (W or W/m2 or W/person)
- Schedule
- Multiplier
- Radiant/visible/return air fractions

Lighting loads represent interior lighting fixtures and their
heat gain to the space.

Requires a model to be loaded via load_osm_model_tool first.

### loads/list_electric_equipment
List all electric equipment (plug loads) in the currently loaded model.

Returns array of electric equipment objects with:
- Name, handle, space
- Design level (W or W/m2 or W/person)
- Schedule
- Multiplier
- Latent/radiant/lost fractions

Electric equipment represents plug loads like computers, printers,
appliances, etc.

Requires a model to be loaded via load_osm_model_tool first.

### loads/list_gas_equipment
List all gas equipment in the currently loaded model.

Returns array of gas equipment objects with:
- Name, handle, space
- Design level (W or W/m2 or W/person)
- Schedule
- Multiplier
- Latent/radiant/lost fractions

Gas equipment represents gas-fired appliances like stoves, ovens,
water heaters (non-HVAC).

Requires a model to be loaded via load_osm_model_tool first.

### loads/list_infiltration
List all infiltration objects in the currently loaded model.

Returns array of infiltration objects with:
- Name, handle, space
- Design flow rate (m3/s or flow/area or ACH)
- Schedule
- Coefficient terms for wind/temperature correlation

Infiltration represents uncontrolled air leakage through cracks
and openings in the building envelope.

Requires a model to be loaded via load_osm_model_tool first.

### loads/create_people_definition
Create a people (occupancy) load and assign to a space.

Args:
    name: Name for the people load
    space_name: Space to assign the load to
    people_per_area: People per m2 of floor area (use this OR num_people)
    num_people: Absolute number of people (use this OR people_per_area)
    schedule_name: Optional ScheduleRuleset for occupancy fraction

Exactly one sizing method (people_per_area or num_people) required.
Requires a model to be loaded via load_osm_model_tool first.

### loads/create_lights_definition
Create a lighting load and assign to a space.

Args:
    name: Name for the lights load
    space_name: Space to assign the load to
    watts_per_area: Lighting power density in W/m2 (use this OR lighting_level_w)
    lighting_level_w: Absolute lighting power in W (use this OR watts_per_area)
    schedule_name: Optional ScheduleRuleset for lighting fraction

Exactly one sizing method (watts_per_area or lighting_level_w) required.
Requires a model to be loaded via load_osm_model_tool first.

### loads/create_electric_equipment
Create an electric equipment (plug load) and assign to a space.

Args:
    name: Name for the equipment
    space_name: Space to assign the load to
    watts_per_area: Equipment power density in W/m2 (use this OR design_level_w)
    design_level_w: Absolute equipment power in W (use this OR watts_per_area)
    schedule_name: Optional ScheduleRuleset for equipment fraction

Exactly one sizing method (watts_per_area or design_level_w) required.
Requires a model to be loaded via load_osm_model_tool first.

### loads/create_gas_equipment
Create a gas equipment load and assign to a space.

Args:
    name: Name for the gas equipment
    space_name: Space to assign the load to
    watts_per_area: Gas equipment power density in W/m2 (use this OR design_level_w)
    design_level_w: Absolute gas equipment power in W (use this OR watts_per_area)
    schedule_name: Optional ScheduleRuleset for equipment fraction

Exactly one sizing method (watts_per_area or design_level_w) required.
Requires a model to be loaded via load_osm_model_tool first.

### loads/create_infiltration
Create an infiltration load and assign to a space.

Args:
    name: Name for the infiltration object
    space_name: Space to assign the infiltration to
    flow_per_exterior_surface_area: Flow rate per exterior surface area in m3/s-m2
    ach: Air changes per hour
    schedule_name: Optional ScheduleRuleset for infiltration fraction

Exactly one sizing method (flow_per_exterior_surface_area or ach) required.
Requires a model to be loaded via load_osm_model_tool first.

---

## space_types

### space_types/list_space_types
List all space types in the currently loaded model.

Returns array of space type objects with:
- Name, handle
- Default construction set and schedule set
- Standards building type and space type
- Counts of people, lights, equipment loads
- Number of spaces using this type

Space types are templates that define characteristics like
constructions, schedules, and internal loads for spaces.

Requires a model to be loaded via load_osm_model_tool first.

### space_types/get_space_type_details
Get detailed information about a specific space type.

Args:
    space_type_name: Name of the space type to retrieve

Returns detailed space type attributes including:
- Basic info (construction set, schedule set, standards type)
- All internal loads (people, lights, electric equipment, gas equipment)
- List of spaces assigned to this space type

Requires a model to be loaded via load_osm_model_tool first.

---

## simulation_outputs

### simulation_outputs/add_output_variable
Add an EnergyPlus output variable to the model.

Args:
    variable_name: EnergyPlus output variable name (e.g., "Zone Mean Air Temperature")
    key_value: Specific object name or "*" for all objects (default: "*")
    reporting_frequency: "Detailed", "Timestep", "Hourly", "Daily", "Monthly", "RunPeriod" (default: "Hourly")

Output variables extract specific simulation results for objects in the
model. Common examples:
- "Zone Mean Air Temperature" - zone temperatures
- "Surface Outside Face Temperature" - surface temps
- "Zone Air System Sensible Heating Rate" - heating loads

Results appear in the SQL output file after simulation.

Use save_osm_model_tool to persist changes before running simulation.

Requires a model to be loaded via load_osm_model_tool first.

### simulation_outputs/add_output_meter
Add an EnergyPlus output meter to the model.

Args:
    meter_name: EnergyPlus meter name (e.g., "Electricity:Facility", "Gas:Facility")
    reporting_frequency: "Detailed", "Timestep", "Hourly", "Daily", "Monthly", "RunPeriod" (default: "Hourly")

Output meters aggregate energy use across categories. Common examples:
- "Electricity:Facility" - total electricity consumption
- "Gas:Facility" - total gas consumption
- "Heating:Electricity" - electric heating energy
- "Cooling:Electricity" - electric cooling energy

Results appear in the SQL output file and meter CSV files after simulation.

Use save_osm_model_tool to persist changes before running simulation.

Requires a model to be loaded via load_osm_model_tool first.

---

## hvac_systems

### hvac_systems/add_baseline_system
Add ASHRAE 90.1 Appendix G baseline HVAC system to the model.

Creates complete HVAC system based on ASHRAE 90.1 baseline system types.
All 10 ASHRAE 90.1 Appendix G baseline systems supported:
- System 1: PTAC (Packaged Terminal Air Conditioner)
- System 2: PTHP (Packaged Terminal Heat Pump)
- System 3: PSZ-AC (Packaged Single Zone Air Conditioner)
- System 4: PSZ-HP (Packaged Single Zone Heat Pump)
- System 5: Packaged VAV w/ Reheat
- System 6: Packaged VAV w/ PFP Boxes
- System 7: VAV w/ Reheat (Chiller/Boiler/Tower)
- System 8: VAV w/ PFP (Chiller/Boiler/Tower)
- System 9: Heating & Ventilation (Gas Unit Heaters)
- System 10: Heating & Ventilation (Electric Unit Heaters)

Args:
    system_type: ASHRAE baseline system type (1-10)
    thermal_zone_names: List of thermal zone names to serve
    heating_fuel: "NaturalGas", "Electricity", or "DistrictHeating"
    cooling_fuel: "Electricity" or "DistrictCooling"
    economizer: Enable air-side economizer where applicable
    system_name: Optional custom system name (auto-generated if None)

Returns:
    JSON string with system details or error

### hvac_systems/list_baseline_systems
List all ASHRAE 90.1 Appendix G baseline system types.

Returns information about all 10 baseline system types including:
- System name and full name
- Description
- Heating/cooling technologies
- Typical applications

Returns:
    JSON string with baseline systems catalog

### hvac_systems/get_baseline_system_info
Get detailed information about a specific ASHRAE baseline system type.

Args:
    system_type: ASHRAE baseline system type (1-10)

Returns:
    JSON string with system metadata including typical use cases,
    heating/cooling types, and distribution methods

### hvac_systems/replace_air_terminals
Replace air terminals on an existing air loop.

Removes existing terminals and installs new type on all zones served by the air loop.
Useful for converting VAV reheat to PFP boxes, or changing terminal configurations.

Args:
    air_loop_name: Name of air loop to modify
    terminal_type: Type of terminals to install. Options:
        - "VAV_Reheat": VAV with hot water reheat coils (requires HW loop)
        - "VAV_NoReheat": VAV without reheat
        - "PFP_Electric": Parallel fan-powered with electric reheat
        - "PFP_HotWater": Parallel fan-powered with HW reheat (requires HW loop)
        - "CAV": Constant air volume (uncontrolled)
        - "FourPipeBeam": 4-pipe active chilled beam (requires CHW + HW loops)
    terminal_options: Optional configuration dict with keys:
        - min_airflow_fraction: 0.0-1.0 (default: 0.3 for VAV, 0.5 for PFP)
        - fan_power_w_per_cfm: Power for PFP fan boxes (optional)

Returns:
    JSON string with replacement results including number of terminals replaced,
    old/new terminal types, and affected zones

### hvac_systems/replace_zone_terminal
Replace the air terminal on a single zone.

Unlike replace_air_terminals_tool which replaces ALL terminals on an air loop,
this tool replaces only one zone's terminal. Enables mixed terminal types on
the same air loop (e.g., VAV reheat for perimeter, VAV no-reheat for core).

Args:
    zone_name: Name of the thermal zone to modify
    terminal_type: Type of terminal to install. Options:
        - "VAV_Reheat": VAV with hot water reheat coils (requires HW loop)
        - "VAV_NoReheat": VAV without reheat
        - "PFP_Electric": Parallel fan-powered with electric reheat
        - "PFP_HotWater": Parallel fan-powered with HW reheat (requires HW loop)
        - "CAV": Constant air volume (uncontrolled)
        - "FourPipeBeam": 4-pipe active chilled beam (requires CHW + HW loops)
    terminal_options: Optional configuration dict with keys:
        - min_airflow_fraction: 0.0-1.0 (default: 0.3 for VAV, 0.5 for PFP)

Returns:
    JSON string with zone name, air loop, old/new terminal types

### hvac_systems/add_doas_system
Add Dedicated Outdoor Air System with zone equipment.

Creates 100% outdoor air ventilation loop with optional energy recovery,
plus zone-level sensible conditioning (fan coils, radiant panels, or chilled beams).
Plant loops are auto-wired with supply equipment (boiler/chiller/tower or district).

DOAS decouples ventilation from sensible load, enabling:
- Lower airflow rates (ventilation-only CFM vs cooling CFM)
- Energy recovery from exhaust air
- Independent control of humidity and temperature

Args:
    thermal_zone_names: List of thermal zone names to serve
    system_name: Name prefix for DOAS components (default "DOAS")
    energy_recovery: Add energy recovery ventilator (default True)
    sensible_effectiveness: ERV sensible effectiveness 0-1 (default 0.75)
    zone_equipment_type: FanCoil | Radiant | ChilledBeams | FourPipeBeam (default FanCoil)
    heating_fuel: NaturalGas | Electricity | DistrictHeating (default NaturalGas)
    cooling_fuel: Electricity | DistrictCooling (default Electricity)

Returns:
    JSON string with system details including DOAS loop, plant loops, and zone equipment

Example:
    {
      "ok": true,
      "system": {
        "name": "DOAS",
        "type": "DOAS",
        "doas_loop": "DOAS DOAS Loop",
        "energy_recovery": true,
        "erv_name": "DOAS ERV",
        "sensible_effectiveness": 0.75,
        "zone_equipment_type": "FanCoil",
        "chilled_water_loop": "DOAS CHW Loop",
        "hot_water_loop": "DOAS HW Loop",
        "num_zones": 4,
        "zone_equipment": [...]
      }
    }

### hvac_systems/add_vrf_system
Add Variable Refrigerant Flow multi-zone heat pump system.

Creates single outdoor unit with individual zone terminals. Heat recovery mode
allows simultaneous heating/cooling across zones with heat transfer via refrigerant.

VRF advantages:
- High efficiency (COP 3-5 typical)
- Zonal control (independent setpoints per zone)
- Heat recovery between zones
- No ductwork or plant loops required

Args:
    thermal_zone_names: List of thermal zone names to serve (max ~20 per outdoor unit)
    system_name: Name prefix for VRF components (default "VRF")
    heat_recovery: Enable heat recovery mode (default True)
    outdoor_unit_capacity_w: Outdoor unit capacity in Watts (autosize if None)

Returns:
    JSON string with system details including outdoor unit and terminals

Example:
    {
      "ok": true,
      "system": {
        "name": "VRF",
        "type": "VRF",
        "outdoor_unit": "VRF VRF Outdoor Unit HR",
        "heat_recovery": true,
        "capacity_w": "autosized",
        "num_zones": 8,
        "terminals": [...]
      }
    }

### hvac_systems/add_radiant_system
Add low-temperature radiant heating/cooling system.

Creates hydronic radiant surfaces (floor, ceiling, or walls) with low-temperature
plant loops. Plant loops are auto-wired with supply equipment (boiler/chiller/tower
or district). Optionally adds DOAS for ventilation/dehumidification.

Radiant advantages:
- High thermal comfort (radiant heat transfer)
- Energy efficiency (low-temp heating, high-temp cooling)
- Silent operation (no fans in zones)
- Aesthetic (hidden distribution)

Considerations:
- Slow response time (thermal mass)
- Requires ventilation system (DOAS recommended)
- Floor coverings affect performance

Args:
    thermal_zone_names: List of thermal zone names to serve
    system_name: Name prefix for radiant components (default "Radiant")
    radiant_type: Floor | Ceiling | Walls (default Floor)
    ventilation_system: DOAS | None (default DOAS, if None ventilation added separately)
    heating_fuel: NaturalGas | Electricity | DistrictHeating (default NaturalGas)
    cooling_fuel: Electricity | DistrictCooling (default Electricity)

Returns:
    JSON string with system details including radiant surfaces and plant loops

Example:
    {
      "ok": true,
      "system": {
        "name": "Radiant",
        "type": "Radiant",
        "radiant_type": "Floor",
        "hot_water_loop": "Radiant Low-Temp HW Loop",
        "chilled_water_loop": "Radiant Low-Temp CHW Loop",
        "hw_supply_temp_f": 120,
        "chw_supply_temp_f": 58,
        "ventilation_system": "DOAS",
        "doas_loop": "Radiant Ventilation DOAS Loop",
        "num_zones": 6,
        "radiant_equipment": [...]
      }
    }

---

## component_properties

### component_properties/list_hvac_components
List all HVAC components in the model with name, type, and category.

Scans the model for known component types (coils, chillers, boilers,
fans, pumps, cooling towers) and returns their names and categories.

Args:
    category: Optional filter -- "coil", "plant", "fan", or "pump"

Returns:
    JSON with component list

### component_properties/get_component_properties
Get all readable properties for a named HVAC component.

Looks up the component by name across all registered types and returns
current property values with units.

Args:
    component_name: Exact name of the HVAC component

Returns:
    JSON with property names, values, units, and types

### component_properties/set_component_properties
Set one or more properties on a named HVAC component.

Finds the component by name, validates property names against the
registry, and applies changes. Returns old and new values.

Args:
    component_name: Exact name of the HVAC component
    properties: JSON string of property_name: value pairs,
        e.g. '{"reference_cop": 6.0, "nominal_capacity_w": 50000}'

Returns:
    JSON with old/new values for each changed property

### component_properties/set_economizer_properties
Modify outdoor air economizer properties on an air loop.

Available properties:
- economizer_control_type: "NoEconomizer", "DifferentialDryBulb",
  "DifferentialEnthalpy", "FixedDryBulb", etc.
- max_limit_drybulb_temp_c: Maximum OA dry-bulb temperature limit
- min_limit_drybulb_temp_c: Minimum OA dry-bulb temperature limit

Args:
    air_loop_name: Name of the air loop
    properties: JSON string of property: value pairs

Returns:
    JSON with old/new values

### component_properties/set_sizing_properties
Modify sizing properties on a plant loop.

Available properties:
- loop_type: "Heating", "Cooling", "Condenser", "Both"
- design_loop_exit_temperature_c: Design supply water temperature
- loop_design_temperature_difference_c: Design delta-T

Args:
    loop_name: Name of the plant loop
    properties: JSON string of property: value pairs

Returns:
    JSON with old/new values

### component_properties/set_setpoint_manager_properties
Modify setpoint manager properties.

Supports SetpointManagerSingleZoneReheat:
- minimum_supply_air_temperature_c
- maximum_supply_air_temperature_c

Supports SetpointManagerScheduled:
- control_variable: "Temperature", "HumidityRatio", etc.

Args:
    setpoint_name: Name of the setpoint manager
    properties: JSON string of property: value pairs

Returns:
    JSON with old/new values

---

## loop_operations

### loop_operations/add_supply_equipment
Create equipment and add to a plant loop's supply side.

Supported types:
- BoilerHotWater: props -- nominal_thermal_efficiency, fuel_type, nominal_capacity_w
- ChillerElectricEIR: props -- reference_cop, reference_capacity_w
- CoolingTowerSingleSpeed: no extra props

Args:
    plant_loop_name: Name of the plant loop
    equipment_type: One of the supported equipment types
    equipment_name: Name for the new equipment
    properties: Optional JSON string of property: value pairs

Returns:
    JSON with creation result

### loop_operations/remove_supply_equipment
Remove named equipment from a plant loop's supply side.

Args:
    plant_loop_name: Name of the plant loop
    equipment_name: Exact name of the equipment to remove

Returns:
    JSON with removal result

### loop_operations/add_zone_equipment
Create zone-level equipment and add to a thermal zone.

Supported types:
- ZoneHVACBaseboardConvectiveElectric: props -- nominal_capacity_w
- ZoneHVACUnitHeater: creates with fan + electric heating coil

Args:
    zone_name: Name of the thermal zone
    equipment_type: One of the supported equipment types
    equipment_name: Name for the new equipment
    properties: Optional JSON string of property: value pairs

Returns:
    JSON with creation result

### loop_operations/remove_zone_equipment
Remove named equipment from a thermal zone.

Args:
    zone_name: Name of the thermal zone
    equipment_name: Exact name of the equipment to remove

### loop_operations/remove_all_zone_equipment
Remove ALL equipment from multiple thermal zones in one call.

Use instead of calling remove_zone_equipment repeatedly.

Args:
    zone_names: JSON array of zone names, e.g. '["Zone1", "Zone2"]'

---

## object_management

### object_management/delete_object
Delete a named object from the loaded model.

Args:
    object_name: Name of the object to delete
    object_type: Optional type hint (e.g. "Space", "BoilerHotWater")
        for disambiguation when multiple types share a name.

Supports spaces, zones, stories, HVAC loops, coils, fans, pumps,
plant equipment, loads, constructions, materials, schedules.

Warning: deleting a Space also removes its surfaces and loads.
Requires a model to be loaded via load_osm_model_tool first.

### object_management/rename_object
Rename a named object in the loaded model.

Args:
    object_name: Current name of the object
    new_name: New name to assign
    object_type: Optional type hint for disambiguation

Supports the same types as delete_object_tool.
Requires a model to be loaded via load_osm_model_tool first.

### object_management/list_model_objects
List all objects of a given type in the loaded model.

Args:
    object_type: Type to list (e.g. "Space", "ThermalZone",
        "BoilerHotWater", "ScheduleRuleset")

Returns name and handle for each object of that type.
Requires a model to be loaded via load_osm_model_tool first.

---

## weather

### weather/get_weather_info
Get weather file information from the loaded model.

Returns city, state, country, latitude, longitude, timezone,
elevation, and EPW file URL if a weather file is attached.

Returns null weather_file if no weather file is set.
Requires a model to be loaded via load_osm_model_tool first.

### weather/set_weather_file
Attach an EPW weather file to the loaded model.

Args:
    epw_path: Absolute path to an EPW file

Sets the WeatherFile object on the model so it persists when
saved via save_osm_model_tool. This is complementary to the
run_osw_tool epw_path parameter which overrides at run time.

Requires a model to be loaded via load_osm_model_tool first.

### weather/add_design_day
Add a sizing design day to the loaded model.

Args:
    name: Design day name (e.g. "Chicago Winter 99%")
    day_type: "WinterDesignDay" or "SummerDesignDay"
    month: Month (1-12)
    day: Day of month (1-31)
    dry_bulb_max_c: Maximum dry-bulb temperature in C
    dry_bulb_range_c: Daily dry-bulb temperature range in C
    humidity_type: "WetBulb" or "DewPoint" (default: "WetBulb")
    humidity_value: Humidity indicator value in C
    wind_speed_ms: Wind speed in m/s
    barometric_pressure_pa: Barometric pressure in Pa

Used for HVAC sizing calculations. Typically add one heating
and one cooling design day.
Requires a model to be loaded via load_osm_model_tool first.

### weather/get_simulation_control
Get SimulationControl flags and Timestep from the loaded model.

Returns do_zone_sizing, do_system_sizing, do_plant_sizing,
run_for_sizing_periods, run_for_weather_file, timesteps_per_hour.

Requires a model to be loaded via load_osm_model first.

### weather/set_simulation_control
Modify SimulationControl flags and/or Timestep on the loaded model.

Args:
    do_zone_sizing: Enable zone sizing calculations
    do_system_sizing: Enable system sizing calculations
    do_plant_sizing: Enable plant sizing calculations
    run_for_sizing_periods: Run simulation for sizing periods
    run_for_weather_file: Run simulation for weather file run periods
    timesteps_per_hour: Number of timesteps per hour (1,2,3,4,5,6,10,12,15,20,30,60)

All parameters are optional -- only provided values are changed.
Requires a model to be loaded via load_osm_model first.

### weather/get_run_period
Get the RunPeriod from the loaded model.

Returns name, begin_month, begin_day, end_month, end_day.

Requires a model to be loaded via load_osm_model first.

### weather/set_run_period
Set or modify the RunPeriod on the loaded model.

Args:
    begin_month: Start month (1-12)
    begin_day: Start day of month (1-31)
    end_month: End month (1-12)
    end_day: End day of month (1-31)
    name: Optional run period name

Also auto-enables runSimulationforWeatherFileRunPeriods so the
period is used during simulation.
Requires a model to be loaded via load_osm_model first.

---

## measures

### measures/list_measure_arguments
List arguments for an OpenStudio measure.

Args:
    measure_dir: Path to the measure directory (contains measure.rb)

Returns measure name, type, description, and list of arguments
with name, display_name, type, default_value, required, and choices.

Does not require a model to be loaded.

### measures/apply_measure
Apply an OpenStudio model measure to the loaded model.

Args:
    measure_dir: Path to the measure directory (contains measure.rb)
    arguments: Optional dict of argument_name -> value overrides

Saves the current model, runs the measure via `openstudio run`,
and reloads the modified model. The in-memory model is updated
with the measure's changes.

Requires a model to be loaded via load_osm_model_tool first.

---

## comstock

### comstock/list_comstock_measures
List available ComStock measures bundled in the server.

Args:
    category: Optional filter -- "baseline", "upgrade", "setup", "other",
              or omit for all measures

Returns categorized list of ~61 measures with names, descriptions,
paths, and argument counts. Use paths with list_measure_arguments
and apply_measure for full control.

Does not require a model to be loaded.

### comstock/create_typical_building
Create a typical building from the loaded model using openstudio-standards.

Adds constructions, loads, HVAC, schedules, and service water heating
to a model that already has geometry and space types assigned.
Wraps the ComStock create_typical_building_from_model measure.

Automatically sets standardsBuildingType on the building and space types
if not already set, using the building_type parameter.

Args:
    template: ASHRAE standard -- "90.1-2019", "90.1-2016", "90.1-2013", etc.
    building_type: DOE prototype type -- "SmallOffice", "LargeOffice",
        "RetailStandalone", "PrimarySchool", "Hospital", etc. Used to set
        standardsBuildingType if missing from model.
    system_type: HVAC system -- "Inferred" (auto-select), "VAV chiller with gas boiler reheat", etc.
    climate_zone: "Lookup From Model" or e.g. "ASHRAE 169-2013-4A"
    htg_src: Heating fuel -- "NaturalGas", "Electricity", "DistrictHeating"
    clg_src: Cooling fuel -- "Electricity" or "DistrictCooling"
    swh_src: SWH fuel -- "Inferred", "NaturalGas", "Electricity"
    add_constructions: Add standard constructions to surfaces
    add_space_type_loads: Add people, lights, equipment per space type
    add_hvac: Add HVAC system
    add_swh: Add service water heating
    add_exterior_lights: Add exterior lighting
    add_thermostat: Add thermostat schedules
    remove_objects: Remove existing HVAC/loads before adding new ones

Requires a model to be loaded via load_osm_model first.
The model should have geometry (spaces with surfaces).

---

## common_measures

### common_measures/list_common_measures
List available common measures bundled in the server.

Args:
    category: Optional filter -- "reporting", "thermostat", "envelope",
              "location", "loads", "renewables", "schedule", "cost",
              "cleanup", "idf", "visualization", "other", or omit for all

Returns categorized list of ~79 measures. Use paths with
list_measure_arguments and apply_measure for direct access.
Does not require a model to be loaded.

### common_measures/view_model
Generate a 3D Three.js HTML viewer of the current model geometry.

Creates an interactive HTML file in /runs/ that can be opened in a
browser. Shows all surfaces, subsurfaces, and shading in 3D.

Args:
    geometry_diagnostics: Enable surface/space convexity checks (slower)

Requires a model to be loaded.

### common_measures/view_simulation_data
Generate a 3D viewer with simulation data overlaid on model surfaces.

Creates an interactive HTML file showing up to 3 output variables
plotted on the model geometry. Requires a completed simulation.

Args:
    run_id: Run ID from a completed simulation (required -- provides SQL results)
    variable_names: Up to 3 EnergyPlus output variable names.
        Defaults to surface temperatures if omitted.
    reporting_frequency: "Timestep" or "Hourly"

Requires a model to be loaded and a simulation to have been run.

### common_measures/generate_results_report
Generate a comprehensive HTML report from simulation results.

Includes building summary, annual/monthly energy, HVAC details,
envelope, zones, economics, and more (~25 sections).

Args:
    run_id: Run ID from a completed simulation (required -- provides SQL results)
    units: "IP" (imperial) or "SI" (metric)

Requires a completed simulation.

### common_measures/run_qaqc_checks
Run ASHRAE baseline QA/QC checks on simulation results.

Compares model against standard targets for efficiency, capacity,
internal loads, envelope, schedules, and mechanical systems.

Args:
    run_id: Run ID from a completed simulation (required -- provides SQL results)
    template: Target ASHRAE standard -- "90.1-2013", "90.1-2016", "90.1-2019"
    checks: Which checks to enable. Defaults to all. Options:
        "part_load_eff", "capacity", "simultaneous_htg_clg",
        "internal_loads", "schedules", "envelope", "dhw",
        "mech_efficiency", "mech_type", "supply_air_temp"

Requires a completed simulation.

### common_measures/adjust_thermostat_setpoints
Shift all thermostat setpoints by specified degree offsets.

Clones schedules so originals are not mutated. Positive cooling_offset
raises setpoint (saves cooling energy); negative heating_offset lowers
setpoint (saves heating energy).

Args:
    cooling_offset_f: Degrees F to raise cooling setpoint
    heating_offset_f: Degrees F to shift heating setpoint
    alter_design_days: Also shift design day schedules

Requires a model to be loaded.

### common_measures/replace_window_constructions
Replace all exterior window constructions with a named construction.

Applies to all exterior windows (excludes skylights and adiabatic).
The construction must already exist in the model.

Args:
    construction_name: Name of the window construction to apply
    fixed_windows: Replace fixed windows
    operable_windows: Replace operable windows

Requires a model to be loaded.

### common_measures/enable_ideal_air_loads
Enable ideal air loads on all thermal zones.

Disconnects existing HVAC. Useful for quick sizing studies
or load calculations without detailed HVAC modeling.

Requires a model to be loaded.

### common_measures/clean_unused_objects
Remove orphan objects and unused resources from the model.

Removes orphaned load instances, surfaces without spaces, and
optionally purges unused space types, schedules, constructions,
load definitions, and performance curves.

Args:
    space_types: Remove unused space types
    load_defs: Remove unused load definitions
    schedules: Remove unused schedules
    constructions: Remove unused constructions and materials
    curves: Remove unused performance curves

Requires a model to be loaded.

### common_measures/inject_idf
Inject raw IDF objects from an external file into the model.

Objects are added to the EnergyPlus workspace before simulation.
Best for adding new objects; modifying forward-translated objects
may cause conflicts.

Args:
    idf_path: Path to the IDF file containing objects to inject

Requires a model to be loaded.

### common_measures/change_building_location
Change building location by setting weather file and climate zone.

Sets the weather file and ASHRAE/CEC climate zone. Also looks up
the .stat file for design day data if available.

Args:
    weather_file: EPW weather file name
    climate_zone: ASHRAE climate zone or "Lookup From Stat File" for auto

Requires a model to be loaded.

### common_measures/set_thermostat_schedules
Set thermostat heating/cooling schedules on a specific zone.

Args:
    zone_name: Thermal zone name
    cooling_schedule: Name of cooling setpoint ScheduleRuleset
    heating_schedule: Name of heating setpoint ScheduleRuleset

### common_measures/replace_thermostat_schedules
Replace thermostat schedules on a zone (overwrites existing).

Args:
    zone_name: Thermal zone name
    cooling_schedule: Name of cooling setpoint ScheduleRuleset
    heating_schedule: Name of heating setpoint ScheduleRuleset

### common_measures/shift_schedule_time
Shift a schedule's profile times forward or backward.

Args:
    schedule_name: Name of the ScheduleRuleset to shift
    shift_hours: Hours to shift (positive=forward, negative=backward, 24hr)

### common_measures/add_rooftop_pv
Add rooftop PV panels as shading surfaces with photovoltaic generators.

Args:
    fraction_of_surface: Fraction of roof area covered (0-1)
    cell_efficiency: PV cell efficiency (0-1, typical 0.15-0.22)
    inverter_efficiency: DC-to-AC inverter efficiency (0-1)

### common_measures/add_pv_to_shading
Add simple PV generators to existing shading surfaces by type.

Args:
    shading_type: "Building Shading", "Site Shading", or "Space Shading"
    fraction: Fraction of shading surface area with PV (0-1)
    cell_efficiency: PV cell efficiency (0-1)

### common_measures/add_ev_load
Add electric vehicle charging load to the building.

Args:
    delay_type: "Min Delay", "Max Delay", or "Midnight"
    charge_behavior: "Business as Usual" or "Free Workplace Charging at Scale"
    station_type: "Typical Public", "Typical Work", or "Typical Home"
    ev_percent: Percent of parked vehicles that are EVs (0-100)
    use_model_occupancy: Use model occupancy to determine EV count

### common_measures/add_zone_ventilation
Add a zone ventilation design flow rate object.

Args:
    zone_name: Thermal zone name
    design_flow_rate: Design flow rate in m3/s
    ventilation_type: "Natural", "Exhaust", "Intake", or "Balanced"
    schedule_name: Optional schedule name (defaults to always-on)

### common_measures/set_lifecycle_cost_params
Set lifecycle cost analysis study period length.

Args:
    study_period: Analysis period in years (1-40)

### common_measures/add_cost_per_floor_area
Add lifecycle cost per floor area to the building.

Args:
    material_cost: Material/installation cost per area ($/ft2)
    om_cost: Operations & maintenance cost per area ($/ft2)
    expected_life: Expected life in years
    lcc_name: Name for the LCC object
    remove_existing: Remove existing building-level LCC objects first

### common_measures/set_adiabatic_boundaries
Set exterior surfaces to adiabatic boundary condition.

Args:
    ext_roofs: Make exterior roof surfaces adiabatic
    ext_floors: Make exterior exposed floor surfaces adiabatic
    ground_floors: Make ground-contact floor surfaces adiabatic
    north_walls: Make north-facing exterior walls adiabatic
    south_walls: Make south-facing exterior walls adiabatic
    east_walls: Make east-facing exterior walls adiabatic
    west_walls: Make west-facing exterior walls adiabatic

---

## skill_discovery

### skill_discovery/list_skills
List available workflow guides for common tasks like creating
buildings, running simulations, and analyzing results.

Call this when you need guidance on multi-step workflows or
don't know which tools to use for a task.

Returns skill names and descriptions. Use get_skill(name) to
get step-by-step instructions for a specific workflow.

### skill_discovery/get_skill
Get step-by-step workflow instructions for a specific task.

Returns tool names, sequences, and domain guidance. Call this
before starting a complex multi-tool workflow.

Args:
    name: Skill name from list_skills (e.g. "simulate",
          "new-building", "retrofit")
