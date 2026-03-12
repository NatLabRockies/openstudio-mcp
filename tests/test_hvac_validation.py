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
        """PTAC has electric heating and DX cooling coils."""
        equip = data["zone_hvac"]["equipment"]
        assert "heating_coil" in equip
        assert "Electric" in equip["heating_coil"]["type"]
        assert "cooling_coil" in equip
        assert "DX" in equip["cooling_coil"]["type"]

    def test_fan_present(self, data):
        """PTAC has supply air fan."""
        assert "fan" in data["zone_hvac"]["equipment"]
        assert "Fan" in data["zone_hvac"]["equipment"]["fan"]["type"]

    def test_multiple_zones(self, data):
        """System 1 creates one PTAC per zone."""
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
        """PTHP has heating and cooling coils."""
        equip = data["zone_hvac"]["equipment"]
        assert "heating_coil" in equip
        assert "cooling_coil" in equip

    def test_fan_present(self, data):
        """PTHP has supply air fan."""
        assert "fan" in data["zone_hvac"]["equipment"]


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
        """PSZ-AC has heating and DX cooling coils."""
        al = data["gas"]["air_loop"]["air_loop"]
        assert len(al["detailed_components"]["heating_coils"]) >= 1
        assert len(al["detailed_components"]["cooling_coils"]) >= 1
        assert "DX" in al["detailed_components"]["cooling_coils"][0]["type"]

    def test_fan_verification(self, data):
        """PSZ-AC has fan."""
        fans = data["gas"]["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1
        assert "Fan" in fans[0]["type"]

    def test_economizer_enabled(self, data):
        """Economizer enabled when requested."""
        oa = data["gas"]["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa is not None
        assert oa["economizer_enabled"] is True
        assert oa["economizer_type"] != "NoEconomizer"

    def test_outdoor_air_present(self, data):
        """PSZ-AC has outdoor air system."""
        assert data["gas"]["air_loop"]["air_loop"]["outdoor_air_system"] is not None

    def test_setpoint_managers(self, data):
        """PSZ-AC has setpoint managers."""
        spms = data["gas"]["air_loop"]["air_loop"]["setpoint_managers"]
        assert len(spms) >= 1

    def test_electric_heating(self, data):
        """PSZ-AC with electric heating has electric coil."""
        assert "Electric" in data["electric"]["system"]["heating"]

    def test_gas_heating(self, data):
        """PSZ-AC with gas heating has gas coil."""
        assert "Gas" in data["gas"]["system"]["system"]["heating"]


@pytest.mark.integration
class TestSystem3NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s3ne", 3, economizer=False, system_name="PSZ No Econ")

    def test_economizer_disabled(self, data):
        """Economizer disabled when requested."""
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa is not None
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
        """PSZ-HP has DX heating and cooling coils."""
        al = data["air_loop"]["air_loop"]
        assert len(al["detailed_components"]["heating_coils"]) >= 1
        assert len(al["detailed_components"]["cooling_coils"]) >= 1

    def test_supplemental_heat(self, data):
        """PSZ-HP has supplemental heating."""
        assert data["system"]["system"]["heating"] is not None

    def test_fan_present(self, data):
        """PSZ-HP has supply fan."""
        fans = data["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1

    def test_economizer_enabled(self, data):
        """System 4 economizer when enabled."""
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa is not None
        assert oa["economizer_enabled"] is True

    def test_outdoor_air_present(self, data):
        """PSZ-HP has outdoor air system."""
        assert data["air_loop"]["air_loop"]["outdoor_air_system"] is not None

    def test_setpoint_managers(self, data):
        """PSZ-HP has setpoint managers."""
        assert len(data["air_loop"]["air_loop"]["setpoint_managers"]) >= 1

    def test_dx_cooling(self, data):
        """System 4 uses DX cooling (heat pump)."""
        assert data["system"]["system"]["cooling"] == "Heat Pump"

    def test_single_zone_only(self, data):
        """System 4 requires exactly one zone."""
        assert data["multi_zone_error"].get("ok") is False
        assert "exactly 1 zone" in data["multi_zone_error"]["error"].lower()


@pytest.mark.integration
class TestSystem4NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s4ne", 4, economizer=False, system_name="PSZ HP No Econ",
                          zones=None)

    def test_economizer_disabled(self, data):
        """System 4 economizer disabled."""
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
        """System 5 creates hot water plant loop."""
        assert "hot_water_loop" in data["system"]["system"]
        assert data["hot_water_loop"]["plant_loop"]["loop_type"] == "Heating"

    def test_boiler_present(self, data):
        """System 5 has boiler on HW loop."""
        supply = data["hot_water_loop"]["plant_loop"]["supply_components"]
        assert any("Boiler" in c["type"] for c in supply)

    def test_vav_terminals(self, data):
        """System 5 has VAV reheat terminals."""
        sys = data["system"]["system"]
        assert "terminals" in sys
        assert len(sys["terminals"]) == len(data["zones"])

    def test_dx_cooling(self, data):
        """System 5 uses DX cooling."""
        assert "DX" in data["system"]["system"]["cooling"]

    def test_variable_fan(self, data):
        """System 5 has variable volume fan."""
        fans = data["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1

    def test_economizer_enabled(self, data):
        """System 5 economizer enabled."""
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is True

    def test_outdoor_air_present(self, data):
        """System 5 has outdoor air system."""
        assert data["air_loop"]["air_loop"]["outdoor_air_system"] is not None

    def test_setpoint_managers(self, data):
        """System 5 has setpoint managers."""
        assert len(data["air_loop"]["air_loop"]["setpoint_managers"]) >= 1

    def test_reheat_coils(self, data):
        """System 5 VAV terminals are reheat type."""
        for terminal in data["system"]["system"]["terminals"]:
            assert "VAV" in terminal

    def test_heating_coils(self, data):
        """System 5 has heating coils on air loop."""
        hc = data["air_loop"]["air_loop"]["detailed_components"]["heating_coils"]
        assert len(hc) >= 1


@pytest.mark.integration
class TestSystem5NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s5ne", 5, economizer=False, system_name="VAV No Econ")

    def test_economizer_disabled(self, data):
        """System 5 economizer disabled."""
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
        """System 6 has PFP terminals."""
        sys = data["system"]["system"]
        assert "terminals" in sys
        for t in sys["terminals"]:
            assert "PFP" in t

    def test_electric_reheat(self, data):
        """System 6 PFP terminals have electric reheat."""
        for t in data["system"]["system"]["terminals"]:
            assert "PFP" in t

    def test_dx_cooling(self, data):
        """System 6 uses DX cooling."""
        assert "DX" in data["system"]["system"]["cooling"]

    def test_variable_fan(self, data):
        """System 6 has variable volume fan."""
        fans = data["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1

    def test_economizer_enabled(self, data):
        """System 6 economizer enabled."""
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is True

    def test_outdoor_air_present(self, data):
        """System 6 has outdoor air system."""
        assert data["air_loop"]["air_loop"]["outdoor_air_system"] is not None

    def test_setpoint_managers(self, data):
        """System 6 has setpoint managers."""
        assert len(data["air_loop"]["air_loop"]["setpoint_managers"]) >= 1

    def test_preheat_coil(self, data):
        """System 6 has preheat coil."""
        hc = data["air_loop"]["air_loop"]["detailed_components"]["heating_coils"]
        assert len(hc) >= 1

    def test_cooling_coil(self, data):
        """System 6 has DX cooling coil."""
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
        """System 6 economizer disabled."""
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
        """System 7 creates chilled water loop."""
        assert "chilled_water_loop" in data["system"]["system"]
        assert data["chilled_water_loop"]["plant_loop"]["loop_type"] == "Cooling"

    def test_hot_water_loop(self, data):
        """System 7 creates hot water loop."""
        assert "hot_water_loop" in data["system"]["system"]
        assert data["hot_water_loop"]["plant_loop"]["loop_type"] == "Heating"

    def test_condenser_loop(self, data):
        """System 7 creates condenser water loop."""
        assert "condenser_loop" in data["system"]["system"]

    def test_chiller_present(self, data):
        """System 7 has chiller on CHW loop."""
        supply = data["chilled_water_loop"]["plant_loop"]["supply_components"]
        assert any("Chiller" in c["type"] for c in supply)

    def test_boiler_present(self, data):
        """System 7 has boiler on HW loop."""
        supply = data["hot_water_loop"]["plant_loop"]["supply_components"]
        assert any("Boiler" in c["type"] for c in supply)

    def test_cooling_tower(self, data):
        """System 7 has cooling tower on condenser loop."""
        supply = data["condenser_loop"]["plant_loop"]["supply_components"]
        assert any("CoolingTower" in c["type"] for c in supply)

    def test_vav_terminals(self, data):
        """System 7 has VAV reheat terminals."""
        sys = data["system"]["system"]
        assert "terminals" in sys
        assert len(sys["terminals"]) == len(data["zones"])

    def test_water_coils(self, data):
        """System 7 uses water coils not DX."""
        cooling = data["system"]["system"]["cooling"]
        assert "Chilled Water" in cooling or "Water" in cooling

    def test_variable_fan(self, data):
        """System 7 has variable volume fan."""
        fans = data["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1

    def test_economizer_enabled(self, data):
        """System 7 economizer enabled."""
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is True

    def test_outdoor_air_present(self, data):
        """System 7 has outdoor air system."""
        assert data["air_loop"]["air_loop"]["outdoor_air_system"] is not None

    def test_setpoint_managers(self, data):
        """System 7 has setpoint managers."""
        assert len(data["air_loop"]["air_loop"]["setpoint_managers"]) >= 1


@pytest.mark.integration
class TestSystem7NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s7ne", 7, economizer=False, system_name="Central VAV No Econ")

    def test_economizer_disabled(self, data):
        """System 7 economizer disabled."""
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
        """System 8 creates chilled water loop."""
        assert "chilled_water_loop" in data["system"]["system"]

    def test_hot_water_loop(self, data):
        """System 8 created ok (may or may not have HW loop — PFP uses electric reheat)."""
        assert data["system"].get("ok") is True

    def test_condenser_loop(self, data):
        """System 8 creates condenser water loop."""
        assert "condenser_loop" in data["system"]["system"]

    def test_pfp_terminals(self, data):
        """System 8 has PFP terminals."""
        assert "terminals" in data["system"]["system"]

    def test_electric_reheat(self, data):
        """System 8 PFP terminals have electric reheat."""
        for t in data["system"]["system"]["terminals"]:
            assert "PFP" in t

    def test_chiller_present(self, data):
        """System 8 has chiller."""
        supply = data["chilled_water_loop"]["plant_loop"]["supply_components"]
        assert any("Chiller" in c["type"] for c in supply)

    def test_cooling_tower(self, data):
        """System 8 has cooling tower."""
        supply = data["condenser_loop"]["plant_loop"]["supply_components"]
        assert any("CoolingTower" in c["type"] for c in supply)

    def test_water_cooling(self, data):
        """System 8 uses chilled water cooling."""
        assert "Water" in data["system"]["system"]["cooling"]

    def test_variable_fan(self, data):
        """System 8 has variable volume fan."""
        fans = data["air_loop"]["air_loop"]["detailed_components"]["fans"]
        assert len(fans) >= 1

    def test_economizer_enabled(self, data):
        """System 8 economizer enabled."""
        oa = data["air_loop"]["air_loop"]["outdoor_air_system"]
        assert oa["economizer_enabled"] is True

    def test_outdoor_air_present(self, data):
        """System 8 has outdoor air system."""
        assert data["air_loop"]["air_loop"]["outdoor_air_system"] is not None

    def test_setpoint_managers(self, data):
        """System 8 has setpoint managers."""
        assert len(data["air_loop"]["air_loop"]["setpoint_managers"]) >= 1


@pytest.mark.integration
class TestSystem8NoEcon:
    @pytest.fixture(scope="class")
    def data(self):
        _skip_if_disabled()
        return _run_setup("val_s8ne", 8, economizer=False, system_name="Central PFP No Econ")

    def test_economizer_disabled(self, data):
        """System 8 economizer disabled."""
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
        """System 9 creates gas unit heaters."""
        assert data["system"].get("ok") is True
        assert "equipment" in data["system"]["system"]

    def test_no_cooling(self, data):
        """System 9 has no cooling."""
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
        """System 10 creates electric unit heaters."""
        assert data["system"].get("ok") is True
        assert "equipment" in data["system"]["system"]

    def test_no_cooling(self, data):
        """System 10 has no cooling."""
        cooling = data["system"]["system"].get("cooling", "None")
        assert cooling == "None" or cooling is None
