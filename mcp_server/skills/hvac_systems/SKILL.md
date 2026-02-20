# hvac_systems

System-level HVAC templates and ASHRAE 90.1 Appendix G baseline systems.

## Overview

The `hvac_systems` skill provides high-level HVAC system creation tools that abstract away component-level wiring complexity. Instead of manually creating and connecting individual coils, fans, loops, and terminals, use these tools to create complete, validated HVAC systems in a single step.

## Current Implementation Status

**Phase 4B: ALL 10 ASHRAE Baseline Systems** ✅ COMPLETE

All ASHRAE 90.1 Appendix G baseline system types fully implemented:

**Zone Equipment Systems:**

- ✅ System 1: PTAC (Packaged Terminal Air Conditioner)
- ✅ System 2: PTHP (Packaged Terminal Heat Pump)
- ✅ System 9: Heating & Ventilation (Gas Unit Heaters)
- ✅ System 10: Heating & Ventilation (Electric Unit Heaters)

**Packaged Rooftop Systems:**

- ✅ System 3: PSZ-AC (Single Zone Air Conditioner)
- ✅ System 4: PSZ-HP (Single Zone Heat Pump)
- ✅ System 5: Packaged VAV w/ Reheat (HW loop, boiler, VAV terminals)
- ✅ System 6: Packaged VAV w/ PFP (Parallel fan-powered boxes)

**Central Plant Systems:**

- ✅ System 7: VAV w/ Reheat (Chiller/Boiler/Tower, HW reheat)
- ✅ System 8: VAV w/ PFP (Chiller/Boiler/Tower, electric reheat)

**Testing:** 18 comprehensive integration tests

- All systems tested with success + error cases
- Multi-zone validation (PSZ rejection)
- Plant loop verification (Systems 5, 7-8)
- Terminal verification (VAV vs PFP)
- Edge case handling

**Implementation Timeline:**

- Phase 4A: Systems 1-3 (1 week)
- Phase 4B Batch 1: Systems 4-6 (2 days)
- Phase 4B Batch 2: Systems 7-8 (2 days)
- Phase 4B Batch 3: Systems 9-10 (1 day)

**Next Phases:**

- Phase 4C: Air terminal replacement tool
- Phase 4D: Component-level validation tests (detailed ASHRAE compliance)
- Phase 4E: Modern templates (DOAS, VRF, Radiant)
- Additional introspection tools

## Tools

### add_baseline_system

Add complete ASHRAE 90.1 Appendix G baseline HVAC system.

**Parameters:**

- `system_type` (int, required): ASHRAE baseline system type (1-3 currently)
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
**Notes:** Central air loop serving single zone, supports economizer

### System 4: PSZ-HP (Coming Soon)

**Equipment:** Packaged single-zone heat pump rooftop unit
**Heating:** DX heat pump with supplemental electric
**Cooling:** DX heat pump
**Use Case:** Small commercial, retail

### Systems 5-10 (Coming Soon)

- System 5: Packaged VAV w/ Reheat
- System 6: Packaged VAV w/ PFP Boxes
- System 7: VAV w/ Reheat (Chiller/Boiler)
- System 8: VAV w/ PFP Boxes (Chiller/Boiler)
- System 9: Heating & Ventilation (Gas)
- System 10: Heating & Ventilation (Electric)

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
- Systems 5-8 will create plant loops (chilled water, hot water, condenser)
- Economizer parameter only applies to central systems (3-8)
- Fuel parameters validated against system type capabilities

## See Also

- `hvac/` skill — Query existing air loops, plant loops, zone equipment
- `spaces/` skill — Create thermal zones to serve with HVAC systems
- Phase 4 Implementation Plan — docs/PHASE_4_IMPLEMENTATION_PLAN.md
