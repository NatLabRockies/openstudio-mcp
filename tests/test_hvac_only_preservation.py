"""hvac_only on a model that was NOT built by create_typical_building.

The swap must leave every non-HVAC input as modeled AND size the new HVAC against
those inputs. Upstream openstudio-standards replaced infiltration and ground
constructions before its sizing run, rewrote reporting tolerances and night-cycle
managers, and purged unused resources; the vendored measure fork gates all of that
(mcp_server/skills/comstock/measures/create_typical_building_from_model/VENDORED.md,
plan-hvac-only-non-hvac-preservation.md, session export 2026-11-04).

The fixture is the SystemD office (44 zones, 4-pipe fan coils + 2 DOAS, Boston
weather). One swap per module; the tests read the collected observations.
"""
import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

FIXTURE = "/repo/tests/assets/SystemD_baseline.osm"  # Baltimore model; Boston EPW set in the test
EPW = ("/opt/comstock-measures/ChangeBuildingLocation"
       "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
SYSTEM = "VAV air-cooled chiller with gas boiler reheat"
TEMPLATE = "90.1-2019"
CZ = "ASHRAE 169-2013-5A"

INFIL_PROPS = ("flowperExteriorSurfaceArea", "constantTermCoefficient",
               "temperatureTermCoefficient", "velocityTermCoefficient",
               "velocitySquaredTermCoefficient", "spaceType")
SHADED_SUBSURFACES = ("Sub Surface 1", "Sub Surface 2", "Sub Surface 15", "Sub Surface 16")
WH_PROPS = ("heaterThermalEfficiency", "offCycleLossCoefficienttoAmbientTemperature",
            "onCycleLossCoefficienttoAmbientTemperature")
PUMP_PROPS = ("motorEfficiency", "coefficient1ofthePartLoadPerformanceCurve",
              "coefficient2ofthePartLoadPerformanceCurve",
              "coefficient3ofthePartLoadPerformanceCurve",
              "coefficient4ofthePartLoadPerformanceCurve")
NC_PROPS = ("thermostatTolerance", "cyclingRunTimeControlType", "cyclingRunTime")
ZONE_KEYS = ("thermostat", "heating_setpoint_schedule", "cooling_setpoint_schedule")


async def _objects(s, object_type):
    r = unwrap(await s.call_tool("list_model_objects", {"object_type": object_type, "max_results": 0}))
    assert r["ok"] is True, r
    return r["objects"]


async def _props(s, object_type, handle, keys):
    r = unwrap(await s.call_tool("get_object_fields", {"object_type": object_type, "object_handle": handle}))
    assert r["ok"] is True, r
    return {k: r["properties"].get(k, {}).get("value") for k in keys}


async def _by_handle(s, object_type, keys):
    return {o["handle"]: {"name": o["name"], **(await _props(s, object_type, o["handle"], keys))}
            for o in await _objects(s, object_type)}


async def _ground_surfaces(s):
    # get_object_fields skips is*() and object-valued getters, so the construction is
    # read through get_surface_details, which resolves the inherited (defaulted) one
    out = {}
    for o in await _objects(s, "Surface"):
        p = await _props(s, "Surface", o["handle"], ("outsideBoundaryCondition",))
        if p["outsideBoundaryCondition"] == "Ground":
            d = unwrap(await s.call_tool("get_surface_details", {"surface_name": o["name"]}))
            assert d["ok"] is True, d
            out[o["handle"]] = {"name": o["name"], "construction": d["surface"]["construction"]}
    return out


async def _subsurface_shading(s):
    out = {}
    for o in await _objects(s, "SubSurface"):
        if o["name"] in SHADED_SUBSURFACES:
            out[o["name"]] = (await _props(s, "SubSurface", o["handle"],
                                           ("numberofShadingControls",)))["numberofShadingControls"]
    return out


async def _zones(s):
    out = {}
    for o in await _objects(s, "ThermalZone"):
        d = unwrap(await s.call_tool("get_thermal_zone_details", {"zone_name": o["name"]}))
        assert d["ok"] is True, d
        out[o["handle"]] = {"name": o["name"], **{k: d["thermal_zone"][k] for k in ZONE_KEYS},
                            **(await _props(s, "ThermalZone", o["handle"], ("multiplier",)))}
    return out


async def _singleton(s, object_type, keys):
    objs = await _objects(s, object_type)
    assert len(objs) == 1, f"{object_type}: expected one object, got {len(objs)}"
    return await _props(s, object_type, objs[0]["handle"], keys)


async def _snapshot(s):
    return {
        "infiltration": await _by_handle(s, "SpaceInfiltrationDesignFlowRate", INFIL_PROPS),
        "ffactor_count": len(await _objects(s, "FFactorGroundFloorConstruction")),
        "ground_surfaces": await _ground_surfaces(s),
        "shading_control_count": len(await _objects(s, "ShadingControl")),
        "subsurface_shading": await _subsurface_shading(s),
        "water_heaters": await _by_handle(s, "WaterHeaterMixed", WH_PROPS),
        "pumps": await _by_handle(s, "PumpVariableSpeed", PUMP_PROPS),
        "tolerances": await _singleton(s, "OutputControlReportingTolerances", (
            "toleranceforTimeHeatingSetpointNotMet", "toleranceforTimeCoolingSetpointNotMet")),
        "sim_control": await _singleton(s, "SimulationControl", ("doHVACSizingSimulationforSizingPeriods",)),
        "night_cycles": await _by_handle(s, "AvailabilityManagerNightCycle", NC_PROPS),
        "zones": await _zones(s),
        "thermostat_count": len(await _objects(s, "ThermostatSetpointDualSetpoint")),
    }


async def _collect():
    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": FIXTURE}))
            assert lr["ok"] is True, lr
            wr = unwrap(await s.call_tool("change_building_location", {"weather_file": EPW}))
            assert wr["ok"] is True, wr
            pre = await _snapshot(s)

            swap = unwrap(await s.call_tool("create_typical_building", {
                "system_type": SYSTEM, "template": TEMPLATE, "climate_zone": CZ,
                "hvac_only": True,
            }))
            assert swap["ok"] is True, f"hvac_only swap failed: {swap.get('error')} {swap.get('log_tail')}"
            post = await _snapshot(s)

            air_loops = unwrap(await s.call_tool("list_air_loops", {}))
            fan_coils = await _objects(s, "ZoneHVACFourPipeFanCoil")
            chillers = await _by_handle(s, "ChillerElectricEIR", ("condenserType", "referenceCOP"))
            boilers = await _by_handle(s, "BoilerHotWater", ("fuelType",))

            # The sizing-run model the measure wrote: what the new HVAC was sized against
            files = unwrap(await s.call_tool("list_files", {
                "directory": swap["run_dir"], "pattern": "in.osm", "max_depth": 5, "max_results": 200}))
            assert files["ok"] is True, files
            # the SR1 OSW dir holds in.osm (the model handed to the sizing run) and a
            # run/in.osm copy the CLI makes; either works, take the OSW-level one
            sr1 = [f["path"] for f in files["items"]
                   if f["path"].endswith("create_typical_building_from_model_SR1/in.osm")]
            assert len(sr1) == 1, f"expected one SR1 in.osm under {swap['run_dir']}, got {sr1}"
            sr = unwrap(await s.call_tool("load_osm_model", {"osm_path": sr1[0]}))
            assert sr["ok"] is True, sr
            sr1_infiltration = len(await _objects(s, "SpaceInfiltrationDesignFlowRate"))
            sr1_ffactor = len(await _objects(s, "FFactorGroundFloorConstruction"))

            return {
                "pre": pre, "post": post, "swap": swap,
                "air_loops": air_loops, "fan_coils": fan_coils,
                "chillers": chillers, "boilers": boilers,
                "sr1_infiltration": sr1_infiltration, "sr1_ffactor": sr1_ffactor,
            }


@pytest.fixture(scope="module")
def obs():
    if not integration_enabled():
        pytest.skip("integration disabled")
    return asyncio.run(_collect())


@pytest.mark.integration
def test_hvac_only_preserves_infiltration(obs):
    # Regression: upstream replaced the 12 space-type infiltration objects with 58 NIST
    # per-space HVAC On/Off pairs at 2.2x the flow (EUI 27 -> 67 kBtu/ft2); add_infiltration is now gated
    pre, post = obs["pre"]["infiltration"], obs["post"]["infiltration"]
    assert len(pre) == 12, f"fixture should carry 12 space-type infiltration objects, got {len(pre)}"
    assert post == pre, "infiltration objects must be identical by handle and field after the swap"
    for entry in post.values():
        assert entry["flowperExteriorSurfaceArea"] == pytest.approx(0.000254, rel=1e-6)
        assert entry["constantTermCoefficient"] == pytest.approx(1.0, abs=1e-12)
        assert "HVAC On Infiltration" not in entry["name"] and "HVAC Off Infiltration" not in entry["name"]


@pytest.mark.integration
def test_hvac_only_preserves_ground_constructions(obs):
    # Regression: upstream hard-assigned 15 F-factor constructions to the 23 ground floors
    # before sizing; set_ground_constructions is now gated
    pre, post = obs["pre"]["ground_surfaces"], obs["post"]["ground_surfaces"]
    assert len(pre) == 23, f"fixture should have 23 ground-boundary surfaces, got {len(pre)}"
    assert post == pre, "ground floors must keep the construction they had (no hard F-factor assignment)"
    assert all("ffactor" not in v["construction"].lower() for v in post.values()), post
    assert obs["pre"]["ffactor_count"] == 0
    assert obs["post"]["ffactor_count"] == 0


@pytest.mark.integration
def test_hvac_only_preserves_shading_controls(obs):
    # Regression: purgeUnusedResourceObjects deleted both ShadingControls and the blinds
    # on Sub Surfaces 1/2/15/16; purge_unused_resources is now gated
    assert obs["pre"]["shading_control_count"] == 2
    assert obs["post"]["shading_control_count"] == 2
    pre, post = obs["pre"]["subsurface_shading"], obs["post"]["subsurface_shading"]
    assert set(pre) == set(SHADED_SUBSURFACES)
    assert post == pre
    assert all(v == 1 for v in post.values()), f"blinds lost on {post}"


@pytest.mark.integration
def test_hvac_only_preserves_swh(obs):
    # Regression: model_apply_hvac_efficiency_standard retuned the retained water heater
    # (eff 0.80110 -> 0.80130, UA 29.77 -> 35.37 W/K, +13% water-systems gas); the guard copies it back
    pre, post = obs["pre"]["water_heaters"], obs["post"]["water_heaters"]
    assert len(pre) == 1
    assert post == pre, "name (standards appends ' 0.801 Therm Eff') and efficiency fields must be restored"
    wh = next(iter(post.values()))
    assert wh["heaterThermalEfficiency"] == pytest.approx(0.8010961390725, rel=1e-9)
    assert wh["offCycleLossCoefficienttoAmbientTemperature"] == pytest.approx(29.7719201655848, rel=1e-9)
    assert wh["onCycleLossCoefficienttoAmbientTemperature"] == pytest.approx(29.7719201655848, rel=1e-9)
    # pumps that survived the swap (by handle) are SWH pumps and must be untouched too
    surviving = {h: v for h, v in obs["post"]["pumps"].items() if h in obs["pre"]["pumps"]}
    assert surviving, "the SWH loop pump must survive an HVAC-only swap"
    for h, v in surviving.items():
        assert v == obs["pre"]["pumps"][h], f"SWH pump {v['name']} retuned by the swap"


@pytest.mark.integration
def test_hvac_only_preserves_reporting_tolerance_and_simcontrol(obs):
    # Regression: upstream wrote 1 R (0.5556 C) to OutputControl:ReportingTolerances, hiding
    # ~1,600 unmet hours in the comparison; set_unmet_hours_tolerance and set_sim_control are gated
    tol = obs["post"]["tolerances"]
    assert tol == obs["pre"]["tolerances"]
    assert tol["toleranceforTimeHeatingSetpointNotMet"] == pytest.approx(0.2, abs=1e-9)
    assert tol["toleranceforTimeCoolingSetpointNotMet"] == pytest.approx(0.2, abs=1e-9)
    assert obs["post"]["sim_control"] == obs["pre"]["sim_control"]


@pytest.mark.integration
def test_hvac_only_night_cycle_managers(obs):
    # Validates: managers that survive keep the model's 1 C / 3600 s values, while the new VAV
    # loops get the standards 1.9999 C / Thermostat values (modify_night_cycle_managers gated)
    pre, post = obs["pre"]["night_cycles"], obs["post"]["night_cycles"]
    assert len(pre) == 13, f"fixture should carry 13 night-cycle managers, got {len(pre)}"
    for h, v in post.items():
        if h in pre:
            assert v == pre[h], f"pre-existing night cycle {v['name']} was rewritten"
    new = {h: v for h, v in post.items() if h not in pre}
    assert len(new) >= 2, f"each new VAV loop should carry a night-cycle manager, got {len(new)}"
    for v in new.values():
        assert v["thermostatTolerance"] == pytest.approx(1.9999, abs=1e-6)
        assert v["cyclingRunTimeControlType"] == "Thermostat"


@pytest.mark.integration
def test_hvac_only_sizing_run_saw_original_envelope(obs):
    # Regression: the first fix attempt restored infiltration AFTER the measure, but sizing run SR1
    # had already autosized the VAV against NIST infiltration and F-factor slabs. The gates run before SR1.
    assert obs["sr1_infiltration"] == 12, "SR1 must have been sized with the model's 12 infiltration objects"
    assert obs["sr1_ffactor"] == 0, "SR1 must not carry F-factor ground constructions"


@pytest.mark.integration
def test_hvac_only_reports_no_remaining_changes(obs):
    # Validates: the response contract — nothing non-HVAC left different, SWH restore reported
    swap = obs["swap"]
    assert swap["hvac_only"] is True
    assert swap["non_hvac_changes"] == [], swap["non_hvac_changes"]
    assert swap["non_hvac_changes_total"] == 0
    categories = [r["category"] for r in swap["restored"]]
    assert categories == ["swh_equipment"], swap["restored"]
    # the water heater for sure; the SWH pump too if the efficiency standard retuned it
    assert swap["restored"][0]["count"] >= 1
    assert set(swap["restored"][0]["fields"]) >= {
        "Name",
        "Heater Thermal Efficiency",
        "Off Cycle Loss Coefficient to Ambient Temperature",
        "On Cycle Loss Coefficient to Ambient Temperature",
    }, swap["restored"][0]


@pytest.mark.integration
def test_hvac_only_still_swaps_hvac(obs):
    # Validates: the gates must not weaken the swap itself — VAV loops, air-cooled chiller,
    # gas boiler, standards COP (not the fixture's 5.3288), fan coils gone
    names = [a["name"] for a in obs["air_loops"]["air_loops"]]
    assert len(names) == 2 and all("VAV" in n for n in names), names
    assert obs["fan_coils"] == []
    assert len(obs["chillers"]) == 1
    chiller = next(iter(obs["chillers"].values()))
    assert chiller["condenserType"] == "AirCooled"
    assert chiller["referenceCOP"] != pytest.approx(5.3288, abs=1e-3), "chiller must carry the 90.1-2019 COP"
    assert len(obs["boilers"]) == 1
    assert next(iter(obs["boilers"].values()))["fuelType"] == "NaturalGas"


@pytest.mark.integration
def test_hvac_only_keeps_zone_thermostats(obs):
    # Validates: OS:ThermalZone is exempt from the non-HVAC diff (its equipment/port fields change),
    # so this is the explicit check that model_remove_prm_hvac did not unlink thermostats or multipliers
    pre, post = obs["pre"]["zones"], obs["post"]["zones"]
    assert len(pre) == 44, f"fixture should have 44 thermal zones, got {len(pre)}"
    assert set(post) == set(pre), "zones must survive by handle"
    for h, v in post.items():
        assert v == pre[h], f"zone {v['name']} thermostat/multiplier changed: {pre[h]} -> {v}"
        assert v["thermostat"], f"zone {v['name']} lost its thermostat"
        assert v["heating_setpoint_schedule"] and v["cooling_setpoint_schedule"], v
    assert obs["post"]["thermostat_count"] == obs["pre"]["thermostat_count"]
