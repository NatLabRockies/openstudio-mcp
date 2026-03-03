"""Modern HVAC system templates — DOAS, VRF, Radiant.

These templates represent contemporary high-efficiency strategies beyond
ASHRAE 90.1 baseline systems. Used for performance modeling, not compliance.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.skills.hvac_systems import wiring

# Map user-facing radiant type names to OpenStudio enum values
_RADIANT_SURFACE_MAP = {
    "Floor": "Floors",
    "Ceiling": "Ceilings",
    "Walls": "AllSurfaces",
}


def create_doas_system(
    model,
    zones: list,
    name: str,
    energy_recovery: bool,
    sensible_effectiveness: float,
    zone_equipment_type: str,
    heating_fuel: str = "NaturalGas",
    cooling_fuel: str = "Electricity",
) -> dict[str, Any]:
    """Create Dedicated Outdoor Air System with zone equipment.

    DOAS Pattern:
    1. Create 100% outdoor air loop (ventilation only, low CFM)
    2. Add energy recovery ventilator if requested
    3. Add preheat/precool coils (55F supply temp target)
    4. Create CHW/HW plant loops for zone equipment
    5. Add zone equipment (fan coils, radiant panels, or chilled beams)

    Args:
        model: OpenStudio model
        zones: List of ThermalZone objects to serve
        name: Name prefix for DOAS components
        energy_recovery: Add ERV to DOAS loop
        sensible_effectiveness: ERV sensible effectiveness (0-1)
        zone_equipment_type: "FanCoil" | "Radiant" | "Chiller_Beams" | "None"

    Returns:
        dict with DOAS loop, plant loops, and zone equipment details
    """
    # Create 100% outdoor air loop
    doas_loop = openstudio.model.AirLoopHVAC(model)
    doas_loop.setName(f"{name} DOAS Loop")

    # Add outdoor air system (100% OA, no recirculation)
    oa_controller = openstudio.model.ControllerOutdoorAir(model)
    oa_controller.setName(f"{name} OA Controller")
    oa_controller.autosizeMinimumOutdoorAirFlowRate()

    oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(model, oa_controller)
    oa_system.setName(f"{name} OA System")
    oa_system.addToNode(doas_loop.supplyInletNode())

    # Add energy recovery ventilator if requested
    erv_name = None
    if energy_recovery:
        erv = openstudio.model.HeatExchangerAirToAirSensibleAndLatent(model)
        erv.setName(f"{name} ERV")
        erv.setSensibleEffectivenessat100HeatingAirFlow(sensible_effectiveness)
        erv.setSensibleEffectivenessat100CoolingAirFlow(sensible_effectiveness)
        erv.setLatentEffectivenessat100HeatingAirFlow(sensible_effectiveness * 0.65)
        erv.setLatentEffectivenessat100CoolingAirFlow(sensible_effectiveness * 0.65)
        erv.setSupplyAirOutletTemperatureControl(False)

        oa_node = oa_system.outboardOANode()
        if oa_node.is_initialized():
            erv.addToNode(oa_node.get())
            erv_name = erv.nameString()

    # Add preheat coil
    preheat_coil = openstudio.model.CoilHeatingGas(model, model.alwaysOnDiscreteSchedule())
    preheat_coil.setName(f"{name} DOAS Preheat Coil")
    preheat_coil.addToNode(doas_loop.supplyInletNode())

    # Add precool/dehumidification coil
    precool_coil = openstudio.model.CoilCoolingDXTwoSpeed(model)
    precool_coil.setName(f"{name} DOAS Precool Coil")
    precool_coil.addToNode(doas_loop.supplyInletNode())

    # Add supply fan
    fan = openstudio.model.FanConstantVolume(model, model.alwaysOnDiscreteSchedule())
    fan.setName(f"{name} DOAS Supply Fan")
    fan.setPressureRise(500.0)
    fan.setFanEfficiency(0.6)
    fan.addToNode(doas_loop.supplyInletNode())

    # Add setpoint manager (constant 55F supply temp)
    spm = openstudio.model.SetpointManagerSingleZoneReheat(model)
    spm.setName(f"{name} DOAS SPM")
    spm.setMinimumSupplyAirTemperature(12.8)  # 55F
    spm.setMaximumSupplyAirTemperature(12.8)
    spm.addToNode(doas_loop.supplyOutletNode())

    # Create plant loops for zone equipment (if needed)
    chw_loop = None
    hw_loop = None
    chw_loop_name = None
    hw_loop_name = None

    if zone_equipment_type in ("FanCoil", "Radiant", "Chiller_Beams"):
        chw_loop = wiring.create_chilled_water_loop(model, f"{name} CHW Loop")
        chw_loop_name = chw_loop.nameString()

    if zone_equipment_type in ("FanCoil", "Radiant"):
        hw_loop = wiring.create_hot_water_loop(model, f"{name} HW Loop")
        hw_loop_name = hw_loop.nameString()

    # Wire supply equipment to plant loops
    cw_loop_name = None
    if chw_loop:
        cw_loop = wiring.add_cooling_supply(model, chw_loop, cooling_fuel, name)
        if cw_loop:
            cw_loop_name = cw_loop.nameString()
    if hw_loop:
        wiring.add_boiler_to_loop(model, hw_loop, heating_fuel)

    # Connect zones to DOAS loop and add zone equipment
    zone_equipment_list = []
    for zone in zones:
        zone_name = zone.nameString()

        if zone_equipment_type == "Chiller_Beams":
            # Chilled beam IS the DOAS air terminal (replaces uncontrolled)
            coil = openstudio.model.CoilCoolingCooledBeam(model)
            beam = openstudio.model.AirTerminalSingleDuctConstantVolumeCooledBeam(
                model, model.alwaysOnDiscreteSchedule(), coil,
            )
            beam.setName(f"{name} Chilled Beam - {zone_name}")
            doas_loop.addBranchForZone(zone, beam)
            chw_loop.addDemandBranchForComponent(coil)

            zone_equipment_list.append({
                "type": "AirTerminalSingleDuctConstantVolumeCooledBeam",
                "name": beam.nameString(),
                "zone": zone_name,
            })
        else:
            # Standard uncontrolled terminal for DOAS ventilation
            terminal = openstudio.model.AirTerminalSingleDuctUncontrolled(
                model, model.alwaysOnDiscreteSchedule(),
            )
            terminal.setName(f"{name} DOAS Terminal - {zone_name}")
            doas_loop.addBranchForZone(zone, terminal)

            if zone_equipment_type == "FanCoil":
                fc = openstudio.model.ZoneHVACFourPipeFanCoil(
                    model,
                    model.alwaysOnDiscreteSchedule(),
                    openstudio.model.FanOnOff(model, model.alwaysOnDiscreteSchedule()),
                    openstudio.model.CoilCoolingWater(model, model.alwaysOnDiscreteSchedule()),
                    openstudio.model.CoilHeatingWater(model, model.alwaysOnDiscreteSchedule()),
                )
                fc.setName(f"{name} Fan Coil - {zone_name}")
                fc.addToThermalZone(zone)
                chw_loop.addDemandBranchForComponent(fc.coolingCoil())
                hw_loop.addDemandBranchForComponent(fc.heatingCoil())

                zone_equipment_list.append({
                    "type": "ZoneHVACFourPipeFanCoil",
                    "name": fc.nameString(),
                    "zone": zone_name,
                })

            elif zone_equipment_type == "Radiant":
                radiant = openstudio.model.ZoneHVACLowTempRadiantVarFlow(model)
                radiant.setName(f"{name} Radiant - {zone_name}")
                radiant.addToThermalZone(zone)
                hw_loop.addDemandBranchForComponent(radiant)
                chw_loop.addDemandBranchForComponent(radiant)

                zone_equipment_list.append({
                    "type": "ZoneHVACLowTempRadiantVarFlow",
                    "name": radiant.nameString(),
                    "zone": zone_name,
                })

    return {
        "name": name,
        "type": "DOAS",
        "doas_loop": doas_loop.nameString(),
        "energy_recovery": energy_recovery,
        "erv_name": erv_name,
        "sensible_effectiveness": sensible_effectiveness if energy_recovery else None,
        "zone_equipment_type": zone_equipment_type,
        "chilled_water_loop": chw_loop_name,
        "hot_water_loop": hw_loop_name,
        "condenser_water_loop": cw_loop_name,
        "heating_fuel": heating_fuel,
        "cooling_fuel": cooling_fuel,
        "num_zones": len(zones),
        "zone_equipment": zone_equipment_list,
    }


def create_vrf_system(
    model,
    zones: list,
    name: str,
    heat_recovery: bool,
    capacity_w: float | None,
) -> dict[str, Any]:
    """Create Variable Refrigerant Flow multi-zone heat pump system.

    VRF Pattern:
    1. Create VRF outdoor unit (condenser)
    2. Add VRF zone terminals (evaporators, 1 per zone)
    3. Configure heat recovery mode if requested
    4. Set capacity or enable autosizing

    Args:
        model: OpenStudio model
        zones: List of ThermalZone objects to serve
        name: Name prefix for VRF components
        heat_recovery: Enable heat recovery mode (simultaneous heating/cooling)
        capacity_w: Outdoor unit capacity in Watts (autosize if None)

    Returns:
        dict with VRF outdoor unit and terminal details
    """
    # Create VRF outdoor unit
    if heat_recovery:
        vrf_system = openstudio.model.AirConditionerVariableRefrigerantFlowFluidTemperatureControlHR(model)
        vrf_system.setName(f"{name} VRF Outdoor Unit HR")
    else:
        vrf_system = openstudio.model.AirConditionerVariableRefrigerantFlow(model)
        vrf_system.setName(f"{name} VRF Outdoor Unit")

    # Set capacity or autosize (HR model uses different API)
    if heat_recovery:
        if capacity_w is not None:
            vrf_system.setRatedEvaporativeCapacity(capacity_w)
            autosized = False
        else:
            vrf_system.autosizeRatedEvaporativeCapacity()
            autosized = True
    else:
        if capacity_w is not None:
            vrf_system.setGrossRatedTotalCoolingCapacity(capacity_w)
            vrf_system.setGrossRatedHeatingCapacity(capacity_w)
            autosized = False
        else:
            vrf_system.autosizeGrossRatedTotalCoolingCapacity()
            vrf_system.autosizeGrossRatedHeatingCapacity()
            autosized = True

    # Create VRF terminals for each zone
    terminals = []
    for zone in zones:
        terminal = openstudio.model.ZoneHVACTerminalUnitVariableRefrigerantFlow(model)
        terminal.setName(f"{name} VRF Terminal - {zone.nameString()}")

        # Connect terminal to VRF system via outdoor unit
        vrf_system.addTerminal(terminal)

        # Add to thermal zone
        terminal.addToThermalZone(zone)

        terminals.append({
            "name": terminal.nameString(),
            "zone": zone.nameString(),
        })

    return {
        "name": name,
        "type": "VRF",
        "outdoor_unit": vrf_system.nameString(),
        "heat_recovery": heat_recovery,
        "capacity_w": capacity_w if not autosized else "autosized",
        "num_zones": len(zones),
        "terminals": terminals,
    }


def create_radiant_system(
    model,
    zones: list,
    name: str,
    radiant_type: str,
    ventilation_system: str,
    heating_fuel: str = "NaturalGas",
    cooling_fuel: str = "Electricity",
) -> dict[str, Any]:
    """Create low-temperature radiant heating/cooling system.

    Radiant Pattern:
    1. Create low-temp hot water loop (120F)
    2. Create low-temp chilled water loop (58F)
    3. Add radiant surfaces to zones (floor/ceiling/walls)
    4. Optionally add DOAS for ventilation if requested

    Args:
        model: OpenStudio model
        zones: List of ThermalZone objects to serve
        name: Name prefix for radiant components
        radiant_type: "Floor" | "Ceiling" | "Walls"
        ventilation_system: "DOAS" | "None" (if None, ventilation added separately)

    Returns:
        dict with radiant system details including plant loops
    """
    # Create low-temperature hot water loop (120F)
    hw_loop = wiring.create_hot_water_loop(model, f"{name} Low-Temp HW Loop")
    sizing = hw_loop.sizingPlant()
    sizing.setDesignLoopExitTemperature(48.9)  # 120F
    sizing.setLoopDesignTemperatureDifference(11.1)  # 20F delta

    # Create low-temperature chilled water loop (58F)
    chw_loop = wiring.create_chilled_water_loop(model, f"{name} Low-Temp CHW Loop")
    sizing = chw_loop.sizingPlant()
    sizing.setDesignLoopExitTemperature(14.4)  # 58F
    sizing.setLoopDesignTemperatureDifference(5.6)  # 10F delta

    # Wire supply equipment to plant loops
    cw_loop_name = None
    cw_loop = wiring.add_cooling_supply(model, chw_loop, cooling_fuel, name)
    if cw_loop:
        cw_loop_name = cw_loop.nameString()
    wiring.add_boiler_to_loop(model, hw_loop, heating_fuel)

    # Map user type to OpenStudio enum
    os_surface_type = _RADIANT_SURFACE_MAP.get(radiant_type, "Floors")

    # Add radiant surfaces to zones
    radiant_equipment = []
    for zone in zones:
        zone_name = zone.nameString()

        radiant = openstudio.model.ZoneHVACLowTempRadiantVarFlow(model)
        radiant.setName(f"{name} {radiant_type} Radiant - {zone_name}")
        radiant.setRadiantSurfaceType(os_surface_type)
        radiant.addToThermalZone(zone)

        # Connect to plant loops
        hw_loop.addDemandBranchForComponent(radiant)
        chw_loop.addDemandBranchForComponent(radiant)

        radiant_equipment.append({
            "name": radiant.nameString(),
            "zone": zone_name,
            "type": radiant_type,  # Return user-facing type, not OS enum
        })

    # Add DOAS for ventilation if requested
    doas_loop_name = None
    if ventilation_system == "DOAS":
        doas_result = create_doas_system(
            model, zones, f"{name} Ventilation",
            energy_recovery=True,
            sensible_effectiveness=0.75,
            zone_equipment_type="None",  # Radiant handles sensible load
        )
        doas_loop_name = doas_result["doas_loop"]

    return {
        "name": name,
        "type": "Radiant",
        "radiant_type": radiant_type,
        "hot_water_loop": hw_loop.nameString(),
        "chilled_water_loop": chw_loop.nameString(),
        "condenser_water_loop": cw_loop_name,
        "heating_fuel": heating_fuel,
        "cooling_fuel": cooling_fuel,
        "hw_supply_temp_f": 120,
        "chw_supply_temp_f": 58,
        "ventilation_system": ventilation_system,
        "doas_loop": doas_loop_name,
        "num_zones": len(zones),
        "radiant_equipment": radiant_equipment,
    }
