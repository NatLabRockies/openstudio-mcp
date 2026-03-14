"""Verify OpenStudio.convert() works for all unit strings documented in SKILL.md.

These are the unit pairs that measures commonly use for BEM calculations.
Runs inside Docker where the openstudio Python bindings are available.
"""
import pytest
from conftest import integration_enabled

# (from_unit, to_unit) pairs — each must produce a finite, non-zero result
CONVERSION_PAIRS = [
    # Energy
    ("J", "kJ"),
    ("J", "MJ"),
    ("J", "GJ"),
    ("J", "kWh"),
    ("J", "MWh"),
    ("J", "Btu"),
    ("kWh", "kBtu"),
    ("GJ", "therm"),
    ("kWh", "Btu"),
    ("MJ", "kBtu"),
    # Power
    ("W", "kW"),
    ("W", "Btu/h"),
    ("ton", "kW"),
    ("ton", "W"),
    ("kW", "Btu/h"),
    # EUI
    ("kWh/m^2", "kBtu/ft^2"),
    ("GJ/m^2", "kBtu/ft^2"),
    ("MJ/m^2", "kWh/m^2"),
    ("J/m^2", "kWh/m^2"),
    # Power density
    ("W/m^2", "W/ft^2"),
    ("W/m^2", "Btu/hr*ft^2"),
    ("W/ft^2", "Btu/hr*ft^2"),
    # R-value (thermal resistance)
    ("m^2*K/W", "ft^2*hr*R/Btu"),
    # U-value (thermal transmittance)
    ("W/m^2*K", "Btu/hr*ft^2*R"),
    # Thermal conductivity
    ("W/m*K", "Btu/hr*ft*R"),
    # Specific heat
    ("J/kg*K", "Btu/lb_m*R"),
    # Flow rate
    ("m^3/s", "cfm"),
    ("m^3/s", "L/s"),
    ("L/s", "cfm"),
    ("gal/min", "L/s"),
    ("gal/min", "m^3/s"),
    # Flow per area
    ("cfm/ft^2", "m^3/s*m^2"),
    ("L/s*m^2", "cfm/ft^2"),
    # Temperature difference — use K↔R for delta-T conversions
    # (deltaC/deltaF not registered in SDK 3.11)
    ("K", "R"),
    # Length
    ("m", "ft"),
    ("m", "in"),
    ("ft", "in"),
    ("m", "cm"),
    ("m", "mm"),
    ("mi", "km"),
    # Area
    ("m^2", "ft^2"),
    ("m^2", "in^2"),
    ("ft^2", "in^2"),
    # Volume
    ("m^3", "ft^3"),
    ("m^3", "gal"),
    ("m^3", "L"),
    ("gal", "L"),
    # Pressure
    ("Pa", "kPa"),
    ("Pa", "psi"),
    ("Pa", "inHg"),
    ("kPa", "psi"),
    # Mass
    ("kg", "lb"),
    ("kg", "lb_m"),
    # Density
    ("kg/m^3", "lb/ft^3"),
    # Illuminance
    ("lux", "fc"),
    # Velocity
    ("m/s", "ft/s"),
    # Time
    ("s", "min"),
    ("s", "hr"),
    ("hr", "min"),
    ("day", "hr"),
]

# Identity conversions — verify these unit strings parse at all
IDENTITY_UNITS = [
    "W", "kW", "MW", "GW",
    "J", "kJ", "MJ", "GJ",
    "Wh", "kWh", "MWh",
    "Btu", "kBtu",
    "therm",
    "ton",
    "m", "cm", "mm", "km",
    "ft", "in",
    "m^2", "ft^2",
    "m^3", "ft^3",
    "gal", "L",
    "kg", "g", "lb", "lb_m",
    "Pa", "kPa",
    "K", "C", "F", "R",
    "s", "min", "hr", "h", "day",
    "N",
    "lux", "fc",
    "Hz",
    "cfm",
]


@pytest.mark.integration
def test_unit_conversion_pairs():
    """All documented from→to unit pairs must produce finite non-zero results."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    import openstudio
    failures = []
    for from_u, to_u in CONVERSION_PAIRS:
        result = openstudio.convert(1.0, from_u, to_u)
        if not result.is_initialized():
            failures.append(f"{from_u} → {to_u}: convert returned empty")
        else:
            val = result.get()
            if val == 0.0 or not isinstance(val, float):
                failures.append(f"{from_u} → {to_u}: got {val}")
    assert not failures, "Failed conversions:\n" + "\n".join(failures)


@pytest.mark.integration
def test_unit_identity_conversions():
    """All documented unit strings must parse (identity conversion)."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    import openstudio
    failures = []
    for unit in IDENTITY_UNITS:
        result = openstudio.convert(1.0, unit, unit)
        if not result.is_initialized():
            failures.append(f"{unit}: identity convert failed")
        else:
            val = result.get()
            if abs(val - 1.0) > 1e-10:
                failures.append(f"{unit}: identity convert got {val}, expected 1.0")
    assert not failures, "Failed identity conversions:\n" + "\n".join(failures)


@pytest.mark.integration
def test_temperature_conversions():
    """Temperature conversions (absolute) need special handling — verify known values."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    import openstudio
    # 0°C = 32°F = 273.15K
    c_to_f = openstudio.convert(0.0, "C", "F")
    assert c_to_f.is_initialized()
    assert abs(c_to_f.get() - 32.0) < 0.01, f"0°C should be 32°F, got {c_to_f.get()}"

    c_to_k = openstudio.convert(0.0, "C", "K")
    assert c_to_k.is_initialized()
    assert abs(c_to_k.get() - 273.15) < 0.01, f"0°C should be 273.15K, got {c_to_k.get()}"

    # 100°C = 212°F
    c100_to_f = openstudio.convert(100.0, "C", "F")
    assert c100_to_f.is_initialized()
    assert abs(c100_to_f.get() - 212.0) < 0.01, f"100°C should be 212°F, got {c100_to_f.get()}"
