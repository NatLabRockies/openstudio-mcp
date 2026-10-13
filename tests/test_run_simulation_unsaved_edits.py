"""run_simulation must say when the session model has edits the file on disk lacks.

Issue #177: load_osm_model(A) -> create_space -> run_simulation(A) returned ok with no
warning and simulated the last saved file. Also covers set_run_period calendar checks.
"""
import asyncio
import uuid
from pathlib import Path

import pytest
from conftest import EPW_PATH, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

UNSAVED = "edits that are not saved"


def _unique(prefix: str = "pytest_unsaved") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _load_example(s) -> str:
    cr = unwrap(await s.call_tool("create_example_osm", {"name": _unique()}))
    assert cr["ok"] is True, cr
    ld = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert ld["ok"] is True, ld
    return cr["osm_path"]


async def _run_and_cancel(s, osm_path: str) -> dict:
    sim = unwrap(await s.call_tool("run_simulation", {"osm_path": osm_path, "epw_path": EPW_PATH}))
    if sim.get("ok") and sim.get("run_id"):
        await s.call_tool("cancel_run", {"run_id": sim["run_id"]})
    return sim


def _stdio(coro_fn):
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await coro_fn(s)
    asyncio.run(_run())


@pytest.mark.integration
def test_run_simulation_warns_on_unsaved_edits():
    # Regression: load -> create_space -> run_simulation(same path) simulated the stale file
    # on disk and said nothing (issue #177, reproduced 2026-10-13)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        path = await _load_example(s)
        sp = unwrap(await s.call_tool("create_space", {"name": "Unsaved Space"}))
        assert sp["ok"] is True, sp
        sim = await _run_and_cancel(s, path)
        assert sim["ok"] is True, sim
        assert any(UNSAVED in w for w in sim.get("warnings", [])), sim
        assert "save_osm_model" in sim["user_message"], sim
    _stdio(body)


@pytest.mark.integration
def test_run_simulation_warns_after_apply_measure():
    # Regression: apply_measure reloads the session model from the run dir, so the loaded
    # file is stale afterwards; run_simulation on it gave no warning (issue #177)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        path = await _load_example(s)
        res = unwrap(await s.call_tool("enable_ideal_air_loads", {}))
        assert res["ok"] is True, res
        sim = await _run_and_cancel(s, path)
        assert sim["ok"] is True, sim
        assert any(UNSAVED in w for w in sim.get("warnings", [])), sim
    _stdio(body)


@pytest.mark.integration
def test_run_simulation_warns_on_old_path_after_save_as():
    # Regression: load A -> edit -> save-as B -> edit -> run_simulation(A): A is two edits
    # behind the session model and must warn (Codex review of the #177 plan)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        path_a = await _load_example(s)
        assert unwrap(await s.call_tool("create_space", {"name": "Space One"}))["ok"] is True
        sv = unwrap(await s.call_tool("save_osm_model", {"save_name": _unique("saveas")}))
        assert sv["ok"] is True, sv
        # A kept its load-time digest through the save-as: one edit behind already.
        sim = await _run_and_cancel(s, path_a)
        assert sim["ok"] is True, sim
        assert any(UNSAVED in w for w in sim.get("warnings", [])), sim
        assert unwrap(await s.call_tool("create_thermal_zone", {"name": "Zone Two"}))["ok"] is True
        sim = await _run_and_cancel(s, path_a)
        assert sim["ok"] is True, sim
        assert any(UNSAVED in w for w in sim.get("warnings", [])), sim
    _stdio(body)


