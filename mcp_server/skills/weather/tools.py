"""MCP tool definitions for weather, design days, simulation control, and run periods."""
from __future__ import annotations

from mcp_server.skills.weather.operations import (
    add_design_day,
    get_run_period,
    get_simulation_control,
    get_weather_info,
    set_run_period,
    set_simulation_control,
    set_weather_file,
)


def register(mcp):
    @mcp.tool(name="get_weather_info")
    def get_weather_info_tool():
        """Get weather file info (city, lat/lon, elevation, EPW URL)."""
        return get_weather_info()

    @mcp.tool(name="set_weather_file")
    def set_weather_file_tool(epw_path: str):
        """Attach an EPW weather file to the loaded model (weather only).

        Does NOT add design days or set climate zone. Prefer
        change_building_location instead — it sets weather, design days,
        and climate zone in one step.

        Args:
            epw_path: Absolute path to an EPW file
        """
        return set_weather_file(epw_path=epw_path)

    @mcp.tool(name="add_design_day")
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
        """Add a sizing design day to the loaded model.

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

    @mcp.tool(name="get_simulation_control")
    def get_simulation_control_tool():
        """Get SimulationControl flags and timestep."""
        return get_simulation_control()

    @mcp.tool(name="set_simulation_control")
    def set_simulation_control_tool(
        do_zone_sizing: bool | None = None,
        do_system_sizing: bool | None = None,
        do_plant_sizing: bool | None = None,
        run_for_sizing_periods: bool | None = None,
        run_for_weather_file: bool | None = None,
        timesteps_per_hour: int | None = None,
    ):
        """Modify SimulationControl flags and/or Timestep on the loaded model.

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

    @mcp.tool(name="get_run_period")
    def get_run_period_tool():
        """Get RunPeriod begin/end dates."""
        return get_run_period()

    @mcp.tool(name="set_run_period")
    def set_run_period_tool(
        begin_month: int,
        begin_day: int,
        end_month: int,
        end_day: int,
        name: str | None = None,
    ):
        """Set or modify the RunPeriod on the loaded model.

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
