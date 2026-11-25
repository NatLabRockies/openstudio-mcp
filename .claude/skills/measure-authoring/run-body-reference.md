# run_body reference

Pattern catalog for the `run_body` argument of `create_measure`. Ruby run_body is indented 4 spaces, Python 8.

## Argument strategy: make measures reusable

- Parameterize anything model-specific: zone/space names, setpoint values,
  schedule names, material properties, thresholds, equipment names
- Hard-code only measure logic (traversal patterns, formulas, output structure)
- Use descriptive display_names so users understand each argument
- Include a description for every argument (units, purpose, behavior)
- Provide a sensible default_value for optional arguments
- Common argument patterns:
    Setpoints/thresholds → Double with default (e.g. R-value, watts/m2)
    Object names/filters → String (zone name, space type, schedule name)
    Enable/disable features → Boolean with default true
    Predefined options → Choice with values list
    Counts/hours/limits → Integer with default (e.g. max_zones, setback_hours)
- Example: a wall insulation measure should parameterize `target_r_value` as a Double,
  `surface_filter` as a String (default ""), and `construction_name` as a String rather
  than hard-coding R-19 for "Exterior Wall" surfaces

## Ruby run_body patterns

```ruby
error/applicability handling:
  runner.registerError("msg") — follow with `return false` (it does not halt)
  runner.registerAsNotApplicable("msg") + return true — guard clause when
    measure doesn't apply (e.g. no windows found, already at target)
  runner.registerInitialCondition("before summary")
  runner.registerFinalCondition("after summary with counts")
  runner.registerInfo("progress message")
  runner.registerWarning("non-fatal issue")
.name returns OptionalString:
  obj.name.to_s — safe string comparison (returns "" if uninitialized)
  WRONG: obj.name == "Foo" — crashes on OptionalString comparison
  RIGHT: obj.name.to_s == "Foo" or obj.name.to_s.include?("Foo")
ModelMeasure:
  model.getSurfaces.each { |s| ... }
  model.getSubSurfaces.each { |ss| ... } — windows/doors
  model.getThermalZones.each { |z| ... }
  model.getSpaces.each { |space| ... }
  model.getBuilding.setName(name)
  surface.outsideBoundaryCondition == "Outdoors" — exterior filter
  ss.subSurfaceType — "FixedWindow", "OperableWindow", "Door", etc.
  opt = surface.construction; if opt.is_initialized then c = opt.get end
  OpenStudio.convert(val, "W/m^2", "Btu/hr*ft^2").get — unit conversion
    Common: W/m^2↔Btu/hr*ft^2, m^2*K/W↔ft^2*hr*R/Btu, kWh/m^2↔kBtu/ft^2
    Full table: get_skill_file(skill_name="measure-authoring", filename="unit-conversions.md")
  model.alwaysOnDiscreteSchedule — reusable schedule for constructors
HVAC traversal (Ruby):
  model.getAirLoopHVACs.each { |loop| ... }
  loop.supplyComponents.each { |c| ... }
  loop.demandComponents.each { |c| ... }
  loop.thermalZones.each { |z| ... }
  model.getPlantLoops.each { |pl| ... }
  pl.supplyComponents.each { |c| ... }
  zone.equipment.each { |eq| ... }
  node = loop.supplyOutletNode
  c.to_CoilHeatingWater.is_initialized → c.to_CoilHeatingWater.get
ReportingMeasure (model & sql already loaded in boilerplate):
  total_site = sql.totalSiteEnergy; runner.registerValue("total_site_energy", total_site.get)
  query = "SELECT Value FROM TabularDataWithStrings WHERE ..."
  val = sql.execAndReturnFirstDouble(query)
  runner.registerInfo("EUI: #{val.get} kBtu/ft2") if val.is_initialized

```

## Python run_body patterns

```python
same error/applicability rules as Ruby:
  runner.registerError("msg") — follow with `return False`
  runner.registerAsNotApplicable("msg") then return True
.name() returns OptionalString:
  str(obj.name()) or obj.name().get() — not bare obj.name()
ModelMeasure:
  for s in model.getSurfaces(): ...
  for ss in model.getSubSurfaces(): ...
  for z in model.getThermalZones(): ...
  model.getBuilding().setName(name)
  s.outsideBoundaryCondition() == "Outdoors"
  opt = surface.construction(); if opt.is_initialized(): c = opt.get()
  openstudio.convert(val, "W/m^2", "Btu/hr*ft^2").get()
  model.alwaysOnDiscreteSchedule()
HVAC traversal (Python):
  for loop in model.getAirLoopHVACs(): ...
  for c in loop.supplyComponents(): ...
  for c in loop.demandComponents(): ...
  for z in loop.thermalZones(): ...
  for pl in model.getPlantLoops(): ...
  node = loop.supplyOutletNode()
  if c.to_CoilHeatingWater().is_initialized(): coil = c.to_CoilHeatingWater().get()
Air terminal types (via air_loop.addBranchForZone, not addToThermalZone):
  CooledBeam (2-pipe):
    coil = CoilCoolingCooledBeam.new(model)
    terminal = AirTerminalSingleDuctConstantVolumeCooledBeam.new(model, sch, coil)
  FourPipeBeam (4-pipe):
    cc = CoilCoolingFourPipeBeam.new(model)
    hc = CoilHeatingFourPipeBeam.new(model)
    terminal = AirTerminalSingleDuctConstantVolumeFourPipeBeam.new(model, cc, hc)
Beams are air terminals, not zone equipment.
Plant loop wiring: chw_loop.addDemandBranchForComponent(coil)
Zone equipment priority:
  model.getZoneHVACEquipmentLists.setCoolingPriority(equip, n)
```
