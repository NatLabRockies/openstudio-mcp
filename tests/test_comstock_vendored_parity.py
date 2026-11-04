"""The vendored create_typical_building_from_model fork reproduces upstream by default.

Guards two things: the fork's new arguments are visible through the measure
interface, and with every gate at its default the measure still does what the
ComStock 2025-3 / openstudio-standards 0.8.5 original did on a non-typical model
(NIST infiltration, F-factor floors, 1 R tolerance, night-cycle rewrite). Those
reference counts were observed with the upstream measure on the same model in the
2026-11-04 session export. See
mcp_server/skills/comstock/measures/create_typical_building_from_model/VENDORED.md.
"""
import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

MEASURE_DIR = "/opt/comstock-measures/create_typical_building_from_model"
FIXTURE = "/repo/tests/assets/SystemD_baseline.osm"  # Baltimore model; Boston EPW set in the test
EPW = ("/opt/comstock-measures/ChangeBuildingLocation"
       "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
SYSTEM = "VAV air-cooled chiller with gas boiler reheat"
CZ = "ASHRAE 169-2013-5A"

NEW_ARG_DEFAULTS = {
    "add_infiltration": "true",
    "airtightness_value": "0",
    "airtightness_area_covered": "5-sided",
    "air_barrier": "false",
    "set_ground_constructions": "true",
    "set_unmet_hours_tolerance": "true",
    "modify_night_cycle_managers": "true",
    "purge_unused_resources": "true",
    "set_sim_control": "true",
}


@pytest.mark.integration
def test_vendored_measure_exposes_new_args():
    # Validates: the overlay in docker/Dockerfile put the fork (not upstream) under
    # COMSTOCK_MEASURES_DIR and measure.xml carries the nine gate/infiltration args with upstream-equivalent defaults
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as s:
                await s.initialize()
                r = unwrap(await s.call_tool("list_measure_arguments", {"measure_dir": MEASURE_DIR}))
                assert r["ok"] is True, r
                defaults = {a["name"]: str(a.get("default_value")) for a in r["arguments"]}
                for name, expected in NEW_ARG_DEFAULTS.items():
                    assert defaults.get(name) == expected, f"{name}: {defaults.get(name)!r} != {expected!r}"

    asyncio.run(_run())


async def _count(s, object_type):
    r = unwrap(await s.call_tool("list_model_objects", {"object_type": object_type, "max_results": 0}))
    assert r["ok"] is True, r
    return len(r["objects"])


async def _handles(s, object_type):
    r = unwrap(await s.call_tool("list_model_objects", {"object_type": object_type, "max_results": 0}))
    assert r["ok"] is True, r
    return [o["handle"] for o in r["objects"]]


async def _value(s, object_type, handle, prop):
    r = unwrap(await s.call_tool("get_object_fields", {"object_type": object_type, "object_handle": handle}))
    assert r["ok"] is True, r
    return r["properties"][prop]["value"]


@pytest.mark.integration
def test_vendored_defaults_match_upstream_behavior():
    # Validates: with hvac_only=False and every gate at its default, the fork does exactly what
    # upstream did on this model (session export: 58 NIST infiltration objects, 15 F-factor
    # constructions, 0.5556 C tolerance, 1.9999/Thermostat night cycles). From-scratch users see no change.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as s:
                await s.initialize()
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": FIXTURE}))
                assert lr["ok"] is True, lr
                wr = unwrap(await s.call_tool("change_building_location", {"weather_file": EPW}))
                assert wr["ok"] is True, wr
                assert await _count(s, "SpaceInfiltrationDesignFlowRate") == 12

                r = unwrap(await s.call_tool("create_typical_building", {
                    "system_type": SYSTEM, "template": "90.1-2019", "climate_zone": CZ,
                    "add_hvac": True, "add_constructions": False, "add_space_type_loads": False,
                    "add_swh": False, "add_exterior_lights": False, "add_thermostat": False,
                    "add_elevators": False, "add_internal_mass": False, "add_exhaust": False,
                    "add_refrigeration": False, "remove_objects": True,
                }))
                assert r["ok"] is True, f"create_typical_building failed: {r.get('error')} {r.get('log_tail')}"
                assert "hvac_only" not in r
                assert "non_hvac_changes" not in r, "the post-check only runs for hvac_only"

                assert await _count(s, "SpaceInfiltrationDesignFlowRate") == 58
                # the session saw 15 distinct F-factor constructions in CZ 3A; the count is
                # climate-zone dependent, the gate being on (> 0) is what this test guards
                assert await _count(s, "FFactorGroundFloorConstruction") > 0
                assert await _count(s, "ShadingControl") == 0, "purge is on by default, as upstream"
                tol = (await _handles(s, "OutputControlReportingTolerances"))[0]
                assert await _value(s, "OutputControlReportingTolerances", tol,
                                    "toleranceforTimeHeatingSetpointNotMet") == pytest.approx(0.5556, abs=1e-3)
                for h in await _handles(s, "AvailabilityManagerNightCycle"):
                    assert await _value(s, "AvailabilityManagerNightCycle", h,
                                        "thermostatTolerance") == pytest.approx(1.9999, abs=1e-6)
                    assert await _value(s, "AvailabilityManagerNightCycle", h,
                                        "cyclingRunTimeControlType") == "Thermostat"

    asyncio.run(_run())
