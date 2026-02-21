"""Common wiring patterns and helper functions for HVAC system construction."""

from __future__ import annotations

import openstudio


def add_outdoor_air_system(
    model,
    air_loop,
    economizer: bool = False,
) -> openstudio.model.AirLoopHVACOutdoorAirSystem | None:
    """Add outdoor air system to air loop with optional economizer.

    Args:
        model: OpenStudio model
        air_loop: AirLoopHVAC object
        economizer: True to enable differential dry-bulb economizer

    Returns:
        AirLoopHVACOutdoorAirSystem or None
    """
    controller_oa = openstudio.model.ControllerOutdoorAir(model)
    controller_oa.setName(f"{air_loop.nameString()} OA Controller")

    if economizer:
        controller_oa.setEconomizerControlType("DifferentialDryBulb")
    else:
        controller_oa.setEconomizerControlType("NoEconomizer")

    oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(model, controller_oa)
    oa_system.setName(f"{air_loop.nameString()} OA System")
    oa_system.addToNode(air_loop.supplyInletNode())

    return oa_system


def create_setpoint_manager_single_zone_reheat(
    model,
    zone,
    node,
) -> openstudio.model.SetpointManagerSingleZoneReheat:
    """Create single zone reheat setpoint manager for PSZ systems.

    Args:
        model: OpenStudio model
        zone: ThermalZone object
        node: Node to place setpoint manager

    Returns:
        SetpointManagerSingleZoneReheat
    """
    setpoint_mgr = openstudio.model.SetpointManagerSingleZoneReheat(model)
    setpoint_mgr.setName(f"{zone.nameString()} Setpoint Manager")
    setpoint_mgr.setControlZone(zone)
    setpoint_mgr.addToNode(node)

    return setpoint_mgr


def create_chilled_water_loop(
    model,
    name: str,
    cooling_fuel: str = "Electricity",
) -> openstudio.model.PlantLoop:
    """Create standard chilled water loop for central systems.

    Args:
        model: OpenStudio model
        name: Name for the plant loop
        cooling_fuel: "Electricity" or "DistrictCooling"

    Returns:
        PlantLoop for chilled water
    """
    loop = openstudio.model.PlantLoop(model)
    loop.setName(name)

    # Sizing
    sizing = loop.sizingPlant()
    sizing.setLoopType("Cooling")
    sizing.setDesignLoopExitTemperature(7.22)  # 45°F in Celsius
    sizing.setLoopDesignTemperatureDifference(6.67)  # 12°F delta-T

    # Setpoint manager
    setpoint_mgr = openstudio.model.SetpointManagerScheduled(
        model,
        _create_chw_temp_schedule(model),
    )
    setpoint_mgr.setName(f"{name} Setpoint Manager")
    setpoint_mgr.addToNode(loop.supplyOutletNode())

    # Add pump
    pump = openstudio.model.PumpVariableSpeed(model)
    pump.setName(f"{name} Pump")
    pump.addToNode(loop.supplyInletNode())

    return loop


def create_hot_water_loop(
    model,
    name: str,
    heating_fuel: str = "NaturalGas",
) -> openstudio.model.PlantLoop:
    """Create standard hot water loop for central systems.

    Args:
        model: OpenStudio model
        name: Name for the plant loop
        heating_fuel: "NaturalGas", "Electricity", or "DistrictHeating"

    Returns:
        PlantLoop for hot water
    """
    loop = openstudio.model.PlantLoop(model)
    loop.setName(name)

    # Sizing
    sizing = loop.sizingPlant()
    sizing.setLoopType("Heating")
    sizing.setDesignLoopExitTemperature(82.0)  # 180°F in Celsius
    sizing.setLoopDesignTemperatureDifference(11.0)  # 20°F delta-T

    # Setpoint manager
    setpoint_mgr = openstudio.model.SetpointManagerScheduled(
        model,
        _create_hw_temp_schedule(model),
    )
    setpoint_mgr.setName(f"{name} Setpoint Manager")
    setpoint_mgr.addToNode(loop.supplyOutletNode())

    # Add pump
    pump = openstudio.model.PumpVariableSpeed(model)
    pump.setName(f"{name} Pump")
    pump.addToNode(loop.supplyInletNode())

    return loop


