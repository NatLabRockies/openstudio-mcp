"""Tests for set_ground_temperatures / read_ground_temperature_state — requires OpenStudio (Docker).

Driven in-process, like tests/test_ground_contact.py, because the assertions turn on SDK
behaviour (which unique objects exist, which months are defaulted) that no MCP response
exposes directly, and because building the model here makes every asserted value exact.

SDK facts (dev/probes/probe_ground_temperatures.py, OpenStudio 3.11.0):
  - The plain Model.get<Class>() getter CREATES the unique object; getOptional<Class>() does
    not. A read path must use the optional form or a "get" tool mutates the session model.
  - All four classes share setAllMonthlyTemperatures(list_of_12) -> bool,
    getTemperatureByMonth(1..12), isMonthDefaulted(1..12), resetAllMonths(), even though their
    per-month named accessors differ (setJanuaryGroundTemperature vs
    setJanuarySurfaceGroundTemperature vs setJanuaryDeepGroundTemperature).
  - IDD defaults differ: BuildingSurface 18.0, FCfactorMethod 13.0, Shallow 13.0, Deep 16.0.
  - Setting one month leaves the rest defaulted, so a "partial" state is reachable.

Boston TMY3 ground temperatures (tests/assets/USA_MA_Boston-Logan...epw line 4), which every
expected value below traces to:
    0.5 m  Jan -0.29  Dec  3.79
    4.0 m  Jan  6.88  Dec  9.84
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_OPENSTUDIO_INTEGRATION"),
        reason="requires OpenStudio (set RUN_OPENSTUDIO_INTEGRATION=1)",
    ),
]

BOSTON_EPW = "/repo/tests/assets/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
AUSTIN_EPW = "/repo/tests/assets/USA_TX_Austin-Camp.Mabry.ANGB.722544_TMYx.2009-2023.epw"

BOSTON_SHALLOW_JAN = -0.29
BOSTON_SHALLOW_DEC = 3.79
BOSTON_DEEP_JAN = 6.88
BOSTON_DEEP_DEC = 9.84


@pytest.fixture(autouse=True)
def _clear_model():
    from mcp_server.model_manager import clear_model
    clear_model()
    yield
    clear_model()


def _allowed_dir() -> Path:
    """A writable directory the path allowlist accepts — pytest's tmp_path (/tmp) is not."""
    from mcp_server.config import user_run_root

    d = user_run_root() / "pytest_ground_temps" / uuid4().hex[:10]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_empty_model() -> None:
    import openstudio

    from mcp_server.model_manager import load_model

    osm_path = _allowed_dir() / "empty.osm"
    openstudio.model.Model().save(openstudio.toPath(str(osm_path)), True)
    load_model(osm_path)


def _load_model_with_thermostats(setpoints_c=(21.1, 21.1), setback_c: float | None = 15.6) -> None:
    """A model whose zones carry dual-setpoint thermostats on ScheduleRulesets."""
    import openstudio

    from mcp_server.model_manager import load_model

    model = openstudio.model.Model()
    for index, setpoint in enumerate(setpoints_c):
        zone = openstudio.model.ThermalZone(model)
        zone.setName(f"Zone {index + 1}")
        schedule = openstudio.model.ScheduleRuleset(model)
        schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), setpoint)
        if setback_c is not None:
            setback_day = openstudio.model.ScheduleDay(model)
            setback_day.addValue(openstudio.Time(0, 24, 0, 0), setback_c)
            openstudio.model.ScheduleRule(schedule, setback_day).setApplySaturday(True)
        thermostat = openstudio.model.ThermostatSetpointDualSetpoint(model)
        thermostat.setHeatingSetpointTemperatureSchedule(schedule)
        zone.setThermostatSetpointDualSetpoint(thermostat)

    osm_path = _allowed_dir() / "thermostats.osm"
    model.save(openstudio.toPath(str(osm_path)), True)
    load_model(osm_path)


def _months(key: str) -> list[float]:
    from mcp_server.model_manager import get_model
    from mcp_server.skills.weather.ground_temperatures import read_ground_temperature_state

    return read_ground_temperature_state(get_model())[key]["monthly_c"]


# --------------------------------------------------------------------------- applying values


