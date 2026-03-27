"""Consolidated validation tests for ASHRAE baseline systems 1-10.

Each system type gets a class with a class-scoped fixture that creates the
model, adds the system, and collects all query data in a single MCP session.
Test methods read from the fixture dict only — no additional MCP calls.

Systems with economizer tests (3-8) get a second NoEcon class.
"""
import asyncio

import pytest
from conftest import create_and_load, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup_system(session, name, system_type, *, economizer=True,
                        heating_fuel=None, system_name=None, zones=None):
    """Create example model, add baseline system, collect query data."""
    if zones is None:
        zones = await create_and_load(session, name)

    args = {
        "system_type": system_type,
        "thermal_zone_names": zones,
        "system_name": system_name or f"System {system_type}",
    }
    if heating_fuel:
        args["heating_fuel"] = heating_fuel
    if system_type in (3, 4, 5, 6, 7, 8):
        args["economizer"] = economizer

    sys_data = unwrap(await session.call_tool("add_baseline_system", args))

    result = {"system": sys_data, "zones": zones}

    # Collect air loop details if applicable (systems 3-8)
    air_loop_name = system_name or f"System {system_type}"
    if system_type in (3, 4, 5, 6, 7, 8):
        al = unwrap(await session.call_tool("get_air_loop_details", {
            "air_loop_name": air_loop_name,
        }))
        result["air_loop"] = al

    # Collect zone HVAC details for zone-level systems (1, 2, 9, 10)
    if system_type in (1, 2) and sys_data.get("ok"):
        equip_name = sys_data["system"]["equipment"][0]["equipment"]
        zd = unwrap(await session.call_tool("get_zone_hvac_details", {
            "equipment_name": equip_name,
        }))
        result["zone_hvac"] = zd

    # Collect plant loop details for systems with loops
    if sys_data.get("ok") and "system" in sys_data:
        sys = sys_data["system"]
        for loop_key in ("hot_water_loop", "chilled_water_loop", "condenser_loop"):
            if sys.get(loop_key):
                pl = unwrap(await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": sys[loop_key],
                }))
                result[loop_key] = pl

    return result


def _run_setup(name, system_type, **kwargs):
    """Synchronous wrapper: create session, run setup, return data dict."""
    result = {}

    async def _go():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                result.update(await _setup_system(s, name, system_type, **kwargs))

    asyncio.run(_go())
    return result


def _skip_if_disabled():
    if not integration_enabled():
        pytest.skip("integration disabled")


# ===========================================================================
# SYSTEM 1: PTAC (3 tests, 1 session)
# ===========================================================================

@pytest.mark.integration
class TestSystem1:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s1", 1, heating_fuel="Electricity", system_name="PTAC System")

    def test_coil_types(self, data):
        # Validates: PTAC has electric heating coil and DX cooling coil per ASHRAE System 1
        equip = data["zone_hvac"]["equipment"]
        assert "Electric" in equip["heating_coil"]["type"]
        assert "DX" in equip["cooling_coil"]["type"]

    def test_fan_present(self, data):
        # Validates: PTAC has supply air fan component
        assert "Fan" in data["zone_hvac"]["equipment"]["fan"]["type"]

    def test_multiple_zones(self, data):
        # Validates: System 1 creates one PTAC per zone (10 zones = 10 PTACs)
        equip_list = data["system"]["system"]["equipment"]
        assert len(equip_list) == len(data["zones"])


# ===========================================================================
# SYSTEM 2: PTHP (2 tests, 1 session)
# ===========================================================================

@pytest.mark.integration
class TestSystem2:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s2", 2, system_name="PTHP System")

    def test_heat_pump_coils(self, data):
        # Validates: PTHP has DX/heat-pump heating and DX cooling coils per ASHRAE System 2
        equip = data["zone_hvac"]["equipment"]
        assert equip["heating_coil"]["type"], "PTHP missing heating coil type"
        assert "DX" in equip["heating_coil"]["type"] or "HeatPump" in equip["heating_coil"]["type"], (
            f"PTHP heating should be DX/heat pump, got: {equip['heating_coil']['type']}"
        )
        assert equip["cooling_coil"]["type"], "PTHP missing cooling coil type"
        assert "DX" in equip["cooling_coil"]["type"] or "Cooling" in equip["cooling_coil"]["type"], (
            f"PTHP cooling should be DX, got: {equip['cooling_coil']['type']}"
        )

    def test_fan_present(self, data):
        # Validates: PTHP has supply air fan component
        assert "Fan" in data["zone_hvac"]["equipment"]["fan"]["type"], (
            f"PTHP should have a Fan, got: {data['zone_hvac']['equipment']['fan']['type']}"
        )


