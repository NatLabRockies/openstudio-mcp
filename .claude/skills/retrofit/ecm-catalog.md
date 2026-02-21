# ECM Catalog — Available Energy Conservation Measures

## Envelope

| ECM | Tool | Typical Savings |
|-----|------|-----------------|
| Upgrade wall insulation | `create_standard_opaque_material` + `create_construction` + `assign_construction_to_surface` | 5-15% heating |
| Replace windows | `replace_window_constructions` | 5-20% heating/cooling |
| Add roof insulation | Same as wall upgrade, target roof surfaces | 5-10% heating/cooling |
| Set adiabatic boundaries | `set_adiabatic_boundaries` | Varies (modeling technique) |

## HVAC / Controls

| ECM | Tool | Typical Savings |
|-----|------|-----------------|
| Widen thermostat deadband | `adjust_thermostat_setpoints` | 5-15% HVAC |
| Schedule optimization | `shift_schedule_time` | 3-10% total |
| Replace thermostat schedules | `replace_thermostat_schedules` | 5-15% HVAC |
| HVAC system upgrade | `add_baseline_system` / `add_vrf_system` / `add_doas_system` | 10-30% HVAC |

## Renewables

| ECM | Tool | Typical Impact |
|-----|------|----------------|
| Rooftop PV | `add_rooftop_pv` | 10-40% electricity offset |
| Shading PV | `add_pv_to_shading` | Varies by surface area |

## Loads

| ECM | Tool | Typical Savings |
|-----|------|-----------------|
| Reduce lighting power | `create_lights_definition` (lower watts_per_area) | 5-20% lighting |
| Reduce plug loads | `create_electric_equipment` (lower watts_per_area) | 3-10% equipment |
| Optimize ventilation | `add_zone_ventilation` | 5-15% HVAC |

## Analysis Tools

| Tool | Purpose |
|------|---------|
| `extract_summary_metrics` | EUI, total energy, unmet hours |
| `extract_end_use_breakdown` | Energy by end use and fuel |
| `run_qaqc_checks` | Verify model quality post-retrofit |
