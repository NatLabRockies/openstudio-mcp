"""HVAC wiring recipes — curated from openstudio-resources simulation tests.

Each recipe shows the minimal Ruby code to construct and connect HVAC
components. Extracted from NatLabRockies/OpenStudio-resources (BSD-3).

Use search_wiring_patterns() to find recipes by component type or keyword.
"""
from __future__ import annotations

RECIPES: dict[str, dict] = {

    # ── Air Terminal Types ───────────────────────────────────────────────

    "four_pipe_beam_terminal": {
        "component_type": "AirTerminalSingleDuctConstantVolumeFourPipeBeam",
        "connections": [
            "CoilCoolingFourPipeBeam → chilled water plant loop (demand)",
            "CoilHeatingFourPipeBeam → hot water plant loop (demand)",
            "Both coils → AirTerminalSingleDuctConstantVolumeFourPipeBeam constructor",
            "Terminal → air loop via addBranchForZone (replaces existing terminal)",
        ],
        "ruby": """\
cc = OpenStudio::Model::CoilCoolingFourPipeBeam.new(model)
p_chw.addDemandBranchForComponent(cc)
hc = OpenStudio::Model::CoilHeatingFourPipeBeam.new(model)
p_hw.addDemandBranchForComponent(hc)
atu = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeFourPipeBeam.new(model, cc, hc)
air_loop.removeBranchForZone(zone)
air_loop.addBranchForZone(zone, atu.to_StraightComponent)""",
        "notes": "Must removeBranchForZone before adding new terminal. "
                 "Coils must be added to plant demand BEFORE ATU is added to air loop. "
                 "Both cooling and heating coils required in constructor.",
        "source": "airterminal_fourpipebeam.rb",
    },

    "cooled_beam_terminal": {
        "component_type": "AirTerminalSingleDuctConstantVolumeCooledBeam",
        "connections": [
            "CoilCoolingCooledBeam → chilled water plant loop (demand)",
            "Coil → AirTerminalSingleDuctConstantVolumeCooledBeam constructor",
            "Terminal → air loop via addBranchForZone",
        ],
        "ruby": """\
coil = OpenStudio::Model::CoilCoolingCooledBeam.new(model)
chw_loop.addDemandBranchForComponent(coil)
atu = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeCooledBeam.new(
  model, model.alwaysOnDiscreteSchedule, coil)
atu.setCooledBeamType('Passive')  # or 'Active'
air_loop.addBranchForZone(zone, atu.to_StraightComponent)""",
        "notes": "Cooling only — no heating coil. Heating via central AHU coil. "
                 "setCooledBeamType: 'Passive' or 'Active'.",
        "source": "airterminal_cooledbeam.rb",
    },

    "vav_no_reheat": {
        "component_type": "AirTerminalSingleDuctVAVNoReheat",
        "connections": [
            "Terminal → air loop via addBranchForZone (replaces existing)",
        ],
        "ruby": """\
air_loop.removeBranchForZone(zone)
atu = OpenStudio::Model::AirTerminalSingleDuctVAVNoReheat.new(model, schedule)
air_loop.addBranchForZone(zone, atu.to_StraightComponent)""",
        "notes": "No reheat coil, no plant loop connection.",
        "source": "air_terminals.rb",
    },

    "constant_volume_reheat_water": {
        "component_type": "AirTerminalSingleDuctConstantVolumeReheat",
        "connections": [
            "CoilHeatingWater → hot water plant loop (demand)",
            "Coil → AirTerminalSingleDuctConstantVolumeReheat constructor",
            "Terminal → air loop via addBranchForZone",
        ],
        "ruby": """\
air_loop.removeBranchForZone(zone)
coil = OpenStudio::Model::CoilHeatingWater.new(model, schedule)
atu = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeReheat.new(model, schedule, coil)
air_loop.addBranchForZone(zone, atu.to_StraightComponent)
hw_loop.addDemandBranchForComponent(coil)""",
        "notes": "Electric/gas reheat: same pattern but no plant connection needed. "
                 "Use CoilHeatingElectric or CoilHeatingGas instead.",
        "source": "air_terminals.rb",
    },

    "parallel_piu_reheat": {
        "component_type": "AirTerminalSingleDuctParallelPIUReheat",
        "connections": [
            "CoilHeatingWater → hot water plant loop (demand)",
            "Fan + coil → AirTerminalSingleDuctParallelPIUReheat constructor",
            "Terminal → air loop via addBranchForZone",
        ],
        "ruby": """\
air_loop.removeBranchForZone(zone)
coil = OpenStudio::Model::CoilHeatingWater.new(model, schedule)
fan = OpenStudio::Model::FanConstantVolume.new(model, schedule)
atu = OpenStudio::Model::AirTerminalSingleDuctParallelPIUReheat.new(model, schedule, fan, coil)
air_loop.addBranchForZone(zone, atu.to_StraightComponent)
hw_loop.addDemandBranchForComponent(coil)""",
        "notes": "ParallelPIU constructor takes schedule; SeriesPIU does NOT.",
        "source": "air_terminals.rb",
    },

    "four_pipe_induction": {
        "component_type": "AirTerminalSingleDuctConstantVolumeFourPipeInduction",
        "connections": [
            "CoilHeatingWater → hot water plant loop (demand)",
            "CoilCoolingWater → chilled water plant loop (demand)",
            "Heating coil → constructor, cooling coil → setCoolingCoil()",
            "Terminal → air loop via addBranchForZone",
        ],
        "ruby": """\
air_loop.removeBranchForZone(zone)
heat_coil = OpenStudio::Model::CoilHeatingWater.new(model, schedule)
cool_coil = OpenStudio::Model::CoilCoolingWater.new(model, schedule)
atu = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeFourPipeInduction.new(model, heat_coil)
atu.setCoolingCoil(cool_coil)
air_loop.addBranchForZone(zone, atu.to_StraightComponent)
hw_loop.addDemandBranchForComponent(heat_coil)
chw_loop.addDemandBranchForComponent(cool_coil)""",
        "notes": "Constructor takes only heating coil. Cooling coil set separately "
                 "via setCoolingCoil(). Different from FourPipeBeam which takes both.",
        "source": "air_terminals.rb",
    },

    # ── Zone HVAC Equipment ──────────────────────────────────────────────

    "four_pipe_fan_coil": {
        "component_type": "ZoneHVACFourPipeFanCoil",
        "connections": [
            "CoilCoolingWater → chilled water plant loop (demand)",
            "CoilHeatingWater → hot water plant loop (demand)",
            "Fan + coils → ZoneHVACFourPipeFanCoil constructor",
            "Fan coil → zone via addToThermalZone",
        ],
        "ruby": """\
fan = OpenStudio::Model::FanOnOff.new(model, model.alwaysOnDiscreteSchedule)
cool_coil = OpenStudio::Model::CoilCoolingWater.new(model, model.alwaysOnDiscreteSchedule)
chw_loop.addDemandBranchForComponent(cool_coil)
heat_coil = OpenStudio::Model::CoilHeatingWater.new(model, model.alwaysOnDiscreteSchedule)
hw_loop.addDemandBranchForComponent(heat_coil)
fc = OpenStudio::Model::ZoneHVACFourPipeFanCoil.new(
  model, model.alwaysOnDiscreteSchedule, fan, cool_coil, heat_coil)
fc.addToThermalZone(zone)""",
        "notes": "Constructor order: (model, schedule, fan, coolingCoil, heatingCoil) — "
                 "cooling before heating.",
        "source": "zone_hvac.rb",
    },

    "baseboard_convective_water": {
        "component_type": "ZoneHVACBaseboardConvectiveWater",
        "connections": [
            "CoilHeatingWaterBaseboard → hot water plant loop (demand)",
            "Coil → ZoneHVACBaseboardConvectiveWater constructor",
            "Baseboard → zone via addToThermalZone",
        ],
        "ruby": """\
coil = OpenStudio::Model::CoilHeatingWaterBaseboard.new(model)
bb = OpenStudio::Model::ZoneHVACBaseboardConvectiveWater.new(
  model, model.alwaysOnDiscreteSchedule, coil)
bb.addToThermalZone(zone)
hw_loop.addDemandBranchForComponent(coil)""",
        "notes": "Uses CoilHeatingWaterBaseboard, not CoilHeatingWater.",
        "source": "zone_hvac.rb",
    },

    "water_to_air_heat_pump": {
        "component_type": "ZoneHVACWaterToAirHeatPump",
        "connections": [
            "CoilHeatingWaterToAirHeatPumpEquationFit → condenser loop (demand)",
            "CoilCoolingWaterToAirHeatPumpEquationFit → condenser loop (demand)",
            "Fan + coils + supplemental → ZoneHVACWaterToAirHeatPump constructor",
            "HP → zone via addToThermalZone",
        ],
        "ruby": """\
fan = OpenStudio::Model::FanOnOff.new(model, model.alwaysOnDiscreteSchedule)
htg = OpenStudio::Model::CoilHeatingWaterToAirHeatPumpEquationFit.new(model)
clg = OpenStudio::Model::CoilCoolingWaterToAirHeatPumpEquationFit.new(model)
supp = OpenStudio::Model::CoilHeatingElectric.new(model, model.alwaysOnDiscreteSchedule)
hp = OpenStudio::Model::ZoneHVACWaterToAirHeatPump.new(
  model, model.alwaysOnDiscreteSchedule, fan, htg, clg, supp)
hp.addToThermalZone(zone)
condenser_loop.addDemandBranchForComponent(htg)
condenser_loop.addDemandBranchForComponent(clg)""",
        "notes": "BOTH heating and cooling coils go on condenser loop demand. "
                 "Supplemental coil is electric (backup heat).",
        "source": "zone_hvac.rb",
    },

    "ptac": {
        "component_type": "ZoneHVACPackagedTerminalAirConditioner",
        "connections": [
            "Fan + coils → PTAC constructor",
            "PTAC → zone via addToThermalZone",
        ],
        "ruby": """\
htg = OpenStudio::Model::CoilHeatingElectric.new(model, schedule)
clg = OpenStudio::Model::CoilCoolingDXSingleSpeed.new(model)
fan = OpenStudio::Model::FanOnOff.new(model, schedule)
ptac = OpenStudio::Model::ZoneHVACPackagedTerminalAirConditioner.new(
  model, schedule, fan, htg, clg)
ptac.addToThermalZone(zone)""",
        "notes": "Constructor order: (model, schedule, fan, heatingCoil, coolingCoil). "
                 "DX variable-speed cooling requires addSpeed(SpeedData).",
        "source": "ptac_othercoils.rb",
    },

    "pthp": {
        "component_type": "ZoneHVACPackagedTerminalHeatPump",
        "connections": [
            "Fan + coils + supplemental → PTHP constructor",
            "PTHP → zone via addToThermalZone",
        ],
        "ruby": """\
htg = OpenStudio::Model::CoilHeatingDXSingleSpeed.new(model)
clg = OpenStudio::Model::CoilCoolingDXSingleSpeed.new(model)
supp = OpenStudio::Model::CoilHeatingElectric.new(model, schedule)
fan = OpenStudio::Model::FanOnOff.new(model, schedule)
pthp = OpenStudio::Model::ZoneHVACPackagedTerminalHeatPump.new(
  model, schedule, fan, htg, clg, supp)
pthp.addToThermalZone(zone)""",
        "notes": "PTHP requires DX heating coil (not electric/gas). "
                 "6th arg is supplemental heating coil. "
                 "Variable-speed DX coils need addSpeed(SpeedData).",
        "source": "pthp_othercoils.rb",
    },

    "unit_heater": {
        "component_type": "ZoneHVACUnitHeater",
        "connections": [
            "Fan + coil → ZoneHVACUnitHeater constructor",
            "Unit heater → zone via addToThermalZone",
        ],
        "ruby": """\
fan = OpenStudio::Model::FanConstantVolume.new(model, model.alwaysOnDiscreteSchedule)
coil = OpenStudio::Model::CoilHeatingElectric.new(model, model.alwaysOnDiscreteSchedule)
uh = OpenStudio::Model::ZoneHVACUnitHeater.new(
  model, model.alwaysOnDiscreteSchedule, fan, coil)
uh.addToThermalZone(zone)""",
        "notes": "Can use CoilHeatingWater instead — add to HW plant demand.",
        "source": "zone_hvac.rb",
    },

    # ── DOAS ─────────────────────────────────────────────────────────────

    "doas_overlay": {
        "component_type": "AirLoopHVACDedicatedOutdoorAirSystem",
        "connections": [
            "ControllerOutdoorAir → AirLoopHVACOutdoorAirSystem",
            "OA system → AirLoopHVACDedicatedOutdoorAirSystem constructor",
            "DOAS → child air loops via addAirLoop()",
            "Coils on DOAS OA node (not air loop supply node)",
            "Water coils → plant loops (demand)",
        ],
        "ruby": """\
controller = OpenStudio::Model::ControllerOutdoorAir.new(model)
oas = OpenStudio::Model::AirLoopHVACOutdoorAirSystem.new(model, controller)
doas = OpenStudio::Model::AirLoopHVACDedicatedOutdoorAirSystem.new(oas)
doas.addAirLoop(airloop1)
doas.addAirLoop(airloop2)
# Equipment on DOAS OA node
cool = OpenStudio::Model::CoilCoolingWater.new(model)
heat = OpenStudio::Model::CoilHeatingWater.new(model)
fan = OpenStudio::Model::FanSystemModel.new(model)
cool.addToNode(oas.outboardOANode.get)
heat.addToNode(oas.outboardOANode.get)
fan.addToNode(oas.outboardOANode.get)
chw_loop.addDemandBranchForComponent(cool)
hw_loop.addDemandBranchForComponent(heat)""",
        "notes": "DOAS has its own OA system separate from child air loops. "
                 "Equipment goes on oas.outboardOANode, NOT the air loop supply node. "
                 "SPMs needed on BOTH DOAS coil outlets AND child air loop supply outlets. "
                 "Wire child air loops fully before calling addAirLoop().",
        "source": "doas.rb",
    },

    # ── Plant Loop Construction ──────────────────────────────────────────

    "hot_water_plant_loop": {
        "component_type": "PlantLoop (Heating)",
        "connections": [
            "PlantLoop → sizingPlant (Heating, 82°C, 11K delta)",
            "PumpVariableSpeed → supplyInletNode",
            "BoilerHotWater → supply branch",
            "SetpointManagerScheduled → supplyOutletNode",
            "Water coils → demand via addDemandBranchForComponent",
        ],
        "ruby": """\
hw_loop = OpenStudio::Model::PlantLoop.new(model)
sizing = hw_loop.sizingPlant
sizing.setLoopType('Heating')
sizing.setDesignLoopExitTemperature(82.0)
sizing.setLoopDesignTemperatureDifference(11.0)
pump = OpenStudio::Model::PumpVariableSpeed.new(model)
pump.addToNode(hw_loop.supplyInletNode)
boiler = OpenStudio::Model::BoilerHotWater.new(model)
hw_loop.addSupplyBranchForComponent(boiler)
spm = OpenStudio::Model::SetpointManagerScheduled.new(model, hw_temp_sch)
spm.addToNode(hw_loop.supplyOutletNode)""",
        "notes": "Pump on supplyInletNode, SPM on supplyOutletNode. "
                 "Alternative: boiler.addToNode(supplySplitter.lastOutletModelObject.get.to_Node.get).",
        "source": "zone_hvac.rb, doas.rb",
    },

    "chilled_water_plant_loop": {
        "component_type": "PlantLoop (Cooling)",
        "connections": [
            "PlantLoop → sizingPlant (Cooling, 7.22°C, 6.67K delta)",
            "PumpVariableSpeed → supplyInletNode",
            "ChillerElectricEIR → supply branch",
            "SetpointManagerScheduled → supplyOutletNode",
            "Cooling coils → demand via addDemandBranchForComponent",
        ],
        "ruby": """\
chw_loop = OpenStudio::Model::PlantLoop.new(model)
sizing = chw_loop.sizingPlant
sizing.setLoopType('Cooling')
sizing.setDesignLoopExitTemperature(7.22)
sizing.setLoopDesignTemperatureDifference(6.67)
pump = OpenStudio::Model::PumpVariableSpeed.new(model)
pump.addToNode(chw_loop.supplyInletNode)
chiller = OpenStudio::Model::ChillerElectricEIR.new(model)
chw_loop.addSupplyBranchForComponent(chiller)
spm = OpenStudio::Model::SetpointManagerScheduled.new(model, chw_temp_sch)
spm.addToNode(chw_loop.supplyOutletNode)""",
        "notes": "Chiller can also connect to condenser loop via "
                 "condenser_loop.addDemandBranchForComponent(chiller).",
        "source": "doas.rb, unitary_system.rb",
    },

    "condenser_water_loop": {
        "component_type": "PlantLoop (Condenser)",
        "connections": [
            "PlantLoop → sizingPlant (Condenser, 29.4°C, 5.6K delta)",
            "PumpVariableSpeed → supplyInletNode",
            "CoolingTower or GroundHX → supply branch",
            "Chillers/HPs → demand via addDemandBranchForComponent",
        ],
        "ruby": """\
cw_loop = OpenStudio::Model::PlantLoop.new(model)
sizing = cw_loop.sizingPlant
sizing.setLoopType('Condenser')
sizing.setDesignLoopExitTemperature(29.4)
sizing.setLoopDesignTemperatureDifference(5.6)
pump = OpenStudio::Model::PumpVariableSpeed.new(model)
pump.addToNode(cw_loop.supplyInletNode)
tower = OpenStudio::Model::CoolingTowerSingleSpeed.new(model)
cw_loop.addSupplyBranchForComponent(tower)
spm = OpenStudio::Model::SetpointManagerFollowOutdoorAirTemperature.new(model)
spm.addToNode(cw_loop.supplyOutletNode)""",
        "notes": "Condenser loop sizingPlant uses 'Condenser' type. "
                 "Can use GroundHeatExchangerVertical instead of cooling tower. "
                 "Chillers and water-source HPs go on demand side.",
        "source": "unitary_system.rb, heatpump_plantloop_eir.rb",
    },

    # ── Plant Loop Heat Pumps ────────────────────────────────────────────

    "plant_loop_heat_pump_air_source": {
        "component_type": "HeatPumpPlantLoopEIRHeating / Cooling",
        "connections": [
            "HeatPumpPlantLoopEIRHeating → HW loop (supply)",
            "HeatPumpPlantLoopEIRCooling → CHW loop (supply)",
            "Companion link: setCompanionCoolingHeatPump / setCompanionHeatingHeatPump",
        ],
        "ruby": """\
hp_htg = OpenStudio::Model::HeatPumpPlantLoopEIRHeating.new(model)
hp_clg = OpenStudio::Model::HeatPumpPlantLoopEIRCooling.new(model)
hp_htg.setCompanionCoolingHeatPump(hp_clg)
hp_clg.setCompanionHeatingHeatPump(hp_htg)
hw_loop.addSupplyBranchForComponent(hp_htg)
chw_loop.addSupplyBranchForComponent(hp_clg)""",
        "notes": "Air-source: supply side only, no condenser loop. "
                 "Companions must be linked bidirectionally.",
        "source": "heatpump_plantloop_eir.rb",
    },

    "plant_loop_heat_pump_water_source": {
        "component_type": "HeatPumpPlantLoopEIRHeating / Cooling (water-source)",
        "connections": [
            "HeatPumpPlantLoopEIRHeating → HW loop (supply) + condenser loop (demand)",
            "HeatPumpPlantLoopEIRCooling → CHW loop (supply) + condenser loop (demand)",
            "Companion link bidirectional",
        ],
        "ruby": """\
hp_htg = OpenStudio::Model::HeatPumpPlantLoopEIRHeating.new(model)
hp_clg = OpenStudio::Model::HeatPumpPlantLoopEIRCooling.new(model)
hp_htg.setCompanionCoolingHeatPump(hp_clg)
hp_clg.setCompanionHeatingHeatPump(hp_htg)
hw_loop.addSupplyBranchForComponent(hp_htg)
chw_loop.addSupplyBranchForComponent(hp_clg)
cw_loop.addDemandBranchForComponent(hp_htg)
cw_loop.addDemandBranchForComponent(hp_clg)""",
        "notes": "Water-source adds condenser loop demand connections. "
                 "Both HP objects go on condenser demand.",
        "source": "heatpump_plantloop_eir.rb",
    },

    "central_heat_pump_system": {
        "component_type": "CentralHeatPumpSystem",
        "connections": [
            "CentralHeatPumpSystemModule → CentralHeatPumpSystem via addModule()",
            "System → condenser loop (demand), CHW loop (supply), HW loop (supply/tertiary)",
        ],
        "ruby": """\
chp = OpenStudio::Model::CentralHeatPumpSystem.new(model)
mod1 = OpenStudio::Model::CentralHeatPumpSystemModule.new(model)
chp.addModule(mod1)
mod2 = OpenStudio::Model::CentralHeatPumpSystemModule.new(model)
mod2.setNumberofChillerHeaterModules(2)
chp.addModule(mod2)
condenser_loop.addDemandBranchForComponent(chp)
chw_loop.addSupplyBranchForComponent(chp)
hw_loop.addSupplyBranchForComponent(chp)""",
        "notes": "Three-loop connection: condenser (demand), CHW (supply), HW (supply/tertiary). "
                 "Modules must be added before loop connections. "
                 "setNumberofChillerHeaterModules sets parallel count per module.",
        "source": "centralheatpumpsystem.rb",
    },

    # ── Unitary Systems ──────────────────────────────────────────────────

    "unitary_system_dx": {
        "component_type": "AirLoopHVACUnitarySystem (DX)",
        "connections": [
            "Fan + cooling coil + heating coil → unitary via setters",
            "Unitary → air loop supply node via addToNode",
            "Terminal → zone via addBranchForZone",
        ],
        "ruby": """\
airloop = OpenStudio::Model::AirLoopHVAC.new(model)
unitary = OpenStudio::Model::AirLoopHVACUnitarySystem.new(model)
fan = OpenStudio::Model::FanOnOff.new(model)
clg = OpenStudio::Model::CoilCoolingDXSingleSpeed.new(model)
htg = OpenStudio::Model::CoilHeatingDXSingleSpeed.new(model)
supp = OpenStudio::Model::CoilHeatingElectric.new(model, schedule)
unitary.setSupplyFan(fan)
unitary.setCoolingCoil(clg)
unitary.setHeatingCoil(htg)
unitary.setSupplementalHeatingCoil(supp)
unitary.setFanPlacement('BlowThrough')
unitary.setControllingZoneorThermostatLocation(zone)
unitary.addToNode(airloop.supplyOutletNode)
atu = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeNoReheat.new(
  model, model.alwaysOnDiscreteSchedule)
airloop.addBranchForZone(zone, atu)""",
        "notes": "setControllingZoneorThermostatLocation required for single-zone. "
                 "Multi-speed coils need stage/speed data added BEFORE assigning to unitary. "
                 "Water coils: add to plant demand before or after unitary assignment.",
        "source": "unitary_system.rb",
    },

    # ── VRF ──────────────────────────────────────────────────────────────

    "vrf_system": {
        "component_type": "AirConditionerVariableRefrigerantFlow",
        "connections": [
            "AirConditionerVariableRefrigerantFlow (outdoor unit, shared)",
            "ZoneHVACTerminalUnitVariableRefrigerantFlow → zone or air loop or OA node",
            "Each terminal registered via vrf.addTerminal()",
        ],
        "ruby": """\
vrf = OpenStudio::Model::AirConditionerVariableRefrigerantFlow.new(model)
# Zone-level terminal (standalone)
term = OpenStudio::Model::ZoneHVACTerminalUnitVariableRefrigerantFlow.new(model)
term.addToThermalZone(zone)
term.setSupplyAirFanPlacement('BlowThrough')
vrf.addTerminal(term)
# Air-loop-mounted terminal
term2 = OpenStudio::Model::ZoneHVACTerminalUnitVariableRefrigerantFlow.new(model)
term2.addToNode(airloop.supplyOutletNode)
term2.setControllingZoneorThermostatLocation(zone)
term2.setSupplyAirFanPlacement('DrawThrough')
vrf.addTerminal(term2)
atu = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeNoReheat.new(
  model, model.alwaysOnDiscreteSchedule)
airloop.addBranchForZone(zone, atu)""",
        "notes": "VRF terminal placement: addToThermalZone (standalone), "
                 "addToNode(supplyOutletNode) (air loop), or "
                 "addToNode(oas.outboardOANode.get) (DOAS). "
                 "Every terminal must be registered via vrf.addTerminal(). "
                 "Zone still needs an ATU when VRF is on air loop.",
        "source": "vrf_airloophvac.rb",
    },

    # ── Absorption Chillers (triple-loop) ────────────────────────────────

    "absorption_chiller_indirect": {
        "component_type": "ChillerAbsorptionIndirect",
        "connections": [
            "Chiller → chilled water loop (supply)",
            "Chiller → condenser water loop (demand)",
            "Chiller → hot water loop (demand) — generator/tertiary",
        ],
        "ruby": """\
chiller = OpenStudio::Model::ChillerAbsorptionIndirect.new(model)
chw_loop.addSupplyBranchForComponent(chiller)
cw_loop.addDemandBranchForComponent(chiller)
hw_loop.addDemandBranchForComponent(chiller)""",
        "notes": "Three-loop connection: CHW (supply), condenser (demand), generator/HW (demand). "
                 "OpenStudio auto-detects tertiary port. "
                 "Order matters: CHW supply first, then condenser, then tertiary.",
        "source": "chillers_tertiary.rb",
    },

    # ── Setpoint Managers ────────────────────────────────────────────────

    "setpoint_manager_system_node_reset": {
        "component_type": "SetpointManagerSystemNodeResetTemperature",
        "connections": [
            "SPM → controlled node via addToNode()",
            "SPM → reference node via setReferenceNode()",
        ],
        "ruby": """\
# HW temp reset based on outdoor air temperature
spm = OpenStudio::Model::SetpointManagerSystemNodeResetTemperature.new(model)
spm.setControlVariable('Temperature')
spm.setSetpointatLowReferenceTemperature(80.0)   # high HW at cold OAT
spm.setSetpointatHighReferenceTemperature(65.6)   # low HW at warm OAT
spm.setLowReferenceTemperature(-6.7)              # cold OAT threshold
spm.setHighReferenceTemperature(10.0)             # warm OAT threshold
spm.setReferenceNode(model.outdoorAirNode)
spm.addToNode(hw_loop.supplyOutletNode)""",
        "notes": "setReferenceNode determines what drives the reset (OA node, return air, etc.). "
                 "addToNode determines what node gets the setpoint. "
                 "Linear interpolation between low/high reference temperatures. "
                 "Humidity variant: SetpointManagerSystemNodeResetHumidity.",
        "source": "setpoint_manager_systemnodereset.rb",
    },

    # ── Air Loop Construction ────────────────────────────────────────────

    "air_loop_from_scratch": {
        "component_type": "AirLoopHVAC (manual construction)",
        "connections": [
            "OA system → supplyOutletNode",
            "Cooling coil → supplyOutletNode (pushes OA upstream)",
            "Heating coil → supplyOutletNode (pushes cooling upstream)",
            "Fan → supplyOutletNode (draw-through)",
            "SPMs on specific nodes",
            "Zones via addBranchForZone with terminal",
        ],
        "ruby": """\
airloop = OpenStudio::Model::AirLoopHVAC.new(model)
sizing = airloop.sizingSystem
sizing.setCentralCoolingDesignSupplyAirTemperature(12.8)
sizing.setCentralHeatingDesignSupplyAirTemperature(12.8)
# OA system
controller = OpenStudio::Model::ControllerOutdoorAir.new(model)
oas = OpenStudio::Model::AirLoopHVACOutdoorAirSystem.new(model, controller)
oas.addToNode(airloop.supplyOutletNode)
# Coils + fan (each addToNode pushes previous equipment upstream)
cool = OpenStudio::Model::CoilCoolingWater.new(model, schedule)
cool.addToNode(airloop.supplyOutletNode)
heat = OpenStudio::Model::CoilHeatingWater.new(model, schedule)
heat.addToNode(airloop.supplyOutletNode)
fan = OpenStudio::Model::FanVariableVolume.new(model, schedule)
fan.addToNode(airloop.supplyOutletNode)
# SPM on fan outlet (= supply outlet after fan is last)
spm = OpenStudio::Model::SetpointManagerScheduled.new(model, deck_temp_sch)
spm.addToNode(fan.outletModelObject.get.to_Node.get)
# Zone connections
atu = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeNoReheat.new(
  model, model.alwaysOnDiscreteSchedule)
airloop.addBranchForZone(zone, atu)""",
        "notes": "Supply side order: OA → cooling → heating → fan (draw-through). "
                 "Each addToNode(supplyOutletNode) pushes previous equipment upstream. "
                 "Water coils need plant loop demand connections.",
        "source": "airterminal_cooledbeam.rb",
    },
}
