"""MCP tool definitions for common measures (openstudio-common-measures-gem)."""
from __future__ import annotations

from mcp_server.osm_helpers import parse_str_list
from mcp_server.skills.common_measures.operations import list_common_measures
from mcp_server.skills.common_measures.wrappers import (
    # Tier 2
    add_cost_per_floor_area_op,
    add_ev_load_op,
    add_pv_to_shading_op,
    add_rooftop_pv_op,
    add_zone_ventilation_op,
    adjust_thermostat_setpoints_op,
    change_building_location_op,
    clean_unused_objects_op,
    enable_ideal_air_loads_op,
    generate_results_report_op,
    inject_idf_op,
    replace_thermostat_schedules_op,
    replace_window_constructions_op,
    run_qaqc_checks_op,
    set_adiabatic_boundaries_op,
    set_lifecycle_cost_params_op,
    set_thermostat_schedules_op,
    shift_schedule_time_op,
    view_model_op,
    view_simulation_data_op,
)


def register(mcp):
    # --- Discovery tool ---

    @mcp.tool(name="list_common_measures")
    def list_common_measures_tool(category: str | None = None):
        """List available common measures bundled in the server.

        Args:
            category: Optional filter — "reporting", "thermostat", "envelope",
                      "location", "loads", "renewables", "schedule", "cost",
                      "cleanup", "idf", "visualization", "other", or omit for all

        Returns categorized list of ~79 measures. Use paths with
        list_measure_arguments and apply_measure for direct access.
        """
        return list_common_measures(category=category)

    # --- Tier 1 wrapper tools ---

    @mcp.tool(name="view_model")
    def view_model_tool(geometry_diagnostics: bool = False):
        """Generate 3D HTML viewer of model geometry.

        Args:
            geometry_diagnostics: Enable surface/space convexity checks (slower)
        """
        return view_model_op(geometry_diagnostics=geometry_diagnostics)

    @mcp.tool(name="view_simulation_data")
    def view_simulation_data_tool(
        run_id: str = "",
        variable_names: list[str] | str | None = None,
        reporting_frequency: str = "Timestep",
    ):
        """Generate 3D HTML viewer with simulation data overlaid.

        Args:
            run_id: Run ID from a completed simulation (required — provides SQL results)
            variable_names: Up to 3 EnergyPlus output variable names.
                Defaults to surface temperatures if omitted.
            reporting_frequency: "Timestep" or "Hourly"
        """
        return view_simulation_data_op(
            run_id=run_id or None,
            variable_names=parse_str_list(variable_names),
            reporting_frequency=reporting_frequency,
        )

    @mcp.tool(name="generate_results_report")
    def generate_results_report_tool(run_id: str = "", units: str = "IP"):
        """Generate comprehensive HTML report from simulation results (~25 sections).

        Args:
            run_id: Run ID from a completed simulation (required — provides SQL results)
            units: "IP" (imperial) or "SI" (metric)
        """
        return generate_results_report_op(run_id=run_id or None, units=units)

    @mcp.tool(name="run_qaqc_checks")
    def run_qaqc_checks_tool(
        run_id: str = "",
        template: str = "90.1-2013",
        checks: list[str] | str | None = None,
    ):
        """Run ASHRAE QA/QC checks on simulation results. Requires a completed
        simulation — call run_simulation first, then pass its run_id here.

        For pre-simulation model validation (no run_id needed), use
        inspect_osm_summary or get_model_summary instead.

        Args:
            run_id: Run ID from a completed simulation (required — provides SQL results)
            template: Target ASHRAE standard — "90.1-2013", "90.1-2016", "90.1-2019"
            checks: Which checks to enable. Defaults to all. Options:
                "part_load_eff", "capacity", "simultaneous_htg_clg",
                "internal_loads", "schedules", "envelope", "dhw",
                "mech_efficiency", "mech_type", "supply_air_temp"
        """
        if not run_id:
            return {
                "ok": False,
                "error": "run_id is required — run a simulation first, then pass its run_id here",
                "hint": "Call run_simulation() first, wait for completion, then call run_qaqc_checks(run_id=...). "
                        "For pre-simulation checks, use inspect_osm_summary or get_model_summary instead.",
            }
        return run_qaqc_checks_op(run_id=run_id, template=template, checks=parse_str_list(checks))

    @mcp.tool(name="adjust_thermostat_setpoints")
    def adjust_thermostat_setpoints_tool(
        cooling_offset_f: float = 0.0,
        heating_offset_f: float = 0.0,
        alter_design_days: bool = False,
    ):
        """Shift all thermostat setpoints by degree offsets. Clones schedules.

        Args:
            cooling_offset_f: Degrees F to raise cooling setpoint
            heating_offset_f: Degrees F to shift heating setpoint
            alter_design_days: Also shift design day schedules
        """
        return adjust_thermostat_setpoints_op(
            cooling_offset_f=cooling_offset_f,
            heating_offset_f=heating_offset_f,
            alter_design_days=alter_design_days,
        )

    @mcp.tool(name="replace_window_constructions")
    def replace_window_constructions_tool(
        construction_name: str = "",
        fixed_windows: bool = True,
        operable_windows: bool = True,
    ):
        """Replace all exterior window constructions with a named construction.

        Args:
            construction_name: Name of the window construction to apply
            fixed_windows: Replace fixed windows
            operable_windows: Replace operable windows
        """
        return replace_window_constructions_op(
            construction_name=construction_name,
            fixed_windows=fixed_windows,
            operable_windows=operable_windows,
        )

    @mcp.tool(name="enable_ideal_air_loads")
    def enable_ideal_air_loads_tool():
        """Enable ideal air loads on all zones. Disconnects existing HVAC."""
        return enable_ideal_air_loads_op()

    @mcp.tool(name="clean_unused_objects")
    def clean_unused_objects_tool(
        space_types: bool = True,
        load_defs: bool = True,
        schedules: bool = True,
        constructions: bool = True,
        curves: bool = True,
    ):
        """Remove orphan objects and unused resources.

        Args:
            space_types: Remove unused space types
            load_defs: Remove unused load definitions
            schedules: Remove unused schedules
            constructions: Remove unused constructions and materials
            curves: Remove unused performance curves
        """
        return clean_unused_objects_op(
            space_types=space_types,
            load_defs=load_defs,
            schedules=schedules,
            constructions=constructions,
            curves=curves,
        )

    @mcp.tool(name="inject_idf")
    def inject_idf_tool(idf_path: str = ""):
        """Inject raw IDF objects from file into model.

        Args:
            idf_path: Path to the IDF file containing objects to inject
        """
        return inject_idf_op(idf_path=idf_path)

    @mcp.tool(name="change_building_location")
    def change_building_location_tool(
        weather_file: str = "",
        climate_zone: str = "Lookup From Stat File",
    ):
        """Set weather file, design days, and ASHRAE climate zone in one step.

        This tool also:
        - Removes existing design days and loads correct ones from the DDY file
        - Sets the ASHRAE climate zone (auto-detected from .stat file or explicit)

        Design days are required for HVAC sizing. Use this tool whenever
        setting the location/weather for a building model.

        IMPORTANT: The EPW file must have companion .stat and .ddy files in
        the same directory with the same base filename. For example, if the
        EPW is "Boston.epw", then "Boston.stat" and "Boston.ddy" must also
        exist. The measure will fail if these are missing.

        Available EPW files with .stat/.ddy companions:
          /opt/comstock-measures/ChangeBuildingLocation/tests/
          Use list_files(directory="/opt/comstock-measures/ChangeBuildingLocation/tests",
          pattern="*.epw") to see available weather files.

        Args:
            weather_file: EPW weather file path (absolute path to .epw file).
                Must have companion .stat and .ddy files alongside it.
            climate_zone: ASHRAE climate zone or "Lookup From Stat File" for auto
        """
        return change_building_location_op(
            weather_file=weather_file,
            climate_zone=climate_zone,
        )

    # --- Tier 2 wrapper tools ---

    @mcp.tool(name="set_thermostat_schedules")
    def set_thermostat_schedules_tool(
        zone_name: str = "",
        cooling_schedule: str = "",
        heating_schedule: str = "",
    ):
        """Set thermostat heating/cooling schedules on a specific zone.

        Args:
            zone_name: Thermal zone name
            cooling_schedule: Name of cooling setpoint ScheduleRuleset
            heating_schedule: Name of heating setpoint ScheduleRuleset
        """
        return set_thermostat_schedules_op(
            zone_name=zone_name,
            cooling_schedule=cooling_schedule,
            heating_schedule=heating_schedule,
        )

    @mcp.tool(name="replace_thermostat_schedules")
    def replace_thermostat_schedules_tool(
        zone_name: str = "",
        cooling_schedule: str = "",
        heating_schedule: str = "",
    ):
        """Replace thermostat schedules on a zone (overwrites existing).

        Args:
            zone_name: Thermal zone name
            cooling_schedule: Name of cooling setpoint ScheduleRuleset
            heating_schedule: Name of heating setpoint ScheduleRuleset
        """
        return replace_thermostat_schedules_op(
            zone_name=zone_name,
            cooling_schedule=cooling_schedule,
            heating_schedule=heating_schedule,
        )

    @mcp.tool(name="shift_schedule_time")
    def shift_schedule_time_tool(
        schedule_name: str = "",
        shift_hours: float = 1.0,
    ):
        """Shift a schedule's profile times forward or backward.

        Args:
            schedule_name: Name of the ScheduleRuleset to shift
            shift_hours: Hours to shift (positive=forward, negative=backward, 24hr)
        """
        return shift_schedule_time_op(
            schedule_name=schedule_name,
            shift_hours=shift_hours,
        )

    @mcp.tool(name="add_rooftop_pv")
    def add_rooftop_pv_tool(
        fraction_of_surface: float = 0.75,
        cell_efficiency: float = 0.18,
        inverter_efficiency: float = 0.98,
    ):
        """Add rooftop PV panels as shading surfaces with photovoltaic generators.

        Args:
            fraction_of_surface: Fraction of roof area covered (0-1)
            cell_efficiency: PV cell efficiency (0-1, typical 0.15-0.22)
            inverter_efficiency: DC-to-AC inverter efficiency (0-1)
        """
        return add_rooftop_pv_op(
            fraction_of_surface=fraction_of_surface,
            cell_efficiency=cell_efficiency,
            inverter_efficiency=inverter_efficiency,
        )

    @mcp.tool(name="add_pv_to_shading")
    def add_pv_to_shading_tool(
        shading_type: str = "Building Shading",
        fraction: float = 0.5,
        cell_efficiency: float = 0.12,
    ):
        """Add simple PV generators to existing shading surfaces by type.

        Args:
            shading_type: "Building Shading", "Site Shading", or "Space Shading"
            fraction: Fraction of shading surface area with PV (0-1)
            cell_efficiency: PV cell efficiency (0-1)
        """
        return add_pv_to_shading_op(
            shading_type=shading_type,
            fraction=fraction,
            cell_efficiency=cell_efficiency,
        )

    @mcp.tool(name="add_ev_load")
    def add_ev_load_tool(
        delay_type: str = "Min Delay",
        charge_behavior: str = "Business as Usual",
        station_type: str = "Typical Public",
        ev_percent: float = 100.0,
        use_model_occupancy: bool = True,
    ):
        """Add electric vehicle charging load to the building.

        Args:
            delay_type: "Min Delay", "Max Delay", or "Midnight"
            charge_behavior: "Business as Usual" or "Free Workplace Charging at Scale"
            station_type: "Typical Public", "Typical Work", or "Typical Home"
            ev_percent: Percent of parked vehicles that are EVs (0-100)
            use_model_occupancy: Use model occupancy to determine EV count
        """
        return add_ev_load_op(
            delay_type=delay_type,
            charge_behavior=charge_behavior,
            station_type=station_type,
            ev_percent=ev_percent,
            use_model_occupancy=use_model_occupancy,
        )

    @mcp.tool(name="add_zone_ventilation")
    def add_zone_ventilation_tool(
        zone_name: str = "",
        design_flow_rate: float = 0.0,
        ventilation_type: str = "Natural",
        schedule_name: str = "",
    ):
        """Add a zone ventilation design flow rate object.

        Args:
            zone_name: Thermal zone name
            design_flow_rate: Design flow rate in m³/s
            ventilation_type: "Natural", "Exhaust", "Intake", or "Balanced"
            schedule_name: Optional schedule name (defaults to always-on)
        """
        return add_zone_ventilation_op(
            zone_name=zone_name,
            design_flow_rate=design_flow_rate,
            ventilation_type=ventilation_type,
            schedule_name=schedule_name,
        )

    @mcp.tool(name="set_lifecycle_cost_params")
    def set_lifecycle_cost_params_tool(
        study_period: int = 25,
    ):
        """Set lifecycle cost analysis study period length.

        Args:
            study_period: Analysis period in years (1-40)
        """
        return set_lifecycle_cost_params_op(study_period=study_period)

    @mcp.tool(name="add_cost_per_floor_area")
    def add_cost_per_floor_area_tool(
        material_cost: float = 0.0,
        om_cost: float = 0.0,
        expected_life: int = 20,
        lcc_name: str = "Building - Life Cycle Costs",
        remove_existing: bool = True,
    ):
        """Add lifecycle cost per floor area to the building.

        Args:
            material_cost: Material/installation cost per area ($/ft²)
            om_cost: Operations & maintenance cost per area ($/ft²)
            expected_life: Expected life in years
            lcc_name: Name for the LCC object
            remove_existing: Remove existing building-level LCC objects first
        """
        return add_cost_per_floor_area_op(
            material_cost=material_cost,
            om_cost=om_cost,
            expected_life=expected_life,
            lcc_name=lcc_name,
            remove_existing=remove_existing,
        )

    @mcp.tool(name="set_adiabatic_boundaries")
    def set_adiabatic_boundaries_tool(
        ext_roofs: bool = True,
        ext_floors: bool = True,
        ground_floors: bool = True,
        north_walls: bool = False,
        south_walls: bool = False,
        east_walls: bool = False,
        west_walls: bool = False,
    ):
        """Set exterior surfaces to adiabatic boundary condition.

        Args:
            ext_roofs: Make exterior roof surfaces adiabatic
            ext_floors: Make exterior exposed floor surfaces adiabatic
            ground_floors: Make ground-contact floor surfaces adiabatic
            north_walls: Make north-facing exterior walls adiabatic
            south_walls: Make south-facing exterior walls adiabatic
            east_walls: Make east-facing exterior walls adiabatic
            west_walls: Make west-facing exterior walls adiabatic
        """
        return set_adiabatic_boundaries_op(
            ext_roofs=ext_roofs,
            ext_floors=ext_floors,
            ground_floors=ground_floors,
            north_walls=north_walls,
            south_walls=south_walls,
            east_walls=east_walls,
            west_walls=west_walls,
        )
