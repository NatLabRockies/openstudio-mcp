"""Weather, design day, simulation control, and run period operations.

Set weather file, read weather info, add design days, configure simulation
control flags, timestep, and run periods on the in-memory model.
Complementary to OSW-level epw_path override in simulation/operations.py.
"""

from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.stdout_suppression import suppress_openstudio_warnings


def get_weather_info() -> dict[str, Any]:
    """Read weather file info from the in-memory model."""
    try:
        model = get_model()
        wf = model.getOptionalWeatherFile()
        if not wf.is_initialized():
            return {"ok": True, "weather_file": None}

        weather = wf.get()
        info: dict[str, Any] = {}

        # City
        if weather.city() != "":
            info["city"] = weather.city()
        # State/province
        if weather.stateProvinceRegion() != "":
            info["state_province"] = weather.stateProvinceRegion()
        # Country
        if weather.country() != "":
            info["country"] = weather.country()
        # Coordinates
        info["latitude"] = float(weather.latitude())
        info["longitude"] = float(weather.longitude())
        info["time_zone"] = float(weather.timeZone())
        info["elevation"] = float(weather.elevation())

        # URL (path to EPW)
        url = weather.url()
        if url and url.is_initialized():
            info["url"] = str(url.get())

        return {"ok": True, "weather_file": info}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get weather info: {e}"}


def set_weather_file(epw_path: str) -> dict[str, Any]:
    """Attach an EPW weather file to the in-memory model.

    Args:
        epw_path: Absolute path to an EPW file
    """
    try:
        model = get_model()

        # Parse EPW
        path_obj = openstudio.toPath(epw_path)
        epw = openstudio.EpwFile(path_obj)

        # Attach to model
        openstudio.model.WeatherFile.setWeatherFile(model, epw)

        # Read back to confirm
        return get_weather_info()

    except RuntimeError as e:
        err_str = str(e)
        if "No such file" in err_str or "Cannot" in err_str or "not" in err_str.lower():
            return {"ok": False, "error": f"EPW file not found: {epw_path}"}
        return {"ok": False, "error": err_str}
    except Exception as e:
        return {"ok": False, "error": f"Failed to set weather file: {e}"}


def add_design_day(
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
) -> dict[str, Any]:
    """Add a SizingPeriod:DesignDay to the model.

    Args:
        name: Design day name (e.g. "Chicago Winter 99%")
        day_type: "WinterDesignDay", "SummerDesignDay", etc.
        month: Month (1-12)
        day: Day of month (1-31)
        dry_bulb_max_c: Maximum dry-bulb temperature (°C)
        dry_bulb_range_c: Daily dry-bulb temperature range (°C)
        humidity_type: "WetBulb" or "DewPoint" (default: "WetBulb")
        humidity_value: Humidity indicator value (°C for WetBulb/DewPoint)
        wind_speed_ms: Wind speed in m/s (default: 0.0)
        barometric_pressure_pa: Barometric pressure in Pa (default: 101325)
    """
    try:
        model = get_model()

        with suppress_openstudio_warnings():
            dd = openstudio.model.DesignDay(model)
            dd.setName(name)
            dd.setDayType(day_type)
            dd.setMonth(month)
            dd.setDayOfMonth(day)
            dd.setMaximumDryBulbTemperature(dry_bulb_max_c)
            dd.setDailyDryBulbTemperatureRange(dry_bulb_range_c)

            # Humidity (use non-deprecated API: setHumidityConditionType, OS 3.3+)
            ht = humidity_type or "WetBulb"
            dd.setHumidityConditionType(ht)
            if humidity_value is not None:
                dd.setWetBulbOrDewPointAtMaximumDryBulb(humidity_value)

            # Wind
            if wind_speed_ms is not None:
                dd.setWindSpeed(wind_speed_ms)

            # Pressure
            if barometric_pressure_pa is not None:
                dd.setBarometricPressure(barometric_pressure_pa)

            # Read back
            result = {
                "name": dd.nameString(),
                "day_type": dd.dayType(),
                "month": dd.month(),
                "day_of_month": dd.dayOfMonth(),
                "max_dry_bulb_c": float(dd.maximumDryBulbTemperature()),
                "daily_dry_bulb_range_c": float(dd.dailyDryBulbTemperatureRange()),
                "humidity_type": dd.humidityConditionType(),
                "wind_speed_ms": float(dd.windSpeed()),
                "barometric_pressure_pa": float(dd.barometricPressure()),
            }

            # Count total design days
            total = len(model.getDesignDays())

        return {"ok": True, "design_day": result, "total_design_days": total}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add design day: {e}"}


