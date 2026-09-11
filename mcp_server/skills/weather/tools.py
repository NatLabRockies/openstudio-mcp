"""MCP tool definitions for weather, design days, simulation control, and run periods."""
from __future__ import annotations

from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures
from mcp_server.skills.weather.operations import (
    add_design_day,
    get_run_period,
    get_simulation_control,
    get_weather_info,
    list_weather_files,
    set_run_period,
    set_simulation_control,
)


def register(mcp):
    @mcp.tool(tags={"core", "simulation"}, name="list_weather_files")
    def list_weather_files_tool():
        """List available EPW weather files with companion .stat and .ddy files for simulation.

        Use returned path with change_building_location.
        Returns name, path, and whether .ddy/.stat companion files exist.
        """
        return list_weather_files()

    @mcp.tool(tags={"simulation"}, name="set_ground_temperatures")
    def set_ground_temperatures_tool(
        epw_path: str | None = None,
        building_surface_method: str = "setpoint_offset",
        building_surface_constant_c: float | None = None,
        overwrite: bool = False,
    ):
        """Apply an EPW weather file's ground temperatures to the model's Site:GroundTemperature objects.

        A gbXML-translated model has no ground temperatures, so EnergyPlus uses its own
        defaults (18 C every month on Ground-boundary surfaces). This reads the EPW header's
        GROUND TEMPERATURES record and writes Shallow, Deep and FCfactorMethod from the
        nearest available depths (0.5 m and 4.0 m), reporting the depth actually used.

        BuildingSurface is treated differently on purpose. EPW ground temperatures are
        UNDISTURBED soil — an open field, no building — and the EPW's own .stat file says
        they "should NOT BE USED in the GroundTemperatures object to compute building floor
        losses". Boston's January value is -0.29 C; writing that to BuildingSurface overstates
        slab heat loss badly. So BuildingSurface gets a value derived from the model's own
        heating setpoints instead, unless you ask otherwise.

        Be aware which objects actually matter for your model: BuildingSurface drives the
        floor heat balance; Shallow and Deep feed ground heat exchangers and are inert without
        one; FCfactorMethod affects only F/C-factor constructions. For real slab-edge heat
        transfer, use Kiva instead (the Foundation boundary condition).

        Changes the in-memory model — call save_osm_model to persist.

        Args:
            epw_path: EPW to read. Defaults to the EPW import_gbxml used for this model, then
                to the model's own weather file.
            building_surface_method: "setpoint_offset" (default) writes mean heating setpoint
                minus 2 C, and writes nothing if the model has no thermostats; "epw_raw"
                writes the undisturbed 0.5 m values and warns; "constant" writes
                building_surface_constant_c; "none" leaves the object alone.
            building_surface_constant_c: Required by building_surface_method="constant".
            overwrite: Replace objects that already carry chosen values. Default False skips
                them and says so.

        Returns:
            applied, skipped, warnings, epw_path, epw_source, depth_sets_available,
            building_surface_method, ground_temperatures
        """
        return set_ground_temperatures(
            epw_path=epw_path,
            building_surface_method=building_surface_method,
            building_surface_constant_c=building_surface_constant_c,
            overwrite=overwrite,
        )

    @mcp.tool(tags={"simulation"}, name="get_weather_info")
    def get_weather_info_tool():
        """Get weather file info: city, state, latitude, longitude, timezone, elevation, EPW path."""
        return get_weather_info()

    @mcp.tool(tags={"simulation"}, name="add_design_day")
    def add_design_day_tool(
        name: str,
        day_type: str,
        month: int,
        day: int,
        dry_bulb_max_c: float,
        dry_bulb_range_c: float,
        humidity_type: str | None = None,
        humidity_value: float | None = None,
        wind_speed_ms: float | None = None,
        barometric_pressure_pa: float | None = None,
    ):
        """Add a heating or cooling sizing design day with temperature, humidity, and wind.

        Args:
            name: Design day name (e.g. "Chicago Winter 99%")
            day_type: "WinterDesignDay" or "SummerDesignDay"
            month: Month (1-12)
            day: Day of month (1-31)
            dry_bulb_max_c: Maximum dry-bulb temperature in °C
            dry_bulb_range_c: Daily dry-bulb temperature range in °C
            humidity_type: "WetBulb" or "DewPoint" (default: "WetBulb")
            humidity_value: Humidity indicator value in °C
            wind_speed_ms: Wind speed in m/s
            barometric_pressure_pa: Barometric pressure in Pa

        """
        return add_design_day(
            name=name, day_type=day_type, month=month, day=day,
            dry_bulb_max_c=dry_bulb_max_c, dry_bulb_range_c=dry_bulb_range_c,
            humidity_type=humidity_type, humidity_value=humidity_value,
            wind_speed_ms=wind_speed_ms, barometric_pressure_pa=barometric_pressure_pa,
        )

    @mcp.tool(tags={"simulation"}, name="get_simulation_control")
    def get_simulation_control_tool():
        """Get SimulationControl: zone/system sizing, run for sizing/weather periods, timestep."""
        return get_simulation_control()

    @mcp.tool(tags={"simulation"}, name="set_simulation_control")
    def set_simulation_control_tool(
        do_zone_sizing: bool | None = None,
        do_system_sizing: bool | None = None,
        do_plant_sizing: bool | None = None,
        run_for_sizing_periods: bool | None = None,
        run_for_weather_file: bool | None = None,
        timesteps_per_hour: int | None = None,
    ):
        """Enable/disable sizing calculations, set timesteps per hour on the loaded model.

        Args:
            do_zone_sizing: Enable zone sizing calculations
            do_system_sizing: Enable system sizing calculations
            do_plant_sizing: Enable plant sizing calculations
            run_for_sizing_periods: Run simulation for sizing periods
            run_for_weather_file: Run simulation for weather file run periods
            timesteps_per_hour: Number of timesteps per hour (1,2,3,4,5,6,10,12,15,20,30,60)

        """
        return set_simulation_control(
            do_zone_sizing=do_zone_sizing,
            do_system_sizing=do_system_sizing,
            do_plant_sizing=do_plant_sizing,
            run_for_sizing_periods=run_for_sizing_periods,
            run_for_weather_file=run_for_weather_file,
            timesteps_per_hour=timesteps_per_hour,
        )

    @mcp.tool(tags={"simulation"}, name="get_run_period")
    def get_run_period_tool():
        """Get RunPeriod simulation start and end dates (month/day)."""
        return get_run_period()

    @mcp.tool(tags={"simulation"}, name="set_run_period")
    def set_run_period_tool(
        begin_month: int,
        begin_day: int,
        end_month: int,
        end_day: int,
        name: str | None = None,
    ):
        """Set annual or partial-year simulation start/end dates on the loaded model.

        Args:
            begin_month: Start month (1-12)
            begin_day: Start day of month (1-31)
            end_month: End month (1-12)
            end_day: End day of month (1-31)
            name: Optional run period name

        """
        return set_run_period(
            begin_month=begin_month, begin_day=begin_day,
            end_month=end_month, end_day=end_day, name=name,
        )
