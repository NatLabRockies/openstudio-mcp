"""Baseline model builder — 10-zone, 2-story commercial building.

Adapted from OpenStudio-resources BaselineModel class (Python version).
Creates a perimeter+core zoned building with detailed schedules, loads,
constructions, and thermostats.

Upstream source:
  https://github.com/NREL/OpenStudio-resources/blob/develop/model/simulationtests/lib/baseline_model.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import openstudio


def _constructions_osm_path() -> Path:
    """Return path to baseline_model_constructions.osm shipped in tests/assets."""
    candidates = [
        Path(__file__).resolve().parents[3] / "tests" / "assets" / "baseline_model_constructions.osm",
        Path("/repo/tests/assets/baseline_model_constructions.osm"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"baseline_model_constructions.osm not found. Searched: {[str(c) for c in candidates]}"
    )


class BaselineModel(openstudio.model.Model):
    """10-zone commercial building model builder.

    Ported from OpenStudio-resources. Methods mirror the upstream API:
      add_geometry, set_constructions, set_space_type, add_thermostats,
      add_hvac, add_windows.
    """

    def add_geometry(
        self,
        length: float = 100.0,
        width: float = 50.0,
        num_floors: int = 2,
        floor_to_floor_height: float = 4.0,
        plenum_height: float = 0.0,
        perimeter_zone_depth: float = 3.0,
    ):
        if length <= 1e-4:
            raise ValueError("Length too small")
        if width <= 1e-4:
            raise ValueError("Width too small")
        if num_floors < 1:
            raise ValueError("num_floors must be >= 1")
        if floor_to_floor_height <= 1e-4:
            raise ValueError("floor_to_floor_height too small")
        if perimeter_zone_depth < 0:
            raise ValueError("perimeter_zone_depth must be >= 0")
        shortest_side = min(length, width)
        if (2 * perimeter_zone_depth) >= (shortest_side - 1e-4):
            raise ValueError("perimeter_zone_depth too large for building dimensions")

        for floor_idx in range(num_floors):
            z = floor_to_floor_height * floor_idx
            story = openstudio.model.BuildingStory(self)
            story.setNominalFloortoFloorHeight(floor_to_floor_height)
            story.setName(f"Story {floor_idx + 1}")

            nw = openstudio.Point3d(0, width, z)
            ne = openstudio.Point3d(length, width, z)
            se = openstudio.Point3d(length, 0, z)
            sw = openstudio.Point3d(0, 0, z)

            m = openstudio.Matrix(4, 4, 0)
            m[0, 0] = 1
            m[1, 1] = 1
            m[2, 2] = 1
            m[3, 3] = 1

            if perimeter_zone_depth > 0:
                p_nw = nw + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0)
                p_ne = ne + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
                p_se = se + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0)
                p_sw = sw + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0)

                # West
                poly = openstudio.Point3dVector()
                for pt in [sw, nw, p_nw, p_sw]:
                    poly.append(pt)
                sp = openstudio.model.Space.fromFloorPrint(poly, floor_to_floor_height, self).get()
                m[0, 3] = sw.x()
                m[1, 3] = sw.y()
                m[2, 3] = sw.z()
                sp.changeTransformation(openstudio.Transformation(m))
                sp.setBuildingStory(story)
                sp.setName(f"{story.nameString()} West Perimeter Space")

                # North
                poly = openstudio.Point3dVector()
                for pt in [nw, ne, p_ne, p_nw]:
                    poly.append(pt)
                sp = openstudio.model.Space.fromFloorPrint(poly, floor_to_floor_height, self).get()
                m[0, 3] = p_nw.x()
                m[1, 3] = p_nw.y()
                m[2, 3] = p_nw.z()
                sp.changeTransformation(openstudio.Transformation(m))
                sp.setBuildingStory(story)
                sp.setName(f"{story.nameString()} North Perimeter Space")

                # East
                poly = openstudio.Point3dVector()
                for pt in [ne, se, p_se, p_ne]:
                    poly.append(pt)
                sp = openstudio.model.Space.fromFloorPrint(poly, floor_to_floor_height, self).get()
                m[0, 3] = p_se.x()
                m[1, 3] = p_se.y()
                m[2, 3] = p_se.z()
                sp.changeTransformation(openstudio.Transformation(m))
                sp.setBuildingStory(story)
                sp.setName(f"{story.nameString()} East Perimeter Space")

                # South
                poly = openstudio.Point3dVector()
                for pt in [se, sw, p_sw, p_se]:
                    poly.append(pt)
                sp = openstudio.model.Space.fromFloorPrint(poly, floor_to_floor_height, self).get()
                m[0, 3] = sw.x()
                m[1, 3] = sw.y()
                m[2, 3] = sw.z()
                sp.changeTransformation(openstudio.Transformation(m))
                sp.setBuildingStory(story)
                sp.setName(f"{story.nameString()} South Perimeter Space")

                # Core
                poly = openstudio.Point3dVector()
                for pt in [p_sw, p_nw, p_ne, p_se]:
                    poly.append(pt)
                sp = openstudio.model.Space.fromFloorPrint(poly, floor_to_floor_height, self).get()
                m[0, 3] = p_sw.x()
                m[1, 3] = p_sw.y()
                m[2, 3] = p_sw.z()
                sp.changeTransformation(openstudio.Transformation(m))
                sp.setBuildingStory(story)
                sp.setName(f"{story.nameString()} Core Space")
            else:
                poly = openstudio.Point3dVector()
                for pt in [sw, nw, ne, se]:
                    poly.append(pt)
                sp = openstudio.model.Space.fromFloorPrint(poly, floor_to_floor_height, self).get()
                m[0, 3] = sw.x()
                m[1, 3] = sw.y()
                m[2, 3] = sw.z()
                sp.changeTransformation(openstudio.Transformation(m))
                sp.setBuildingStory(story)
                sp.setName(f"{story.nameString()} Core Space")

            story.setNominalZCoordinate(z)

        # Match surfaces and create thermal zones
        spaces = sorted(self.getSpaces(), key=lambda s: s.nameString())
        openstudio.model.matchSurfaces(openstudio.model.SpaceVector(spaces))

        renamed_surfaces = set()
        for space in spaces:
            if not space.thermalZone().is_initialized():
                tz = openstudio.model.ThermalZone(self)
                space.setThermalZone(tz)
                tz.setName(space.nameString().replace("Space", "Thermal Zone"))

            for s in space.surfaces():
                from_name = space.nameString()
                bc = s.outsideBoundaryCondition().lower()
                st = s.surfaceType().lower()
                if bc == "ground":
                    s.setName(f"{from_name} Exterior Ground Floor")
                elif bc == "outdoors":
                    if st == "wall":
                        s.setName(f"{from_name} Exterior Wall")
                    elif st == "roofceiling":
                        s.setName(f"{from_name} Exterior Roof")
                    elif st == "floor":
                        s.setName(f"{from_name} Exterior Floor")
                elif bc == "surface":
                    if s.handle() in renamed_surfaces:
                        continue
                    adj = s.adjacentSurface()
                    if not adj.is_initialized():
                        continue
                    adj_s = adj.get()
                    adj_sp = adj_s.space()
                    if not adj_sp.is_initialized():
                        continue
                    to_name = adj_sp.get().nameString()
                    s.setName(f"{from_name} to {to_name} Interior {s.surfaceType()}")
                    adj_s.setName(f"{to_name} to {from_name} Interior {s.surfaceType()}")
                    renamed_surfaces.add(s.handle())
                    renamed_surfaces.add(adj_s.handle())

    def set_constructions(self):
        """Load constructions from baseline_model_constructions.osm."""
        lib_path = _constructions_osm_path()
        vt = openstudio.osversion.VersionTranslator()
        lib = vt.loadModel(str(lib_path)).get()
        default_set = lib.getDefaultConstructionSets()[0].clone(self).to_DefaultConstructionSet().get()
        self.getBuilding().setDefaultConstructionSet(default_set)
        # Clone air boundary construction
        if openstudio.VersionString(openstudio.openStudioVersion()) > openstudio.VersionString("3.4.0"):
            lib.getConstructionAirBoundarys()[0].clone(self)
        else:
            for c in lib.getConstructions():
                if c.nameString().strip() == "Air_Wall":
                    c.clone(self)
                    break

    def set_space_type(self):
        """Add baseline space type with loads and schedules (90.1-2004 Large Office)."""
        space_type = openstudio.model.SpaceType(self)
        space_type.setName("Baseline Model Space Type")

        default_sch_set = openstudio.model.DefaultScheduleSet(self)
        default_sch_set.setName("Baseline Model Schedule Set")
        space_type.setDefaultScheduleSet(default_sch_set)

        # Infiltration schedule
        sch = openstudio.model.ScheduleRuleset(self)
        sch.setName("Baseline Model Infiltration Schedule")
        dd = openstudio.model.ScheduleDay(self)
        sch.setWinterDesignDaySchedule(dd)
        sch.winterDesignDaySchedule().setName("Baseline Model Infiltration Schedule Winter Design Day")
        sch.winterDesignDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 1)
        dd = openstudio.model.ScheduleDay(self)
        sch.setSummerDesignDaySchedule(dd)
        sch.summerDesignDaySchedule().setName("Baseline Model Infiltration Schedule Summer Design Day")
        sch.summerDesignDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 1)
        wd = sch.defaultDaySchedule()
        wd.setName("Baseline Model Infiltration Schedule All Days")
        wd.addValue(openstudio.Time(0, 6, 0, 0), 1)
        wd.addValue(openstudio.Time(0, 22, 0, 0), 0.25)
        wd.addValue(openstudio.Time(0, 24, 0, 0), 1)
        default_sch_set.setInfiltrationSchedule(sch)

        # People/Lights/Equipment schedule
        sch = openstudio.model.ScheduleRuleset(self)
        sch.setName("Baseline Model People Lights and Equipment Schedule")
        dd = openstudio.model.ScheduleDay(self)
        sch.setWinterDesignDaySchedule(dd)
        sch.winterDesignDaySchedule().setName("Baseline Model People Lights and Equipment Schedule Winter Design Day")
        sch.winterDesignDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 0)
        dd = openstudio.model.ScheduleDay(self)
        sch.setSummerDesignDaySchedule(dd)
        sch.summerDesignDaySchedule().setName("Baseline Model People Lights and Equipment Schedule Summer Design Day")
        sch.summerDesignDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 1)
        wd = sch.defaultDaySchedule()
        wd.setName("Baseline Model People Lights and Equipment Schedule Week Day")
        wd.addValue(openstudio.Time(0, 6, 0, 0), 0)
        wd.addValue(openstudio.Time(0, 7, 0, 0), 0.1)
        wd.addValue(openstudio.Time(0, 8, 0, 0), 0.2)
        wd.addValue(openstudio.Time(0, 12, 0, 0), 0.95)
        wd.addValue(openstudio.Time(0, 13, 0, 0), 0.5)
        wd.addValue(openstudio.Time(0, 17, 0, 0), 0.95)
        wd.addValue(openstudio.Time(0, 18, 0, 0), 0.7)
        wd.addValue(openstudio.Time(0, 20, 0, 0), 0.4)
        wd.addValue(openstudio.Time(0, 22, 0, 0), 0.1)
        wd.addValue(openstudio.Time(0, 24, 0, 0), 0.05)
        # Saturday
        sat_rule = openstudio.model.ScheduleRule(sch)
        sat_rule.setName("Baseline Model Saturday Rule")
        sat_rule.setApplySaturday(True)
        sat = sat_rule.daySchedule()
        sat.setName("Baseline Model People Lights and Equipment Schedule Saturday")
        sat.addValue(openstudio.Time(0, 6, 0, 0), 0)
        sat.addValue(openstudio.Time(0, 8, 0, 0), 0.1)
        sat.addValue(openstudio.Time(0, 14, 0, 0), 0.5)
        sat.addValue(openstudio.Time(0, 17, 0, 0), 0.1)
        sat.addValue(openstudio.Time(0, 24, 0, 0), 0)
        # Sunday
        sun_rule = openstudio.model.ScheduleRule(sch)
        sun_rule.setName("Baseline Model Sunday Rule")
        sun_rule.setApplySunday(True)
        sun = sun_rule.daySchedule()
        sun.setName("Baseline Model People Lights and Equipment Schedule Sunday")
        sun.addValue(openstudio.Time(0, 24, 0, 0), 0)
        default_sch_set.setNumberofPeopleSchedule(sch)
        default_sch_set.setLightingSchedule(sch)
        default_sch_set.setElectricEquipmentSchedule(sch)

        # Activity schedule (120W)
        act = openstudio.model.ScheduleRuleset(self)
        act.setName("Baseline Model People Activity Schedule")
        act.defaultDaySchedule().setName("Baseline Model People Activity Schedule Default")
        act.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 120)
        default_sch_set.setPeopleActivityLevelSchedule(act)

        # OA (20 cfm/person)
        oa = openstudio.model.DesignSpecificationOutdoorAir(self)
        oa.setName("Baseline Model OA")
        space_type.setDesignSpecificationOutdoorAir(oa)
        oa.setOutdoorAirMethod("Sum")
        oa.setOutdoorAirFlowperPerson(openstudio.convert(20, "ft^3/min*person", "m^3/s*person").get())

        # Infiltration (0.06 cfm/ft²)
        infil = openstudio.model.SpaceInfiltrationDesignFlowRate(self)
        infil.setName("Baseline Model Infiltration")
        infil.setSpaceType(space_type)
        infil.setFlowperExteriorSurfaceArea(openstudio.convert(0.06, "ft^3/min*ft^2", "m^3/s*m^2").get())

        # People (0.005 people/ft²)
        pdef = openstudio.model.PeopleDefinition(self)
        pdef.setName("Baseline Model People Definition")
        pdef.setPeopleperSpaceFloorArea(openstudio.convert(0.005, "people/ft^2", "people/m^2").get())
        people = openstudio.model.People(pdef)
        people.setName("Baseline Model People")
        people.setSpaceType(space_type)

        # Lights (1 W/ft²)
        ldef = openstudio.model.LightsDefinition(self)
        ldef.setName("Baseline Model Lights Definition")
        ldef.setWattsperSpaceFloorArea(openstudio.convert(1, "W/ft^2", "W/m^2").get())
        lights = openstudio.model.Lights(ldef)
        lights.setName("Baseline Model Lights")
        lights.setSpaceType(space_type)

        # Electric equipment (1 W/ft²)
        edef = openstudio.model.ElectricEquipmentDefinition(self)
        edef.setName("Baseline Model Electric Equipment Definition")
        edef.setWattsperSpaceFloorArea(openstudio.convert(1, "W/ft^2", "W/m^2").get())
        equip = openstudio.model.ElectricEquipment(edef)
        equip.setName("Baseline Model Electric Equipment")
        equip.setSpaceType(space_type)

        self.getBuilding().setSpaceType(space_type)

    def add_thermostats(self, heating_setpoint: float = 24.0, cooling_setpoint: float = 28.0):
        t24 = openstudio.Time(0, 24, 0, 0)
        clg = openstudio.model.ScheduleRuleset(self)
        clg.setName("Cooling Sch")
        clg.defaultDaySchedule().setName("Cooling Sch Default")
        clg.defaultDaySchedule().addValue(t24, cooling_setpoint)
        htg = openstudio.model.ScheduleRuleset(self)
        htg.setName("Heating Sch")
        htg.defaultDaySchedule().setName("Heating Sch Default")
        htg.defaultDaySchedule().addValue(t24, heating_setpoint)
        for zone in sorted(self.getThermalZones(), key=lambda z: z.nameString()):
            tstat = openstudio.model.ThermostatSetpointDualSetpoint(self)
            tstat.setHeatingSchedule(htg)
            tstat.setCoolingSchedule(clg)
            zone.setThermostatSetpointDualSetpoint(tstat)

    def add_hvac(self, ashrae_sys_num: str):
        """Add ASHRAE baseline HVAC using OpenStudio convenience methods."""
        valid = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10"]
        if ashrae_sys_num not in valid:
            raise ValueError(f"Invalid system: {ashrae_sys_num}. Valid: {valid}")

        zones = sorted(self.getThermalZones(), key=lambda z: z.nameString())
        sys_map = {
            "01": openstudio.model.addSystemType1,
            "02": openstudio.model.addSystemType2,
            "03": openstudio.model.addSystemType3,
            "04": openstudio.model.addSystemType4,
            "05": openstudio.model.addSystemType5,
            "06": openstudio.model.addSystemType6,
            "07": openstudio.model.addSystemType7,
            "08": openstudio.model.addSystemType8,
            "09": openstudio.model.addSystemType9,
            "10": openstudio.model.addSystemType10,
        }
        fn = sys_map[ashrae_sys_num]

        if ashrae_sys_num in ("01", "02"):
            fn(self, zones)
        elif ashrae_sys_num in ("03", "04", "09", "10"):
            for zone in zones:
                hvac = fn(self).to_AirLoopHVAC().get()
                hvac.addBranchForZone(zone)
                outlet = hvac.supplyOutletNode()
                for spm in outlet.setpointManagers():
                    szr = spm.to_SetpointManagerSingleZoneReheat()
                    if szr.is_initialized():
                        szr = szr.get()
                        szr.setControlZone(zone)
                        if ashrae_sys_num == "03":
                            szr.setMinimumSupplyAirTemperature(14)
                            szr.setMaximumSupplyAirTemperature(40)
                        break
        else:  # 05-08 multi-zone
            hvac = fn(self).to_AirLoopHVAC().get()
            for zone in zones:
                hvac.addBranchForZone(zone)

    def add_windows(self, wwr: float = 0.4, offset: float = 1.0, application_type: str = "Above Floor"):
        if wwr <= 0 or wwr >= 1:
            return
        above = application_type == "Above Floor"
        for s in self.getSurfaces():
            if s.outsideBoundaryCondition() != "Outdoors":
                continue
            result = s.setWindowToWallRatio(wwr, offset, above)
            if result.is_initialized():
                result.get().setName(f"{s.nameString()} Window")


# ---------------------------------------------------------------------------
# Public entry point for MCP tool
# ---------------------------------------------------------------------------

def create_baseline_model(
    name: str = "Baseline Model",
    num_floors: int = 2,
    floor_to_floor_height: float = 4.0,
    perimeter_zone_depth: float = 3.0,
    length: float = 100.0,
    width: float = 50.0,
    ashrae_sys_num: str | None = None,
    wwr: float | None = None,
) -> tuple[openstudio.model.Model, dict[str, Any]]:
    """Build a complete baseline model.

    Returns:
        (model, info) where info has building stats.
    """
    model = BaselineModel()
    model.getBuilding().setName(name)

    model.add_geometry(
        length=length,
        width=width,
        num_floors=num_floors,
        floor_to_floor_height=floor_to_floor_height,
        perimeter_zone_depth=perimeter_zone_depth,
    )
    model.set_constructions()
    model.set_space_type()
    model.add_thermostats()

    if ashrae_sys_num is not None:
        model.add_hvac(ashrae_sys_num)

    if wwr is not None and wwr > 0:
        model.add_windows(wwr=wwr)

    # Enable sizing calculations so autosized HVAC can run in EnergyPlus
    sim_control = model.getSimulationControl()
    sim_control.setDoZoneSizingCalculation(True)
    sim_control.setDoSystemSizingCalculation(True)
    sim_control.setDoPlantSizingCalculation(True)
    sim_control.setRunSimulationforSizingPeriods(True)
    sim_control.setRunSimulationforWeatherFileRunPeriods(True)

    num_spaces = len(list(model.getSpaces()))
    num_zones = len(list(model.getThermalZones()))
    num_surfaces = len(list(model.getSurfaces()))

    info = {
        "building_name": name,
        "num_floors": num_floors,
        "num_spaces": num_spaces,
        "num_zones": num_zones,
        "num_surfaces": num_surfaces,
        "has_hvac": ashrae_sys_num is not None,
        "has_windows": wwr is not None and wwr > 0,
    }

    return model, info
