"""ASHRAE 90.1 Appendix G Baseline System implementations."""

from __future__ import annotations

from typing import Any

import openstudio


def create_baseline_system_1(
    model,
    zones: list,
    heating_fuel: str,
    cooling_fuel: str,
    economizer: bool,
    name: str,
) -> dict[str, Any]:
    """Baseline System 1: PTAC with electric resistance heating and DX cooling.

    Zone-level packaged terminal air conditioner.
    - Electric resistance heating coil
    - Single-speed DX cooling coil
    - Fan cycling with load
    - No outdoor air economizer (packaged unit)

    Args:
        model: OpenStudio model
        zones: List of ThermalZone objects to serve
        heating_fuel: "Electricity" or "NaturalGas" (PTAC is always electric)
        cooling_fuel: "Electricity" (always for DX)
        economizer: Not applicable for PTAC (ignored)
        name: Base name for system

    Returns:
        dict with system details
    """
    always_on = model.alwaysOnDiscreteSchedule()
    equipment_added = []

    for zone in zones:
        zone_name = zone.nameString()
        ptac_name = f"{name} PTAC - {zone_name}"

        # Create heating coil (electric resistance)
        htg_coil = openstudio.model.CoilHeatingElectric(model, always_on)
        htg_coil.setName(f"{ptac_name} Heating Coil")

        # Create cooling coil (single-speed DX)
        clg_coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
        clg_coil.setName(f"{ptac_name} Cooling Coil")

        # Create fan (constant volume, cycling)
        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f"{ptac_name} Fan")

        # Create PTAC unit
        ptac = openstudio.model.ZoneHVACPackagedTerminalAirConditioner(
            model,
            always_on,
            fan,
            htg_coil,
            clg_coil,
        )
        ptac.setName(ptac_name)

        # Add to zone
        ptac.addToThermalZone(zone)

        equipment_added.append(
            {
                "zone": zone_name,
                "equipment": ptac_name,
                "heating_coil": htg_coil.nameString(),
                "cooling_coil": clg_coil.nameString(),
                "fan": fan.nameString(),
            },
        )

    return {
        "ok": True,
        "system": {
            "name": name,
            "type": "PTAC (Baseline System 1)",
            "category": "baseline",
            "system_number": 1,
            "equipment_type": "Zone HVAC",
            "zones_served": len(zones),
            "equipment": equipment_added,
            "heating": "Electric Resistance",
            "cooling": "DX Single Speed",
        },
    }


def create_baseline_system_2(
    model,
    zones: list,
    heating_fuel: str,
    cooling_fuel: str,
    economizer: bool,
    name: str,
) -> dict[str, Any]:
    """Baseline System 2: PTHP (Packaged Terminal Heat Pump).

    Zone-level heat pump unit.
    - DX heating coil (heat pump mode)
    - DX cooling coil (heat pump mode)
    - Supplemental electric resistance heating
    - Fan cycling with load

    Args:
        model: OpenStudio model
        zones: List of ThermalZone objects
        heating_fuel: Ignored (heat pump is always electric)
        cooling_fuel: Ignored (heat pump is always electric)
        economizer: Not applicable for PTHP (ignored)
        name: Base name for system

    Returns:
        dict with system details
    """
    always_on = model.alwaysOnDiscreteSchedule()
    equipment_added = []

    for zone in zones:
        zone_name = zone.nameString()
        pthp_name = f"{name} PTHP - {zone_name}"

        # Create DX heating coil (heat pump)
        htg_coil = openstudio.model.CoilHeatingDXSingleSpeed(model)
        htg_coil.setName(f"{pthp_name} HP Heating Coil")

        # Create DX cooling coil (heat pump)
        clg_coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
        clg_coil.setName(f"{pthp_name} HP Cooling Coil")

        # Create supplemental heating coil (electric resistance)
        supp_htg_coil = openstudio.model.CoilHeatingElectric(model, always_on)
        supp_htg_coil.setName(f"{pthp_name} Supplemental Heating Coil")

        # Create fan
        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f"{pthp_name} Fan")

        # Create PTHP unit
        pthp = openstudio.model.ZoneHVACPackagedTerminalHeatPump(
            model,
            always_on,
            fan,
            htg_coil,
            clg_coil,
            supp_htg_coil,
        )
        pthp.setName(pthp_name)

        # Add to zone
        pthp.addToThermalZone(zone)

        equipment_added.append(
            {
                "zone": zone_name,
                "equipment": pthp_name,
                "heating_coil": htg_coil.nameString(),
                "cooling_coil": clg_coil.nameString(),
                "supplemental_heating_coil": supp_htg_coil.nameString(),
                "fan": fan.nameString(),
            },
        )

    return {
        "ok": True,
        "system": {
            "name": name,
            "type": "PTHP (Baseline System 2)",
            "category": "baseline",
            "system_number": 2,
            "equipment_type": "Zone HVAC",
            "zones_served": len(zones),
            "equipment": equipment_added,
            "heating": "Heat Pump",
            "cooling": "Heat Pump",
        },
    }


