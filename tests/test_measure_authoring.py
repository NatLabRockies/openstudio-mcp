"""Integration tests for measure authoring tools (Phase 9).

Tests create_measure, test_measure, edit_measure.
"""
import asyncio
import uuid

import pytest
from conftest import integration_enabled, server_params, setup_example, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_authoring") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


RUBY_BODY = '    model.getBuilding.setName("MeasureWasHere")\n    runner.registerInfo("Done")'
PYTHON_BODY = '        model.getBuilding().setName("MeasureWasHere")\n        runner.registerInfo("Done")'

RUBY_ARGS = [
    {"name": "r_value", "display_name": "R-Value", "type": "Double",
     "required": True, "default_value": "13"},
    {"name": "apply_to_walls", "display_name": "Apply to Walls",
     "type": "Boolean", "required": True, "default_value": "true"},
]

PYTHON_ARGS = [
    {"name": "wall_name", "display_name": "Wall Name", "type": "String",
     "required": False, "default_value": "exterior"},
]


@pytest.mark.integration
def test_list_custom_measures():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # Create a measure first
                name = _unique("list_meas")
                unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Listable measure",
                    "run_body": RUBY_BODY,
                    "language": "Ruby",
                }))
                # List and verify it appears
                res = unwrap(await s.call_tool("list_custom_measures", {}))
                assert res.get("ok") is True
                assert res["count"] >= 1
                names = [m["name"] for m in res["measures"]]
                assert name in names
    asyncio.run(_run())


@pytest.mark.integration
def test_create_measure_ruby():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("ruby_meas")
                res = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Test ruby measure",
                    "run_body": RUBY_BODY,
                    "language": "Ruby",
                }))
                assert res.get("ok") is True, res
                assert res["language"] == "Ruby"
                assert res["script_file"] == "measure.rb"
                assert res["validation"]["syntax_ok"] is True
    asyncio.run(_run())


@pytest.mark.integration
def test_create_measure_python():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("py_meas")
                res = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Test python measure",
                    "run_body": PYTHON_BODY,
                    "language": "Python",
                }))
                assert res.get("ok") is True, res
                assert res["language"] == "Python"
                assert res["script_file"] == "measure.py"
                assert res["validation"]["syntax_ok"] is True
    asyncio.run(_run())


@pytest.mark.integration
def test_create_with_arguments():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("args_meas")
                res = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Measure with typed args",
                    "run_body": RUBY_BODY,
                    "language": "Ruby",
                    "arguments": RUBY_ARGS,
                }))
                assert res.get("ok") is True, res
                # Verify args via list_measure_arguments
                args_res = unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": res["measure_dir"],
                }))
                assert args_res.get("ok") is True
                arg_names = [a["name"] for a in args_res["arguments"]]
                assert "r_value" in arg_names
                assert "apply_to_walls" in arg_names
    asyncio.run(_run())


@pytest.mark.integration
def test_create_bad_syntax():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("bad_meas")
                res = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Bad syntax measure",
                    "run_body": "    def def def broken",
                    "language": "Ruby",
                }))
                # Should still create but report syntax error
                assert res.get("ok") is True
                assert res["validation"]["syntax_ok"] is False
    asyncio.run(_run())


@pytest.mark.integration
def test_test_measure_ruby_passes():
    """Create a simple Ruby measure, run its tests."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("test_rb")
                body = '    runner.registerInfo("hello")'
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Simple test measure",
                    "run_body": body,
                    "language": "Ruby",
                }))
                assert create.get("ok") is True
                res = unwrap(await s.call_tool("test_measure", {
                    "measure_dir": create["measure_dir"],
                }))
                assert res.get("ok") is True, res.get("test_output", "")
                assert res["passed"] > 0
    asyncio.run(_run())


@pytest.mark.integration
def test_test_measure_python_passes():
    """Create a simple Python measure, run its tests."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("test_py")
                body = '        runner.registerInfo("hello")'
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Simple test measure",
                    "run_body": body,
                    "language": "Python",
                }))
                assert create.get("ok") is True
                res = unwrap(await s.call_tool("test_measure", {
                    "measure_dir": create["measure_dir"],
                }))
                assert res.get("ok") is True, res.get("test_output", "")
                assert res["passed"] > 0
    asyncio.run(_run())


