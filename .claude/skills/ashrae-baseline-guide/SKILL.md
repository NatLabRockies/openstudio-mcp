---
name: ashrae-baseline-guide
description: ASHRAE 90.1 Appendix G baseline system selection criteria. Use when recommending HVAC system types, creating baseline models, or answering questions about ASHRAE 90.1 compliance.
user-invocable: false
---

# ASHRAE 90.1 Appendix G Baseline System Selection

## System Selection (Table G3.1.1)

Select baseline system based on **building type**, **heating fuel**, and **floor area / floor count**.

### Residential Buildings
(hotels/motels, dormitories, apartments)

| Heating Source | System |
|---------------|--------|
| Fossil fuel / hybrid | **System 1: PTAC** (any size) |
| Electric resistance | **System 2: PTHP** (any size) |

### Non-Residential Buildings

| Heating Source | < 25,000 ft2 | 25,000-150,000 ft2 | > 150,000 ft2 |
|---------------|---------------|----------------------|----------------|
| Fossil fuel / hybrid (<=3 floors) | **System 3: PSZ-AC** | **System 3: PSZ-AC** | **System 5: Pkg VAV w/ Reheat** |
| Fossil fuel / hybrid (>3 floors) | **System 3: PSZ-AC** | **System 5: Pkg VAV w/ Reheat** | **System 7: VAV w/ Reheat** |
| Electric resistance (<=3 floors) | **System 4: PSZ-HP** | **System 4: PSZ-HP** | **System 6: Pkg VAV w/ PFP** |
| Electric resistance (>3 floors) | **System 4: PSZ-HP** | **System 6: Pkg VAV w/ PFP** | **System 8: VAV w/ PFP** |

### Heated-Only Buildings
(warehouses, garages, no mechanical cooling)

| Heating Source | System |
|---------------|--------|
| Fossil fuel / hybrid | **System 9: Gas Unit Heater** |
| Electric resistance | **System 10: Electric Unit Heater** |

## System Summary

| # | Name | Equipment Level | Heating | Cooling | Plant Loops |
|---|------|----------------|---------|---------|-------------|
| 1 | PTAC | Zone | Electric resistance | DX single speed | None |
| 2 | PTHP | Zone | DX heat pump + elec backup | DX heat pump | None |
| 3 | PSZ-AC | Central (single zone) | Gas furnace or elec | DX single speed | None |
| 4 | PSZ-HP | Central (single zone) | DX HP + elec backup | DX heat pump | None |
| 5 | Pkg VAV w/ Reheat | Central (multi zone) | HW reheat coils | DX two speed | Hot water loop + boiler |
| 6 | Pkg VAV w/ PFP | Central (multi zone) | Electric PFP boxes | DX two speed | None |
| 7 | VAV w/ Reheat | Central (multi zone) | HW reheat coils | Chilled water | HW + CHW + condenser loops |
| 8 | VAV w/ PFP | Central (multi zone) | Electric PFP boxes | Chilled water | CHW + condenser loops |
| 9 | Gas Unit Heater | Zone | Gas unit heater | None | None |
| 10 | Electric Unit Heater | Zone | Electric unit heater | None | None |

## Heating Fuel Logic

The `heating_fuel` parameter maps to:
- `"NaturalGas"` → fossil fuel systems (1, 3, 5, 7, 9)
- `"Electricity"` → electric systems (2, 4, 6, 8, 10)
- `"DistrictHeating"` → treated as fossil fuel path

## Economizer Applicability

- **Systems 3-8:** Support air-side economizer (`economizer=True` by default)
- **Systems 1-2, 9-10:** Zone equipment, no economizer possible
- Climate zone affects economizer control type (not yet parameterized)

## Multi-Zone Constraints

- **Systems 1-2, 9-10:** One unit per zone (zone equipment)
- **Systems 3-4:** One air loop per zone (PSZ = packaged single-zone)
- **Systems 5-8:** One air loop serves multiple zones (VAV)

When user provides multiple zones:
- Systems 3-4 create separate air loops per zone
- Systems 5-8 create one shared air loop

## Tool Mapping

| Action | Tool | Key Parameters |
|--------|------|----------------|
| Create baseline system | `add_baseline_system` | `system_type`, `thermal_zone_names`, `heating_fuel` |
| List available systems | `list_baseline_systems` | (none) |
| System details | `get_baseline_system_info` | `system_type` |
| Modern alternatives | `add_doas_system`, `add_vrf_system`, `add_radiant_system` | `thermal_zone_names` |

## When to Recommend Modern Templates Instead

| Scenario | Recommendation |
|----------|---------------|
| High ventilation requirements (labs, hospitals) | **DOAS** with fan coils or chilled beams |
| Many small zones with diverse loads | **VRF** heat pump system |
| Comfort-critical spaces, radiant heating/cooling | **Radiant** floor/ceiling |
| Net-zero or high-performance target | **DOAS + Radiant** or **DOAS + VRF** |
