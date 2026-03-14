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


# ── measure.xml checksum validity ─────────────────────────────────────


@pytest.mark.integration
def test_measure_xml_checksums_valid():
    """measure.xml file checksums must match actual files on disk.

    Regression: _write_test_file was called AFTER _update_measure_xml,
    leaving stale checksums that caused OS App Measure Manager to silently
    reject the measure.
    """
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        import binascii
        import xml.etree.ElementTree as ET
        from pathlib import Path

        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("checksum")
                body = '    runner.registerInfo("checksum test")'
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Checksum validation test",
                    "run_body": body,
                    "language": "Ruby",
                }))
                assert create.get("ok") is True

                # Read measure.xml and verify checksums
                xml_res = unwrap(await s.call_tool("read_file", {
                    "file_path": f"{create['measure_dir']}/measure.xml",
                }))
                assert xml_res.get("ok") is True
                root = ET.fromstring(xml_res["text"])

                mdir = Path(create["measure_dir"])
                for file_elem in root.findall(".//file"):
                    fname = file_elem.findtext("filename")
                    expected_crc = file_elem.findtext("checksum")
                    if not fname or not expected_crc:
                        continue
                    # Find file on disk (could be in tests/ or docs/)
                    candidates = list(mdir.rglob(fname))
                    assert candidates, f"File {fname} listed in XML but not on disk"
                    actual_data = candidates[0].read_bytes()
                    actual_crc = f"{binascii.crc32(actual_data) & 0xffffffff:08X}"
                    assert actual_crc == expected_crc, (
                        f"Checksum mismatch for {fname}: "
                        f"XML says {expected_crc}, actual {actual_crc}"
                    )
    asyncio.run(_run())


# ── ReportingMeasure tests ─────────────────────────────────────────────

RUBY_REPORTING_BODY = (
    '    query = "SELECT Value FROM TabularDataWithStrings '
    "WHERE ReportName='AnnualBuildingUtilityPerformanceSummary' "
    "AND TableName='Site and Source Energy' "
    "AND RowName='Total Site Energy' "
    "AND ColumnName='Total Energy' "
    "AND Units='GJ'\"\n"
    "    val = sql.execAndReturnFirstDouble(query)\n"
    "    if val.is_initialized\n"
    '      runner.registerValue("total_site_energy_gj", val.get)\n'
    '      runner.registerInfo("Total Site Energy: #{val.get} GJ")\n'
    "    end\n"
    '    runner.registerFinalCondition("Report complete")'
)

PYTHON_REPORTING_BODY = (
    "        query = (\"SELECT Value FROM TabularDataWithStrings \"\n"
    "                 \"WHERE ReportName='AnnualBuildingUtilityPerformanceSummary' \"\n"
    "                 \"AND TableName='Site and Source Energy' \"\n"
    "                 \"AND RowName='Total Site Energy' \"\n"
    "                 \"AND ColumnName='Total Energy' \"\n"
    "                 \"AND Units='GJ'\")\n"
    "        val = sql.execAndReturnFirstDouble(query)\n"
    "        if val.is_initialized():\n"
    "            runner.registerValue('total_site_energy_gj', val.get())\n"
    "            runner.registerInfo(f'Total Site Energy: {val.get()} GJ')\n"
    "        runner.registerFinalCondition('Report complete')"
)


@pytest.mark.integration
def test_create_reporting_measure_ruby():
    """Create a Ruby ReportingMeasure, verify correct class/signature."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("rpt_rb")
                res = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Test reporting measure",
                    "run_body": RUBY_REPORTING_BODY,
                    "language": "Ruby",
                    "measure_type": "ReportingMeasure",
                }))
                assert res.get("ok") is True, res
                assert res["measure_type"] == "ReportingMeasure"
                assert res["validation"]["syntax_ok"] is True
                # Verify script content
                script = unwrap(await s.call_tool("read_file", {
                    "file_path": f"{res['measure_dir']}/measure.rb",
                }))
                text = script["text"]
                assert "ReportingMeasure" in text
                assert "def run(runner, user_arguments)" in text
                assert "super(runner, user_arguments)" in text
                assert "lastOpenStudioModel" in text
                assert "lastEnergyPlusSqlFilePath" in text
                assert "energyPlusOutputRequests" in text
    asyncio.run(_run())


@pytest.mark.integration
def test_create_reporting_measure_python():
    """Create a Python ReportingMeasure, verify correct class/signature."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("rpt_py")
                res = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Test reporting measure",
                    "run_body": PYTHON_REPORTING_BODY,
                    "language": "Python",
                    "measure_type": "ReportingMeasure",
                }))
                assert res.get("ok") is True, res
                assert res["measure_type"] == "ReportingMeasure"
                assert res["validation"]["syntax_ok"] is True
                # Verify script content
                script = unwrap(await s.call_tool("read_file", {
                    "file_path": f"{res['measure_dir']}/measure.py",
                }))
                text = script["text"]
                assert "ReportingMeasure" in text
                assert "def run(self, runner, user_arguments)" in text
                assert "lastOpenStudioModel" in text
                assert "lastEnergyPlusSqlFilePath" in text
                assert "energyPlusOutputRequests" in text
    asyncio.run(_run())


