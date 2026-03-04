"""High-level wrappers for common measures (Tier 1 + Tier 2).

Each wrapper maps friendly Python kwargs to measure arguments, calls
apply_measure internally. This gives LLMs a consistent, typed interface
instead of raw apply_measure with guessable argument names.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp_server.skills.measures.operations import apply_measure


def _measure_path(measure_name: str) -> Path:
    """Resolve path to a bundled common measure."""
    base = Path(os.environ.get("COMMON_MEASURES_DIR", "/opt/common-measures"))
    return base / measure_name


def _run(
    measure_name: str,
    arguments: dict[str, str] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run a common measure with optional arguments."""
    path = _measure_path(measure_name)
    if not path.is_dir():
        return {"ok": False, "error": f"Measure not found: {path}"}
    return apply_measure(measure_dir=str(path), arguments=arguments, run_id=run_id)


# --- 1. view_model: 3D geometry viewer ---

def view_model_op(geometry_diagnostics: bool = False) -> dict[str, Any]:
    """Generate a Three.js HTML viewer of the current model geometry.

    The HTML file is written to /runs/ and can be opened in a browser.

    Args:
        geometry_diagnostics: Enable surface/space convexity checks (slower)
    """
    return _run("view_model", {
        "use_geometry_diagnostics": str(geometry_diagnostics).lower(),
    })


# --- 2. view_simulation_data: post-sim 3D data visualization ---

