"""Integration tests for measures tools (Phase 6D).

Tests list_measure_arguments, apply_measure.
Uses a minimal test measure at tests/assets/measures/set_building_name/.
"""

import asyncio
import json
import os
import shlex
import uuid

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _integration_enabled() -> bool:
    return os.environ.get("RUN_OPENSTUDIO_INTEGRATION", "").strip() in ("1", "true", "TRUE", "yes", "YES")


def _unwrap(res):
    if isinstance(res, dict):
        return res
    content = getattr(res, "content", None)
    if not content:
        return res
    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        return str(first)
    t = text.strip()
    if not t:
        return t
    try:
        return json.loads(t)
    except Exception:
        return t


def _unique(prefix: str = "pytest_measures") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _server_params():
    cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    args = shlex.split(args_env) if args_env else []
    return StdioServerParameters(command=cmd, args=args, env=os.environ.copy())


# Measure path inside container (repo mounted at /repo)
MEASURE_DIR = "/repo/tests/assets/measures/set_building_name"


async def _setup_example(session, model_name):
    cr = _unwrap(await session.call_tool("create_example_osm", {"name": model_name}))
    assert cr.get("ok") is True
    lr = _unwrap(await session.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr.get("ok") is True


@pytest.mark.integration
def test_list_measure_arguments():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            res = _unwrap(
                await s.call_tool(
                    "list_measure_arguments",
                    {
                        "measure_dir": MEASURE_DIR,
                    },
                ),
            )
            assert res.get("ok") is True
            assert len(res["arguments"]) >= 1
            # Check building_name argument exists
            arg_names = [a["name"] for a in res["arguments"]]
            assert "building_name" in arg_names

    asyncio.run(_run())


@pytest.mark.integration
def test_list_measure_not_found():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            res = _unwrap(
                await s.call_tool(
                    "list_measure_arguments",
                    {
                        "measure_dir": "/nonexistent/measure",
                    },
                ),
            )
            assert res.get("ok") is False

    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_default_args():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            res = _unwrap(
                await s.call_tool(
                    "apply_measure",
                    {
                        "measure_dir": MEASURE_DIR,
                    },
                ),
            )
            assert res.get("ok") is True
            # After measure, building name should be "Test Building" (default)
            bldg = _unwrap(await s.call_tool("get_building_info", {}))
            assert bldg.get("ok") is True
            assert bldg["building"]["name"] == "Test Building"

    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_custom_args():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            res = _unwrap(
                await s.call_tool(
                    "apply_measure",
                    {
                        "measure_dir": MEASURE_DIR,
                        "arguments": {"building_name": "My Custom Building"},
                    },
                ),
            )
            assert res.get("ok") is True
            bldg = _unwrap(await s.call_tool("get_building_info", {}))
            assert bldg.get("ok") is True
            assert bldg["building"]["name"] == "My Custom Building"

    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_invalid_dir():
    """Measure with bad directory path."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            res = _unwrap(
                await s.call_tool(
                    "apply_measure",
                    {
                        "measure_dir": "/nonexistent/measure",
                    },
                ),
            )
            assert res.get("ok") is False

    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_verify_model_changed():
    """Verify model state changed after measure application."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            # Get original building name
            bldg_before = _unwrap(await s.call_tool("get_building_info", {}))
            original_name = bldg_before["building"]["name"]
            # Apply measure with different name
            new_name = f"Changed_{uuid.uuid4().hex[:6]}"
            res = _unwrap(
                await s.call_tool(
                    "apply_measure",
                    {
                        "measure_dir": MEASURE_DIR,
                        "arguments": {"building_name": new_name},
                    },
                ),
            )
            assert res.get("ok") is True
            # Verify changed
            bldg_after = _unwrap(await s.call_tool("get_building_info", {}))
            assert bldg_after["building"]["name"] == new_name
            assert bldg_after["building"]["name"] != original_name

    asyncio.run(_run())