def create_condenser_water_loop(
    model,
    name: str,
) -> openstudio.model.PlantLoop:
    """Create condenser water loop for chiller heat rejection.

    Args:
        model: OpenStudio model
        name: Name for the condenser loop

    Returns:
        PlantLoop for condenser water
    """
    loop = openstudio.model.PlantLoop(model)
    loop.setName(name)

    # Sizing
    sizing = loop.sizingPlant()
    sizing.setLoopType("Condenser")
    sizing.setDesignLoopExitTemperature(29.4)  # 85°F in Celsius
    sizing.setLoopDesignTemperatureDifference(5.6)  # 10°F delta-T

    # Setpoint manager (follow outdoor air temperature)
    setpoint_mgr = openstudio.model.SetpointManagerFollowOutdoorAirTemperature(model)
    setpoint_mgr.setName(f"{name} Setpoint Manager")
    setpoint_mgr.setControlVariable("Temperature")
    setpoint_mgr.setReferenceTemperatureType("OutdoorAirWetBulb")
    setpoint_mgr.setOffsetTemperatureDifference(0.0)
    setpoint_mgr.addToNode(loop.supplyOutletNode())

    # Add pump
    pump = openstudio.model.PumpVariableSpeed(model)
    pump.setName(f"{name} Pump")
    pump.addToNode(loop.supplyInletNode())

    return loop


def add_chiller_to_loops(
    model,
    chw_loop: openstudio.model.PlantLoop,
    cw_loop: openstudio.model.PlantLoop,
    chiller_type: str = "ElectricEIR",
):
    """Add chiller to chilled water and condenser loops.

    Args:
        model: OpenStudio model
        chw_loop: Chilled water plant loop
        cw_loop: Condenser water plant loop
        chiller_type: "ElectricEIR" or "ElectricReformulatedEIR"

    Returns:
        Chiller object
    """
    chiller = openstudio.model.ChillerElectricEIR(model)
    chiller.setName(f"{chw_loop.nameString()} Chiller")

    # Add to chilled water loop (supply side)
    chw_loop.addSupplyBranchForComponent(chiller)

    # Add to condenser loop (demand side)
    cw_loop.addDemandBranchForComponent(chiller)

    return chiller


def add_boiler_to_loop(
    model,
    hw_loop: openstudio.model.PlantLoop,
    heating_fuel: str = "NaturalGas",
):
    """Add boiler to hot water loop.

    Args:
        model: OpenStudio model
        hw_loop: Hot water plant loop
        heating_fuel: "NaturalGas" or "Electricity"

    Returns:
        Boiler object
    """
    if heating_fuel == "NaturalGas":
        boiler = openstudio.model.BoilerHotWater(model)
        boiler.setName(f"{hw_loop.nameString()} Gas Boiler")
        boiler.setFuelType("NaturalGas")
    else:
        boiler = openstudio.model.BoilerHotWater(model)
        boiler.setName(f"{hw_loop.nameString()} Electric Boiler")
        boiler.setFuelType("Electricity")

    # Add to hot water loop
    hw_loop.addSupplyBranchForComponent(boiler)

    return boiler


def add_cooling_tower_to_loop(
    model,
    cw_loop: openstudio.model.PlantLoop,
):
    """Add cooling tower to condenser water loop.

    Args:
        model: OpenStudio model
        cw_loop: Condenser water plant loop

    Returns:
        CoolingTowerSingleSpeed object
    """
    tower = openstudio.model.CoolingTowerSingleSpeed(model)
    tower.setName(f"{cw_loop.nameString()} Cooling Tower")

    # Add to condenser loop
    cw_loop.addSupplyBranchForComponent(tower)

    return tower


def _create_chw_temp_schedule(model) -> openstudio.model.ScheduleRuleset:
    """Create chilled water supply temperature schedule (44°F / 6.7°C)."""
    schedule = openstudio.model.ScheduleRuleset(model)
    schedule.setName("Chilled Water Temperature")
    schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 6.7)
    return schedule


def _create_hw_temp_schedule(model) -> openstudio.model.ScheduleRuleset:
    """Create hot water supply temperature schedule (180°F / 82°C)."""
    schedule = openstudio.model.ScheduleRuleset(model)
    schedule.setName("Hot Water Temperature")
    schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 82.0)
    return schedule