@pytest.mark.integration
def test_test_measure_reports_errors():
    """Create measure with failing code, verify test reports failure."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("fail_meas")
                # Ruby code that raises at runtime
                body = '    raise "intentional failure"'
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Failing measure",
                    "run_body": body,
                    "language": "Ruby",
                }))
                assert create.get("ok") is True
                res = unwrap(await s.call_tool("test_measure", {
                    "measure_dir": create["measure_dir"],
                }))
                # Should report failures or errors
                assert res.get("ok") is False or res.get("failed", 0) > 0 or res.get("errors", 0) > 0
    asyncio.run(_run())


@pytest.mark.integration
def test_edit_run_body():
    """Create measure, edit run body, verify updated."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("edit_body")
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Editable measure",
                    "run_body": '    runner.registerInfo("v1")',
                    "language": "Ruby",
                }))
                assert create.get("ok") is True
                edit = unwrap(await s.call_tool("edit_measure", {
                    "measure_name": name,
                    "run_body": '    runner.registerInfo("v2")',
                }))
                assert edit.get("ok") is True
                assert "run_body" in edit["changes_made"]
                assert edit["validation"]["syntax_ok"] is True
    asyncio.run(_run())


@pytest.mark.integration
def test_edit_arguments():
    """Create measure, edit arguments, verify XML updated."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("edit_args")
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Args measure",
                    "run_body": '    runner.registerInfo("ok")',
                    "language": "Ruby",
                    "arguments": [{"name": "old_arg", "type": "String", "required": True, "default_value": "x"}],
                }))
                assert create.get("ok") is True
                new_args = [
                    {"name": "new_arg", "type": "Double", "required": True, "default_value": "42"},
                ]
                edit = unwrap(await s.call_tool("edit_measure", {
                    "measure_name": name,
                    "arguments": new_args,
                }))
                assert edit.get("ok") is True
                assert "arguments" in edit["changes_made"]
                # Verify via list_measure_arguments
                args_res = unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": edit["measure_dir"],
                }))
                assert args_res.get("ok") is True
                arg_names = [a["name"] for a in args_res["arguments"]]
                assert "new_arg" in arg_names
    asyncio.run(_run())


@pytest.mark.integration
def test_full_lifecycle():
    """Create → test → apply → verify model changed."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique("lifecycle"))

                # Get original name
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                original = bldg["building"]["name"]

                # Create measure
                name = _unique("lifecycle_m")
                new_bldg_name = f"Lifecycle_{uuid.uuid4().hex[:6]}"
                body = f'    model.getBuilding.setName("{new_bldg_name}")\n    runner.registerInfo("applied")'
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Lifecycle test measure",
                    "run_body": body,
                    "language": "Ruby",
                }))
                assert create.get("ok") is True

                # Test it
                test = unwrap(await s.call_tool("test_measure", {
                    "measure_dir": create["measure_dir"],
                }))
                assert test.get("ok") is True

                # Apply it
                apply = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": create["measure_dir"],
                }))
                assert apply.get("ok") is True

                # Verify model changed
                bldg2 = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg2["building"]["name"] == new_bldg_name
                assert bldg2["building"]["name"] != original
    asyncio.run(_run())