def view_simulation_data_op(
    variable_names: list[str] | None = None,
    reporting_frequency: str = "Timestep",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Generate a Three.js HTML viewer with simulation data overlaid on surfaces.

    Requires a completed simulation. The HTML file is written to /runs/.

    Args:
        variable_names: Up to 3 EnergyPlus output variable names to visualize.
            Defaults to surface temperatures if not specified.
        reporting_frequency: "Timestep", "Hourly", "Daily", "Monthly", "RunPeriod"
        run_id: Completed simulation run_id (provides SQL results)
    """
    defaults = [
        "Surface Inside Face Temperature",
        "Surface Outside Face Temperature",
        "Surface Inside Face Convection Heat Transfer Coefficient",
    ]
    vars_ = variable_names if variable_names else defaults
    if not vars_:
        return {"ok": False, "error": "variable_names must not be empty"}
    # Pad to 3 variables (measure expects exactly 3)
    while len(vars_) < 3:
        vars_.append(vars_[-1])
    # file_source is Choice: "Last OSM" or "Last IDF"
    # reporting_frequency is Choice: "Timestep" or "Hourly"
    freq = reporting_frequency if reporting_frequency in ("Timestep", "Hourly") else "Hourly"
    return _run("view_data", {
        "file_source": "Last OSM",
        "reporting_frequency": freq,
        "variable1_name": vars_[0],
        "variable2_name": vars_[1],
        "variable3_name": vars_[2],
        "use_geometry_diagnostics": "false",
    }, run_id=run_id)


# --- 3. generate_results_report: comprehensive HTML report ---

def generate_results_report_op(units: str = "IP", run_id: str | None = None) -> dict[str, Any]:
    """Generate a comprehensive HTML report from simulation results.

    Includes building summary, energy use, HVAC, envelope, zones, and more.
    Requires a completed simulation.

    Args:
        units: "IP" (imperial) or "SI" (metric)
        run_id: Completed simulation run_id (provides SQL results)
    """
    return _run("openstudio_results", {"units": units}, run_id=run_id)


# --- 4. run_qaqc_checks: ASHRAE QA/QC ---

def run_qaqc_checks_op(
    template: str = "90.1-2013",
    checks: list[str] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run ASHRAE baseline QA/QC checks on simulation results.

    Compares model against standard targets for efficiency, capacity,
    internal loads, envelope, schedules, and more.

    Args:
        template: Target ASHRAE standard — "90.1-2013", "90.1-2016", "90.1-2019"
        checks: Which checks to enable. Defaults to all. Options:
            "part_load_eff", "capacity", "simultaneous_htg_clg",
            "internal_loads", "schedules", "envelope", "dhw",
            "mech_efficiency", "mech_type", "supply_air_temp"
        run_id: Completed simulation run_id (provides SQL results)
    """
    all_checks = [
        "check_mech_sys_part_load_eff", "check_mech_sys_capacity",
        "check_simultaneous_heating_and_cooling", "check_internal_loads",
        "check_schedules", "check_envelope_conductance",
        "check_domestic_hot_water", "check_mech_sys_efficiency",
        "check_mech_sys_type", "check_supply_air_and_thermostat_temp_difference",
    ]
    # Map short names to full argument names
    short_to_full = {
        "part_load_eff": "check_mech_sys_part_load_eff",
        "capacity": "check_mech_sys_capacity",
        "simultaneous_htg_clg": "check_simultaneous_heating_and_cooling",
        "internal_loads": "check_internal_loads",
        "schedules": "check_schedules",
        "envelope": "check_envelope_conductance",
        "dhw": "check_domestic_hot_water",
        "mech_efficiency": "check_mech_sys_efficiency",
        "mech_type": "check_mech_sys_type",
        "supply_air_temp": "check_supply_air_and_thermostat_temp_difference",
    }
    args: dict[str, str] = {"template": template}
    if checks:
        valid_short = set(short_to_full.keys()) | set(all_checks)
        unknown = [c for c in checks if c not in valid_short]
        if unknown:
            return {"ok": False, "error": f"Unknown check names: {unknown}. Valid: {sorted(short_to_full.keys())}"}
        enabled = {short_to_full.get(c, c) for c in checks}
        for check_name in all_checks:
            args[check_name] = str(check_name in enabled).lower()
    else:
        for check_name in all_checks:
            args[check_name] = "true"
    return _run("generic_qaqc", args, run_id=run_id)


# --- 5. adjust_thermostat_setpoints ---

def adjust_thermostat_setpoints_op(
    cooling_offset_f: float = 0.0,
    heating_offset_f: float = 0.0,
    alter_design_days: bool = False,
) -> dict[str, Any]:
    """Shift all thermostat setpoints by specified degree offsets.

    Clones schedules so originals are not mutated.

    Args:
        cooling_offset_f: Degrees F to raise cooling setpoint (positive = warmer)
        heating_offset_f: Degrees F to lower heating setpoint (negative = cooler)
        alter_design_days: Also shift design day schedules
    """
    return _run("AdjustThermostatSetpointsByDegrees", {
        "cooling_adjustment": str(cooling_offset_f),
        "heating_adjustment": str(heating_offset_f),
        "alter_design_days": str(alter_design_days).lower(),
    })


# --- 6. replace_window_constructions ---

def replace_window_constructions_op(
    construction_name: str,
    fixed_windows: bool = True,
    operable_windows: bool = True,
) -> dict[str, Any]:
    """Replace all exterior window constructions with a named construction.

    The construction must already exist in the model.

    Args:
        construction_name: Name of the window construction to apply
        fixed_windows: Replace fixed windows
        operable_windows: Replace operable windows
    """
    return _run("ReplaceExteriorWindowConstruction", {
        "construction": construction_name,
        "change_fixed_windows": str(fixed_windows).lower(),
        "change_operable_windows": str(operable_windows).lower(),
    })


# --- 7. enable_ideal_air_loads ---

def enable_ideal_air_loads_op() -> dict[str, Any]:
    """Enable ideal air loads on all thermal zones.

    Disconnects existing HVAC but does not remove orphaned loops/equipment.
    Useful for quick sizing studies.
    """
    return _run("EnableIdealAirLoadsForAllZones")


# --- 8. clean_unused_objects ---

def clean_unused_objects_op(
    space_types: bool = True,
    load_defs: bool = True,
    schedules: bool = True,
    constructions: bool = True,
    curves: bool = True,
) -> dict[str, Any]:
    """Remove orphan objects and unused resources from the model.

    Purges in dependency order to avoid dangling references.

    Args:
        space_types: Remove unused space types
        load_defs: Remove unused load definitions
        schedules: Remove unused schedules
        constructions: Remove unused constructions and materials
        curves: Remove unused performance curves
    """
    return _run("remove_orphan_objects_and_unused_resources", {
        "remove_unused_space_types": str(space_types).lower(),
        "remove_unused_load_defs": str(load_defs).lower(),
        "remove_unused_schedules": str(schedules).lower(),
        "remove_unused_constructions": str(constructions).lower(),
        "remove_unused_curves": str(curves).lower(),
    })


# --- 9. inject_idf ---

def inject_idf_op(idf_path: str) -> dict[str, Any]:
    """Inject raw IDF objects from an external file into the model.

    Objects are added to the EnergyPlus workspace before simulation.
    Best for adding new objects; modifying forward-translated objects
    may cause conflicts.

    Args:
        idf_path: Path to the IDF file containing objects to inject
    """
    return _run("inject_idf_objects", {
        "source_idf_path": idf_path,
    })


# --- 10. change_building_location ---

def change_building_location_op(
    weather_file: str,
    climate_zone: str = "Lookup From Stat File",
) -> dict[str, Any]:
    """Change building location by setting weather file and climate zone.

    Also looks up the .stat file for design day data if available.

    Args:
        weather_file: EPW weather file name (must be accessible in file_paths)
        climate_zone: ASHRAE climate zone or "Lookup From Stat File" for auto-detect
    """
    return _run("ChangeBuildingLocation", {
        "weather_file_name": weather_file,
        "climate_zone": climate_zone,
    })


# ===================================================================
# Tier 2 wrappers
# ===================================================================


def _resolve_handle(name: str) -> str:
    """Resolve a model object name to its OpenStudio handle string.

    Measure Choice arguments reference objects by handle (UUID).
    This helper looks up the in-memory model object by name and
    returns its handle. Falls back to returning the name if not found.
    """
    from mcp_server.model_manager import get_model
    from mcp_server.stdout_suppression import suppress_openstudio_warnings
    with suppress_openstudio_warnings():
        model = get_model()
        obj = model.getModelObjectByName(name)
        if obj.is_initialized():
            return str(obj.get().handle())
    return name


# --- 11. set_thermostat_schedules ---

def set_thermostat_schedules_op(
    zone_name: str,
    cooling_schedule: str = "",
    heating_schedule: str = "",
) -> dict[str, Any]:
    """Set thermostat heating/cooling schedules on a specific zone.

    Args:
        zone_name: Thermal zone name
        cooling_schedule: Name of cooling setpoint ScheduleRuleset
        heating_schedule: Name of heating setpoint ScheduleRuleset
    """
    args: dict[str, str] = {"zones": _resolve_handle(zone_name)}
    if cooling_schedule:
        args["cooling_sch"] = _resolve_handle(cooling_schedule)
    if heating_schedule:
        args["heating_sch"] = _resolve_handle(heating_schedule)
    return _run("SetThermostatSchedules", args)


# --- 12. replace_thermostat_schedules ---

def replace_thermostat_schedules_op(
    zone_name: str,
    cooling_schedule: str = "",
    heating_schedule: str = "",
) -> dict[str, Any]:
    """Replace thermostat schedules on a zone (overwrites existing).

    Unlike set_thermostat_schedules which adds, this replaces existing
    thermostat schedule assignments.

    Args:
        zone_name: Thermal zone name
        cooling_schedule: Name of cooling setpoint ScheduleRuleset
        heating_schedule: Name of heating setpoint ScheduleRuleset
    """
    args: dict[str, str] = {"zones": _resolve_handle(zone_name)}
    if cooling_schedule:
        args["cooling_sch"] = _resolve_handle(cooling_schedule)
    if heating_schedule:
        args["heating_sch"] = _resolve_handle(heating_schedule)
    return _run("ReplaceThermostatSchedules", args)


# --- 13. shift_schedule_time ---

def shift_schedule_time_op(
    schedule_name: str,
    shift_hours: float = 1.0,
) -> dict[str, Any]:
    """Shift a schedule's profile times forward or backward.

    Args:
        schedule_name: Name of the ScheduleRuleset to shift
        shift_hours: Hours to shift forward (use negative for backward, 24hr clock)
    """
    return _run("ShiftScheduleProfileTime", {
        "schedule": _resolve_handle(schedule_name),
        "shift_value": str(shift_hours),
    })


# --- 14. add_rooftop_pv ---

def add_rooftop_pv_op(
    fraction_of_surface: float = 0.75,
    cell_efficiency: float = 0.18,
    inverter_efficiency: float = 0.98,
) -> dict[str, Any]:
    """Add rooftop PV panels as shading surfaces with photovoltaic generators.

    Creates roof-level shading surfaces and attaches PV generators.

    Args:
        fraction_of_surface: Fraction of roof area covered (0-1)
        cell_efficiency: PV cell efficiency (0-1, typical 0.15-0.22)
        inverter_efficiency: DC-to-AC inverter efficiency (0-1)
    """
    return _run("add_rooftop_pv", {
        "fraction_of_surface": str(fraction_of_surface),
        "cell_efficiency": str(cell_efficiency),
        "inverter_efficiency": str(inverter_efficiency),
    })


# --- 15. add_pv_to_shading ---

def add_pv_to_shading_op(
    shading_type: str = "Building Shading",
    fraction: float = 0.5,
    cell_efficiency: float = 0.12,
) -> dict[str, Any]:
    """Add simple PV generators to existing shading surfaces by type.

    Args:
        shading_type: "Building Shading", "Site Shading", or "Space Shading"
        fraction: Fraction of shading surface area with PV (0-1)
        cell_efficiency: PV cell efficiency (0-1)
    """
    return _run("AddSimplePvToShadingSurfacesByType", {
        "shading_type": shading_type,
        "fraction_surfacearea_with_pv": str(fraction),
        "value_for_cell_efficiency": str(cell_efficiency),
    })


# --- 16. add_ev_load ---

def add_ev_load_op(
    delay_type: str = "Min Delay",
    charge_behavior: str = "Business as Usual",
    station_type: str = "Typical Public",
    ev_percent: float = 100.0,
    use_model_occupancy: bool = True,
) -> dict[str, Any]:
    """Add electric vehicle charging load to the building.

    Args:
        delay_type: "Min Delay", "Max Delay", or "Midnight"
        charge_behavior: "Business as Usual" or "Free Workplace Charging at Scale"
        station_type: "Typical Public", "Typical Work", or "Typical Home"
        ev_percent: Percent of parked vehicles that are EVs (0-100)
        use_model_occupancy: Use model occupancy to determine EV count
    """
    return _run("add_ev_load", {
        "delay_type": delay_type,
        "charge_behavior": charge_behavior,
        "chg_station_type": station_type,
        "ev_percent": str(ev_percent),
        "ev_use_model_occupancy": str(use_model_occupancy).lower(),
    })


# --- 17. add_zone_ventilation ---

def add_zone_ventilation_op(
    zone_name: str,
    design_flow_rate: float,
    ventilation_type: str = "Natural",
    schedule_name: str = "",
) -> dict[str, Any]:
    """Add a zone ventilation design flow rate object.

    Args:
        zone_name: Thermal zone name
        design_flow_rate: Design flow rate in m³/s
        ventilation_type: "Natural", "Exhaust", "Intake", or "Balanced"
        schedule_name: Optional schedule name (defaults to always-on)
    """
    args: dict[str, str] = {
        "zone": _resolve_handle(zone_name),
        "vent_type": ventilation_type,
        "design_flow_rate": str(design_flow_rate),
    }
    if schedule_name:
        args["vent_sch"] = _resolve_handle(schedule_name)
    return _run("add_zone_ventilation_design_flow_rate_object", args)


# --- 18. set_lifecycle_cost_params ---

def set_lifecycle_cost_params_op(
    study_period: int = 25,
) -> dict[str, Any]:
    """Set lifecycle cost analysis study period length.

    Args:
        study_period: Analysis period in years (1-40)
    """
    return _run("SetLifecycleCostParameters", {
        "study_period": str(study_period),
    })


# --- 19. add_cost_per_floor_area ---

def add_cost_per_floor_area_op(
    material_cost: float = 0.0,
    om_cost: float = 0.0,
    expected_life: int = 20,
    lcc_name: str = "Building - Life Cycle Costs",
    remove_existing: bool = True,
) -> dict[str, Any]:
    """Add lifecycle cost per floor area to the building.

    Args:
        material_cost: Material/installation cost per area ($/ft²)
        om_cost: Operations & maintenance cost per area ($/ft²)
        expected_life: Expected life in years
        lcc_name: Name for the LCC object
        remove_existing: Remove existing building-level LCC objects first
    """
    return _run("AddCostPerFloorAreaToBuilding", {
        "material_cost_ip": str(material_cost),
        "om_cost_ip": str(om_cost),
        "expected_life": str(expected_life),
        "lcc_name": lcc_name,
        "remove_costs": str(remove_existing).lower(),
    })


# --- 20. set_adiabatic_boundaries ---

def set_adiabatic_boundaries_op(
    ext_roofs: bool = True,
    ext_floors: bool = True,
    ground_floors: bool = True,
    north_walls: bool = False,
    south_walls: bool = False,
    east_walls: bool = False,
    west_walls: bool = False,
) -> dict[str, Any]:
    """Set exterior surfaces to adiabatic boundary condition.

    Useful for isolating zones for load studies or core-only analysis.

    Args:
        ext_roofs: Make exterior roof surfaces adiabatic
        ext_floors: Make exterior exposed floor surfaces adiabatic
        ground_floors: Make ground-contact floor surfaces adiabatic
        north_walls: Make north-facing exterior walls adiabatic
        south_walls: Make south-facing exterior walls adiabatic
        east_walls: Make east-facing exterior walls adiabatic
        west_walls: Make west-facing exterior walls adiabatic
    """
    return _run("set_exterior_walls_and_floors_to_adiabatic", {
        "ext_roofs": str(ext_roofs).lower(),
        "ext_floors": str(ext_floors).lower(),
        "ground_floors": str(ground_floors).lower(),
        "north_walls": str(north_walls).lower(),
        "south_walls": str(south_walls).lower(),
        "east_walls": str(east_walls).lower(),
        "west_walls": str(west_walls).lower(),
    })
