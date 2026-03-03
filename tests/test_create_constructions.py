import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_construction") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_create_standard_opaque_material():
    """Test creating a standard opaque material."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Create material
                material_resp = await session.call_tool("create_standard_opaque_material", {
                    "name": "Test Concrete",
                    "roughness": "Rough",
                    "thickness_m": 0.2,
                    "conductivity_w_m_k": 1.7,
                    "density_kg_m3": 2400.0,
                    "specific_heat_j_kg_k": 900.0,
                })
                material_result = unwrap(material_resp)

                assert material_result.get("ok") is True
                assert material_result["material"]["name"] == "Test Concrete"
                assert material_result["material"]["thickness_m"] == 0.2
                assert material_result["material"]["conductivity_w_m_k"] == 1.7

                # Verify it appears in list
                list_resp = await session.call_tool("list_materials", {})
                list_result = unwrap(list_resp)
                assert any(m["name"] == "Test Concrete" for m in list_result["materials"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_material_no_model_loaded():
    """Test error when no model is loaded."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to create material without loading model
                material_resp = await session.call_tool("create_standard_opaque_material", {"name": "Should Fail"})
                material_result = unwrap(material_resp)

                assert material_result.get("ok") is False
                assert "error" in material_result
                assert "No model loaded" in material_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_create_construction_from_materials():
    """Test creating a construction from materials."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Create materials
                mat1_resp = await session.call_tool("create_standard_opaque_material", {
                    "name": "Exterior Finish",
                    "thickness_m": 0.01,
                })
                assert unwrap(mat1_resp).get("ok") is True

                mat2_resp = await session.call_tool("create_standard_opaque_material", {
                    "name": "Insulation",
                    "thickness_m": 0.1,
                    "conductivity_w_m_k": 0.04,
                })
                assert unwrap(mat2_resp).get("ok") is True

                mat3_resp = await session.call_tool("create_standard_opaque_material", {
                    "name": "Interior Finish",
                    "thickness_m": 0.01,
                })
                assert unwrap(mat3_resp).get("ok") is True

                # Create construction
                construction_resp = await session.call_tool("create_construction", {
                    "name": "Test Wall Construction",
                    "material_names": ["Exterior Finish", "Insulation", "Interior Finish"],
                })
                construction_result = unwrap(construction_resp)

                assert construction_result.get("ok") is True
                assert construction_result["construction"]["name"] == "Test Wall Construction"
                assert construction_result["construction"]["num_layers"] == 3
                assert construction_result["construction"]["layers"] == ["Exterior Finish", "Insulation", "Interior Finish"]

                # Verify it appears in list
                list_resp = await session.call_tool("list_constructions", {})
                list_result = unwrap(list_resp)
                assert any(c["name"] == "Test Wall Construction" for c in list_result["constructions"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_construction_invalid_material():
    """Test error when material doesn't exist."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Try to create construction with non-existent material
                construction_resp = await session.call_tool("create_construction", {
                    "name": "Test Construction",
                    "material_names": ["NonexistentMaterial"],
                })
                construction_result = unwrap(construction_resp)

                assert construction_result.get("ok") is False
                assert "error" in construction_result
                assert "not found" in construction_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_assign_construction_to_surface():
    """Test assigning a construction to a surface."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Get a surface name
                surfaces_resp = await session.call_tool("list_surfaces", {})
                surfaces_result = unwrap(surfaces_resp)
                assert len(surfaces_result["surfaces"]) > 0
                surface_name = surfaces_result["surfaces"][0]["name"]

                # Get an existing construction name
                constructions_resp = await session.call_tool("list_constructions", {})
                constructions_result = unwrap(constructions_resp)
                assert len(constructions_result["constructions"]) > 0
                construction_name = constructions_result["constructions"][0]["name"]

                # Assign construction to surface
                assign_resp = await session.call_tool("assign_construction_to_surface", {
                    "surface_name": surface_name,
                    "construction_name": construction_name,
                })
                assign_result = unwrap(assign_resp)

                assert assign_result.get("ok") is True
                assert assign_result["surface"]["name"] == surface_name
                assert assign_result["surface"]["construction"] == construction_name

                # Independent query verification
                sd = unwrap(await session.call_tool("get_surface_details", {
                    "surface_name": surface_name,
                }))
                assert sd["surface"]["construction"] == construction_name

    asyncio.run(_run())


@pytest.mark.integration
def test_assign_construction_invalid_surface():
    """Test error when surface doesn't exist."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Try to assign to non-existent surface
                assign_resp = await session.call_tool("assign_construction_to_surface", {
                    "surface_name": "NonexistentSurface",
                    "construction_name": "Any Construction",
                })
                assign_result = unwrap(assign_resp)

                assert assign_result.get("ok") is False
                assert "error" in assign_result
                assert "not found" in assign_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_end_to_end_construction_workflow():
    """Test complete workflow: create materials -> construction -> assign to surface."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Step 1: Create materials
                await session.call_tool("create_standard_opaque_material", {
                    "name": "Brick",
                    "thickness_m": 0.1,
                    "conductivity_w_m_k": 0.8,
                })
                await session.call_tool("create_standard_opaque_material", {
                    "name": "Foam Insulation",
                    "thickness_m": 0.05,
                    "conductivity_w_m_k": 0.03,
                })
                await session.call_tool("create_standard_opaque_material", {
                    "name": "Gypsum",
                    "thickness_m": 0.015,
                    "conductivity_w_m_k": 0.16,
                })

                # Step 2: Create construction
                construction_resp = await session.call_tool("create_construction", {
                    "name": "Insulated Brick Wall",
                    "material_names": ["Brick", "Foam Insulation", "Gypsum"],
                })
                construction_result = unwrap(construction_resp)
                assert construction_result.get("ok") is True

                # Step 3: Get a surface
                surfaces_resp = await session.call_tool("list_surfaces", {})
                surfaces_result = unwrap(surfaces_resp)
                surface_name = surfaces_result["surfaces"][0]["name"]

                # Step 4: Assign construction to surface
                assign_resp = await session.call_tool("assign_construction_to_surface", {
                    "surface_name": surface_name,
                    "construction_name": "Insulated Brick Wall",
                })
                assign_result = unwrap(assign_resp)
                assert assign_result.get("ok") is True
                assert assign_result["surface"]["construction"] == "Insulated Brick Wall"

                # Independent query verification
                sd = unwrap(await session.call_tool("get_surface_details", {
                    "surface_name": surface_name,
                }))
                assert sd["surface"]["construction"] == "Insulated Brick Wall"

    asyncio.run(_run())
