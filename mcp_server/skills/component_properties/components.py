"""Explicit per-component property getters and setters.

This file defines how to read and write properties for each supported HVAC
component type. Every OpenStudio API method is called directly — no dynamic
dispatch or getattr() magic. This makes the code grepable, debuggable, and
easy for contributors to extend.

ADDING A NEW COMPONENT TYPE:
    1. Write a _get_<type>_props(obj) function that returns a dict of
       property_name -> {"value": ..., "unit": "..."}.
    2. Write a _set_<type>_props(obj, properties) function that takes a
       dict of property_name -> value and returns (changes_dict, errors_list).
    3. Add an entry to COMPONENT_TYPES at the bottom of this file.

This project is intended as a template for other building energy simulation
engines (EnergyPlus, TRNSYS, DOE-2, etc.). Each component function shows
exactly which simulation engine API methods are needed, making it
straightforward to map to equivalent methods in other engines.

OpenStudio API methods verified against openstudio-resources simulation tests:
https://github.com/NatLabRockies/OpenStudio-resources/tree/develop/model/simulationtests
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Helper: read OpenStudio OptionalDouble values
# ---------------------------------------------------------------------------
# OpenStudio uses boost::optional<double> for autosizable fields.
# The Python binding returns an object with is_initialized()/get() methods.
# Non-optional fields return a plain Python float.

def _read_optional_double(optional_val) -> float | str:
    """Read an OptionalDouble. Returns float if set, 'Autosize' if unset."""
    if hasattr(optional_val, "is_initialized"):
        return float(optional_val.get()) if optional_val.is_initialized() else "Autosize"
    return float(optional_val)


# ===================================================================
# COILS — Heating
# ===================================================================

# --- CoilHeatingElectric ---
# Simple electric resistance heating coil. Used in PTAC (System 1),
# unit heaters, and as reheat coils in VAV terminals.

def _get_coil_heating_electric_props(coil) -> dict:
    return {
        "efficiency": {
            "value": float(coil.efficiency()),  # CoilHeatingElectric.efficiency()
            "unit": "",
        },
        "nominal_capacity_w": {
            "value": _read_optional_double(coil.nominalCapacity()),  # .nominalCapacity()
            "unit": "W",
        },
    }


def _set_coil_heating_electric_props(coil, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "efficiency":
            old = float(coil.efficiency())
            coil.setEfficiency(float(value))                   # .setEfficiency(double)
            changes[name] = {"old": old, "new": float(coil.efficiency()), "unit": ""}
        elif name == "nominal_capacity_w":
            old = _read_optional_double(coil.nominalCapacity())
            coil.setNominalCapacity(float(value))              # .setNominalCapacity(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.nominalCapacity()), "unit": "W"}
        else:
            errors.append(f"Unknown property '{name}' for CoilHeatingElectric")
    return changes, errors


# --- CoilHeatingGas ---
# Gas-fired heating coil. Used in Systems 3-4 (PSZ-AC/HP) and as
# preheat coils in VAV systems.

def _get_coil_heating_gas_props(coil) -> dict:
    return {
        "gas_burner_efficiency": {
            "value": float(coil.gasBurnerEfficiency()),  # .gasBurnerEfficiency()
            "unit": "",
        },
        "nominal_capacity_w": {
            "value": _read_optional_double(coil.nominalCapacity()),  # .nominalCapacity()
            "unit": "W",
        },
    }


def _set_coil_heating_gas_props(coil, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "gas_burner_efficiency":
            old = float(coil.gasBurnerEfficiency())
            coil.setGasBurnerEfficiency(float(value))          # .setGasBurnerEfficiency(double)
            changes[name] = {"old": old, "new": float(coil.gasBurnerEfficiency()), "unit": ""}
        elif name == "nominal_capacity_w":
            old = _read_optional_double(coil.nominalCapacity())
            coil.setNominalCapacity(float(value))              # .setNominalCapacity(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.nominalCapacity()), "unit": "W"}
        else:
            errors.append(f"Unknown property '{name}' for CoilHeatingGas")
    return changes, errors


# --- CoilHeatingWater ---
# Hot-water heating coil connected to a hot water plant loop.
# Used in Systems 5, 7 (VAV reheat coils) and fan coil units.

def _get_coil_heating_water_props(coil) -> dict:
    return {
        "rated_capacity_w": {
            "value": _read_optional_double(coil.ratedCapacity()),  # .ratedCapacity()
            "unit": "W",
        },
        "max_water_flow_rate_m3s": {
            "value": _read_optional_double(coil.maximumWaterFlowRate()),  # .maximumWaterFlowRate()
            "unit": "m3/s",
        },
    }


def _set_coil_heating_water_props(coil, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "rated_capacity_w":
            old = _read_optional_double(coil.ratedCapacity())
            coil.setRatedCapacity(float(value))                # .setRatedCapacity(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.ratedCapacity()), "unit": "W"}
        elif name == "max_water_flow_rate_m3s":
            old = _read_optional_double(coil.maximumWaterFlowRate())
            coil.setMaximumWaterFlowRate(float(value))         # .setMaximumWaterFlowRate(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.maximumWaterFlowRate()), "unit": "m3/s"}
        else:
            errors.append(f"Unknown property '{name}' for CoilHeatingWater")
    return changes, errors


# --- CoilHeatingDXSingleSpeed ---
# DX heat pump heating coil. Used in PTHP (System 2) and PSZ-HP (System 4).

def _get_coil_heating_dx_single_speed_props(coil) -> dict:
    return {
        "rated_cop": {
            "value": float(coil.ratedCOP()),                    # .ratedCOP()
            "unit": "",
        },
        "rated_capacity_w": {
            "value": _read_optional_double(coil.ratedTotalHeatingCapacity()),  # .ratedTotalHeatingCapacity()
            "unit": "W",
        },
    }


def _set_coil_heating_dx_single_speed_props(coil, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "rated_cop":
            old = float(coil.ratedCOP())
            coil.setRatedCOP(float(value))                     # .setRatedCOP(double)
            changes[name] = {"old": old, "new": float(coil.ratedCOP()), "unit": ""}
        elif name == "rated_capacity_w":
            old = _read_optional_double(coil.ratedTotalHeatingCapacity())
            coil.setRatedTotalHeatingCapacity(float(value))    # .setRatedTotalHeatingCapacity(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.ratedTotalHeatingCapacity()), "unit": "W"}
        else:
            errors.append(f"Unknown property '{name}' for CoilHeatingDXSingleSpeed")
    return changes, errors


# ===================================================================
# COILS — Cooling
# ===================================================================

# --- CoilCoolingDXSingleSpeed ---
# Single-speed DX cooling coil. Used in PTAC (System 1), PTHP (System 2),
# PSZ-AC (System 3), and PSZ-HP (System 4).

def _get_coil_cooling_dx_single_speed_props(coil) -> dict:
    return {
        "rated_cop": {
            "value": float(coil.ratedCOP()),                    # .ratedCOP()
            "unit": "",
        },
        "rated_capacity_w": {
            "value": _read_optional_double(coil.ratedTotalCoolingCapacity()),  # .ratedTotalCoolingCapacity()
            "unit": "W",
        },
        "rated_shr": {
            "value": _read_optional_double(coil.ratedSensibleHeatRatio()),  # .ratedSensibleHeatRatio()
            "unit": "",
        },
    }


def _set_coil_cooling_dx_single_speed_props(coil, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "rated_cop":
            old = float(coil.ratedCOP())
            coil.setRatedCOP(float(value))                     # .setRatedCOP(double)
            changes[name] = {"old": old, "new": float(coil.ratedCOP()), "unit": ""}
        elif name == "rated_capacity_w":
            old = _read_optional_double(coil.ratedTotalCoolingCapacity())
            coil.setRatedTotalCoolingCapacity(float(value))    # .setRatedTotalCoolingCapacity(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.ratedTotalCoolingCapacity()), "unit": "W"}
        elif name == "rated_shr":
            old = _read_optional_double(coil.ratedSensibleHeatRatio())
            coil.setRatedSensibleHeatRatio(float(value))       # .setRatedSensibleHeatRatio(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.ratedSensibleHeatRatio()), "unit": ""}
        else:
            errors.append(f"Unknown property '{name}' for CoilCoolingDXSingleSpeed")
    return changes, errors


# --- CoilCoolingDXTwoSpeed ---
# Two-speed DX cooling coil. Used in Systems 5-6 (packaged VAV).

def _get_coil_cooling_dx_two_speed_props(coil) -> dict:
    return {
        "high_speed_cop": {
            "value": _read_optional_double(coil.ratedHighSpeedCOP()),  # .ratedHighSpeedCOP()
            "unit": "",
        },
        "low_speed_cop": {
            "value": _read_optional_double(coil.ratedLowSpeedCOP()),   # .ratedLowSpeedCOP()
            "unit": "",
        },
        "high_speed_capacity_w": {
            "value": _read_optional_double(coil.ratedHighSpeedTotalCoolingCapacity()),  # .ratedHighSpeedTotalCoolingCapacity()
            "unit": "W",
        },
    }


def _set_coil_cooling_dx_two_speed_props(coil, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "high_speed_cop":
            old = _read_optional_double(coil.ratedHighSpeedCOP())
            coil.setRatedHighSpeedCOP(float(value))            # .setRatedHighSpeedCOP(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.ratedHighSpeedCOP()), "unit": ""}
        elif name == "low_speed_cop":
            old = _read_optional_double(coil.ratedLowSpeedCOP())
            coil.setRatedLowSpeedCOP(float(value))             # .setRatedLowSpeedCOP(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.ratedLowSpeedCOP()), "unit": ""}
        elif name == "high_speed_capacity_w":
            old = _read_optional_double(coil.ratedHighSpeedTotalCoolingCapacity())
            coil.setRatedHighSpeedTotalCoolingCapacity(float(value))  # .setRatedHighSpeedTotalCoolingCapacity(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.ratedHighSpeedTotalCoolingCapacity()), "unit": "W"}
        else:
            errors.append(f"Unknown property '{name}' for CoilCoolingDXTwoSpeed")
    return changes, errors


# --- CoilCoolingWater ---
# Chilled-water cooling coil connected to a CHW plant loop.
# Used in Systems 7-8 (central VAV) and fan coil units.

def _get_coil_cooling_water_props(coil) -> dict:
    return {
        "design_water_flow_rate_m3s": {
            "value": _read_optional_double(coil.designWaterFlowRate()),  # .designWaterFlowRate()
            "unit": "m3/s",
        },
        "design_air_flow_rate_m3s": {
            "value": _read_optional_double(coil.designAirFlowRate()),    # .designAirFlowRate()
            "unit": "m3/s",
        },
    }


def _set_coil_cooling_water_props(coil, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "design_water_flow_rate_m3s":
            old = _read_optional_double(coil.designWaterFlowRate())
            coil.setDesignWaterFlowRate(float(value))          # .setDesignWaterFlowRate(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.designWaterFlowRate()), "unit": "m3/s"}
        elif name == "design_air_flow_rate_m3s":
            old = _read_optional_double(coil.designAirFlowRate())
            coil.setDesignAirFlowRate(float(value))            # .setDesignAirFlowRate(double)
            changes[name] = {"old": old, "new": _read_optional_double(coil.designAirFlowRate()), "unit": "m3/s"}
        else:
            errors.append(f"Unknown property '{name}' for CoilCoolingWater")
    return changes, errors


# ===================================================================
# PLANT EQUIPMENT
# ===================================================================

# --- ChillerElectricEIR ---
# Electric chiller using EIR (Energy Input Ratio) performance curves.
# Used in Systems 7-8 (central VAV with chiller/boiler/tower).

def _get_chiller_electric_eir_props(chiller) -> dict:
    return {
        "reference_cop": {
            "value": float(chiller.referenceCOP()),             # .referenceCOP()
            "unit": "",
        },
        "reference_capacity_w": {
            "value": _read_optional_double(chiller.referenceCapacity()),  # .referenceCapacity()
            "unit": "W",
        },
        "leaving_chw_temp_c": {
            "value": float(chiller.referenceLeavingChilledWaterTemperature()),  # .referenceLeavingChilledWaterTemperature()
            "unit": "C",
        },
    }


def _set_chiller_electric_eir_props(chiller, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "reference_cop":
            old = float(chiller.referenceCOP())
            chiller.setReferenceCOP(float(value))              # .setReferenceCOP(double)
            changes[name] = {"old": old, "new": float(chiller.referenceCOP()), "unit": ""}
        elif name == "reference_capacity_w":
            old = _read_optional_double(chiller.referenceCapacity())
            chiller.setReferenceCapacity(float(value))         # .setReferenceCapacity(double)
            changes[name] = {"old": old, "new": _read_optional_double(chiller.referenceCapacity()), "unit": "W"}
        elif name == "leaving_chw_temp_c":
            old = float(chiller.referenceLeavingChilledWaterTemperature())
            chiller.setReferenceLeavingChilledWaterTemperature(float(value))  # .setReferenceLeavingChilledWaterTemperature(double)
            changes[name] = {"old": old, "new": float(chiller.referenceLeavingChilledWaterTemperature()), "unit": "C"}
        else:
            errors.append(f"Unknown property '{name}' for ChillerElectricEIR")
    return changes, errors


# --- BoilerHotWater ---
# Hot water boiler. Used in Systems 5, 7 (central heating plant).
# Fuel type verified in our wiring.py:224.

def _get_boiler_hot_water_props(boiler) -> dict:
    return {
        "nominal_thermal_efficiency": {
            "value": float(boiler.nominalThermalEfficiency()),  # .nominalThermalEfficiency()
            "unit": "",
        },
        "nominal_capacity_w": {
            "value": _read_optional_double(boiler.nominalCapacity()),  # .nominalCapacity()
            "unit": "W",
        },
        "fuel_type": {
            "value": str(boiler.fuelType()),                    # .fuelType()
            "unit": "",
        },
    }


def _set_boiler_hot_water_props(boiler, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "nominal_thermal_efficiency":
            old = float(boiler.nominalThermalEfficiency())
            boiler.setNominalThermalEfficiency(float(value))   # .setNominalThermalEfficiency(double)
            changes[name] = {"old": old, "new": float(boiler.nominalThermalEfficiency()), "unit": ""}
        elif name == "nominal_capacity_w":
            old = _read_optional_double(boiler.nominalCapacity())
            boiler.setNominalCapacity(float(value))            # .setNominalCapacity(double)
            changes[name] = {"old": old, "new": _read_optional_double(boiler.nominalCapacity()), "unit": "W"}
        elif name == "fuel_type":
            old = str(boiler.fuelType())
            boiler.setFuelType(str(value))                     # .setFuelType(string)
            changes[name] = {"old": old, "new": str(boiler.fuelType()), "unit": ""}
        else:
            errors.append(f"Unknown property '{name}' for BoilerHotWater")
    return changes, errors


# --- CoolingTowerSingleSpeed ---
# Single-speed cooling tower on condenser water loop.
# Used in Systems 7-8 (central VAV with chiller/boiler/tower).

def _get_cooling_tower_single_speed_props(tower) -> dict:
    return {
        "design_water_flow_rate_m3s": {
            "value": _read_optional_double(tower.designWaterFlowRate()),  # .designWaterFlowRate()
            "unit": "m3/s",
        },
        "design_air_flow_rate_m3s": {
            "value": _read_optional_double(tower.designAirFlowRate()),    # .designAirFlowRate()
            "unit": "m3/s",
        },
    }


def _set_cooling_tower_single_speed_props(tower, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "design_water_flow_rate_m3s":
            old = _read_optional_double(tower.designWaterFlowRate())
            tower.setDesignWaterFlowRate(float(value))         # .setDesignWaterFlowRate(double)
            changes[name] = {"old": old, "new": _read_optional_double(tower.designWaterFlowRate()), "unit": "m3/s"}
        elif name == "design_air_flow_rate_m3s":
            old = _read_optional_double(tower.designAirFlowRate())
            tower.setDesignAirFlowRate(float(value))           # .setDesignAirFlowRate(double)
            changes[name] = {"old": old, "new": _read_optional_double(tower.designAirFlowRate()), "unit": "m3/s"}
        else:
            errors.append(f"Unknown property '{name}' for CoolingTowerSingleSpeed")
    return changes, errors


# ===================================================================
# FANS
# ===================================================================

# --- FanConstantVolume ---
# Constant-volume fan. Used in PTAC/PTHP (Systems 1-2) and PSZ (Systems 3-4).
# Pressure rise verified in our templates.py.

def _get_fan_constant_volume_props(fan) -> dict:
    return {
        "pressure_rise_pa": {
            "value": float(fan.pressureRise()),                 # .pressureRise()
            "unit": "Pa",
        },
        "fan_efficiency": {
            "value": float(fan.fanEfficiency()),                # .fanEfficiency()
            "unit": "",
        },
        "motor_efficiency": {
            "value": float(fan.motorEfficiency()),              # .motorEfficiency()
            "unit": "",
        },
    }


def _set_fan_constant_volume_props(fan, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "pressure_rise_pa":
            old = float(fan.pressureRise())
            fan.setPressureRise(float(value))                   # .setPressureRise(double)
            changes[name] = {"old": old, "new": float(fan.pressureRise()), "unit": "Pa"}
        elif name == "fan_efficiency":
            old = float(fan.fanEfficiency())
            fan.setFanEfficiency(float(value))                  # .setFanEfficiency(double)
            changes[name] = {"old": old, "new": float(fan.fanEfficiency()), "unit": ""}
        elif name == "motor_efficiency":
            old = float(fan.motorEfficiency())
            fan.setMotorEfficiency(float(value))                # .setMotorEfficiency(double)
            changes[name] = {"old": old, "new": float(fan.motorEfficiency()), "unit": ""}
        else:
            errors.append(f"Unknown property '{name}' for FanConstantVolume")
    return changes, errors


# --- FanVariableVolume ---
# Variable-volume fan. Used in Systems 5-8 (VAV systems).

def _get_fan_variable_volume_props(fan) -> dict:
    return {
        "pressure_rise_pa": {
            "value": float(fan.pressureRise()),                 # .pressureRise()
            "unit": "Pa",
        },
        "fan_total_efficiency": {
            "value": float(fan.fanTotalEfficiency()),           # .fanTotalEfficiency()
            "unit": "",
        },
        "motor_efficiency": {
            "value": float(fan.motorEfficiency()),              # .motorEfficiency()
            "unit": "",
        },
    }


def _set_fan_variable_volume_props(fan, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "pressure_rise_pa":
            old = float(fan.pressureRise())
            fan.setPressureRise(float(value))                   # .setPressureRise(double)
            changes[name] = {"old": old, "new": float(fan.pressureRise()), "unit": "Pa"}
        elif name == "fan_total_efficiency":
            old = float(fan.fanTotalEfficiency())
            fan.setFanTotalEfficiency(float(value))             # .setFanTotalEfficiency(double)
            changes[name] = {"old": old, "new": float(fan.fanTotalEfficiency()), "unit": ""}
        elif name == "motor_efficiency":
            old = float(fan.motorEfficiency())
            fan.setMotorEfficiency(float(value))                # .setMotorEfficiency(double)
            changes[name] = {"old": old, "new": float(fan.motorEfficiency()), "unit": ""}
        else:
            errors.append(f"Unknown property '{name}' for FanVariableVolume")
    return changes, errors


# --- FanOnOff ---
# On/off cycling fan. Used in PTAC/PTHP zone equipment and unit heaters.

def _get_fan_on_off_props(fan) -> dict:
    return {
        "pressure_rise_pa": {
            "value": float(fan.pressureRise()),                 # .pressureRise()
            "unit": "Pa",
        },
        "fan_efficiency": {
            "value": float(fan.fanEfficiency()),                # .fanEfficiency()
            "unit": "",
        },
        "motor_efficiency": {
            "value": float(fan.motorEfficiency()),              # .motorEfficiency()
            "unit": "",
        },
    }


def _set_fan_on_off_props(fan, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "pressure_rise_pa":
            old = float(fan.pressureRise())
            fan.setPressureRise(float(value))                   # .setPressureRise(double)
            changes[name] = {"old": old, "new": float(fan.pressureRise()), "unit": "Pa"}
        elif name == "fan_efficiency":
            old = float(fan.fanEfficiency())
            fan.setFanEfficiency(float(value))                  # .setFanEfficiency(double)
            changes[name] = {"old": old, "new": float(fan.fanEfficiency()), "unit": ""}
        elif name == "motor_efficiency":
            old = float(fan.motorEfficiency())
            fan.setMotorEfficiency(float(value))                # .setMotorEfficiency(double)
            changes[name] = {"old": old, "new": float(fan.motorEfficiency()), "unit": ""}
        else:
            errors.append(f"Unknown property '{name}' for FanOnOff")
    return changes, errors


# ===================================================================
# PUMPS
# ===================================================================

# --- PumpVariableSpeed ---
# Variable-speed pump on plant loops. Used in Systems 7-8 for CHW/CW loops.
# API verified in openstudio-resources lib/baseline_model.py.

def _get_pump_variable_speed_props(pump) -> dict:
    return {
        "rated_flow_rate_m3s": {
            "value": _read_optional_double(pump.ratedFlowRate()),  # .ratedFlowRate()
            "unit": "m3/s",
        },
        "rated_pump_head_pa": {
            "value": float(pump.ratedPumpHead()),               # .ratedPumpHead()
            "unit": "Pa",
        },
        "motor_efficiency": {
            "value": float(pump.motorEfficiency()),             # .motorEfficiency()
            "unit": "",
        },
    }


def _set_pump_variable_speed_props(pump, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "rated_flow_rate_m3s":
            old = _read_optional_double(pump.ratedFlowRate())
            pump.setRatedFlowRate(float(value))                # .setRatedFlowRate(double)
            changes[name] = {"old": old, "new": _read_optional_double(pump.ratedFlowRate()), "unit": "m3/s"}
        elif name == "rated_pump_head_pa":
            old = float(pump.ratedPumpHead())
            pump.setRatedPumpHead(float(value))                # .setRatedPumpHead(double)
            changes[name] = {"old": old, "new": float(pump.ratedPumpHead()), "unit": "Pa"}
        elif name == "motor_efficiency":
            old = float(pump.motorEfficiency())
            pump.setMotorEfficiency(float(value))              # .setMotorEfficiency(double)
            changes[name] = {"old": old, "new": float(pump.motorEfficiency()), "unit": ""}
        else:
            errors.append(f"Unknown property '{name}' for PumpVariableSpeed")
    return changes, errors


# --- PumpConstantSpeed ---
# Constant-speed pump on plant loops. Used in Systems 5, 7 for HW loops.
# API verified in openstudio-resources lib/baseline_model.py.

def _get_pump_constant_speed_props(pump) -> dict:
    return {
        "rated_flow_rate_m3s": {
            "value": _read_optional_double(pump.ratedFlowRate()),  # .ratedFlowRate()
            "unit": "m3/s",
        },
        "rated_pump_head_pa": {
            "value": float(pump.ratedPumpHead()),               # .ratedPumpHead()
            "unit": "Pa",
        },
        "motor_efficiency": {
            "value": float(pump.motorEfficiency()),             # .motorEfficiency()
            "unit": "",
        },
    }


def _set_pump_constant_speed_props(pump, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for name, value in properties.items():
        if name == "rated_flow_rate_m3s":
            old = _read_optional_double(pump.ratedFlowRate())
            pump.setRatedFlowRate(float(value))                # .setRatedFlowRate(double)
            changes[name] = {"old": old, "new": _read_optional_double(pump.ratedFlowRate()), "unit": "m3/s"}
        elif name == "rated_pump_head_pa":
            old = float(pump.ratedPumpHead())
            pump.setRatedPumpHead(float(value))                # .setRatedPumpHead(double)
            changes[name] = {"old": old, "new": float(pump.ratedPumpHead()), "unit": "Pa"}
        elif name == "motor_efficiency":
            old = float(pump.motorEfficiency())
            pump.setMotorEfficiency(float(value))              # .setMotorEfficiency(double)
            changes[name] = {"old": old, "new": float(pump.motorEfficiency()), "unit": ""}
        else:
            errors.append(f"Unknown property '{name}' for PumpConstantSpeed")
    return changes, errors


# ===================================================================
# COMPONENT TYPE TABLE
# ===================================================================
# Maps OpenStudio class name -> (category, get_fn, set_fn).
#
# To add a new component type:
#   1. Write _get_<type>_props and _set_<type>_props functions above.
#   2. Add an entry here with the OpenStudio class name as key.
#   3. The "os_type" key must match model.get<OsType>s() and
#      model.get<OsType>ByName() method naming.
#
# The operations module uses this table to:
#   - Scan the model for all known component types (list_hvac_components)
#   - Look up a component by name and dispatch to its get/set functions

COMPONENT_TYPES: dict[str, dict[str, Any]] = {
    # Heating coils
    "CoilHeatingElectric": {
        "category": "coil",
        "get_props": _get_coil_heating_electric_props,
        "set_props": _set_coil_heating_electric_props,
    },
    "CoilHeatingGas": {
        "category": "coil",
        "get_props": _get_coil_heating_gas_props,
        "set_props": _set_coil_heating_gas_props,
    },
    "CoilHeatingWater": {
        "category": "coil",
        "get_props": _get_coil_heating_water_props,
        "set_props": _set_coil_heating_water_props,
    },
    "CoilHeatingDXSingleSpeed": {
        "category": "coil",
        "get_props": _get_coil_heating_dx_single_speed_props,
        "set_props": _set_coil_heating_dx_single_speed_props,
    },
    # Cooling coils
    "CoilCoolingDXSingleSpeed": {
        "category": "coil",
        "get_props": _get_coil_cooling_dx_single_speed_props,
        "set_props": _set_coil_cooling_dx_single_speed_props,
    },
    "CoilCoolingDXTwoSpeed": {
        "category": "coil",
        "get_props": _get_coil_cooling_dx_two_speed_props,
        "set_props": _set_coil_cooling_dx_two_speed_props,
    },
    "CoilCoolingWater": {
        "category": "coil",
        "get_props": _get_coil_cooling_water_props,
        "set_props": _set_coil_cooling_water_props,
    },
    # Plant equipment
    "ChillerElectricEIR": {
        "category": "plant",
        "get_props": _get_chiller_electric_eir_props,
        "set_props": _set_chiller_electric_eir_props,
    },
    "BoilerHotWater": {
        "category": "plant",
        "get_props": _get_boiler_hot_water_props,
        "set_props": _set_boiler_hot_water_props,
    },
    "CoolingTowerSingleSpeed": {
        "category": "plant",
        "get_props": _get_cooling_tower_single_speed_props,
        "set_props": _set_cooling_tower_single_speed_props,
    },
    # Fans
    "FanConstantVolume": {
        "category": "fan",
        "get_props": _get_fan_constant_volume_props,
        "set_props": _set_fan_constant_volume_props,
    },
    "FanVariableVolume": {
        "category": "fan",
        "get_props": _get_fan_variable_volume_props,
        "set_props": _set_fan_variable_volume_props,
    },
    "FanOnOff": {
        "category": "fan",
        "get_props": _get_fan_on_off_props,
        "set_props": _set_fan_on_off_props,
    },
    # Pumps
    "PumpVariableSpeed": {
        "category": "pump",
        "get_props": _get_pump_variable_speed_props,
        "set_props": _set_pump_variable_speed_props,
    },
    "PumpConstantSpeed": {
        "category": "pump",
        "get_props": _get_pump_constant_speed_props,
        "set_props": _set_pump_constant_speed_props,
    },
}

# Valid categories for filtering
CATEGORIES = sorted({v["category"] for v in COMPONENT_TYPES.values()})
