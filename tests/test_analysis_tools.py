import hashlib
import json
import zipfile
from pathlib import Path

from mcp_server.skills.analysis import operations

FIXTURE_ANALYSIS_ZIP = Path(__file__).parent / "assets" / "analysis.zip"


def _measure_xml(
    name: str,
    class_name: str | None = None,
    measure_type: str = "ModelMeasure",
    arguments: list[dict] | None = None,
) -> str:
    class_name = class_name or "".join(part.capitalize() for part in name.split("_"))
    args = ""
    for argument in arguments or []:
        args += f"""
    <argument>
      <name>{argument["name"]}</name>
      <display_name>{argument.get("display_name", argument["name"])}</display_name>
      <type>{argument.get("type", "Double")}</type>
      <required>true</required>
      <model_dependent>false</model_dependent>
      <default_value>{argument.get("default_value", "")}</default_value>
    </argument>"""
    return f"""<?xml version="1.0"?>
<measure>
  <schema_version>3.1</schema_version>
  <name>{name}</name>
  <uid>{name}-uuid</uid>
  <version_id>{name}-version</version_id>
  <class_name>{class_name}</class_name>
  <display_name>{name.replace("_", " ").title()}</display_name>
  <description>{name} test measure</description>
  <arguments>{args}
  </arguments>
  <attributes>
    <attribute>
      <name>Measure Type</name>
      <value>{measure_type}</value>
      <datatype>string</datatype>
    </attribute>
  </attributes>
</measure>"""


def _write_foundational_measure_entries(archive: zipfile.ZipFile):
    measure_types = {
        "view_model": "ModelMeasure",
        "openstudio_results": "ReportingMeasure",
        "generic_qaqc": "ReportingMeasure",
    }
    for measure_name in ("view_model", "openstudio_results", "generic_qaqc"):
        archive.writestr(f"measures/{measure_name}/measure.rb", f"class {measure_name}; end")
        archive.writestr(
            f"measures/{measure_name}/measure.xml",
            _measure_xml(measure_name, measure_type=measure_types[measure_name]),
        )


def test_create_and_validate_osa_json(tmp_path):
    path = tmp_path / "osa.json"

    created = operations.create_osa_json(
        output_path=str(path),
        analysis_name="Baseline Analysis",
        analysis_type="single_run",
        output_variables=[{"name": "openstudio_results.electricity_ip"}],
        algorithm={"debug_messages": 1},
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )

    assert created["ok"] is True
    assert created["osa_json_path"] == str(path.resolve())
    assert created["validation"]["ok"] is True

    data = json.loads(path.read_text())
    assert data["analysis"]["display_name"] == "Baseline Analysis"
    assert data["analysis"]["name"] == "baseline_analysis"
    assert data["analysis"]["problem"]["analysis_type"] == "single_run"
    assert data["analysis"]["seed"] == {"file_type": "OSM", "path": "./seed.osm"}
    assert data["analysis"]["weather_file"] == {"file_type": "EPW", "path": "./weather/USA.epw"}
    assert data["analysis"]["file_format_version"] == 1
    assert data["analysis"]["output_variables"][0]["objective_function"] is False
    workflow_names = [step["measure_definition_name"] for step in data["analysis"]["problem"]["workflow"]]
    assert workflow_names == ["view_model", "openstudio_results", "generic_qaqc"]

    validation = operations.validate_osa_json(str(path))
    assert validation["ok"] is True
    assert validation["issues"] == []
    assert validation["analysis_type"] == "single_run"


def test_create_osa_json_uses_foundational_output_variables_by_default(tmp_path):
    path = tmp_path / "osa.json"

    created = operations.create_osa_json(
        output_path=str(path),
        analysis_name="Default Outputs",
        analysis_type="single_run",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )

    assert created["ok"] is True
    assert created["validation"]["ok"] is True

    data = json.loads(path.read_text())
    output_variables = data["analysis"]["output_variables"]
    names = [variable["name"] for variable in output_variables]
    expected_summary_names = [
        f"openstudio_results.{variable_name}"
        for variable_name in operations.WHOLE_BUILDING_OUTPUT_VARIABLE_NAMES
    ]
    expected_end_use_names = [
        f"openstudio_results.{fuel}_{category}_ip"
        for fuel in operations.END_USE_FUELS
        for category in operations.END_USE_CATEGORIES
    ]
    assert len(output_variables) == len(expected_summary_names) + len(expected_end_use_names)
    assert names[: len(expected_summary_names)] == expected_summary_names
    assert names[len(expected_summary_names) :] == expected_end_use_names
    assert output_variables[0]["objective_function"] is False
    assert all(variable["visualize"] is True for variable in output_variables)
    assert all(variable["export"] is True for variable in output_variables)
    assert output_variables[len(expected_summary_names)]["name"] == "openstudio_results.electricity_cooling_ip"
    assert output_variables[-1]["name"] == "openstudio_results.natural_gas_water_systems_ip"
    assert all(not name.startswith("feature_reports.default_scenario_report") for name in names)