# ---- Simulation control & timestep ----


def get_simulation_control() -> dict[str, Any]:
    """Read SimulationControl flags and Timestep from the in-memory model."""
    try:
        model = get_model()
        sc = model.getSimulationControl()
        ts = model.getTimestep()
        return {
            "ok": True,
            "simulation_control": {
                "do_zone_sizing": sc.doZoneSizingCalculation(),
                "do_system_sizing": sc.doSystemSizingCalculation(),
                "do_plant_sizing": sc.doPlantSizingCalculation(),
                "run_for_sizing_periods": sc.runSimulationforSizingPeriods(),
                "run_for_weather_file": sc.runSimulationforWeatherFileRunPeriods(),
                "timesteps_per_hour": ts.numberOfTimestepsPerHour(),
            },
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get simulation control: {e}"}


def set_simulation_control(
    do_zone_sizing: bool | None = None,
    do_system_sizing: bool | None = None,
    do_plant_sizing: bool | None = None,
    run_for_sizing_periods: bool | None = None,
    run_for_weather_file: bool | None = None,
    timesteps_per_hour: int | None = None,
) -> dict[str, Any]:
    """Modify SimulationControl flags and/or Timestep.

    All parameters are optional — only provided values are changed.
    """
    try:
        model = get_model()
        sc = model.getSimulationControl()
        ts = model.getTimestep()

        if do_zone_sizing is not None:
            sc.setDoZoneSizingCalculation(do_zone_sizing)
        if do_system_sizing is not None:
            sc.setDoSystemSizingCalculation(do_system_sizing)
        if do_plant_sizing is not None:
            sc.setDoPlantSizingCalculation(do_plant_sizing)
        if run_for_sizing_periods is not None:
            sc.setRunSimulationforSizingPeriods(run_for_sizing_periods)
        if run_for_weather_file is not None:
            sc.setRunSimulationforWeatherFileRunPeriods(run_for_weather_file)
        if timesteps_per_hour is not None:
            ts.setNumberOfTimestepsPerHour(timesteps_per_hour)

        # Read back
        return get_simulation_control()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to set simulation control: {e}"}


# ---- Run period ----


def get_run_period() -> dict[str, Any]:
    """Read the RunPeriod from the in-memory model."""
    try:
        model = get_model()
        rp = model.getRunPeriod()
        return {
            "ok": True,
            "run_period": {
                "name": rp.nameString(),
                "begin_month": rp.getBeginMonth(),
                "begin_day": rp.getBeginDayOfMonth(),
                "end_month": rp.getEndMonth(),
                "end_day": rp.getEndDayOfMonth(),
            },
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get run period: {e}"}


def set_run_period(
    begin_month: int,
    begin_day: int,
    end_month: int,
    end_day: int,
    name: str | None = None,
) -> dict[str, Any]:
    """Create or modify the RunPeriod on the in-memory model.

    Also sets runSimulationforWeatherFileRunPeriods(True) so the period
    is actually used during simulation.
    """
    try:
        model = get_model()
        rp = model.getRunPeriod()
        if name is not None:
            rp.setName(name)
        rp.setBeginMonth(begin_month)
        rp.setBeginDayOfMonth(begin_day)
        rp.setEndMonth(end_month)
        rp.setEndDayOfMonth(end_day)

        # Auto-enable weather file run periods so users don't forget
        sc = model.getSimulationControl()
        sc.setRunSimulationforWeatherFileRunPeriods(True)

        return get_run_period()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to set run period: {e}"}