def create_baseline_system_3(
    model,
    zones: list,
    heating_fuel: str,
    cooling_fuel: str,
    economizer: bool,
    name: str,
) -> dict[str, Any]:
    """Baseline System 3: PSZ-AC (Packaged Single Zone Air Conditioner).

    Packaged rooftop unit serving a single zone.
    - Gas furnace or electric heating
    - Single-speed DX cooling
    - Constant volume supply fan
    - Optional outdoor air economizer

    Args:
        model: OpenStudio model
        zones: List with single ThermalZone (PSZ = single zone)
        heating_fuel: "NaturalGas" or "Electricity"
        cooling_fuel: "Electricity" (always for DX)
        economizer: True to enable air-side economizer
        name: Base name for system

    Returns:
        dict with system details
    """
    from mcp_server.skills.hvac_systems.wiring import add_outdoor_air_system, create_setpoint_manager_single_zone_reheat

    if len(zones) != 1:
        return {
            "ok": False,
            "error": f"PSZ-AC requires exactly 1 zone, got {len(zones)}",
        }

    zone = zones[0]
    always_on = model.alwaysOnDiscreteSchedule()

    # Create air loop
    air_loop = openstudio.model.AirLoopHVAC(model)
    air_loop.setName(name)

    # Add outdoor air system
    oa_system = add_outdoor_air_system(model, air_loop, economizer)

    # Create supply fan
    fan = openstudio.model.FanConstantVolume(model, always_on)
    fan.setName(f"{name} Supply Fan")
    fan.addToNode(air_loop.supplyInletNode())

    # Create heating coil
    if heating_fuel == "NaturalGas":
        htg_coil = openstudio.model.CoilHeatingGas(model, always_on)
        htg_coil.setName(f"{name} Gas Heating Coil")
    else:
        htg_coil = openstudio.model.CoilHeatingElectric(model, always_on)
        htg_coil.setName(f"{name} Electric Heating Coil")
    htg_coil.addToNode(air_loop.supplyInletNode())

    # Create cooling coil
    clg_coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
    clg_coil.setName(f"{name} DX Cooling Coil")
    clg_coil.addToNode(air_loop.supplyInletNode())

    # Create uncontrolled terminal
    terminal = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
    terminal.setName(f"{name} Terminal")

    # Connect to zone
    air_loop.addBranchForZone(zone, terminal)

    # Add setpoint manager
    setpoint_mgr = create_setpoint_manager_single_zone_reheat(
        model,
        zone,
        air_loop.supplyOutletNode(),
    )

    return {
        "ok": True,
        "system": {
            "name": name,
            "type": "PSZ-AC (Baseline System 3)",
            "category": "baseline",
            "system_number": 3,
            "equipment_type": "Packaged Rooftop Unit",
            "air_loop": air_loop.nameString(),
            "zones_served": 1,
            "zone": zone.nameString(),
            "economizer": economizer,
            "heating": "Gas Furnace" if heating_fuel == "NaturalGas" else "Electric Resistance",
            "cooling": "DX Single Speed",
            "outdoor_air_system": oa_system.nameString() if oa_system else None,
            "setpoint_manager": setpoint_mgr.nameString() if setpoint_mgr else None,
        },
    }