def test_foundational_analysis_measures_tool_reports_common_measure_set():
    payload = operations.get_foundational_analysis_measures()

    assert payload["measure_names"] == ["view_model", "openstudio_results", "generic_qaqc"]
    assert all(measure["measure_dir"].endswith(measure["measure_name"]) for measure in payload["measures"])


def test_validate_osa_json_requires_foundational_workflow_measures_by_default(tmp_path):
    path = tmp_path / "osa.json"
    created = operations.create_osa_json(
        output_path=str(path),
        analysis_name="No Foundational Measures",
        analysis_type="single_run",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
        include_foundational_measures=False,
    )

    assert created["ok"] is True
    assert created["validation"]["ok"] is True
    assert created["validation"]["require_foundational_measures"] is False

    validation = operations.validate_osa_json(str(path))
    assert validation["ok"] is False
    assert validation["missing_foundational_measures"] == ["view_model", "openstudio_results", "generic_qaqc"]
    assert any("missing foundational analysis measure" in issue for issue in validation["issues"])

    legacy_validation = operations.validate_osa_json(str(path), require_foundational_measures=False)
    assert legacy_validation["ok"] is True


def test_default_output_variables_tool_payload_matches_create_defaults(tmp_path):
    path = tmp_path / "osa.json"
    payload = operations.get_default_output_variables()

    created = operations.create_osa_json(
        output_path=str(path),
        analysis_name="Default Output Match",
        analysis_type="single_run",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )

    assert payload["ok"] is True
    assert payload["count"] == len(operations.WHOLE_BUILDING_OUTPUT_VARIABLE_NAMES) + len(
        operations.END_USE_FUELS
    ) * len(operations.END_USE_CATEGORIES)
    assert payload["names"] == [variable["name"] for variable in payload["output_variables"]]
    assert all(variable["visualize"] is True for variable in payload["output_variables"])
    assert created["ok"] is True

    data = json.loads(path.read_text())
    assert data["analysis"]["output_variables"] == payload["output_variables"]


def test_create_osa_json_explicit_output_variables_override_defaults(tmp_path):
    path = tmp_path / "osa.json"

    created = operations.create_osa_json(
        output_path=str(path),
        analysis_name="Custom Outputs",
        analysis_type="single_run",
        output_variables=[{"name": "openstudio_results.electricity_ip"}],
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )

    assert created["ok"] is True
    data = json.loads(path.read_text())
    assert [variable["name"] for variable in data["analysis"]["output_variables"]] == [
        "openstudio_results.electricity_ip"
    ]


def test_validate_osa_json_reports_missing_required_fields(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"analysis": {"problem": {}}}))

    validation = operations.validate_osa_json(str(path))

    assert validation["ok"] is False
    assert "analysis.name is missing." in validation["issues"]
    assert "analysis.uuid is missing." in validation["issues"]
    assert "analysis.problem.analysis_type is missing." in validation["issues"]
    assert validation["schema_issues"]


