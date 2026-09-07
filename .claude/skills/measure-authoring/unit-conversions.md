# Unit Conversion — OpenStudio.convert

`OpenStudio.convert(value, from_unit, to_unit).get` (Ruby) /
`openstudio.convert(value, from_unit, to_unit).get()` (Python) — composable
unit parser.

Syntax: `*` (multiply), `/` (divide), `^` (exponent). Scale prefixes: `k`, `M`, `G`, `m`, `c`.

| Category | Unit strings |
|---|---|
| Energy | `J`, `kJ`, `MJ`, `GJ`, `kWh`, `MWh`, `Btu`, `kBtu`, `therm` |
| Power | `W`, `kW`, `Btu/h`, `ton` |
| EUI | `kWh/m^2`, `kBtu/ft^2`, `GJ/m^2` |
| Power density | `W/m^2`, `W/ft^2`, `Btu/hr*ft^2` |
| R-value | `m^2*K/W`, `ft^2*hr*R/Btu` |
| U-value | `W/m^2*K`, `Btu/hr*ft^2*R` |
| Thermal conductivity | `W/m*K`, `Btu/hr*ft*R` |
| Specific heat | `J/kg*K`, `Btu/lb_m*R` |
| Flow rate | `m^3/s`, `cfm`, `L/s`, `gal/min` |
| Flow/area | `cfm/ft^2`, `m^3/s*m^2`, `L/s*m^2` |
| Temperature | `C`, `F`, `K`, `R` |
| Length/Area/Volume | `m`, `ft`, `in`, `m^2`, `ft^2`, `m^3`, `ft^3`, `gal`, `L` |
| Pressure | `Pa`, `kPa`, `psi`, `inHg` |
| Mass/Density | `kg`, `lb`, `lb_m`, `kg/m^3`, `lb/ft^3` |
| Illuminance | `lux`, `fc` |

Source: [OpenStudio SDK units](https://github.com/NREL/OpenStudio/tree/develop/src/utilities/units/)