def create_baseline_system_4(
    model,
    zones: list,
    heating_fuel: str,
    cooling_fuel: str,
    economizer: bool,
    name: str,
) -> dict[str, Any]:
    """Baseline System 4: PSZ-HP (Packaged Single Zone Heat Pump).

    Packaged rooftop heat pump serving a single zone.
    - DX heating coil (heat pump mode)
    - DX cooling coil (heat pump mode)
    - Supplemental electric resistance heating
    - Constant volume supply fan
    - Optional outdoor air economizer

    Args:
        model: OpenStudio model
        zones: List with single ThermalZone
        heating_fuel: Ignored (heat pump is electric)
        cooling_fuel: Ignored (heat pump is electric)
        economizer: True to enable air-side economizer
        name: Base name for system

    Returns:
        dict with system details
    """
    from mcp_server.skills.hvac_systems.wiring import add_outdoor_air_system, create_setpoint_manager_single_zone_reheat

    if len(zones) != 1:
        return {
            "ok": False,
            "error": f"PSZ-HP requires exactly 1 zone, got {len(zones)}",
        }

    zone = zones[0]
    always_on = model.alwaysOnDiscreteSchedule()

    # Create air loop
    air_loop = openstudio.model.AirLoopHVAC(model)
    air_loop.setName(name)

    # Add outdoor air system
    oa_system = add_outdoor_air_system(model, air_loop, economizer)

    # Create supply fan
    fan = openstudio.model.FanConstantVolume(model, always_on)
    fan.setName(f"{name} Supply Fan")
    fan.addToNode(air_loop.supplyInletNode())

    # Create DX heating coil (heat pump)
    htg_coil = openstudio.model.CoilHeatingDXSingleSpeed(model)
    htg_coil.setName(f"{name} HP Heating Coil")
    htg_coil.addToNode(air_loop.supplyInletNode())

    # Create DX cooling coil (heat pump)
    clg_coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
    clg_coil.setName(f"{name} HP Cooling Coil")
    clg_coil.addToNode(air_loop.supplyInletNode())

    # Create supplemental heating coil
    supp_htg_coil = openstudio.model.CoilHeatingElectric(model, always_on)
    supp_htg_coil.setName(f"{name} Supplemental Heating Coil")
    supp_htg_coil.addToNode(air_loop.supplyInletNode())

    # Create uncontrolled terminal
    terminal = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
    terminal.setName(f"{name} Terminal")

    # Connect to zone
    air_loop.addBranchForZone(zone, terminal)

    # Add setpoint manager
    setpoint_mgr = create_setpoint_manager_single_zone_reheat(
        model,
        zone,
        air_loop.supplyOutletNode(),
    )

    return {
        "ok": True,
        "system": {
            "name": name,
            "type": "PSZ-HP (Baseline System 4)",
            "category": "baseline",
            "system_number": 4,
            "equipment_type": "Packaged Rooftop Heat Pump",
            "air_loop": air_loop.nameString(),
            "zones_served": 1,
            "zone": zone.nameString(),
            "economizer": economizer,
            "heating": "Heat Pump",
            "cooling": "Heat Pump",
            "outdoor_air_system": oa_system.nameString() if oa_system else None,
            "setpoint_manager": setpoint_mgr.nameString() if setpoint_mgr else None,
        },
    }