def test_create_osa_json_from_measures_promotes_arguments_to_variables(tmp_path):
    path = tmp_path / "osa.json"
    measure_dir = "tests/assets/measures/set_building_name"

    created = operations.create_osa_json_from_measures(
        output_path=str(path),
        analysis_name="Parametric Names",
        measure_specs=[
            {
                "measure_dir": measure_dir,
                "variables": [
                    {
                        "argument_name": "building_name",
                        "display_name": "Building Name Variant",
                        "static_value": "Baseline",
                        "distribution": {
                            "type": "discrete",
                            "minimum": "A",
                            "maximum": "C",
                            "mode": "B",
                            "values": ["A", "B", "C"],
                        },
                    }
                ],
            }
        ],
        algorithm={"sampling_algorithm": "full_factorial"},
    )

    assert created["ok"] is True
    data = json.loads(path.read_text())
    workflow = data["analysis"]["problem"]["workflow"]
    assert data["analysis"]["problem"]["analysis_type"] == "single_run"
    assert data["analysis"]["problem"]["algorithm"] == {"sampling_algorithm": "full_factorial"}
    assert len(workflow) == 4

    step = workflow[0]
    assert step["measure_definition_name"] == "set_building_name"
    assert step["measure_definition_directory"] == "./measures/set_building_name"
    assert step["arguments"] == []
    assert len(step["variables"]) == 1

    variable = step["variables"][0]
    assert variable["argument"]["name"] == "building_name"
    assert variable["static_value"] == "Baseline"
    assert variable["variable"] is True
    assert variable["uncertainty_description"]["type"] == "discrete"
    discrete = variable["uncertainty_description"]["attributes"][0]
    assert discrete["name"] == "discrete"
    assert discrete["values_and_weights"] == [
        {"value": "A", "weight": 1 / 3},
        {"value": "B", "weight": 1 / 3},
        {"value": "C", "weight": 1 / 3},
    ]
    assert [step["measure_definition_name"] for step in workflow[1:]] == [
        "view_model",
        "openstudio_results",
        "generic_qaqc",
    ]


def test_validate_osa_json_rejects_doe_with_one_variable(tmp_path):
    path = tmp_path / "osa.json"
    created = operations.create_osa_json_from_measures(
        output_path=str(path),
        analysis_name="One Variable DOE",
        measure_specs=[
            {
                "measure_dir": "tests/assets/measures/set_building_name",
                "variables": [
                    {
                        "argument_name": "building_name",
                        "distribution": {
                            "type": "discrete",
                            "minimum": "A",
                            "maximum": "B",
                            "mode": "A",
                            "values": ["A", "B"],
                        },
                    }
                ],
            }
        ],
        analysis_type="doe",
    )

    assert created["ok"] is True
    validation = operations.validate_osa_json(str(path))
    assert validation["ok"] is False
    assert validation["analysis_type"] == "doe"
    assert validation["analysis_variable_count"] == 1
    assert any("DOE analyses require at least two measure variables" in issue for issue in validation["issues"])


def test_add_measure_to_osa_json_keeps_static_arguments(tmp_path):
    path = tmp_path / "osa.json"
    operations.create_osa_json(str(path), "Static Measure")

    result = operations.add_measure_to_osa_json(
        osa_json_path=str(path),
        measure_dir="tests/assets/measures/set_building_name",
        arguments={"building_name": "Fixed Name"},
    )

    assert result["ok"] is True
    data = json.loads(path.read_text())
    step = data["analysis"]["problem"]["workflow"][-1]
    assert step["arguments"][0]["name"] == "building_name"
    assert step["arguments"][0]["value"] == "Fixed Name"
    assert step["variables"] == []


def test_submit_analysis_posts_to_project_endpoint(monkeypatch, tmp_path):
    osa_path = tmp_path / "osa.json"
    operations.create_osa_json(
        str(osa_path),
        "Submit Me",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )
    seen = {}

    class FakeResponse:
        status = 201
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"_id":"analysis-123"}'

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["body"] = json.loads(req.data.decode())
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(operations, "urlopen", fake_urlopen)

    result = operations.submit_analysis(
        project_id="project-abc",
        osa_json_path=str(osa_path),
        server_url="http://server.example",
    )

    assert result["ok"] is True
    assert result["analysis_id"] == "analysis-123"
    assert seen["url"] == "http://server.example/projects/project-abc/analyses.json"
    assert seen["method"] == "POST"
    assert seen["body"]["analysis"]["display_name"] == "Submit Me"


def test_start_sampled_analysis_run_starts_lhs_before_batch_run(monkeypatch):
    requests = []

    class FakeResponse:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"code":200}'

    def fake_urlopen(req, timeout):
        requests.append((req.full_url, req.data.decode()))
        return FakeResponse()

    monkeypatch.setattr(operations, "urlopen", fake_urlopen)

    result = operations.start_sampled_analysis_run(
        analysis_id="analysis-123",
        server_url="http://server.example",
        sampler_analysis_type="lhs",
    )

    assert result["ok"] is True
    assert [body for _, body in requests] == [
        "analysis_action=start&analysis_type=lhs",
        "analysis_action=start&analysis_type=batch_run",
    ]


