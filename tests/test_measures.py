"""Integration tests for measures tools (Phase 6D).

Tests list_measure_arguments, apply_measure.
Uses a minimal test measure at tests/assets/measures/set_building_name/.
"""
import asyncio
import uuid

import pytest

from conftest import unwrap, integration_enabled, server_params, setup_example
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_measures") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# Measure path inside container (repo mounted at /repo)
MEASURE_DIR = "/repo/tests/assets/measures/set_building_name"


@pytest.mark.integration
def test_list_measure_arguments():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": MEASURE_DIR
                }))
                assert res.get("ok") is True
                assert len(res["arguments"]) >= 1
                # Check building_name argument exists
                arg_names = [a["name"] for a in res["arguments"]]
                assert "building_name" in arg_names
    asyncio.run(_run())


@pytest.mark.integration
def test_list_measure_not_found():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": "/nonexistent/measure"
                }))
                assert res.get("ok") is False
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_default_args():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR
                }))
                assert res.get("ok") is True
                # After measure, building name should be "Test Building" (default)
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg.get("ok") is True
                assert bldg["building"]["name"] == "Test Building"
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_custom_args():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                    "arguments": {"building_name": "My Custom Building"}
                }))
                assert res.get("ok") is True
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg.get("ok") is True
                assert bldg["building"]["name"] == "My Custom Building"
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_invalid_dir():
    """Measure with bad directory path."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": "/nonexistent/measure"
                }))
                assert res.get("ok") is False
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_verify_model_changed():
    """Verify model state changed after measure application."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Get original building name
                bldg_before = unwrap(await s.call_tool("get_building_info", {}))
                original_name = bldg_before["building"]["name"]
                # Apply measure with different name
                new_name = f"Changed_{uuid.uuid4().hex[:6]}"
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                    "arguments": {"building_name": new_name}
                }))
                assert res.get("ok") is True
                # Verify changed
                bldg_after = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg_after["building"]["name"] == new_name
                assert bldg_after["building"]["name"] != original_name
    asyncio.run(_run())