def test_applies_boston_epw_values_at_the_right_depths():
    # Validates: the 0.5 m / 4.0 m split the EPW's own .stat calls for. Deep must carry the
    # 4 m values, not the 0.5 m ones — getting the depths backwards is the easiest mistake
    # here and produces a plausible-looking but wrong model.
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures(epw_path=BOSTON_EPW, building_surface_method="none")

    assert result["ok"] is True, result
    assert result["depth_sets_available"] == [0.5, 2.0, 4.0]
    assert result["epw_source"] == "argument"

    shallow = _months("shallow")
    deep = _months("deep")
    fcfactor = _months("fcfactor_method")

    assert shallow[0] == BOSTON_SHALLOW_JAN
    assert shallow[11] == BOSTON_SHALLOW_DEC
    assert deep[0] == BOSTON_DEEP_JAN
    assert deep[11] == BOSTON_DEEP_DEC
    assert fcfactor[0] == BOSTON_SHALLOW_JAN
    assert deep[0] != shallow[0]

    applied = result["applied"]
    assert applied["Site:GroundTemperature:Shallow"]["depth_m"] == 0.5
    assert applied["Site:GroundTemperature:Deep"]["depth_m"] == 4.0
    assert applied["Site:GroundTemperature:Deep"]["depth_delta_m"] == 0.0


def test_austin_values_differ_from_boston():
    # Validates: the tool reads the EPW it was given, not a cached or hardcoded table
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    assert set_ground_temperatures(epw_path=AUSTIN_EPW, building_surface_method="none")["ok"]

    assert _months("shallow")[0] == 13.34
    assert _months("deep")[0] == 18.56