def test_submit_analysis_blocks_schema_invalid_json_before_http(monkeypatch, tmp_path):
    osa_path = tmp_path / "bad_osa.json"
    operations.create_osa_json(
        str(osa_path),
        "Invalid Submit",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )
    data = json.loads(osa_path.read_text())
    data["analysis"]["seed_model"] = "./seed.osm"
    osa_path.write_text(json.dumps(data))

    def fail_urlopen(req, timeout):
        raise AssertionError("submit_analysis should not contact OSAF when schema validation fails")

    monkeypatch.setattr(operations, "urlopen", fail_urlopen)

    result = operations.submit_analysis(
        project_id="project-abc",
        osa_json_path=str(osa_path),
        server_url="http://server.example",
    )

    assert result["ok"] is False
    assert result["error"] == "OSA JSON validation failed."
    assert any("Additional properties are not allowed" in issue for issue in result["validation"]["schema_issues"])


def test_submit_analysis_blocks_one_variable_doe_before_http(monkeypatch, tmp_path):
    osa_path = tmp_path / "osa.json"
    operations.create_osa_json_from_measures(
        output_path=str(osa_path),
        analysis_name="Invalid DOE Submit",
        measure_specs=[
            {
                "measure_dir": "tests/assets/measures/set_building_name",
                "variables": [
                    {
                        "argument_name": "building_name",
                        "distribution": {
                            "type": "discrete",
                            "minimum": "A",
                            "maximum": "B",
                            "mode": "A",
                            "values": ["A", "B"],
                        },
                    }
                ],
            }
        ],
        analysis_type="doe",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )

    def fail_urlopen(req, timeout):
        raise AssertionError("submit_analysis should not contact OSAF when DOE has fewer than two variables")

    monkeypatch.setattr(operations, "urlopen", fail_urlopen)

    result = operations.submit_analysis(
        project_id="project-abc",
        osa_json_path=str(osa_path),
        server_url="http://server.example",
    )

    assert result["ok"] is False
    assert result["error"] == "OSA JSON validation failed."
    assert result["validation"]["analysis_variable_count"] == 1
    assert any("DOE analyses require at least two measure variables" in issue for issue in result["validation"]["issues"])


def test_submit_analysis_blocks_missing_foundational_measures_before_http(monkeypatch, tmp_path):
    osa_path = tmp_path / "osa.json"
    operations.create_osa_json(
        output_path=str(osa_path),
        analysis_name="Missing Foundational Submit",
        analysis_type="single_run",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
        include_foundational_measures=False,
    )

    def fail_urlopen(req, timeout):
        raise AssertionError("submit_analysis should not contact OSAF when foundational measures are missing")

    monkeypatch.setattr(operations, "urlopen", fail_urlopen)

    result = operations.submit_analysis(
        project_id="project-abc",
        osa_json_path=str(osa_path),
        server_url="http://server.example",
    )

    assert result["ok"] is False
    assert result["error"] == "OSA JSON validation failed."
    assert result["validation"]["missing_foundational_measures"] == [
        "view_model",
        "openstudio_results",
        "generic_qaqc",
    ]


