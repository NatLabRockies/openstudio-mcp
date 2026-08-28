# hvac_systems — internal dev notes

System-level HVAC templates and ASHRAE 90.1 Appendix G baseline systems.
Served agent guidance lives in `.claude/skills/add-hvac/SKILL.md` (via
`get_skill("add-hvac")`), including the comfort-defaults doctrine.

## Overview

The `hvac_systems` skill provides high-level HVAC system creation tools that abstract away component-level wiring complexity. Instead of manually creating and connecting individual coils, fans, loops, and terminals, use these tools to create complete, validated HVAC systems in a single step.

## Scope and Role (read this first)

These are GENERIC WIRING TEMPLATES: explicit topology control via direct SDK
calls, no standards equipment efficiencies. For comparative studies or
decision-grade EUI/comfort numbers, use the openstudio-standards path
instead: `create_typical_building(system_type=..., hvac_only=True)` replaces
only the HVAC and preserves loads/schedules/thermostats (issue #97).

All 10 ASHRAE 90.1 Appendix G baseline system types are implemented, plus
modern templates (DOAS, VRF, Radiant) and terminal replacement tools.

- Systems 1-2, 9-10: zone equipment (PTAC, PTHP, gas/electric unit heaters)
- Systems 3-4: packaged single-zone (PSZ-AC gas/electric; PSZ-HP as a
  unitary heat pump composite with full-size staged supplemental heat) —
  one air loop per zone; pass the full zone list, the tool fans out
- Systems 5-6: packaged VAV (HW reheat / PFP boxes), one shared air loop
- Systems 7-8: central plant VAV (chiller/boiler/tower)

## Comfort defaults

Migrated to the served add-hvac skill ("Why These Defaults") — edit it there. Implementation: baseline.py / templates.py.

## Tools

### add_baseline_system

Add complete ASHRAE 90.1 Appendix G baseline HVAC system.

**Parameters:**
- `system_type` (int, required): ASHRAE baseline system type (1-10)
- `thermal_zone_names` (list[str], required): Thermal zone names to serve
- `heating_fuel` (str, default="NaturalGas"): "NaturalGas", "Electricity", or "DistrictHeating"
- `cooling_fuel` (str, default="Electricity"): "Electricity" or "DistrictCooling"
- `economizer` (bool, default=True): Enable air-side economizer where applicable
- `system_name` (str, optional): Custom system name (auto-generated if None)

**Returns:**
```json
{
  "ok": true,
  "system": {
    "name": "PTAC HVAC",
    "type": "PTAC (Baseline System 1)",
    "category": "baseline",
    "system_number": 1,
    "equipment_type": "Zone HVAC",
    "zones_served": 4,
    "equipment": [
      {
        "zone": "Zone 1",
        "equipment": "PTAC HVAC PTAC - Zone 1",
        "heating_coil": "...",
        "cooling_coil": "...",
        "fan": "..."
      }
    ],
    "heating": "Electric Resistance",
    "cooling": "DX Single Speed"
  },
  "validation": {
    "ok": true,
    "valid": true,
    "zones": [...]
  }
}
```

**Example:**
```python
# Add PTAC system to all zones
add_baseline_system(
    system_type=1,
    thermal_zone_names=["Zone 1", "Zone 2", "Zone 3"],
    heating_fuel="Electricity",
    system_name="PTAC System"
)

# Add PSZ-AC rooftop unit to single zone
add_baseline_system(
    system_type=3,
    thermal_zone_names=["Main Zone"],
    heating_fuel="NaturalGas",
    economizer=True,
    system_name="Rooftop Unit 1"
)
```

### list_baseline_systems

List all ASHRAE 90.1 Appendix G baseline system types (1-10) and modern templates.

**Parameters:** None

**Returns:**
```json
{
  "ok": true,
  "baseline_systems": [
    {
      "category": "baseline",
      "system_type": 1,
      "name": "PTAC",
      "description": "Electric resistance heating, DX cooling, zone-level equipment"
    },
    ...
  ],
  "modern_templates": [
    {
      "category": "modern",
      "name": "DOAS",
      "description": "100% outdoor air with heat recovery, tempering only"
    },
    ...
  ],
  "total_count": 13
}
```

### get_baseline_system_info

Get detailed metadata for a specific ASHRAE baseline system type.

**Parameters:**
- `system_type` (int, required): System type (1-10)

**Returns:**
```json
{
  "ok": true,
  "system": {
    "name": "PTAC",
    "full_name": "Packaged Terminal Air Conditioner",
    "description": "Electric resistance heating, DX cooling, zone-level equipment",
    "heating": "Electric Resistance",
    "cooling": "DX",
    "distribution": "Zone Equipment",
    "typical_use": "Low-rise residential, motels"
  }
}
```

## System Types Reference

### System 1: PTAC
**Equipment:** Zone-level packaged terminal air conditioner
**Heating:** Electric resistance coil
**Cooling:** Single-speed DX coil
**Use Case:** Low-rise residential, motels, small spaces
**Notes:** One PTAC unit per zone, no central air loop

### System 2: PTHP
**Equipment:** Zone-level packaged terminal heat pump
**Heating:** DX heat pump with electric resistance supplemental
**Cooling:** DX heat pump
**Use Case:** Low-rise residential, motels
**Notes:** Same as PTAC but with heat pump efficiency

### System 3: PSZ-AC
**Equipment:** Packaged single-zone rooftop unit
**Heating:** Gas furnace or electric resistance
**Cooling:** Single-speed DX coil
**Use Case:** Small commercial, retail, single-zone buildings
**Notes:** One air loop per zone — pass the full zone list, the tool fans out; supports economizer

### System 4: PSZ-HP
**Equipment:** Packaged single-zone heat pump rooftop unit
**Heating:** DX heat pump with supplemental electric
**Cooling:** DX heat pump
**Use Case:** Small commercial, retail
**Notes:** One air loop per zone (pass the full zone list); supports economizer

### System 5: Packaged VAV w/ Reheat
**Equipment:** Packaged rooftop VAV with hot water reheat
**Heating:** HW boiler loop + DX cooling
**Cooling:** DX coil
**Use Case:** Medium commercial
**Notes:** Creates HW plant loop with boiler, VAV reheat terminals

### System 6: Packaged VAV w/ PFP Boxes
**Equipment:** Packaged rooftop VAV with parallel fan-powered boxes
**Heating:** Electric reheat in PFP terminals
**Cooling:** DX coil
**Use Case:** Medium commercial
**Notes:** PFP terminals with electric reheat, no HW loop

### System 7: VAV w/ Reheat (Chiller/Boiler)
**Equipment:** Central VAV with chiller, boiler, cooling tower
**Heating:** HW boiler, HW reheat coils
**Cooling:** Chilled water coil
**Use Case:** Large commercial
**Notes:** Creates CHW, HW, and condenser water loops

### System 8: VAV w/ PFP Boxes (Chiller/Boiler)
**Equipment:** Central VAV with chiller, cooling tower, PFP terminals
**Heating:** Electric reheat in PFP terminals
**Cooling:** Chilled water coil
**Use Case:** Large commercial
**Notes:** Creates CHW and condenser loops, PFP with electric reheat

### System 9: Heating & Ventilation (Gas)
**Equipment:** Gas-fired unit heaters
**Heating:** Gas unit heater per zone
**Cooling:** None
**Use Case:** Warehouses, mechanical rooms

### System 10: Heating & Ventilation (Electric)
**Equipment:** Electric unit heaters
**Heating:** Electric unit heater per zone
**Cooling:** None
**Use Case:** Warehouses, mechanical rooms

## Validation

All systems are automatically validated after creation:
- Zone equipment properly connected
- Air loops have required components
- Plant loops properly sized and connected
- Setpoint managers in place
- No orphaned nodes or components

Validation results included in tool response under `"validation"` key.

## Design Principles

1. **System-level abstraction** — Hide component wiring complexity
2. **Safe defaults** — Use ASHRAE 90.1 values where applicable
3. **Minimal parameters** — Only expose high-value configuration
4. **Model integrity** — Validate connections automatically
5. **Integration tested** — Every system type has test coverage

## Implementation Notes

- Systems 1-2 create zone equipment (no air loops)
- System 3 creates central air loop with outdoor air system
- Plant loops: System 5 creates HW; 7 creates CHW + HW + condenser; 8 creates CHW + condenser; 6 creates none (electric PFP reheat)
- Economizer parameter only applies to central systems (3-8)
- Fuel parameters validated against system type capabilities

## DOAS Zone Equipment Types

| Type | Description | Plant Loops Required |
|------|-------------|---------------------|
| `FanCoil` | 4-pipe fan coil units (heating + cooling) | CHW + HW |
| `Radiant` | Low-temp radiant panels (floor/ceiling) | CHW + HW |
| `ChilledBeams` | Passive/active chilled beams (cooling only) | CHW only |
| `FourPipeBeam` | 4-pipe active chilled beams (heating + cooling) | CHW + HW |

(`CooledBeam` is a terminal type for `replace_air_terminals`, NOT a valid
`add_doas_system` zone_equipment_type — the tool accepts only the four above.)

## API Reference

- OpenStudio SDK: https://openstudio-sdk-documentation.s3.amazonaws.com/index.html
- HVAC wiring patterns: https://github.com/NatLabRockies/OpenStudio-resources/tree/develop/model/simulationtests
  - Key files: airterminal_fourpipebeam.py, airterminal_cooledbeam.py, baseline_sys*.py

## See Also

- `hvac/` skill — Query existing air loops, plant loops, zone equipment
- `spaces/` skill — Create thermal zones to serve with HVAC systems
