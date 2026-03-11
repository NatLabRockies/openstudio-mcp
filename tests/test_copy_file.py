"""Integration tests for read_file and copy_file tools."""
import asyncio
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_file") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.mark.integration
def test_read_file_absolute_path():
    """read_file reads a file by absolute path."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    run_id = _unique()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create example model to get a known file
                cr = await session.call_tool("create_example_osm", {"name": run_id})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd
                osm_path = cd["osm_path"]

                # Read it via absolute path
                resp = await session.call_tool("read_file", {"file_path": osm_path})
                result = unwrap(resp)
                print("read_file:", result.get("ok"), result.get("file_size"))
                assert result.get("ok") is True, result
                assert result["kind"] == "text"
                assert result["file_size"] > 0
                assert "file_path" in result

    asyncio.run(_run())


@pytest.mark.integration
def test_read_file_rejects_outside_mounts():
    """read_file returns error for paths outside allowed roots."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resp = await session.call_tool("read_file", {"file_path": "/etc/passwd"})
                result = unwrap(resp)
                print("read_file reject:", result)
                assert result.get("ok") is False
                assert "invalid_path" in result.get("error", "")

    asyncio.run(_run())


@pytest.mark.integration
def test_copy_file_absolute_path():
    """copy_file copies a file by absolute path."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    run_id = _unique()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create example model to get a known file
                cr = await session.call_tool("create_example_osm", {"name": run_id})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd
                osm_path = cd["osm_path"]

                # Copy via absolute path
                resp = await session.call_tool("copy_file", {
                    "file_path": osm_path,
                })
                result = unwrap(resp)
                print("copy_file:", result)
                assert result.get("ok") is True, result
                assert "destination" in result
                assert result["size_bytes"] > 0

    asyncio.run(_run())


@pytest.mark.integration
def test_copy_file_rejects_escape():
    """copy_file returns error for paths outside allowed roots."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resp = await session.call_tool("copy_file", {
                    "file_path": "/etc/passwd",
                })
                result = unwrap(resp)
                print("copy_file reject:", result)
                assert result.get("ok") is False

    asyncio.run(_run())