def create_baseline_system_5(
    model,
    zones: list,
    heating_fuel: str,
    cooling_fuel: str,
    economizer: bool,
    name: str,
) -> dict[str, Any]:
    """Baseline System 5: Packaged VAV with Reheat.

    Packaged rooftop VAV with hot water reheat terminals.
    - DX cooling
    - Gas/electric heating at air handler
    - Hot water boiler for reheat coils
    - VAV terminals with hot water reheat
    - Economizer

    Args:
        model: OpenStudio model
        zones: List of ThermalZone objects (multi-zone)
        heating_fuel: "NaturalGas" or "Electricity"
        cooling_fuel: "Electricity" (always for DX)
        economizer: True to enable economizer
        name: Base name for system

    Returns:
        dict with system details
    """
    from mcp_server.skills.hvac_systems.wiring import add_boiler_to_loop, add_outdoor_air_system, create_hot_water_loop

    always_on = model.alwaysOnDiscreteSchedule()

    # Create hot water loop for reheat
    hw_loop = create_hot_water_loop(model, f"{name} Hot Water Loop", heating_fuel)
    add_boiler_to_loop(model, hw_loop, heating_fuel)

    # Create VAV air loop
    air_loop = openstudio.model.AirLoopHVAC(model)
    air_loop.setName(name)

    # Add outdoor air system
    add_outdoor_air_system(model, air_loop, economizer)

    # Create supply fan (VAV)
    fan = openstudio.model.FanVariableVolume(model, always_on)
    fan.setName(f"{name} Supply Fan")
    fan.addToNode(air_loop.supplyInletNode())

    # Create heating coil at air handler
    if heating_fuel == "NaturalGas":
        htg_coil = openstudio.model.CoilHeatingGas(model, always_on)
        htg_coil.setName(f"{name} Preheat Coil")
    else:
        htg_coil = openstudio.model.CoilHeatingElectric(model, always_on)
        htg_coil.setName(f"{name} Preheat Coil")
    htg_coil.addToNode(air_loop.supplyInletNode())

    # Create DX cooling coil
    clg_coil = openstudio.model.CoilCoolingDXTwoSpeed(model)
    clg_coil.setName(f"{name} DX Cooling Coil")
    clg_coil.addToNode(air_loop.supplyInletNode())

    # Add setpoint manager (scheduled)
    setpoint_mgr = openstudio.model.SetpointManagerScheduled(
        model,
        _create_supply_air_temp_schedule(model),
    )
    setpoint_mgr.setName(f"{name} Supply Air Setpoint Manager")
    setpoint_mgr.addToNode(air_loop.supplyOutletNode())

    # Add VAV reheat terminals to zones
    terminals = []
    for zone in zones:
        # Create hot water reheat coil
        reheat_coil = openstudio.model.CoilHeatingWater(model, always_on)
        reheat_coil.setName(f"{name} Reheat Coil - {zone.nameString()}")
        hw_loop.addDemandBranchForComponent(reheat_coil)

        # Create VAV terminal with reheat
        terminal = openstudio.model.AirTerminalSingleDuctVAVReheat(
            model,
            always_on,
            reheat_coil,
        )
        terminal.setName(f"{name} VAV Terminal - {zone.nameString()}")
        air_loop.addBranchForZone(zone, terminal)
        terminals.append(terminal.nameString())

    return {
        "ok": True,
        "system": {
            "name": name,
            "type": "Packaged VAV w/ Reheat (Baseline System 5)",
            "category": "baseline",
            "system_number": 5,
            "equipment_type": "Packaged VAV",
            "air_loop": air_loop.nameString(),
            "hot_water_loop": hw_loop.nameString(),
            "zones_served": len(zones),
            "terminals": terminals,
            "economizer": economizer,
            "heating": "Hot Water Reheat",
            "cooling": "DX Two Speed",
        },
    }