@pytest.mark.integration
def test_run_simulation_clean_after_save_as():
    # Validates: the path a save-as wrote is clean right after the save; no false warning
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        await _load_example(s)
        assert unwrap(await s.call_tool("create_space", {"name": "Space One"}))["ok"] is True
        sv = unwrap(await s.call_tool("save_osm_model", {"save_name": _unique("saveas")}))
        assert sv["ok"] is True, sv
        sim = await _run_and_cancel(s, sv["osm_path"])
        assert sim["ok"] is True, sim
        assert "warnings" not in sim, sim
        # The saved path IS tracked: an edit after the save warns, a re-save clears it.
        # (Without this, a save that records nothing would pass the check above too.)
        assert unwrap(await s.call_tool("create_thermal_zone", {"name": "Zone Two"}))["ok"] is True
        sim = await _run_and_cancel(s, sv["osm_path"])
        assert sim["ok"] is True, sim
        assert any(UNSAVED in w for w in sim.get("warnings", [])), sim
        sv2 = unwrap(await s.call_tool("save_osm_model", {"osm_path": sv["osm_path"]}))
        assert sv2["ok"] is True, sv2
        sim = await _run_and_cancel(s, sv["osm_path"])
        assert sim["ok"] is True, sim
        assert "warnings" not in sim, sim
    _stdio(body)


@pytest.mark.integration
def test_run_simulation_clean_on_fresh_load():
    # Validates: a freshly loaded, untouched model gives no unsaved-edits warning
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        path = await _load_example(s)
        sim = await _run_and_cancel(s, path)
        assert sim["ok"] is True, sim
        assert "warnings" not in sim, sim
    _stdio(body)


@pytest.mark.integration
@pytest.mark.parametrize(("month", "day", "month_name"), [
    (2, 30, "February"),
    (4, 31, "April"),
    (2, 29, "February"),  # the example model has no calendar year: not a leap year
])
def test_set_run_period_rejects_impossible_dates(month, day, month_name):
    # Regression: set_run_period only checked 1-31, so February 30 was accepted and the
    # error surfaced at EnergyPlus run time (issue #177)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        await _load_example(s)
        before = unwrap(await s.call_tool("get_run_period", {}))["run_period"]
        res = unwrap(await s.call_tool("set_run_period", {
            "begin_month": 1, "begin_day": 1, "end_month": month, "end_day": day,
        }))
        assert res["ok"] is False, res
        assert month_name in res["error"] and str(day) in res["error"], res["error"]
        after = unwrap(await s.call_tool("get_run_period", {}))["run_period"]
        assert after == before, "a rejected call must not change the run period"
    _stdio(body)


@pytest.mark.integration
def test_set_run_period_accepts_feb_29_on_leap_year_model():
    # Validates: the day limit follows the model's calendar year; a fixed non-leap table
    # would wrongly reject February 29 on a leap-year model
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        # The example model has no OS:YearDescription and no tool sets a calendar year
        # (set_object_property does not support that unique object), so the fixture gets
        # one appended to the file before the load.
        cr = unwrap(await s.call_tool("create_example_osm", {"name": _unique("leap")}))
        assert cr["ok"] is True, cr
        with Path(cr["osm_path"]).open("a", encoding="utf-8") as f:
            f.write(
                "\nOS:YearDescription,\n"
                "  {5d1c0d7e-1b4f-4e4e-9c6a-2f0b7e2a9a01}, !- Handle\n"
                "  2024,                                   !- Calendar Year\n"
                "  Sunday;                                 !- Day of Week for Start Day\n",
            )
        ld = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
        assert ld["ok"] is True, ld
        res = unwrap(await s.call_tool("set_run_period", {
            "begin_month": 2, "begin_day": 29, "end_month": 2, "end_day": 29,
        }))
        assert res["ok"] is True, res
        assert res["run_period"]["begin_day"] == 29
    _stdio(body)


@pytest.mark.integration
def test_set_run_period_accepts_year_wrap():
    # Validates: EnergyPlus runs a period whose end date is before its begin date (it wraps
    # the year; Dec 1 to Jan 31 completed successfully on 2026-10-13), so it is not rejected
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        await _load_example(s)
        res = unwrap(await s.call_tool("set_run_period", {
            "begin_month": 12, "begin_day": 1, "end_month": 1, "end_day": 31,
        }))
        assert res["ok"] is True, res
        assert (res["run_period"]["begin_month"], res["run_period"]["end_month"]) == (12, 1)
    _stdio(body)