def test_building_surface_uses_the_occupied_setpoint_minus_two():
    # Validates: setpoint_offset takes the occupied 21.1, not the 15.6 setback and not their
    # mean — so BuildingSurface lands at 19.1 for all 12 months
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_model_with_thermostats(setpoints_c=(21.1, 21.1), setback_c=15.6)
    result = set_ground_temperatures(epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    detail = result["applied"]["Site:GroundTemperature:BuildingSurface"]
    assert detail["source"] == "setpoint_offset"
    assert detail["mean_heating_setpoint_c"] == 21.1
    assert detail["offset_c"] == 2.0
    assert _months("building_surface") == [19.1] * 12
    # And it is emphatically not the undisturbed soil profile.
    assert _months("building_surface")[0] != BOSTON_SHALLOW_JAN


def test_building_surface_skipped_when_the_model_has_no_thermostats():
    # Regression: a gbXML import may arrive without thermostats. The other three objects must
    # still be written and ok must stay True — a skipped BuildingSurface is a reported
    # outcome, not a failure.
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures(epw_path=BOSTON_EPW)

    assert result["ok"] is True, result
    reason = result["skipped"]["Site:GroundTemperature:BuildingSurface"]
    assert "no thermostat in the model" in reason
    assert "building_surface_constant_c" in reason
    assert _months("building_surface") is None
    assert _months("deep")[0] == BOSTON_DEEP_JAN


def test_epw_raw_applies_undisturbed_values_and_warns_loudly():
    # Validates: the escape hatch works, and never silently — the .stat's own wording travels
    # with the result
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures(epw_path=BOSTON_EPW, building_surface_method="epw_raw")

    assert result["ok"] is True, result
    assert _months("building_surface")[0] == BOSTON_SHALLOW_JAN
    assert any("should NOT BE USED" in w for w in result["warnings"]), result["warnings"]


def test_constant_method_writes_the_given_value():
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures(
        epw_path=BOSTON_EPW, building_surface_method="constant", building_surface_constant_c=18.5,
    )

    assert result["ok"] is True, result
    assert _months("building_surface") == [18.5] * 12


def test_none_method_leaves_building_surface_absent():
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures(epw_path=BOSTON_EPW, building_surface_method="none")

    assert result["ok"] is True, result
    assert _months("building_surface") is None
    assert result["skipped"]["Site:GroundTemperature:BuildingSurface"] == (
        "building_surface_method='none'"
    )


# --------------------------------------------------------------------------- argument errors


def test_constant_method_without_a_value_is_rejected():
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures(epw_path=BOSTON_EPW, building_surface_method="constant")

    assert result["ok"] is False
    assert "requires building_surface_constant_c" in result["error"]


def test_implausible_constant_is_rejected():
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures(
        epw_path=BOSTON_EPW, building_surface_method="constant", building_surface_constant_c=500.0,
    )

    assert result["ok"] is False
    assert "outside" in result["error"]


def test_unknown_building_surface_method_is_rejected_listing_the_valid_ones():
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures(epw_path=BOSTON_EPW, building_surface_method="kiva")

    assert result["ok"] is False
    assert "setpoint_offset" in result["error"]
    assert "epw_raw" in result["error"]


def test_no_model_loaded_reports_instead_of_raising():
    # Validates: the operations contract — never raise through MCP (CLAUDE.md rule 5)
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    result = set_ground_temperatures(epw_path=BOSTON_EPW)

    assert result["ok"] is False
    assert "error" in result


def test_missing_epw_is_rejected():
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures(epw_path="/repo/tests/assets/does_not_exist.epw")

    assert result["ok"] is False
    assert "not found" in result["error"]


def test_non_epw_suffix_is_rejected():
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures(
        epw_path="/repo/tests/assets/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.stat",
    )

    assert result["ok"] is False
    assert "Not an EPW file" in result["error"]


def test_epw_without_a_ground_temperature_record_reports_and_writes_nothing():
    # Validates: a parse failure leaves the model untouched rather than half-written
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    bad = _allowed_dir() / "headerless.epw"
    bad.write_text("LOCATION,x,,,,,,,0,0,0,0\nDESIGN CONDITIONS,0\n", encoding="utf-8")

    result = set_ground_temperatures(epw_path=str(bad))

    assert result["ok"] is False
    assert "GROUND TEMPERATURES" in result["error"]
    assert _months("deep") is None


def test_no_epw_anywhere_names_every_route_it_tried():
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    result = set_ground_temperatures()

    assert result["ok"] is False
    assert "epw_path" in result["error"]
    assert "import_gbxml" in result["error"]
    assert "change_building_location" in result["error"]


# --------------------------------------------------------------------------- read-back


def test_reading_state_does_not_create_the_unique_objects():
    # Regression: the plain Model.get<Class>() getter creates the object as a side effect
    # (probed on 3.11.0). If read_ground_temperature_state used it, the first call would make
    # every model look like it already had ground temperatures — and a later save would
    # persist four all-defaulted objects nobody asked for.
    import openstudio

    from mcp_server.model_manager import get_model
    from mcp_server.skills.weather.ground_temperatures import read_ground_temperature_state

    _load_empty_model()
    model = get_model()
    idd = openstudio.model.SiteGroundTemperatureDeep.iddObjectType()
    assert len(model.getObjectsByType(idd)) == 0

    for _ in range(3):
        state = read_ground_temperature_state(model)
        assert state["deep"]["state"] == "absent"

    assert len(model.getObjectsByType(idd)) == 0


def test_get_weather_info_reports_ground_temperatures_without_a_weather_file():
    # Regression: get_weather_info early-returns when OS:WeatherFile is absent, which is
    # exactly the gbXML-import case. The ground block must survive that return.
    from mcp_server.skills.weather.operations import get_weather_info

    _load_empty_model()
    info = get_weather_info()

    assert info["ok"] is True, info
    assert info["weather_file"] is None
    assert info["ground_temperatures"]["deep"]["state"] == "absent"


def test_get_weather_info_reflects_applied_values():
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures
    from mcp_server.skills.weather.operations import get_weather_info

    _load_empty_model()
    assert set_ground_temperatures(epw_path=BOSTON_EPW, building_surface_method="none")["ok"]

    deep = get_weather_info()["ground_temperatures"]["deep"]
    assert deep["state"] == "set"
    assert deep["months_set"] == 12
    assert deep["monthly_c"][0] == BOSTON_DEEP_JAN


def test_a_defaulted_object_is_reported_as_missing_not_set():
    # Regression: an all-defaulted object is written to the OSM and survives reload, so
    # presence is not evidence anyone chose a value. A typical OSM ships BuildingSurface and
    # Deep already present at their defaults.
    from mcp_server.model_manager import get_model
    from mcp_server.skills.weather.ground_temperatures import (
        find_missing_ground_temperatures,
        read_ground_temperature_state,
    )

    _load_empty_model()
    model = get_model()
    created = model.getSiteGroundTemperatureDeep()   # create, choose nothing
    assert created.getTemperatureByMonth(1) == 16.0

    assert read_ground_temperature_state(model)["deep"]["state"] == "defaulted"
    report = find_missing_ground_temperatures()
    assert report["ground_temperatures_missing"] is True
    assert "Site:GroundTemperature:Deep" in report["ground_temperatures_missing_objects"]


def test_a_partially_written_object_is_reported_as_partial():
    # Validates: setting one month leaves the other 11 defaulted; that half-written state is
    # worse than either extreme and must be visible rather than rounded to "set"
    from mcp_server.model_manager import get_model
    from mcp_server.skills.weather.ground_temperatures import read_ground_temperature_state

    _load_empty_model()
    model = get_model()
    model.getSiteGroundTemperatureDeep().setTemperatureByMonth(1, 5.0)

    state = read_ground_temperature_state(model)["deep"]
    assert state["state"] == "partial"
    assert state["months_set"] == 1


# --------------------------------------------------------------------------- overwrite guard


def test_existing_values_are_not_replaced_without_overwrite():
    # Validates: idempotence, and that a hand-tuned set is not silently stomped
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    assert set_ground_temperatures(epw_path=BOSTON_EPW, building_surface_method="none")["ok"]

    second = set_ground_temperatures(epw_path=AUSTIN_EPW, building_surface_method="none")

    assert second["ok"] is True, second
    assert "overwrite=True" in second["skipped"]["Site:GroundTemperature:Deep"]
    assert _months("deep")[0] == BOSTON_DEEP_JAN


def test_overwrite_replaces_and_reports_the_previous_values():
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    assert set_ground_temperatures(epw_path=BOSTON_EPW, building_surface_method="none")["ok"]

    second = set_ground_temperatures(
        epw_path=AUSTIN_EPW, building_surface_method="none", overwrite=True,
    )

    assert second["ok"] is True, second
    entry = second["applied"]["Site:GroundTemperature:Deep"]
    assert entry["replaced_monthly_c"][0] == BOSTON_DEEP_JAN
    assert _months("deep")[0] == 18.56


# --------------------------------------------------------------------------- report contract


def test_report_flags_a_fresh_model_and_clears_after_applying():
    from mcp_server.skills.weather.ground_temperatures import (
        find_missing_ground_temperatures,
        set_ground_temperatures,
    )

    _load_model_with_thermostats()
    before = find_missing_ground_temperatures()
    assert before["ok"] is True, before
    assert before["ground_temperatures_missing"] is True
    assert before["ground_temperatures_missing_count"] == 4
    assert before["ground_temperatures_state"]["deep"] == "absent"

    assert set_ground_temperatures(epw_path=BOSTON_EPW)["ok"]

    after = find_missing_ground_temperatures()
    assert after["ground_temperatures_missing"] is False
    assert after["ground_temperatures_missing_count"] == 0


def test_report_with_no_model_loaded_reports_instead_of_raising():
    from mcp_server.skills.weather.ground_temperatures import find_missing_ground_temperatures

    result = find_missing_ground_temperatures()

    assert result["ok"] is False
    assert "error" in result


# --------------------------------------------------------------------------- depth handling


def test_single_depth_epw_serves_deep_from_the_nearest_set_and_warns():
    # Validates: nearest-available depth selection, and that a 3.5 m substitution is not
    # allowed to pass silently
    from mcp_server.skills.weather.ground_temperatures import set_ground_temperatures

    _load_empty_model()
    one_set = _allowed_dir() / "one_depth.epw"
    months = ",".join(str(v) for v in [-0.29, -1.36, 0.53, 3.49, 11.23, 17.2,
                                       21.23, 22.45, 20.36, 15.73, 9.53, 3.79])
    one_set.write_text(
        "LOCATION,x,,,,,,,0,0,0,0\n"
        "DESIGN CONDITIONS,0\n"
        "TYPICAL/EXTREME PERIODS,0\n"
        f"GROUND TEMPERATURES,1,0.5,,,,{months}\n",
        encoding="utf-8",
    )

    result = set_ground_temperatures(epw_path=str(one_set), building_surface_method="none")

    assert result["ok"] is True, result
    assert result["depth_sets_available"] == [0.5]
    assert result["applied"]["Site:GroundTemperature:Deep"]["depth_delta_m"] == 3.5
    assert _months("deep")[0] == BOSTON_SHALLOW_JAN
    assert any("3.5 m away" in w for w in result["warnings"]), result["warnings"]


def test_save_and_reload_preserves_the_applied_values():
    # Validates: the write actually reaches the file, not just the in-memory model
    import openstudio

    from mcp_server.model_manager import get_model, load_model
    from mcp_server.skills.weather.ground_temperatures import (
        read_ground_temperature_state,
        set_ground_temperatures,
    )

    _load_empty_model()
    assert set_ground_temperatures(epw_path=BOSTON_EPW, building_surface_method="none")["ok"]

    osm_path = _allowed_dir() / "saved.osm"
    assert get_model().save(openstudio.toPath(str(osm_path)), True)
    load_model(osm_path)

    deep = read_ground_temperature_state(get_model())["deep"]
    assert deep["state"] == "set"
    assert deep["monthly_c"][0] == BOSTON_DEEP_JAN
