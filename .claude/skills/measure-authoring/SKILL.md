---
name: measure-authoring
description: Create, test, and apply custom OpenStudio measures. Use when user asks to "write a measure", "create a custom measure", "modify the model with Ruby/Python code", or needs logic beyond what existing tools provide.
disable-model-invocation: true
---

# Measure Authoring

Create custom OpenStudio ModelMeasures with user-provided logic, test them, and apply them to models.

## When to Use

Use measure authoring when:
- No existing MCP tool does what the user needs
- User explicitly asks for a "custom measure" or "Ruby/Python measure"
- Complex model modifications requiring iteration over many objects
- User wants reusable, repeatable model transformations

Do NOT use when an existing tool already does the job (e.g., `replace_air_terminals` for terminal swaps, `adjust_thermostat_setpoints` for thermostat changes).

## Workflow

### 1. Create the Measure
```
create_measure(
    name="set_lights_8w",
    description="Set all lights to 8 W/m2",
    language="Ruby",
    run_body="    model.getLightsDefinitions.each { |ld| ld.setWattsperSpaceFloorArea(8.0) }\n    runner.registerFinalCondition('Done')"
)
```

### 2. Test It
```
test_measure(measure_dir="/runs/custom_measures/set_lights_8w")
```
Tests run against the currently loaded model (or SystemD_baseline.osm fallback),
so measures that depend on HVAC, plant loops, or zones will work correctly.
Use `model_path` to test against a specific model.

### 3. Apply to Model
```
apply_measure(measure_dir="/runs/custom_measures/set_lights_8w")
```

### 4. Verify Results (Before/After Comparison)
For rigorous validation, run a baseline simulation BEFORE applying the measure:
```
save_osm_model(save_path="/runs/baseline.osm")
run_simulation(osm_path="/runs/baseline.osm", epw_path="<epw>")
extract_summary_metrics(run_id=<baseline_id>)   # record baseline EUI

# reload, apply measure, re-simulate
load_osm_model(osm_path="<original>")
apply_measure(measure_dir="/runs/custom_measures/set_lights_8w")
save_osm_model(save_path="/runs/retrofit.osm")
run_simulation(osm_path="/runs/retrofit.osm", epw_path="<epw>")
extract_summary_metrics(run_id=<retrofit_id>)   # compare to baseline
```

## Language Choice

- **Ruby**: Preferred for most measures. Matches OpenStudio SDK documentation and existing measure libraries.
- **Python**: Works but less common. Use when user prefers Python.

## Common run_body Patterns (Ruby)

### Envelope
```ruby
    model.getLightsDefinitions.each { |ld| ld.setWattsperSpaceFloorArea(8.0) }
    model.getSpaceInfiltrationDesignFlowRates.each { |inf| inf.setFlowperExteriorSurfaceArea(0.0003) }
    model.getSurfaces.each { |s| next unless s.outsideBoundaryCondition == 'Outdoors'; ... }
```

### HVAC
```ruby
    model.getAirLoopHVACs.each do |loop|
      loop.thermalZones.each do |zone|
        loop.removeBranchForZone(zone)
        # create new terminal...
        loop.addBranchForZone(zone, terminal.to_StraightComponent.get)
      end
    end
```

### Zone Equipment
```ruby
    model.getThermalZones.each do |zone|
      bb = OpenStudio::Model::ZoneHVACBaseboardConvectiveElectric.new(model)
      bb.setName("#{zone.name} Baseboard")
      bb.addToThermalZone(zone)
    end
```

### Air Terminals (beams)
```ruby
    # CooledBeam (2-pipe, cooling only)
    coil = OpenStudio::Model::CoilCoolingCooledBeam.new(model)
    terminal = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeCooledBeam.new(model, sch, coil)

    # FourPipeBeam (4-pipe, heating + cooling)
    cc = OpenStudio::Model::CoilCoolingFourPipeBeam.new(model)
    hc = OpenStudio::Model::CoilHeatingFourPipeBeam.new(model)
    terminal = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeFourPipeBeam.new(model, cc, hc)
```

WARNING: Beams are AIR TERMINALS (connect via `air_loop.addBranchForZone`), NOT zone equipment (`addToThermalZone`).

## Notes

- `run_body` indentation matters: Ruby = 4 spaces, Python = 8 spaces
- Always call `runner.registerFinalCondition("msg")` at end of run body
- `create_measure` is idempotent (overwrites existing measure with same name)
- Use `edit_measure` to modify an existing measure without recreating from scratch
- Use `list_custom_measures` to see all created measures