@pytest.mark.integration
def test_create_measure_large_run_body():
    """Create a measure with a ~2KB run_body — validates large payloads survive MCP transport."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("large_body")
                # Build a ~2KB run_body with comments and real logic
                lines = ['    runner.registerInfo("Start large body test")']
                for i in range(40):
                    lines.append(f'    # Step {i}: set building attribute to validate measure execution')
                    lines.append(f'    runner.registerInfo("Processing step {i} of large measure body")')
                lines.append('    model.getBuilding.setName("LargeBodyTest")')
                lines.append('    runner.registerInfo("Done")')
                run_body = "\n".join(lines)
                assert len(run_body) > 2000, f"run_body only {len(run_body)} bytes"

                res = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Large run_body transport test",
                    "run_body": run_body,
                    "language": "Ruby",
                }))
                assert res.get("ok") is True, res
                assert res["validation"]["syntax_ok"] is True
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_existing_measure():
    """Apply an existing measure from tests/assets/ to a model."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique("apply_ext"))
                # Inspect the measure first
                args = unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": "/repo/tests/assets/measures/set_building_name",
                }))
                assert args.get("ok") is True
                assert any(a["name"] == "building_name" for a in args["arguments"])
                # Apply it
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": "/repo/tests/assets/measures/set_building_name",
                    "arguments": {"building_name": "Applied Externally"},
                }))
                assert res.get("ok") is True
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg["building"]["name"] == "Applied Externally"
    asyncio.run(_run())


# ── Name validation tests ──────────────────────────────────────────────


@pytest.mark.integration
def test_create_measure_rejects_path_traversal():
    """create_measure must reject names with path traversal."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                for bad_name in ["../../etc", "../passwd", "a/b", ""]:
                    res = unwrap(await s.call_tool("create_measure", {
                        "name": bad_name,
                        "description": "bad",
                        "run_body": '    runner.registerInfo("x")',
                        "language": "Ruby",
                    }))
                    assert res.get("ok") is False, f"Should reject name={bad_name!r}"
    asyncio.run(_run())


@pytest.mark.integration
def test_edit_measure_rejects_path_traversal():
    """edit_measure must reject names with path traversal."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("edit_measure", {
                    "measure_name": "../../etc",
                    "run_body": '    runner.registerInfo("x")',
                }))
                assert res.get("ok") is False
    asyncio.run(_run())


# ── Idempotent create test ─────────────────────────────────────────────


@pytest.mark.integration
def test_create_measure_idempotent():
    """Calling create_measure twice with same name should succeed both times."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("idempotent")
                body = '    runner.registerInfo("v1")'
                # First create
                res1 = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "First version",
                    "run_body": body,
                    "language": "Ruby",
                }))
                assert res1.get("ok") is True, res1
                # Second create (same name, different body)
                body2 = '    runner.registerInfo("v2")'
                res2 = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Second version",
                    "run_body": body2,
                    "language": "Ruby",
                }))
                assert res2.get("ok") is True, f"Idempotent create failed: {res2}"
                assert res2["validation"]["syntax_ok"] is True
    asyncio.run(_run())


# ── Test with real model ───────────────────────────────────────────────


@pytest.mark.integration
def test_test_measure_with_real_model():
    """Measure requiring HVAC should pass test_measure against a real model.

    Regression: previously test_measure always used an empty Model.new(),
    causing measures that depend on plant loops/air loops to fail.
    """
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # Load the complex model so test_measure picks it up
                load = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": "/repo/tests/assets/SystemD_baseline.osm",
                }))
                assert load.get("ok") is True

                # Create a measure that requires plant loops to exist
                name = _unique("needs_hvac")
                body = (
                    '    chw = nil\n'
                    '    model.getPlantLoops.each { |pl| chw = pl if pl.name.to_s.include?("Chilled") }\n'
                    '    if chw.nil?\n'
                    '      runner.registerError("No Chilled Water Loop found")\n'
                    '      return false\n'
                    '    end\n'
                    '    runner.registerFinalCondition("Found #{chw.name}")'
                )
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Requires CHW loop",
                    "run_body": body,
                    "language": "Ruby",
                }))
                assert create.get("ok") is True

                # test_measure should pass because model has CHW loop
                test = unwrap(await s.call_tool("test_measure", {
                    "measure_dir": create["measure_dir"],
                }))
                assert test.get("ok") is True, (
                    f"test_measure failed (should pass with real model): "
                    f"{test.get('test_output', '')[:500]}"
                )
                assert test["passed"] > 0
                assert test["failed"] == 0
    asyncio.run(_run())