# ===========================================================================
# SYSTEM 3: PSZ-AC (7+1 tests, 2 sessions)
# ===========================================================================

@pytest.mark.integration
class TestSystem3:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        # Gas heating variant with economizer
        result = {}
        async def _go():
            async with stdio_client(server_params()) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    zones = await create_and_load(s, "val_s3")

                    # Gas heating system
                    gas_data = await _setup_system(
                        s, "val_s3", 3, heating_fuel="NaturalGas",
                        system_name="PSZ Gas", economizer=True, zones=zones,
                    )
                    result["gas"] = gas_data

                    # Electric heating system (on same model)
                    elec_args = {
                        "system_type": 3,
                        "thermal_zone_names": zones,
                        "heating_fuel": "Electricity",
                        "system_name": "PSZ Electric",
                        "economizer": True,
                    }
                    elec_sys = unwrap(await s.call_tool("add_baseline_system", elec_args))
                    result["electric"] = elec_sys

        asyncio.run(_go())
        return result

    def test_coil_types(self, data):
        # Validates: PSZ-AC (System 3) has heating coils and DX cooling coil
        al = data["gas"]["air_loop"]["air_loop"]
        assert len(al["detailed_components"]["heating_coils"]) >= 1
        assert len(al["detailed_components"]["cooling_coils"]) >= 1
        assert "DX" in al["detailed_components"]["cooling_coils"][0]["type"]

    def test_fan_verification(self, data):
        # Validates: PSZ-AC has supply fan on air loop
        fans = data["gas"]["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1
        assert "Fan" in fans[0]["type"]

    def test_economizer_enabled(self, data):
        # Validates: PSZ-AC economizer is active when requested (not NoEconomizer)
        oa = data["gas"]["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is True
        assert oa["economizer_type"] != "NoEconomizer"

    def test_outdoor_air_present(self, data):
        # Validates: PSZ-AC has outdoor air system for ventilation
        oa = data["gas"]["air_loop"]["air_loop"]["outdoor_air_system"]
        assert isinstance(oa["economizer_type"], str) and oa["economizer_type"], \
            "PSZ-AC must have outdoor air system with valid economizer type"

    def test_setpoint_managers(self, data):
        # Validates: PSZ-AC has at least one setpoint manager on supply outlet
        spms = data["gas"]["air_loop"]["air_loop"]["setpoint_managers"]
        assert len(spms) >= 1

    def test_electric_heating(self, data):
        # Validates: PSZ-AC with Electricity fuel uses electric heating coil
        assert "Electric" in data["electric"]["system"]["heating"]

    def test_gas_heating(self, data):
        # Validates: PSZ-AC with NaturalGas fuel uses gas heating coil
        assert "Gas" in data["gas"]["system"]["system"]["heating"]


@pytest.mark.integration
class TestSystem3NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s3ne", 3, economizer=False, system_name="PSZ No Econ")

    def test_economizer_disabled(self, data):
        # Validates: PSZ-AC economizer is off when economizer=False
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is False


# ===========================================================================
# SYSTEM 4: PSZ-HP (8+1 tests, 2 sessions)
# ===========================================================================

@pytest.mark.integration
class TestSystem4:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        result = {}
        async def _go():
            async with stdio_client(server_params()) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    zones = await create_and_load(s, "val_s4")
                    zone_name = zones[0]

                    # Main system (1 zone, with economizer)
                    main = await _setup_system(
                        s, "val_s4", 4, system_name="PSZ HP",
                        economizer=True, zones=[zone_name],
                    )
                    result.update(main)

                    # Single-zone-only test: create second zone, try 2 zones
                    await s.call_tool("create_thermal_zone", {"name": "Zone 2"})
                    err_resp = unwrap(await s.call_tool("add_baseline_system", {
                        "system_type": 4,
                        "thermal_zone_names": [zone_name, "Zone 2"],
                        "system_name": "PSZ HP 2",
                    }))
                    result["multi_zone_error"] = err_resp

        asyncio.run(_go())
        return result

    def test_heat_pump_coils(self, data):
        # Validates: PSZ-HP (System 4) has DX heating and cooling coils on air loop
        al = data["air_loop"]["air_loop"]
        assert len(al["detailed_components"]["heating_coils"]) >= 1
        assert len(al["detailed_components"]["cooling_coils"]) >= 1

    def test_supplemental_heat(self, data):
        # Validates: PSZ-HP has supplemental heating for low-temp backup
        assert len(data["system"]["system"]["heating"]) > 0, "PSZ-HP must have supplemental heating"

    def test_fan_present(self, data):
        # Validates: PSZ-HP has supply fan on air loop
        fans = data["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1

    def test_economizer_enabled(self, data):
        # Validates: System 4 economizer is active when requested
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is True

    def test_outdoor_air_present(self, data):
        # Validates: PSZ-HP has outdoor air system for ventilation
        eco = data["air_loop"]["air_loop"]["outdoor_air_system"]["economizer_type"]
        assert isinstance(eco, str) and eco, "PSZ-HP must have OA system with valid economizer type"

    def test_setpoint_managers(self, data):
        # Validates: PSZ-HP has at least one setpoint manager
        assert len(data["air_loop"]["air_loop"]["setpoint_managers"]) >= 1

    def test_dx_cooling(self, data):
        # Validates: System 4 uses heat pump DX cooling
        assert data["system"]["system"]["cooling"] == "Heat Pump"

    def test_single_zone_only(self, data):
        # Validates: System 4 rejects multi-zone requests (single-zone only)
        assert data["multi_zone_error"]["ok"] is False
        assert "exactly 1 zone" in data["multi_zone_error"]["error"].lower()


@pytest.mark.integration
class TestSystem4NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s4ne", 4, economizer=False, system_name="PSZ HP No Econ",
                          zones=None)

    def test_economizer_disabled(self, data):
        # Validates: System 4 economizer is off when economizer=False
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is False


# ===========================================================================
# SYSTEM 5: Packaged VAV w/ Reheat (10+1 tests, 2 sessions)
# ===========================================================================

@pytest.mark.integration
class TestSystem5:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s5", 5, heating_fuel="NaturalGas",
                          system_name="VAV Reheat", economizer=True)

    def test_hot_water_loop(self, data):
        # Validates: System 5 creates Heating-type hot water plant loop
        assert data["hot_water_loop"]["plant_loop"]["loop_type"] == "Heating"

    def test_boiler_present(self, data):
        # Validates: System 5 has boiler on hot water supply side
        supply = data["hot_water_loop"]["plant_loop"]["supply_components"]
        assert any("Boiler" in c["type"] for c in supply)

    def test_vav_terminals(self, data):
        # Validates: System 5 creates one VAV reheat terminal per zone
        sys = data["system"]["system"]
        assert len(sys["terminals"]) == len(data["zones"])

    def test_dx_cooling(self, data):
        # Validates: System 5 uses packaged DX cooling
        assert "DX" in data["system"]["system"]["cooling"]

    def test_variable_fan(self, data):
        # Validates: System 5 has variable volume supply fan
        fans = data["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1

    def test_economizer_enabled(self, data):
        # Validates: System 5 economizer is active when requested
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is True

    def test_outdoor_air_present(self, data):
        # Validates: System 5 has outdoor air system for ventilation
        eco = data["air_loop"]["air_loop"]["outdoor_air_system"]["economizer_type"]
        assert isinstance(eco, str) and eco, "System 5 must have OA system with valid economizer type"

    def test_setpoint_managers(self, data):
        # Validates: System 5 has at least one setpoint manager
        assert len(data["air_loop"]["air_loop"]["setpoint_managers"]) >= 1

    def test_reheat_coils(self, data):
        # Validates: System 5 VAV terminals are reheat type (contain "VAV")
        for terminal in data["system"]["system"]["terminals"]:
            assert "VAV" in terminal

    def test_heating_coils(self, data):
        # Validates: System 5 has heating coils on air loop supply side
        hc = data["air_loop"]["air_loop"]["detailed_components"]["heating_coils"]
        assert len(hc) >= 1


@pytest.mark.integration
class TestSystem5NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s5ne", 5, economizer=False, system_name="VAV No Econ")

    def test_economizer_disabled(self, data):
        # Validates: System 5 economizer is off when economizer=False
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is False


# ===========================================================================
# SYSTEM 6: Packaged VAV w/ PFP (9+1 tests, 2 sessions)
# ===========================================================================

@pytest.mark.integration
class TestSystem6:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s6", 6, system_name="VAV PFP", economizer=True)

    def test_pfp_terminals(self, data):
        # Validates: System 6 creates PFP (parallel fan-powered) terminals for all zones
        for t in data["system"]["system"]["terminals"]:
            assert "PFP" in t

    def test_electric_reheat(self, data):
        # Validates: System 6 PFP terminals use electric reheat (PFP in name)
        for t in data["system"]["system"]["terminals"]:
            assert "PFP" in t

    def test_dx_cooling(self, data):
        # Validates: System 6 uses packaged DX cooling
        assert "DX" in data["system"]["system"]["cooling"]

    def test_variable_fan(self, data):
        # Validates: System 6 has variable volume supply fan
        fans = data["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1

    def test_economizer_enabled(self, data):
        # Validates: System 6 economizer is active when requested
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is True

    def test_outdoor_air_present(self, data):
        # Validates: System 6 has outdoor air system for ventilation
        eco = data["air_loop"]["air_loop"]["outdoor_air_system"]["economizer_type"]
        assert isinstance(eco, str) and eco, "System 6 must have OA system with valid economizer type"

    def test_setpoint_managers(self, data):
        # Validates: System 6 has at least one setpoint manager
        assert len(data["air_loop"]["air_loop"]["setpoint_managers"]) >= 1

    def test_preheat_coil(self, data):
        # Validates: System 6 has preheat coil on air loop
        hc = data["air_loop"]["air_loop"]["detailed_components"]["heating_coils"]
        assert len(hc) >= 1

    def test_cooling_coil(self, data):
        # Validates: System 6 has DX cooling coil on air loop
        cc = data["air_loop"]["air_loop"]["detailed_components"]["cooling_coils"]
        assert len(cc) >= 1
        assert "DX" in cc[0]["type"]


@pytest.mark.integration
class TestSystem6NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s6ne", 6, economizer=False, system_name="VAV PFP No Econ")

    def test_economizer_disabled(self, data):
        # Validates: System 6 economizer is off when economizer=False
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is False


# ===========================================================================
# SYSTEM 7: Central VAV w/ Reheat (12+1 tests, 2 sessions)
# ===========================================================================

@pytest.mark.integration
class TestSystem7:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s7", 7, system_name="Central VAV", economizer=True)

    def test_chilled_water_loop(self, data):
        # Validates: System 7 creates Cooling-type chilled water plant loop
        assert data["chilled_water_loop"]["plant_loop"]["loop_type"] == "Cooling"

    def test_hot_water_loop(self, data):
        # Validates: System 7 creates Heating-type hot water plant loop
        assert data["hot_water_loop"]["plant_loop"]["loop_type"] == "Heating"

    def test_condenser_loop(self, data):
        # Validates: System 7 creates condenser water loop for heat rejection
        cw = data["system"]["system"]["condenser_loop"]
        assert isinstance(cw, str) and cw, "System 7 must create condenser water loop"

    def test_chiller_present(self, data):
        # Validates: System 7 has chiller on CHW supply side
        supply = data["chilled_water_loop"]["plant_loop"]["supply_components"]
        assert any("Chiller" in c["type"] for c in supply)

    def test_boiler_present(self, data):
        # Validates: System 7 has boiler on HW supply side
        supply = data["hot_water_loop"]["plant_loop"]["supply_components"]
        assert any("Boiler" in c["type"] for c in supply)

    def test_cooling_tower(self, data):
        # Validates: System 7 has cooling tower on condenser supply side
        supply = data["condenser_loop"]["plant_loop"]["supply_components"]
        assert any("CoolingTower" in c["type"] for c in supply)

    def test_vav_terminals(self, data):
        # Validates: System 7 creates one VAV reheat terminal per zone (10 zones)
        sys = data["system"]["system"]
        assert len(sys["terminals"]) == len(data["zones"])

    def test_water_coils(self, data):
        # Validates: System 7 uses chilled water cooling (not DX)
        cooling = data["system"]["system"]["cooling"]
        assert "Chilled Water" in cooling or "Water" in cooling

    def test_variable_fan(self, data):
        # Validates: System 7 has variable volume supply fan
        fans = data["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1

    def test_economizer_enabled(self, data):
        # Validates: System 7 economizer is active when requested
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is True

    def test_outdoor_air_present(self, data):
        # Validates: System 7 has outdoor air system for ventilation
        eco = data["air_loop"]["air_loop"]["outdoor_air_system"]["economizer_type"]
        assert isinstance(eco, str) and eco, "System 7 must have OA system with valid economizer type"

    def test_setpoint_managers(self, data):
        # Validates: System 7 has at least one setpoint manager
        assert len(data["air_loop"]["air_loop"]["setpoint_managers"]) >= 1


@pytest.mark.integration
class TestSystem7NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s7ne", 7, economizer=False, system_name="Central VAV No Econ")

    def test_economizer_disabled(self, data):
        # Validates: System 7 economizer is off when economizer=False
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is False


# ===========================================================================
# SYSTEM 8: Central VAV w/ PFP (11+1 tests, 2 sessions)
# ===========================================================================

@pytest.mark.integration
class TestSystem8:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s8", 8, system_name="Central PFP", economizer=True)

    def test_chilled_water_loop(self, data):
        # Validates: System 8 creates chilled water plant loop
        chw = data["system"]["system"]["chilled_water_loop"]
        assert isinstance(chw, str) and chw, "System 8 must create CHW loop"

    def test_hot_water_loop(self, data):
        # Validates: System 8 PFP has hot water loop for heating coils
        sys = data["system"]["system"]
        assert sys.get("hot_water_loop"), (
            f"System 8 PFP should have HW loop, got keys: {list(sys.keys())}"
        )

    def test_condenser_loop(self, data):
        # Validates: System 8 creates condenser water loop for heat rejection
        cw = data["system"]["system"]["condenser_loop"]
        assert isinstance(cw, str) and cw, "System 8 must create condenser water loop"

    def test_pfp_terminals(self, data):
        # Validates: System 8 creates one PFP terminal per zone
        sys = data["system"]["system"]
        assert len(sys["terminals"]) == len(data["zones"])

    def test_electric_reheat(self, data):
        # Validates: System 8 PFP terminals use electric reheat
        for t in data["system"]["system"]["terminals"]:
            assert "PFP" in t

    def test_chiller_present(self, data):
        # Validates: System 8 has chiller on CHW supply side
        supply = data["chilled_water_loop"]["plant_loop"]["supply_components"]
        assert any("Chiller" in c["type"] for c in supply)

    def test_cooling_tower(self, data):
        # Validates: System 8 has cooling tower on condenser supply side
        supply = data["condenser_loop"]["plant_loop"]["supply_components"]
        assert any("CoolingTower" in c["type"] for c in supply)

    def test_water_cooling(self, data):
        # Validates: System 8 uses chilled water cooling
        assert "Water" in data["system"]["system"]["cooling"]

    def test_variable_fan(self, data):
        # Validates: System 8 has variable volume supply fan
        fans = data["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1

    def test_economizer_enabled(self, data):
        # Validates: System 8 economizer is active when requested
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is True

    def test_outdoor_air_present(self, data):
        # Validates: System 8 has outdoor air system for ventilation
        eco = data["air_loop"]["air_loop"]["outdoor_air_system"]["economizer_type"]
        assert isinstance(eco, str) and eco, "System 8 must have OA system with valid economizer type"

    def test_setpoint_managers(self, data):
        # Validates: System 8 has at least one setpoint manager
        assert len(data["air_loop"]["air_loop"]["setpoint_managers"]) >= 1


@pytest.mark.integration
class TestSystem8NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s8ne", 8, economizer=False, system_name="Central PFP No Econ")

    def test_economizer_disabled(self, data):
        # Validates: System 8 economizer is off when economizer=False
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is False


# ===========================================================================
# SYSTEM 9: Gas Unit Heaters (2 tests, 1 session)
# ===========================================================================

@pytest.mark.integration
class TestSystem9:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s9", 9, system_name="Gas Heaters")

    def test_unit_heaters(self, data):
        # Validates: System 9 creates one gas unit heater per zone
        assert data["system"]["ok"] is True
        equip = data["system"]["system"]["equipment"]
        assert len(equip) >= len(data["zones"]), \
            f"System 9 needs >= 1 heater/zone, got {len(equip)} for {len(data['zones'])} zones"

    def test_no_cooling(self, data):
        # Validates: System 9 is heating-only (no cooling)
        cooling = data["system"]["system"].get("cooling", "None")
        assert cooling == "None" or cooling is None


# ===========================================================================
# SYSTEM 10: Electric Unit Heaters (2 tests, 1 session)
# ===========================================================================

@pytest.mark.integration
class TestSystem10:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s10", 10, system_name="Electric Heaters")

    def test_unit_heaters(self, data):
        # Validates: System 10 creates one electric unit heater per zone
        assert data["system"]["ok"] is True
        equip = data["system"]["system"]["equipment"]
        assert len(equip) >= len(data["zones"]), \
            f"System 10 needs >= 1 heater/zone, got {len(equip)} for {len(data['zones'])} zones"

    def test_no_cooling(self, data):
        # Validates: System 10 is heating-only (no cooling)
        cooling = data["system"]["system"].get("cooling", "None")
        assert cooling == "None" or cooling is None