def test_server_config_single_run_checks_health_and_runs_datapoint(monkeypatch, tmp_path):
    seed = b"OSM seed contents"
    manifest = {
        "ok": True,
        "seed_sha256": hashlib.sha256(seed).hexdigest(),
        "run_id": "run_seed_preflight_123",
        "basic_qaqc": {"passed": True, "issues": []},
    }
    package_path = tmp_path / "analysis.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("weather/example.ddy", "design days")
        archive.writestr("weather/example.epw", "weather")
        archive.writestr("seeds/example.osm", seed)
        archive.writestr("measures/SetWWR/measure.rb", "class SetWWR; end")
        archive.writestr(
            "measures/SetWWR/measure.xml",
            _measure_xml(
                "set_wwr",
                class_name="SetWWR",
                arguments=[
                    {
                        "name": "wwr",
                        "display_name": "Window-to-Wall Ratio",
                        "type": "Double",
                        "default_value": 0.4,
                    }
                ],
            ),
        )
        _write_foundational_measure_entries(archive)
        archive.writestr("scripts/data_point/initialization.sh", "exit 0\n")
        archive.writestr("lib/seed_simulation_qaqc.json", json.dumps(manifest))

    requests = []

    class FakeHeaders(dict):
        def get(self, key, default=None):
            return super().get(key.lower(), default)

    class FakeResponse:
        status = 200
        headers = FakeHeaders({})

        def __init__(self, body, status=200):
            self.body = body
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(self.body).encode()

    status_calls = 0

    def fake_urlopen(req, timeout):
        nonlocal status_calls
        requests.append((req.get_method(), req.full_url, req.data))
        if req.full_url == "http://server.example/status.json":
            return FakeResponse({"status": "ok"})
        if req.full_url == "http://server.example/projects.json":
            return FakeResponse({"_id": "project-123"}, status=201)
        if req.full_url == "http://server.example/projects/project-123/analyses.json":
            body = json.loads(req.data.decode())
            assert body["analysis"]["problem"]["analysis_type"] == "single_run"
            assert body["analysis"]["seed"] == {"file_type": "OSM", "path": "./seeds/example.osm"}
            assert body["analysis"]["weather_file"] == {"file_type": "EPW", "path": "./weather/example.epw"}
            assert body["analysis"]["cli_debug"] == ""
            assert body["analysis"]["cli_verbose"] == ""
            assert body["analysis"]["download_reports"] is False
            assert body["analysis"]["download_osw"] is False
            assert body["analysis"]["download_osm"] is False
            assert body["analysis"]["download_zip"] is False
            workflow = body["analysis"]["problem"]["workflow"]
            assert [step["measure_definition_name"] for step in workflow] == [
                "set_wwr",
                "view_model",
                "openstudio_results",
                "generic_qaqc",
            ]
            assert workflow[0]["arguments"][0]["name"] == "wwr"
            assert workflow[0]["arguments"][0]["value"] == 0.4
            assert workflow[0]["variables"] == []
            return FakeResponse({"_id": "analysis-123"}, status=201)
        if req.full_url == "http://server.example/analyses/analysis-123/upload.json":
            return FakeResponse({"_id": "analysis-123"}, status=201)
        if req.full_url == "http://server.example/analyses/analysis-123/action.json":
            return FakeResponse({"code": 200, "analysis": {"_id": "analysis-123"}})
        if req.full_url == "http://server.example/analyses/analysis-123/status.json":
            status_calls += 1
            data_point_status = "na" if status_calls == 1 else "completed"
            return FakeResponse(
                {
                    "analysis": {
                        "_id": "analysis-123",
                        "status": "completed",
                        "analysis_type": "single_run",
                        "run_flag": True,
                        "total_datapoints": 1,
                        "jobs": [],
                        "data_points": [{"_id": "dp-123", "status": data_point_status, "name": "Single Run"}],
                    }
                }
            )
        raise AssertionError(f"Unexpected request: {req.get_method()} {req.full_url}")

    monkeypatch.setattr(operations, "urlopen", fake_urlopen)

    result = operations.test_server_config_single_run(
        upload_zip_path=str(package_path),
        server_url="http://server.example",
        output_dir=str(tmp_path / "out"),
        wait_timeout_seconds=2,
        poll_interval_seconds=1,
    )

    assert result["ok"] is True
    assert result["project_id"] == "project-123"
    assert result["analysis_id"] == "analysis-123"
    action_bodies = [body.decode() for method, url, body in requests if url.endswith("/action.json")]
    assert "analysis_action=start&analysis_type=single_run" in action_bodies
    assert "analysis_action=start&analysis_type=batch_run" in action_bodies


def test_wait_for_datapoint_completion_treats_failure_message_as_failure(monkeypatch):
    def fake_status(analysis_id, server_url=None, analysis_type=None):
        return {
            "ok": True,
            "response": {
                "analysis": {
                    "data_points": [
                        {
                            "_id": "dp-123",
                            "status": "completed",
                            "status_message": "datapoint failure",
                        }
                    ]
                }
            },
        }

    monkeypatch.setattr(operations, "get_analysis_status", fake_status)

    result = operations._wait_for_datapoint_completion(
        "analysis-123",
        "http://server.example",
        timeout_seconds=1,
        poll_interval_seconds=1,
    )

    assert result["ok"] is False
    assert "datapoint failure" in result["error"]