def create_baseline_system_6(
    model,
    zones: list,
    heating_fuel: str,
    cooling_fuel: str,
    economizer: bool,
    name: str,
) -> dict[str, Any]:
    """Baseline System 6: Packaged VAV with PFP Boxes.

    Packaged rooftop VAV with parallel fan-powered boxes.
    - DX cooling
    - Gas/electric heating at air handler
    - Parallel fan-powered terminals with electric reheat
    - Economizer

    Args:
        model: OpenStudio model
        zones: List of ThermalZone objects
        heating_fuel: "NaturalGas" or "Electricity" (for air handler)
        cooling_fuel: "Electricity"
        economizer: True to enable economizer
        name: Base name for system

    Returns:
        dict with system details
    """
    from mcp_server.skills.hvac_systems.wiring import add_outdoor_air_system

    always_on = model.alwaysOnDiscreteSchedule()

    # Create VAV air loop
    air_loop = openstudio.model.AirLoopHVAC(model)
    air_loop.setName(name)

    # Add outdoor air system
    add_outdoor_air_system(model, air_loop, economizer)

    # Create supply fan (VAV)
    fan = openstudio.model.FanVariableVolume(model, always_on)
    fan.setName(f"{name} Supply Fan")
    fan.addToNode(air_loop.supplyInletNode())

    # Create heating coil
    if heating_fuel == "NaturalGas":
        htg_coil = openstudio.model.CoilHeatingGas(model, always_on)
        htg_coil.setName(f"{name} Preheat Coil")
    else:
        htg_coil = openstudio.model.CoilHeatingElectric(model, always_on)
        htg_coil.setName(f"{name} Preheat Coil")
    htg_coil.addToNode(air_loop.supplyInletNode())

    # Create DX cooling coil
    clg_coil = openstudio.model.CoilCoolingDXTwoSpeed(model)
    clg_coil.setName(f"{name} DX Cooling Coil")
    clg_coil.addToNode(air_loop.supplyInletNode())

    # Add setpoint manager
    setpoint_mgr = openstudio.model.SetpointManagerScheduled(
        model,
        _create_supply_air_temp_schedule(model),
    )
    setpoint_mgr.setName(f"{name} Supply Air Setpoint Manager")
    setpoint_mgr.addToNode(air_loop.supplyOutletNode())

    # Add parallel fan-powered terminals
    terminals = []
    for zone in zones:
        # Create electric reheat coil
        reheat_coil = openstudio.model.CoilHeatingElectric(model, always_on)
        reheat_coil.setName(f"{name} PFP Reheat - {zone.nameString()}")

        # Create parallel fan
        pfp_fan = openstudio.model.FanConstantVolume(model, always_on)
        pfp_fan.setName(f"{name} PFP Fan - {zone.nameString()}")

        # Create parallel fan-powered terminal
        terminal = openstudio.model.AirTerminalSingleDuctParallelPIUReheat(
            model,
            always_on,
            pfp_fan,
            reheat_coil,
        )
        terminal.setName(f"{name} PFP Terminal - {zone.nameString()}")
        air_loop.addBranchForZone(zone, terminal)
        terminals.append(terminal.nameString())

    return {
        "ok": True,
        "system": {
            "name": name,
            "type": "Packaged VAV w/ PFP (Baseline System 6)",
            "category": "baseline",
            "system_number": 6,
            "equipment_type": "Packaged VAV",
            "air_loop": air_loop.nameString(),
            "zones_served": len(zones),
            "terminals": terminals,
            "economizer": economizer,
            "heating": "Electric Reheat in PFP Boxes",
            "cooling": "DX Two Speed",
        },
    }


def _create_supply_air_temp_schedule(model) -> openstudio.model.ScheduleRuleset:
    """Create supply air temperature schedule for VAV systems (55°F / 12.8°C)."""
    schedule = openstudio.model.ScheduleRuleset(model)
    schedule.setName("VAV Supply Air Temperature")
    schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 12.8)
    return schedule