@pytest.mark.integration
def test_test_reporting_measure_args_only():
    """Test a ReportingMeasure without run_id — only arg validation runs."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("rpt_args")
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Reporting measure args test",
                    "run_body": '    runner.registerInfo("hello")',
                    "language": "Ruby",
                    "measure_type": "ReportingMeasure",
                    "arguments": [
                        {"name": "report_title", "type": "String",
                         "required": True, "default_value": "My Report"},
                    ],
                }))
                assert create.get("ok") is True
                # Test without run_id — should pass arg tests
                res = unwrap(await s.call_tool("test_measure", {
                    "measure_dir": create["measure_dir"],
                }))
                assert res.get("ok") is True, res.get("test_output", "")
                assert res["passed"] > 0
    asyncio.run(_run())


@pytest.mark.integration
def test_create_with_choice_values():
    """Create a measure with Choice argument that has values list."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("choice_vals")
                choice_args = [
                    {"name": "insulation_type", "display_name": "Insulation Type",
                     "type": "Choice", "required": True,
                     "default_value": "fiberglass",
                     "values": ["fiberglass", "foam", "mineral_wool"]},
                    {"name": "thickness", "display_name": "Thickness (in)",
                     "type": "Double", "required": True, "default_value": "3.5"},
                ]
                body = (
                    '    insulation_type = runner.getStringArgumentValue("insulation_type", user_arguments)\n'
                    '    thickness = runner.getDoubleArgumentValue("thickness", user_arguments)\n'
                    '    runner.registerInfo("Using #{insulation_type} at #{thickness} in")'
                )
                res = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Measure with choice values",
                    "run_body": body,
                    "language": "Ruby",
                    "arguments": choice_args,
                }))
                assert res.get("ok") is True, res
                assert res["validation"]["syntax_ok"] is True
                # Verify the generated script contains addChoice calls
                script = unwrap(await s.call_tool("read_file", {
                    "file_path": f"{res['measure_dir']}/measure.rb",
                }))
                text = script["text"]
                assert '"fiberglass"' in text
                assert '"foam"' in text
                assert '"mineral_wool"' in text
                assert "StringVector" in text
                # Test the measure runs
                test = unwrap(await s.call_tool("test_measure", {
                    "measure_dir": res["measure_dir"],
                }))
                assert test.get("ok") is True, test.get("test_output", "")
                assert test["passed"] > 0
    asyncio.run(_run())


@pytest.mark.integration
def test_edit_reporting_measure():
    """Edit a ReportingMeasure run_body, verify correct signature preserved."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("rpt_edit")
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Editable reporting measure",
                    "run_body": '    runner.registerInfo("v1")',
                    "language": "Ruby",
                    "measure_type": "ReportingMeasure",
                }))
                assert create.get("ok") is True
                # Edit run_body
                edit = unwrap(await s.call_tool("edit_measure", {
                    "measure_name": name,
                    "run_body": '    runner.registerInfo("v2")',
                }))
                assert edit.get("ok") is True
                assert "run_body" in edit["changes_made"]
                assert edit["validation"]["syntax_ok"] is True
                # Verify ReportingMeasure signature still intact
                script = unwrap(await s.call_tool("read_file", {
                    "file_path": f"{edit['measure_dir']}/measure.rb",
                }))
                text = script["text"]
                assert "ReportingMeasure" in text
                assert "def run(runner, user_arguments)" in text
                assert '"v2"' in text
    asyncio.run(_run())


@pytest.mark.integration
def test_create_with_description_ruby():
    """Argument description field emits setDescription() in Ruby."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("desc_rb")
                args = [{
                    "name": "r_value", "display_name": "R-Value",
                    "description": "Insulation R-value in ft2-F-hr/Btu",
                    "type": "Double", "required": True, "default_value": "19.0",
                }]
                res = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Description test",
                    "run_body": '    runner.registerInfo("ok")',
                    "language": "Ruby",
                    "arguments": args,
                }))
                assert res.get("ok") is True
                script = unwrap(await s.call_tool("read_file", {
                    "file_path": f"{res['measure_dir']}/measure.rb",
                }))
                assert 'setDescription("Insulation R-value in ft2-F-hr/Btu")' in script["text"]
    asyncio.run(_run())


@pytest.mark.integration
def test_create_with_description_python():
    """Argument description field emits setDescription() in Python."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("desc_py")
                args = [{
                    "name": "wall_name", "display_name": "Wall Name",
                    "description": "Name filter for wall surfaces",
                    "type": "String", "required": False, "default_value": "exterior",
                }]
                res = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Description test",
                    "run_body": '        runner.registerInfo("ok")',
                    "language": "Python",
                    "arguments": args,
                }))
                assert res.get("ok") is True
                script = unwrap(await s.call_tool("read_file", {
                    "file_path": f"{res['measure_dir']}/measure.py",
                }))
                assert 'setDescription("Name filter for wall surfaces")' in script["text"]
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_returns_runner_messages():
    """apply_measure should include runner_messages from out.osw."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique("runner_msg"))
                name = _unique("msg_meas")
                body = (
                    '    runner.registerInitialCondition("Starting measure")\n'
                    '    model.getBuilding.setName("RunnerMsgTest")\n'
                    '    runner.registerInfo("Applied name change")\n'
                    '    runner.registerFinalCondition("Measure complete")'
                )
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name,
                    "description": "Runner messages test",
                    "run_body": body,
                    "language": "Ruby",
                }))
                assert create.get("ok") is True
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": create["measure_dir"],
                }))
                assert res.get("ok") is True
                msgs = res.get("runner_messages")
                assert msgs is not None, f"No runner_messages in response: {res.keys()}"
                assert msgs["result"] == "Success"
                assert "initial_condition" in msgs
                assert "final_condition" in msgs
                assert "info" in msgs
    asyncio.run(_run())
