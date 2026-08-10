"""Integration tests for add_layer_to_construction and the assembly-R
decrease warning on assign_construction_to_surface (benchmark finding F7:
agents "insulated" roofs by replacing the whole assembly with a bare slab)."""
import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_add_layer") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


async def _load_example_model(session, name):
    create_result = unwrap(await session.call_tool("create_example_osm", {"name": name}))
    assert create_result["ok"] is True
    load_result = unwrap(await session.call_tool(
        "load_osm_model", {"osm_path": create_result["osm_path"]}))
    assert load_result["ok"] is True


async def _make_base_construction(session, construction_name):
    """3-layer assembly with exactly known R: 0.02 + 2.5 + 0.04 = 2.56 m2K/W."""
    for mat_name, thickness, conductivity in [
        ("TestMembrane", 0.01, 0.5),      # R = 0.02
        ("TestBaseInsul", 0.1, 0.04),     # R = 2.5
        ("TestDeck", 0.02, 0.5),          # R = 0.04
    ]:
        result = unwrap(await session.call_tool("create_standard_opaque_material", {
            "name": mat_name, "thickness_m": thickness,
            "conductivity_w_m_k": conductivity,
        }))
        assert result["ok"] is True, f"material {mat_name} failed: {result.get('error')}"
    result = unwrap(await session.call_tool("create_construction", {
        "name": construction_name,
        "material_names": ["TestMembrane", "TestBaseInsul", "TestDeck"],
    }))
    assert result["ok"] is True, f"base construction failed: {result.get('error')}"


async def _make_added_insulation(session):
    """One insulation layer with exactly known R: 0.089/0.04 = 2.225 m2K/W."""
    result = unwrap(await session.call_tool("create_standard_opaque_material", {
        "name": "TestAddedInsul", "thickness_m": 0.089,
        "conductivity_w_m_k": 0.04,
    }))
    assert result["ok"] is True


@pytest.mark.integration
def test_add_layer_inside_default():
    """Default position appends at the innermost face, preserving all layers."""
    # Validates: add_layer_to_construction keeps original layers, exact before/after assembly R (F7)
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # --- Arrange ---
                await _load_example_model(session, name)
                await _make_base_construction(session, "Test Roof")
                await _make_added_insulation(session)

                # --- Act ---
                result = unwrap(await session.call_tool("add_layer_to_construction", {
                    "construction_name": "Test Roof",
                    "material_name": "TestAddedInsul",
                }))

                # --- Assert ---
                assert result["ok"] is True, f"add_layer failed: {result.get('error')}"
                assert result["construction"]["name"] == "Test Roof + TestAddedInsul"
                assert result["construction"]["num_layers"] == 4
                assert result["construction"]["layers"] == [
                    "TestMembrane", "TestBaseInsul", "TestDeck", "TestAddedInsul"]
                assert result["source_construction"] == "Test Roof"
                assert result["assembly_r_si_before"] == pytest.approx(2.56, abs=1e-3)
                assert result["assembly_r_si_after"] == pytest.approx(4.785, abs=1e-3)

                # Source construction untouched — still its original 3 layers
                details = unwrap(await session.call_tool("get_construction_details", {
                    "construction_name": "Test Roof"}))
                assert details["construction"]["num_layers"] == 3

    asyncio.run(_run())


@pytest.mark.integration
def test_add_layer_outside_position():
    """position="outside" slots the layer directly beneath the outermost layer."""
    # Validates: outside insert keeps the weather/finish layer outermost (above-deck insulation convention)
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _load_example_model(session, name)
                await _make_base_construction(session, "Test Roof Out")
                await _make_added_insulation(session)

                result = unwrap(await session.call_tool("add_layer_to_construction", {
                    "construction_name": "Test Roof Out",
                    "material_name": "TestAddedInsul",
                    "position": "outside",
                    "new_construction_name": "Roof Above Deck",
                }))

                assert result["ok"] is True, f"add_layer failed: {result.get('error')}"
                assert result["construction"]["name"] == "Roof Above Deck"
                assert result["construction"]["layers"] == [
                    "TestMembrane", "TestAddedInsul", "TestBaseInsul", "TestDeck"]
                assert result["assembly_r_si_after"] == pytest.approx(4.785, abs=1e-3)

    asyncio.run(_run())


@pytest.mark.integration
def test_add_layer_missing_construction():
    """Unknown construction fails with a clear error."""
    # Validates: add_layer_to_construction rejects nonexistent construction with error
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _load_example_model(session, name)
                await _make_added_insulation(session)

                result = unwrap(await session.call_tool("add_layer_to_construction", {
                    "construction_name": "NoSuchConstruction",
                    "material_name": "TestAddedInsul",
                }))
                assert result["ok"] is False
                assert "not found" in result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_add_layer_missing_material():
    """Unknown material fails and points at create_standard_opaque_material."""
    # Validates: add_layer_to_construction rejects nonexistent material and hints creation tool
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _load_example_model(session, name)
                await _make_base_construction(session, "Test Roof NoMat")

                result = unwrap(await session.call_tool("add_layer_to_construction", {
                    "construction_name": "Test Roof NoMat",
                    "material_name": "NoSuchMaterial",
                }))
                assert result["ok"] is False
                assert "not found" in result["error"].lower()
                assert "create_standard_opaque_material" in result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_assign_construction_r_decrease_warning():
    """Replacing a high-R assembly with a bare slab warns and hints the additive path."""
    # Regression: benchmark F7 — every model replaced multi-layer roofs with a single
    # insulation slab, lowering assembly R, and got a silent ok:True
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # --- Arrange ---
                await _load_example_model(session, name)
                await _make_base_construction(session, "Good Roof")  # R = 2.56
                result = unwrap(await session.call_tool("create_standard_opaque_material", {
                    "name": "BareSlab", "thickness_m": 0.02,
                    "conductivity_w_m_k": 0.04,  # R = 0.5
                }))
                assert result["ok"] is True
                result = unwrap(await session.call_tool("create_construction", {
                    "name": "Bare Slab Roof", "material_names": ["BareSlab"],
                }))
                assert result["ok"] is True

                surfaces = unwrap(await session.call_tool("list_surfaces", {"max_results": 0}))
                surface_name = surfaces["surfaces"][0]["name"]
                assign = unwrap(await session.call_tool("assign_construction_to_surface", {
                    "surface_name": surface_name, "construction_name": "Good Roof",
                }))
                assert assign["ok"] is True
                assert assign["assembly_r_si"] == pytest.approx(2.56, abs=1e-3)

                # --- Act: the F7 anti-pattern (whole-assembly replacement) ---
                assign = unwrap(await session.call_tool("assign_construction_to_surface", {
                    "surface_name": surface_name, "construction_name": "Bare Slab Roof",
                }))

                # --- Assert ---
                assert assign["ok"] is True  # warn, never hard-fail: lowering R is legitimate
                assert assign["previous_construction"] == "Good Roof"
                assert assign["previous_assembly_r_si"] == pytest.approx(2.56, abs=1e-3)
                assert assign["assembly_r_si"] == pytest.approx(0.5, abs=1e-3)
                assert "add_layer_to_construction" in assign["warning"], (
                    f"warning must hint the additive path, got: {assign['warning']}")

                # Restoring the better assembly must NOT warn
                assign = unwrap(await session.call_tool("assign_construction_to_surface", {
                    "surface_name": surface_name, "construction_name": "Good Roof",
                }))
                assert assign["ok"] is True
                assert "warning" not in assign, (
                    f"R increase must not warn: {assign.get('warning')}")

    asyncio.run(_run())