def create_baseline_system_7(
    model,
    zones: list,
    heating_fuel: str,
    cooling_fuel: str,
    economizer: bool,
    name: str,
) -> dict[str, Any]:
    """Baseline System 7: VAV with Reheat.

    Built-up VAV system with chiller/boiler and hot water reheat.
    - Chilled water cooling
    - Hot water heating at air handler
    - Hot water reheat at terminals
    - Chiller with cooling tower
    - Boiler
    - Economizer
    """
    from mcp_server.skills.hvac_systems.wiring import (
        add_boiler_to_loop,
        add_chiller_to_loops,
        add_cooling_tower_to_loop,
        add_outdoor_air_system,
        create_chilled_water_loop,
        create_condenser_water_loop,
        create_hot_water_loop,
    )

    always_on = model.alwaysOnDiscreteSchedule()

    # Create plant loops
    chw_loop = create_chilled_water_loop(model, f"{name} Chilled Water Loop")
    hw_loop = create_hot_water_loop(model, f"{name} Hot Water Loop", heating_fuel)
    cw_loop = create_condenser_water_loop(model, f"{name} Condenser Loop")

    # Add equipment to loops
    add_chiller_to_loops(model, chw_loop, cw_loop)
    add_boiler_to_loop(model, hw_loop, heating_fuel)
    add_cooling_tower_to_loop(model, cw_loop)

    # Create VAV air loop
    air_loop = openstudio.model.AirLoopHVAC(model)
    air_loop.setName(name)

    # Add outdoor air system
    add_outdoor_air_system(model, air_loop, economizer)

    # Create supply fan (VAV)
    fan = openstudio.model.FanVariableVolume(model, always_on)
    fan.setName(f"{name} Supply Fan")
    fan.addToNode(air_loop.supplyInletNode())

    # Create chilled water cooling coil
    clg_coil = openstudio.model.CoilCoolingWater(model, always_on)
    clg_coil.setName(f"{name} CHW Cooling Coil")
    clg_coil.addToNode(air_loop.supplyInletNode())
    chw_loop.addDemandBranchForComponent(clg_coil)

    # Create hot water heating coil
    htg_coil = openstudio.model.CoilHeatingWater(model, always_on)
    htg_coil.setName(f"{name} HW Heating Coil")
    htg_coil.addToNode(air_loop.supplyInletNode())
    hw_loop.addDemandBranchForComponent(htg_coil)

    # Add setpoint manager
    setpoint_mgr = openstudio.model.SetpointManagerScheduled(
        model,
        _create_supply_air_temp_schedule(model),
    )
    setpoint_mgr.setName(f"{name} Supply Air Setpoint Manager")
    setpoint_mgr.addToNode(air_loop.supplyOutletNode())

    # Add VAV reheat terminals
    terminals = []
    for zone in zones:
        reheat_coil = openstudio.model.CoilHeatingWater(model, always_on)
        reheat_coil.setName(f"{name} Reheat Coil - {zone.nameString()}")
        hw_loop.addDemandBranchForComponent(reheat_coil)

        terminal = openstudio.model.AirTerminalSingleDuctVAVReheat(
            model,
            always_on,
            reheat_coil,
        )
        terminal.setName(f"{name} VAV Terminal - {zone.nameString()}")
        air_loop.addBranchForZone(zone, terminal)
        terminals.append(terminal.nameString())

    return {
        "ok": True,
        "system": {
            "name": name,
            "type": "VAV w/ Reheat (Baseline System 7)",
            "category": "baseline",
            "system_number": 7,
            "equipment_type": "Built-up VAV",
            "air_loop": air_loop.nameString(),
            "chilled_water_loop": chw_loop.nameString(),
            "hot_water_loop": hw_loop.nameString(),
            "condenser_loop": cw_loop.nameString(),
            "zones_served": len(zones),
            "terminals": terminals,
            "economizer": economizer,
            "heating": "Hot Water",
            "cooling": "Chilled Water",
        },
    }


