"""Weather, design day, simulation control, and run period operations.

Set weather file, read weather info, add design days, configure simulation
control flags, timestep, and run periods on the in-memory model.
Complementary to OSW-level epw_path override in simulation/operations.py.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.config import COMSTOCK_MEASURES_DIR, INPUT_ROOT, OSCLI_GEM_PATH
from mcp_server.model_manager import get_model


def _parse_climate_zone_from_stat(stat_path: Path) -> str | None:
    """Extract ASHRAE climate zone from a .stat file (e.g. "5A", "2B").

    Looks for line like:
      - Climate type "5A" (ASHRAE Standard 196-2006 Climate Zone)**
    """
    try:
        text = stat_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'Climate type "([^"]+)" \(ASHRAE Standards?', text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _estimate_climate_zone_from_epw(epw_path: Path) -> str | None:
    """Estimate ASHRAE 169 climate zone number from EPW hourly dry-bulb temps.

    Computes HDD18°C and CDD10°C from the 8760 hourly values (column 6)
    and applies the ASHRAE 169 threshold table. Returns the numeric zone
    only (no A/B/C moisture suffix — that requires precipitation data).
    """
    try:
        import csv

        temps: list[float] = []
        with open(epw_path, encoding="utf-8", errors="replace") as f:
            # Skip 8 header lines
            for _ in range(8):
                next(f)
            reader = csv.reader(f)
            for row in reader:
                if len(row) > 6:
                    temps.append(float(row[6]))

        if len(temps) < 8760:
            return None

        hdd18 = sum(max(18.0 - t, 0.0) for t in temps) / 24.0
        cdd10 = sum(max(t - 10.0, 0.0) for t in temps) / 24.0

        if cdd10 > 5000:
            return "1"
        if cdd10 > 3500:
            return "2"
        if cdd10 > 2500:
            return "3"
        if hdd18 <= 2000:
            return "3"  # 3C (marine)
        if hdd18 <= 3000:
            return "4"
        if hdd18 <= 4000:
            return "5"
        if hdd18 <= 5000:
            return "6"
        if hdd18 <= 7000:
            return "7"
        return "8"
    except Exception:
        return None


def list_weather_files() -> dict[str, Any]:
    """Discover available EPW weather files with companion file info.

    Scans openstudio-standards gem weather data dir and /inputs for EPW files.
    Returns path, name, and whether .ddy/.stat companions exist.
    """
    try:
        weather_files: list[dict[str, Any]] = []
        sources: list[str] = []

        # 1. openstudio-standards gem weather dir (version-proof glob)
        gem_root = Path(OSCLI_GEM_PATH)
        weather_dirs = list(gem_root.glob("ruby/*/gems/openstudio-standards-*/data/weather"))
        for wd in weather_dirs:
            if wd.is_dir():
                sources.append(str(wd))
                for epw in sorted(wd.glob("*.epw")):
                    base = epw.with_suffix("")
                    weather_files.append({
                        "name": epw.name,
                        "path": str(epw),
                        "has_ddy": base.with_suffix(".ddy").exists(),
                        "has_stat": base.with_suffix(".stat").exists(),
                    })

        # 2. ChangeBuildingLocation measure test EPWs
        cbl_tests = COMSTOCK_MEASURES_DIR / "ChangeBuildingLocation" / "tests"
        if cbl_tests.is_dir():
            sources.append(str(cbl_tests))
            for epw in sorted(cbl_tests.glob("*.epw")):
                base = epw.with_suffix("")
                weather_files.append({
                    "name": epw.name,
                    "path": str(epw),
                    "has_ddy": base.with_suffix(".ddy").exists(),
                    "has_stat": base.with_suffix(".stat").exists(),
                })

        # 3. /inputs directory
        if INPUT_ROOT.exists():
            input_epws = sorted(INPUT_ROOT.rglob("*.epw"))
            if input_epws:
                sources.append(str(INPUT_ROOT))
                for epw in input_epws:
                    base = epw.with_suffix("")
                    weather_files.append({
                        "name": epw.name,
                        "path": str(epw),
                        "has_ddy": base.with_suffix(".ddy").exists(),
                        "has_stat": base.with_suffix(".stat").exists(),
                    })

        return {
            "ok": True,
            "count": len(weather_files),
            "weather_files": weather_files,
            "sources": sources,
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to list weather files: {e}"}


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
        # H-19: validate inputs
        _VALID_DAY_TYPES = {"SummerDesignDay", "WinterDesignDay", "Sunday", "Monday", "Tuesday",
                            "Wednesday", "Thursday", "Friday", "Saturday", "Holiday",
                            "CustomDay1", "CustomDay2"}
        if day_type not in _VALID_DAY_TYPES:
            valid_str = ", ".join(sorted(_VALID_DAY_TYPES))
            return {"ok": False, "error": f"Invalid day_type '{day_type}'. Valid: {valid_str}"}
        if not (1 <= month <= 12):
            return {"ok": False, "error": f"month must be 1-12, got {month}"}
        if not (1 <= day <= 31):
            return {"ok": False, "error": f"day must be 1-31, got {day}"}
        if humidity_type is not None and humidity_type not in ("WetBulb", "DewPoint"):
            return {"ok": False, "error": f"humidity_type must be 'WetBulb' or 'DewPoint', got '{humidity_type}'"}

        model = get_model()

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
        # H-20: validate timesteps_per_hour
        _VALID_TIMESTEPS = {1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60}
        if timesteps_per_hour is not None and timesteps_per_hour not in _VALID_TIMESTEPS:
            return {"ok": False,
                    "error": f"timesteps_per_hour must be in {sorted(_VALID_TIMESTEPS)}, got {timesteps_per_hour}"}

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
        # H-20: validate month/day ranges
        for label, val in [("begin_month", begin_month), ("end_month", end_month)]:
            if not (1 <= val <= 12):
                return {"ok": False, "error": f"{label} must be 1-12, got {val}"}
        for label, val in [("begin_day", begin_day), ("end_day", end_day)]:
            if not (1 <= val <= 31):
                return {"ok": False, "error": f"{label} must be 1-31, got {val}"}

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