def test_validate_analysis_package_accepts_osaf_fixture_layout():
    validation = operations.validate_analysis_package(
        str(FIXTURE_ANALYSIS_ZIP),
        require_seed_qaqc=False,
        require_foundational_measures=False,
    )

    assert validation["ok"] is True
    assert validation["issues"] == []
    assert validation["root_folders"] == ["lib", "measures", "scripts", "seeds", "weather"]
    assert validation["file_count"] == 24
    assert validation["complete_measure_count"] == 3
    assert validation["seed_files"] == ["seeds/example_model.osm"]
    assert validation["weather_files"] == ["weather/USA_CO_Golden-NREL.724666_TMY3.epw"]


def test_validate_analysis_package_requires_seed_qaqc_manifest():
    validation = operations.validate_analysis_package(str(FIXTURE_ANALYSIS_ZIP))

    assert validation["ok"] is False
    assert any("seed_simulation_qaqc.json" in issue for issue in validation["issues"])


def test_validate_analysis_package_accepts_seed_qaqc_manifest(tmp_path):
    seed = b"OSM seed contents"
    manifest = {
        "ok": True,
        "seed_sha256": hashlib.sha256(seed).hexdigest(),
        "run_id": "run_seed_preflight_123",
        "basic_qaqc": {"passed": True, "issues": []},
    }
    package_path = tmp_path / "analysis.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("weather/example.epw", "weather")
        archive.writestr("seeds/example.osm", seed)
        archive.writestr("measures/SetWWR/measure.rb", "class SetWWR; end")
        archive.writestr("measures/SetWWR/measure.xml", _measure_xml("set_wwr", class_name="SetWWR"))
        _write_foundational_measure_entries(archive)
        archive.writestr("scripts/data_point/initialization.sh", "exit 0\n")
        archive.writestr("lib/seed_simulation_qaqc.json", json.dumps(manifest))

    validation = operations.validate_analysis_package(str(package_path))

    assert validation["ok"] is True
    assert validation["seed_qaqc_manifest"]["run_id"] == "run_seed_preflight_123"


def test_validate_analysis_package_rejects_wrong_root_layout(tmp_path):
    package_path = tmp_path / "bad_analysis.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("analysis/weather/example.epw", "weather")
        archive.writestr("analysis/seeds/example.osm", "seed")
        archive.writestr("analysis/measures/Example/measure.rb", "class Example; end")
        archive.writestr("analysis/measures/Example/measure.xml", "<measure/>")

    validation = operations.validate_analysis_package(str(package_path))

    assert validation["ok"] is False
    assert "Unexpected root folders/files: analysis" in validation["issues"]
    assert "Missing required root folders: lib, measures, scripts, seeds, weather" in validation["issues"]


def test_submit_analysis_blocks_invalid_package_before_http(monkeypatch, tmp_path):
    osa_path = tmp_path / "osa.json"
    operations.create_osa_json(
        str(osa_path),
        "Submit With Bad Package",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )
    package_path = tmp_path / "bad_analysis.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("weather/example.epw", "weather")
        archive.writestr("seeds/example.osm", "seed")

    def fail_urlopen(req, timeout):
        raise AssertionError("submit_analysis should not contact OSAF when package validation fails")

    monkeypatch.setattr(operations, "urlopen", fail_urlopen)

    result = operations.submit_analysis(
        project_id="project-abc",
        osa_json_path=str(osa_path),
        server_url="http://server.example",
        upload_zip_path=str(package_path),
    )

    assert result["ok"] is False
    assert result["error"] == "Analysis package ZIP validation failed."
    assert result["validation"]["ok"] is True
    assert result["package_validation"]["ok"] is False
    assert any("Missing required root folders" in issue for issue in result["package_validation"]["issues"])


def test_download_analysis_data_uses_content_disposition(monkeypatch, tmp_path):
    class FakeHeaders(dict):
        def get(self, key, default=None):
            return super().get(key.lower(), default)

    class FakeResponse:
        status = 200
        headers = FakeHeaders(
            {
                "content-disposition": 'attachment; filename="results.csv"',
                "content-type": "text/csv",
            }
        )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"a,b\n1,2\n"

    def fake_urlopen(req, timeout):
        assert req.full_url == "http://server.example/analyses/analysis-123/download_data.csv?export=true"
        return FakeResponse()

    monkeypatch.setattr(operations, "urlopen", fake_urlopen)

    result = operations.download_analysis_data(
        analysis_id="analysis-123",
        output_dir=str(tmp_path),
        server_url="http://server.example",
    )

    assert result["ok"] is True
    assert result["bytes"] == 8
    assert (tmp_path / "results.csv").read_text() == "a,b\n1,2\n"