def create_baseline_system_8(
    model,
    zones: list,
    heating_fuel: str,
    cooling_fuel: str,
    economizer: bool,
    name: str,
) -> dict[str, Any]:
    """Baseline System 8: VAV with PFP Boxes.

    Built-up VAV with chiller/boiler and parallel fan-powered boxes.
    - Chilled water cooling
    - Hot water heating at air handler
    - Electric reheat in PFP terminals
    - Chiller with cooling tower
    - Boiler
    - Economizer
    """
    from mcp_server.skills.hvac_systems.wiring import (
        add_boiler_to_loop,
        add_chiller_to_loops,
        add_cooling_tower_to_loop,
        add_outdoor_air_system,
        create_chilled_water_loop,
        create_condenser_water_loop,
        create_hot_water_loop,
    )

    always_on = model.alwaysOnDiscreteSchedule()

    # Create plant loops
    chw_loop = create_chilled_water_loop(model, f"{name} Chilled Water Loop")
    hw_loop = create_hot_water_loop(model, f"{name} Hot Water Loop", heating_fuel)
    cw_loop = create_condenser_water_loop(model, f"{name} Condenser Loop")

    # Add equipment
    add_chiller_to_loops(model, chw_loop, cw_loop)
    add_boiler_to_loop(model, hw_loop, heating_fuel)
    add_cooling_tower_to_loop(model, cw_loop)

    # Create VAV air loop
    air_loop = openstudio.model.AirLoopHVAC(model)
    air_loop.setName(name)

    # Add outdoor air system
    add_outdoor_air_system(model, air_loop, economizer)

    # Create supply fan (VAV)
    fan = openstudio.model.FanVariableVolume(model, always_on)
    fan.setName(f"{name} Supply Fan")
    fan.addToNode(air_loop.supplyInletNode())

    # Create chilled water cooling coil
    clg_coil = openstudio.model.CoilCoolingWater(model, always_on)
    clg_coil.setName(f"{name} CHW Cooling Coil")
    clg_coil.addToNode(air_loop.supplyInletNode())
    chw_loop.addDemandBranchForComponent(clg_coil)

    # Create hot water heating coil
    htg_coil = openstudio.model.CoilHeatingWater(model, always_on)
    htg_coil.setName(f"{name} HW Heating Coil")
    htg_coil.addToNode(air_loop.supplyInletNode())
    hw_loop.addDemandBranchForComponent(htg_coil)

    # Add setpoint manager
    setpoint_mgr = openstudio.model.SetpointManagerScheduled(
        model,
        _create_supply_air_temp_schedule(model),
    )
    setpoint_mgr.setName(f"{name} Supply Air Setpoint Manager")
    setpoint_mgr.addToNode(air_loop.supplyOutletNode())

    # Add PFP terminals
    terminals = []
    for zone in zones:
        reheat_coil = openstudio.model.CoilHeatingElectric(model, always_on)
        reheat_coil.setName(f"{name} PFP Reheat - {zone.nameString()}")

        pfp_fan = openstudio.model.FanConstantVolume(model, always_on)
        pfp_fan.setName(f"{name} PFP Fan - {zone.nameString()}")

        terminal = openstudio.model.AirTerminalSingleDuctParallelPIUReheat(
            model,
            always_on,
            pfp_fan,
            reheat_coil,
        )
        terminal.setName(f"{name} PFP Terminal - {zone.nameString()}")
        air_loop.addBranchForZone(zone, terminal)
        terminals.append(terminal.nameString())

    return {
        "ok": True,
        "system": {
            "name": name,
            "type": "VAV w/ PFP (Baseline System 8)",
            "category": "baseline",
            "system_number": 8,
            "equipment_type": "Built-up VAV",
            "air_loop": air_loop.nameString(),
            "chilled_water_loop": chw_loop.nameString(),
            "hot_water_loop": hw_loop.nameString(),
            "condenser_loop": cw_loop.nameString(),
            "zones_served": len(zones),
            "terminals": terminals,
            "economizer": economizer,
            "heating": "Hot Water",
            "cooling": "Chilled Water",
        },
    }


def create_baseline_system_9(
    model,
    zones: list,
    heating_fuel: str,
    cooling_fuel: str,
    economizer: bool,
    name: str,
) -> dict[str, Any]:
    """Baseline System 9: Heating and Ventilation (Gas).

    Gas-fired unit heaters, no mechanical cooling.
    - Gas unit heaters (zone equipment)
    - No cooling
    - Ventilation only

    Args:
        model: OpenStudio model
        zones: List of ThermalZone objects
        heating_fuel: "NaturalGas"
        cooling_fuel: Not applicable
        economizer: Not applicable
        name: Base name for system

    Returns:
        dict with system details
    """
    always_on = model.alwaysOnDiscreteSchedule()
    equipment_added = []

    for zone in zones:
        zone_name = zone.nameString()
        heater_name = f"{name} Unit Heater - {zone_name}"

        # Create gas heating coil
        htg_coil = openstudio.model.CoilHeatingGas(model, always_on)
        htg_coil.setName(f"{heater_name} Coil")

        # Create fan
        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f"{heater_name} Fan")

        # Create unit heater
        unit_heater = openstudio.model.ZoneHVACUnitHeater(
            model,
            always_on,
            fan,
            htg_coil,
        )
        unit_heater.setName(heater_name)

        # Add to zone
        unit_heater.addToThermalZone(zone)

        equipment_added.append(
            {
                "zone": zone_name,
                "equipment": heater_name,
            },
        )

    return {
        "ok": True,
        "system": {
            "name": name,
            "type": "Heating & Ventilation (Baseline System 9)",
            "category": "baseline",
            "system_number": 9,
            "equipment_type": "Zone Unit Heaters",
            "zones_served": len(zones),
            "equipment": equipment_added,
            "heating": "Gas Unit Heaters",
            "cooling": "None",
        },
    }


def create_baseline_system_10(
    model,
    zones: list,
    heating_fuel: str,
    cooling_fuel: str,
    economizer: bool,
    name: str,
) -> dict[str, Any]:
    """Baseline System 10: Heating and Ventilation (Electric).

    Electric unit heaters, no mechanical cooling.
    - Electric unit heaters (zone equipment)
    - No cooling
    - Ventilation only

    Args:
        model: OpenStudio model
        zones: List of ThermalZone objects
        heating_fuel: "Electricity"
        cooling_fuel: Not applicable
        economizer: Not applicable
        name: Base name for system

    Returns:
        dict with system details
    """
    always_on = model.alwaysOnDiscreteSchedule()
    equipment_added = []

    for zone in zones:
        zone_name = zone.nameString()
        heater_name = f"{name} Unit Heater - {zone_name}"

        # Create electric heating coil
        htg_coil = openstudio.model.CoilHeatingElectric(model, always_on)
        htg_coil.setName(f"{heater_name} Coil")

        # Create fan
        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f"{heater_name} Fan")

        # Create unit heater
        unit_heater = openstudio.model.ZoneHVACUnitHeater(
            model,
            always_on,
            fan,
            htg_coil,
        )
        unit_heater.setName(heater_name)

        # Add to zone
        unit_heater.addToThermalZone(zone)

        equipment_added.append(
            {
                "zone": zone_name,
                "equipment": heater_name,
            },
        )

    return {
        "ok": True,
        "system": {
            "name": name,
            "type": "Heating & Ventilation (Baseline System 10)",
            "category": "baseline",
            "system_number": 10,
            "equipment_type": "Zone Unit Heaters",
            "zones_served": len(zones),
            "equipment": equipment_added,
            "heating": "Electric Unit Heaters",
            "cooling": "None",
        },
    }
