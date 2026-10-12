import hashlib
import json
import zipfile
from pathlib import Path

import pytest

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


def test_create_osa_json_applies_safe_analysis_field_defaults(tmp_path):
    # Regression: #96 — absent cli_debug/cli_verbose/download_* keys made
    # openstudio-analysis/OS-server default to --debug/--verbose logging and
    # per-datapoint downloads, pushing successful datapoints over the 16MB
    # BSON cap and corrupting R-driven analyses
    path = tmp_path / "osa.json"
    created = operations.create_osa_json(
        output_path=str(path),
        analysis_name="Safe Defaults",
        analysis_type="single_run",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )
    assert created["ok"] is True

    analysis = json.loads(path.read_text())["analysis"]
    assert analysis["cli_debug"] == ""
    assert analysis["cli_verbose"] == ""
    assert analysis["download_reports"] is False
    assert analysis["download_osw"] is False
    assert analysis["download_osm"] is False
    assert analysis["download_zip"] is False


def test_create_osa_json_extra_fields_override_safe_defaults(tmp_path):
    # Validates: callers can still opt back into debug logging / downloads
    path = tmp_path / "osa.json"
    created = operations.create_osa_json(
        output_path=str(path),
        analysis_name="Debug Override",
        analysis_type="single_run",
        extra_analysis_fields={"cli_debug": "--debug", "download_zip": True},
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )
    assert created["ok"] is True

    analysis = json.loads(path.read_text())["analysis"]
    assert analysis["cli_debug"] == "--debug"
    assert analysis["download_zip"] is True
    assert analysis["cli_verbose"] == ""
    assert analysis["download_reports"] is False


def test_foundational_generic_qaqc_checks_disabled_by_default(tmp_path):
    # Regression: #96 — generic_qaqc with all checks on emits ~19MB of
    # warnings per real multi-zone datapoint, blowing the server's BSON cap;
    # the foundational workflow step must ship with every check_* off
    path = tmp_path / "osa.json"
    created = operations.create_osa_json(
        output_path=str(path),
        analysis_name="QAQC Checks Off",
        analysis_type="single_run",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )
    assert created["ok"] is True

    workflow = json.loads(path.read_text())["analysis"]["problem"]["workflow"]
    qaqc_step = next(s for s in workflow if s["measure_definition_name"] == "generic_qaqc")
    arg_values = {arg["name"]: arg["value"] for arg in qaqc_step["arguments"]}
    check_args = [
        "check_mech_sys_part_load_eff",
        "check_mech_sys_capacity",
        "check_simultaneous_heating_and_cooling",
        "check_internal_loads",
        "check_schedules",
        "check_envelope_conductance",
        "check_domestic_hot_water",
        "check_mech_sys_efficiency",
        "check_mech_sys_type",
        "check_supply_air_and_thermostat_temp_difference",
    ]
    for name in check_args:
        assert arg_values[name] is False, f"{name} must default to False in analyses (#96)"


def test_foundational_analysis_measures_tool_reports_common_measure_set():
    payload = operations.get_foundational_analysis_measures()

    assert payload["measure_names"] == ["view_model", "openstudio_results", "generic_qaqc"]
    assert all(measure["measure_dir"].endswith(measure["measure_name"]) for measure in payload["measures"])


def test_validate_osa_json_can_require_foundational_workflow_measures(tmp_path):
    path = tmp_path / "osa.json"
    created = operations.create_osa_json(
        output_path=str(path),
        analysis_name="No Foundational Measures",
        analysis_type="single_run",
        seed="./seed.osm",
        weather_file="./weather/USA.epw",
    )

    assert created["ok"] is True
    assert created["validation"]["ok"] is True
    assert created["validation"]["require_foundational_measures"] is True
    data = json.loads(path.read_text())
    data["analysis"]["problem"]["workflow"] = []
    path.write_text(json.dumps(data))

    validation = operations.validate_osa_json(str(path), require_foundational_measures=True)
    assert validation["ok"] is False
    assert validation["missing_foundational_measures"] == ["view_model", "openstudio_results", "generic_qaqc"]
    assert any("missing foundational analysis measure" in issue for issue in validation["issues"])

    legacy_validation = operations.validate_osa_json(str(path))
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


def test_osaf_algorithms_describe_supported_analysis_types():
    payload = operations.get_osaf_algorithms()

    assert payload["ok"] is True
    assert "sampling" in payload["categories"]
    assert "optimization" in payload["categories"]
    assert "sensitivity" in payload["categories"]

    by_type = {algorithm["analysis_type"]: algorithm for algorithm in payload["algorithms"]}
    assert by_type["lhs"]["start_sequence"] == ["lhs", "batch_run"]
    assert "one-variable" in by_type["lhs"]["best_for"]
    assert "fewer than two real measure variables" in by_type["doe"]["notes"]
    assert "c_1" in by_type["pso"]["typical_algorithm_keys"]
    assert "random_seed_2" in by_type["sobol"]["typical_algorithm_keys"]

    filtered = operations.get_osaf_algorithms(category="sensitivity")
    assert filtered["ok"] is True
    assert {algorithm["analysis_type"] for algorithm in filtered["algorithms"]} >= {"sobol", "morris"}

    lhs = operations.get_osaf_algorithms(category="lhs")
    assert lhs["analysis_types"] == ["lhs"]


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
    assert "analysis.problem.analysis_type is missing." in validation["issues"]
    assert validation["schema_issues"]


def test_validate_osa_json_accepts_legacy_server_algorithm_configs(tmp_path):
    cases = [
        (
            "nsga_nrel",
            {
                "number_of_samples": 2,
                "generations": 1,
                "tournament_size": 2,
                "cprob": 0.85,
                "xover_dist_idx": 5,
                "mu_dist_idx": 5,
                "mprob": 0.8,
                "objective_functions": ["report.electricity"],
            },
            {"delete_simulation_dir": True},
        ),
        (
            "pso",
            {
                "npart": 2,
                "maxit": 1,
                "maxfn": 4,
                "lambda": 0.9,
                "c_1": 1,
                "c_2": 1,
                "boundary": "reflecting",
                "topology": "random",
                "xini": "lhs",
                "vini": "lhs2011",
                "method": "spso2011",
            },
            {},
        ),
        (
            "rgenoud",
            {
                "popsize": 2,
                "generations": 1,
                "wait_generations": 2,
                "bfgsburnin": 6,
                "bfgs": 0,
                "r_genoud_debug_flag": 1,
            },
            {},
        ),
        (
            "spea_nrel",
            {
                "number_of_samples": 2,
                "generations": 1,
                "tournament_size": 2,
                "cprob": 0.85,
                "cidx": 5,
                "midx": 5,
                "mprob": 0.8,
            },
            {},
        ),
        (
            "lhs",
            {
                "sample_method": "all_variables",
                "number_of_samples": "2",
            },
            {},
        ),
        (
            "sobol",
            {
                "number_of_samples": 2,
                "random_seed": 1979,
                "random_seed_2": 1973,
                "order": 1,
                "nboot": 0,
                "conf": 0.95,
                "type": "sobol",
            },
            {},
        ),
    ]

    for index, (analysis_type, algorithm, analysis_overrides) in enumerate(cases):
        path = tmp_path / f"legacy_{index}.json"
        analysis = {
            "display_name": f"Legacy {analysis_type}",
            "name": f"legacy_{analysis_type}",
            "file_format_version": 1,
            "output_variables": [],
            "seed": {"file_type": "OSM", "path": "./seeds/example.osm"},
            "weather_file": {"file_type": "EPW", "path": "./weather/example.epw"},
            "problem": {
                "analysis_type": analysis_type,
                "algorithm": algorithm,
                "workflow": [],
            },
        }
        analysis.update(analysis_overrides)
        path.write_text(json.dumps({"analysis": analysis}))

        validation = operations.validate_osa_json(str(path), require_foundational_measures=False)

        assert validation["ok"] is True, validation["issues"]


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

    assert result["ok"] is True, result
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

    assert result["ok"] is True, result
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
    )
    data = json.loads(osa_path.read_text())
    data["analysis"]["problem"]["workflow"] = []
    osa_path.write_text(json.dumps(data))

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


def test_prepare_analysis_package_always_adds_foundational_measures(monkeypatch, tmp_path):
    common_measures = tmp_path / "common_measures"
    package_dir = tmp_path / "package"
    seed = b"OSM seed contents"
    for measure_name in ("view_model", "openstudio_results", "generic_qaqc"):
        measure_dir = common_measures / measure_name
        measure_dir.mkdir(parents=True)
        measure_dir.joinpath("measure.rb").write_text(f"class {measure_name}; end")
        measure_dir.joinpath("measure.xml").write_text(
            _measure_xml(
                measure_name,
                measure_type="ModelMeasure" if measure_name == "view_model" else "ReportingMeasure",
            )
        )
    package_dir.joinpath("seeds").mkdir(parents=True)
    package_dir.joinpath("weather").mkdir()
    package_dir.joinpath("scripts/data_point").mkdir(parents=True)
    package_dir.joinpath("lib").mkdir()
    package_dir.joinpath("measures/SetWWR").mkdir(parents=True)
    package_dir.joinpath("seeds/example.osm").write_bytes(seed)
    package_dir.joinpath("weather/example.epw").write_text("weather")
    package_dir.joinpath("scripts/data_point/initialization.sh").write_text("exit 0\n")
    package_dir.joinpath("measures/SetWWR/measure.rb").write_text("class SetWWR; end")
    package_dir.joinpath("measures/SetWWR/measure.xml").write_text(_measure_xml("set_wwr", class_name="SetWWR"))
    monkeypatch.setenv("COMMON_MEASURES_DIR", str(common_measures))

    def fake_preflight_seed_for_analysis_package(**kwargs):
        manifest = {
            "ok": True,
            "ready": True,
            "seed_sha256": hashlib.sha256(seed).hexdigest(),
            "run_id": "run_seed_preflight_123",
            "basic_qaqc": {"passed": True, "issues": []},
        }
        Path(kwargs["manifest_path"]).write_text(json.dumps(manifest))
        return manifest

    monkeypatch.setattr(operations, "preflight_seed_for_analysis_package", fake_preflight_seed_for_analysis_package)
    monkeypatch.setattr("mcp_server.config.is_path_allowed", lambda path, write=False: True)

    result = operations.prepare_analysis_package(
        package_dir=str(package_dir),
        output_zip_path=str(tmp_path / "analysis.zip"),
    )

    assert result["ok"] is True, result
    assert result["foundational_measures"]["copied"] == ["view_model", "openstudio_results", "generic_qaqc"]
    with zipfile.ZipFile(result["zip_path"]) as archive:
        names = set(archive.namelist())
    assert "measures/view_model/measure.xml" in names
    assert "measures/openstudio_results/measure.xml" in names
    assert "measures/generic_qaqc/measure.xml" in names


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


# --- SSRF / token / path hardening (#173) ---------------------------------

_ANALYSIS_ENV = (
    "MCP_TRANSPORT", "OPENSTUDIO_SERVER_URL", "OS_SERVER_URL", "OPENSTUDIO_API_TOKEN",
    "OS_SERVER_API_TOKEN", "OSMCP_ANALYSIS_ALLOWED_HOSTS",
)


def _stdio_env(monkeypatch):
    """Single-user stdio mode with no server, token or allowlist configured."""
    for var in _ANALYSIS_ENV:
        monkeypatch.delenv(var, raising=False)


def _http_tenant(monkeypatch, tmp_path) -> Path:
    """Shared HTTP mode as tenant 'alice': RUN_ROOT=tmp_path/runs, returns alice's own root.

    A sibling tenant 'bob' (RUN_ROOT/bob) exists so tests can prove isolation, and the
    stdio-only tempdir fallback is off.
    """
    from mcp_server import config

    _stdio_env(monkeypatch)
    run_root = (tmp_path / "runs").resolve()
    (run_root / "bob").mkdir(parents=True)
    monkeypatch.setattr(config, "RUN_ROOT", run_root)
    monkeypatch.setattr(config, "MEASURES_DIR", (tmp_path / "measures").resolve())
    monkeypatch.setattr("mcp_server.identity._is_http_transport", lambda: True)
    monkeypatch.setattr("mcp_server.identity.user_key", lambda: "alice")
    root = run_root / "alice"
    root.mkdir()
    return root


def _never_called(req, timeout):
    pytest.fail(f"urlopen must not be reached, got {req.full_url}")


class _FakeResponse:
    status = 200

    def __init__(self, body: bytes = b"{}", headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None

    def read(self):
        return self._body


def _local_http_server(record: list):
    """A loopback HTTP server that records every request path; returns (server, port)."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            record.append(self.path)
            body = b'{"type": "object"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_port


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd", "ftp://host/x", "gopher://h", "localhost:8080", "http://",
    "http://osa:8080\t/x", "http://osa:80 80",
])
def test_server_url_rejects_non_http_or_malformed(monkeypatch, bad):
    # Validates: only an absolute http(s) URL with no embedded whitespace ever reaches the socket
    # layer (file:/ftp: would read or fetch; whitespace reaches http.client as InvalidURL)
    _stdio_env(monkeypatch)
    with pytest.raises(ValueError, match=r"absolute http|whitespace"):
        operations._server_url(bad)


def test_server_url_normalizes_trailing_slash(monkeypatch):
    # Validates: a trailing slash never produces '//' in built endpoint URLs
    _stdio_env(monkeypatch)
    assert operations._server_url("https://osa.example.com:8080/") == "https://osa.example.com:8080"


def test_server_url_restricted_in_http_mode(monkeypatch):
    # Validates: on the shared server a caller-chosen server_url may only target the configured
    # origin (scheme, host and port) or an allowlisted host (SSRF)
    _stdio_env(monkeypatch)
    monkeypatch.setattr("mcp_server.identity._is_http_transport", lambda: True)
    monkeypatch.setenv("OPENSTUDIO_SERVER_URL", "http://osa:8080")
    assert operations._server_url(None) == "http://osa:8080"
    assert operations._server_url("http://osa:8080/") == "http://osa:8080"
    for other in ("http://169.254.169.254/latest", "http://osa:8081", "https://osa:8080"):
        with pytest.raises(ValueError, match="not permitted"):
            operations._server_url(other)


@pytest.mark.parametrize(("allowed", "url", "ok"), [
    ("other:9000", "http://other:9000", True),
    ("other:9000", "http://other:9001", False),
    ("other", "http://other:9000", True),
    ("other", "https://other", True),
    ("https://other:9000", "https://other:9000", True),
    ("https://other:9000", "http://other:9000", False),
    (" Other:9000 ,x", "http://other:9000", True),
])
def test_allowed_hosts_match_by_origin(monkeypatch, allowed, url, ok):
    # Regression: the allowlist compared raw netloc strings, so equivalent origins were rejected
    # and an entry written with a scheme never matched anything
    _stdio_env(monkeypatch)
    monkeypatch.setattr("mcp_server.identity._is_http_transport", lambda: True)
    monkeypatch.setenv("OSMCP_ANALYSIS_ALLOWED_HOSTS", allowed)
    if ok:
        assert operations._server_url(url) == url
    else:
        with pytest.raises(ValueError, match="not permitted"):
            operations._server_url(url)


def test_configured_origin_matches_equivalent_forms(monkeypatch):
    # Regression: 'osa' vs 'osa:80' never matched, and a trailing space in OPENSTUDIO_SERVER_URL
    # rejected every call on the shared server
    _stdio_env(monkeypatch)
    monkeypatch.setattr("mcp_server.identity._is_http_transport", lambda: True)
    monkeypatch.setenv("OPENSTUDIO_SERVER_URL", "http://osa:80 ")
    assert operations._server_url(None) == "http://osa:80"
    assert operations._server_url("http://osa") == "http://osa"


def test_api_token_only_sent_to_configured_origin(monkeypatch):
    # Validates: the operator bearer token never leaves the configured origin (host, port, scheme)
    _stdio_env(monkeypatch)
    monkeypatch.setenv("OPENSTUDIO_SERVER_URL", "http://osa:8080")
    monkeypatch.setenv("OPENSTUDIO_API_TOKEN", "secret")
    assert operations._auth_headers("http://osa:8080") == {"Authorization": "Bearer secret"}
    assert operations._auth_headers("http://osa:8080/") == {"Authorization": "Bearer secret"}
    assert operations._auth_headers("http://evil:8080") == {}
    assert operations._auth_headers("http://osa:8081") == {}
    monkeypatch.setenv("OPENSTUDIO_SERVER_URL", "https://osa.example")
    assert operations._auth_headers("http://osa.example") == {}
    assert operations._auth_headers("https://osa.example:443") == {"Authorization": "Bearer secret"}


def test_stdio_token_without_configured_server_is_refused(monkeypatch):
    # Regression: with OPENSTUDIO_API_TOKEN set but no OPENSTUDIO_SERVER_URL the token was silently
    # withheld from the caller-supplied URL and every request came back 401 with no hint
    _stdio_env(monkeypatch)
    monkeypatch.setenv("OPENSTUDIO_API_TOKEN", "secret")
    monkeypatch.setattr(operations, "urlopen", _never_called)
    res = operations.get_analysis_status("x", server_url="http://osa:8080")
    assert res["ok"] is False
    assert "set OPENSTUDIO_SERVER_URL" in res["error"], res


def _submit_with_bad_url(tmp_path):
    osa_path = tmp_path / "osa.json"
    operations.create_osa_json(str(osa_path), "Rule Five", seed="./seed.osm", weather_file="./w.epw")
    return operations.submit_analysis(project_id="p", osa_json_path=str(osa_path), server_url="file:///x#")


@pytest.mark.parametrize("call", [
    lambda _t: operations.check_server_health("file:///x#"),
    lambda _t: operations.get_analysis_status("a", server_url="file:///x#"),
    lambda _t: operations.start_analysis("a", server_url="file:///x#"),
    lambda t: operations.download_analysis_data("a", output_dir=str(t), server_url="file:///x#"),
    lambda _t: operations.get_analysis_results_json("a", server_url="file:///x#"),
    lambda _t: operations.wait_for_analysis(
        "a", server_url="file:///x#", poll_interval_seconds=1, timeout_seconds=1,
    ),
    lambda t: operations.test_server_config_single_run(str(t / "pkg.zip"), server_url="file:///x#"),
    _submit_with_bad_url,
])
def test_bad_server_url_returns_error_not_exception(monkeypatch, tmp_path, call):
    # Regression: _server_url raised ValueError outside any handler in six entry points, so a bad
    # server_url escaped through MCP as a raw error instead of {"ok": false}
    _stdio_env(monkeypatch)
    monkeypatch.setattr(operations, "urlopen", _never_called)
    res = call(tmp_path)
    assert res["ok"] is False
    assert "absolute http(s)" in res["error"], res


def test_request_turns_invalid_url_into_error(monkeypatch):
    # Regression: http.client.InvalidURL is not a URLError, so a URL the stdlib refuses at the
    # socket layer escaped _request_json as a raw exception
    from http.client import InvalidURL

    _stdio_env(monkeypatch)

    def raise_invalid(req, timeout):
        raise InvalidURL("nonnumeric port: 'x'")

    monkeypatch.setattr(operations, "urlopen", raise_invalid)
    res = operations.get_analysis_status("a", server_url="http://osa:8080")
    assert res["ok"] is False
    assert "nonnumeric port" in res["error"], res


_EVIL_ID = "../../admin/secret?"
_QUOTED_ID = "..%2F..%2Fadmin%2Fsecret%3F"


@pytest.mark.parametrize(("call", "expected_path"), [
    (lambda: operations.get_analysis_status(_EVIL_ID), f"/analyses/{_QUOTED_ID}/status.json"),
    (lambda: operations.get_analysis_results_json(_EVIL_ID), f"/analyses/{_QUOTED_ID}/analysis_data.json"),
    (lambda: operations.start_analysis(_EVIL_ID), f"/analyses/{_QUOTED_ID}/action.json"),
])
def test_path_segments_are_fully_quoted(monkeypatch, call, expected_path):
    # Regression: quote() keeps '/', so analysis_id='../../admin/secret?' sent
    # GET /analyses/../../admin/secret%3F/status.json with the operator token attached
    _stdio_env(monkeypatch)
    monkeypatch.setenv("OPENSTUDIO_SERVER_URL", "http://osa:8080")
    seen = []

    def fake(req, timeout):
        seen.append(req.full_url)
        return _FakeResponse(b'{"analysis": {"status": "completed"}}')

    monkeypatch.setattr(operations, "urlopen", fake)
    res = call()
    assert res["ok"] is True, res
    assert seen == ["http://osa:8080" + expected_path]


@pytest.mark.parametrize("fmt", ["../../../../admin/users", "csv?x=1", "json", "CSV", ""])
def test_download_rejects_unknown_file_format(monkeypatch, tmp_path, fmt):
    # Regression: file_format was interpolated into the URL path, so '../../admin/users' fetched an
    # arbitrary server path with the operator token and saved the body under the tenant's dir
    _stdio_env(monkeypatch)
    monkeypatch.setattr(operations, "urlopen", _never_called)
    res = operations.download_analysis_data(
        "1", output_dir=str(tmp_path), server_url="http://osa:8080", file_format=fmt,
    )
    assert res == {"ok": False, "error": f"file_format must be one of csv, rdata; got {fmt!r}"}


def test_download_gates_output_dir_before_request(monkeypatch, tmp_path):
    # Regression: _download fetched and buffered the whole body before checking output_dir, so a
    # disallowed directory still cost a full authenticated download
    _http_tenant(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENSTUDIO_SERVER_URL", "http://osa:8080")
    monkeypatch.setattr(operations, "urlopen", _never_called)
    res = operations.download_analysis_data("1", output_dir=str(tmp_path / "outside"))
    assert res["ok"] is False
    assert "not writable/allowed" in res["error"], res


def test_urlopen_refuses_file_scheme(tmp_path):
    # Validates: the module opener has no file:// handler, so a file URL can never read local files
    from urllib.error import URLError
    from urllib.request import Request

    target = tmp_path / "x.txt"
    target.write_text("hi")
    with pytest.raises(URLError):
        operations.urlopen(Request(target.as_uri()), timeout=1)  # noqa: S310


def test_urlopen_refuses_redirects():
    # Validates: a redirect is refused outright (a hostile server could bounce the bearer header
    # to another host), with a message that names the refusal rather than a generic HTTPError
    from urllib.error import HTTPError
    from urllib.request import Request

    seen: list[str] = []
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(HTTPError, match=r"redirect to http://127\.0\.0\.1:1/ refused"):
            operations.urlopen(Request(f"http://127.0.0.1:{srv.server_port}/"), timeout=2)
    finally:
        srv.shutdown()
    assert seen == ["/"]


@pytest.mark.parametrize("ref", ["http://127.0.0.1:{port}/meta-data/iam", "file:///etc/hostname"])
def test_schema_remote_ref_is_never_fetched(monkeypatch, tmp_path, ref):
    # Regression: jsonschema resolved a remote $ref in a tenant-supplied schema with its own urllib,
    # an SSRF/file read that bypassed every URL and path gate in this module
    root = _http_tenant(monkeypatch, tmp_path)
    hits: list[str] = []
    srv, port = _local_http_server(hits)
    try:
        schema = root / "evil_schema.json"
        schema.write_text(json.dumps({"$ref": ref.format(port=port)}), encoding="utf-8")
        osa = root / "x.json"
        osa.write_text(
            json.dumps({"analysis": {"name": "x", "problem": {"analysis_type": "single_run"}}}), encoding="utf-8",
        )
        res = operations.validate_osa_json(str(osa), schema_path=str(schema))
    finally:
        srv.shutdown()
    assert res["ok"] is False
    assert "remote or unresolvable $ref" in res["error"], res
    assert hits == []
    assert "hostname" not in json.dumps(res).replace("/etc/hostname", "")


def test_schema_internal_refs_still_resolve(monkeypatch, tmp_path):
    # Validates: refusing remote retrieval must not break '#/definitions/...' refs, which the
    # shipped OSA schema relies on
    _stdio_env(monkeypatch)
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({
        "definitions": {"a": {"type": "string"}},
        "properties": {"analysis": {"$ref": "#/definitions/a"}},
    }), encoding="utf-8")
    osa = tmp_path / "x.json"
    osa.write_text(json.dumps({"analysis": 1}), encoding="utf-8")
    res = operations.validate_osa_json(str(osa), schema_path=str(schema))
    assert res["schema_issues"] == ["$.analysis: 1 is not of type 'string'"]


def test_schema_path_outside_tenant_root_refused(monkeypatch, tmp_path):
    # Regression: a caller-supplied schema_path read any file on the server, and its content came
    # back through the SchemaError message
    root = _http_tenant(monkeypatch, tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"secret": "TOPSECRET", "type": "nope"}), encoding="utf-8")
    osa = root / "x.json"
    osa.write_text("{}", encoding="utf-8")
    res = operations.validate_osa_json(str(osa), schema_path=str(outside))
    assert res["ok"] is False
    assert "Schema path is not allowed" in res["error"], res
    assert "TOPSECRET" not in json.dumps(res)


def test_static_workflow_extracts_under_tenant_root_in_http_mode(monkeypatch, tmp_path):
    # Regression: the smoke test extracted packaged measures to the global tempdir, which the
    # HTTP-mode path gate rejects, so openstudio_analysis_test_server_config was dead on the
    # shared server ("Measure directory is not allowed: /tmp/openstudio_smoke_measures_...")
    root = _http_tenant(monkeypatch, tmp_path)
    pkg = root / "pkg.zip"
    with zipfile.ZipFile(pkg, "w") as archive:
        archive.writestr("measures/m1/measure.xml", _measure_xml("m1"))
        archive.writestr("measures/m1/measure.rb", "class M1; end")
    workflow = operations._build_static_workflow_from_package(
        str(pkg), {"measure_files": ["measures/m1/measure.xml", "measures/m1/measure.rb"]},
    )
    assert [step["measure_definition_name"] for step in workflow] == ["m1"]
    assert [p.name for p in root.iterdir()] == ["pkg.zip"], "extraction temp dir must be cleaned up"


def test_smoke_test_requires_configured_server_url(monkeypatch, tmp_path):
    # Regression: server_url defaulted to http://localhost:8080, which HTTP mode rejects and which
    # stdio mode used even when OPENSTUDIO_SERVER_URL pointed somewhere else
    _stdio_env(monkeypatch)
    monkeypatch.setattr(operations, "urlopen", _never_called)
    res = operations.test_server_config_single_run(str(tmp_path / "pkg.zip"))
    assert res["ok"] is False
    assert "Missing server_url" in res["error"], res


def test_multipart_upload_rejects_path_outside_tenant_root(monkeypatch, tmp_path):
    # Regression: the upload file path was sent to the server without the tenant path gate, so any
    # readable server file could be exfiltrated to the OpenStudio Server
    _http_tenant(monkeypatch, tmp_path)
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"PK")
    res = operations._multipart_upload("http://osa:8080", "/x", str(outside))
    assert res["ok"] is False
    assert "not allowed" in res["error"], res


def test_tmp_fallback_disabled_in_http_mode(monkeypatch, tmp_path):
    # Validates: /tmp is shared between tenants, so the stdio-only tempdir allowance is off on the
    # shared server
    _stdio_env(monkeypatch)
    monkeypatch.setattr("mcp_server.identity._is_http_transport", lambda: True)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    assert operations._is_analysis_path_allowed((tmp_path / "f").resolve()) is False


def test_http_tenant_cannot_touch_sibling_root(monkeypatch, tmp_path):
    # Validates: the tenant fixture is a real scoped tenant (not 'local' owning RUN_ROOT), so a
    # sibling tenant's dir is refused for both reads and writes
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "m").mkdir()
    (bob / "m" / "measure.xml").write_text(_measure_xml("m"), encoding="utf-8")
    with pytest.raises(ValueError, match="not allowed"):
        operations._read_measure_metadata(bob / "m")
    with pytest.raises(ValueError, match="not writable/allowed"):
        operations._write_json(bob / "x.json", {})
    assert operations._write_json(root / "x.json", {}) == str(root / "x.json")


def test_server_url_rejects_query_fragment_and_foreign_path(monkeypatch):
    # Regression: with OPENSTUDIO_SERVER_URL=http://osa/prefix, server_url=http://osa/admin/secret#
    # passed the origin check and the endpoint landed in the fragment, so the request (with the
    # operator token) went to /admin/secret; a plain foreign path on the same host was accepted too
    _stdio_env(monkeypatch)
    monkeypatch.setattr("mcp_server.identity._is_http_transport", lambda: True)
    monkeypatch.setenv("OPENSTUDIO_SERVER_URL", "http://osa/prefix")
    monkeypatch.setenv("OPENSTUDIO_API_TOKEN", "secret")
    for bad in ("http://osa/admin/secret#", "http://osa/prefix?x=1", "http://osa/prefix#"):
        with pytest.raises(ValueError, match="query or fragment"):
            operations._server_url(bad)
    with pytest.raises(ValueError, match="not permitted"):
        operations._server_url("http://osa/admin")
    assert operations._server_url("http://osa/prefix/") == "http://osa/prefix"
    assert operations._auth_headers("http://osa/prefix") == {"Authorization": "Bearer secret"}
    assert operations._auth_headers("http://osa/admin") == {}


@pytest.mark.parametrize("bad_id", ["..", ".", "...", ""])
def test_dot_only_ids_are_refused(monkeypatch, bad_id):
    # Regression: quote(safe='') leaves '.' alone, so analysis_id='..' still sent
    # /analyses/../status.json, which servers and proxies collapse out of the namespace
    _stdio_env(monkeypatch)
    monkeypatch.setattr(operations, "urlopen", _never_called)
    for res in (
        operations.get_analysis_status(bad_id, server_url="http://osa:8080"),
        operations.start_analysis(bad_id, server_url="http://osa:8080"),
        operations.download_analysis_data(bad_id, output_dir=".", server_url="http://osa:8080"),
        operations.get_analysis_results_json(bad_id, server_url="http://osa:8080"),
    ):
        assert res["ok"] is False
        assert "invalid identifier" in res["error"], res


def test_dot_only_project_id_is_refused(monkeypatch, tmp_path):
    # Regression: project_id went through the same quote() path as analysis_id
    _stdio_env(monkeypatch)
    monkeypatch.setattr(operations, "urlopen", _never_called)
    osa_path = tmp_path / "osa.json"
    operations.create_osa_json(str(osa_path), "Dots", seed="./seed.osm", weather_file="./w.epw")
    res = operations.submit_analysis(project_id="..", osa_json_path=str(osa_path), server_url="http://osa:8080")
    assert res["ok"] is False
    assert "invalid identifier" in res["error"], res


def test_non_ascii_server_url_returns_error(monkeypatch):
    # Regression: a non-ASCII path passed validation and http.client raised UnicodeEncodeError,
    # which is neither URLError nor HTTPException, so it escaped as a raw exception
    _stdio_env(monkeypatch)
    res = operations.get_analysis_status("a", server_url="http://osa:8080/caf\u00e9")
    assert res["ok"] is False
    assert "ASCII" in res["error"], res


def test_download_never_writes_through_planted_symlink(monkeypatch, tmp_path):
    # Regression: output_dir was gated but the final file was not, so results.csv planted as a
    # symlink into another tenant's root made write_bytes overwrite that tenant's file
    root = _http_tenant(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENSTUDIO_SERVER_URL", "http://osa:8080")
    victim = root.parent / "bob" / "victim.csv"
    victim.write_text("keep", encoding="utf-8")
    (root / "results.csv").symlink_to(victim)

    def serve_csv(req, timeout):
        return _FakeResponse(
            b"evil", {"content-disposition": 'attachment; filename="results.csv"', "content-type": "text/csv"},
        )

    monkeypatch.setattr(operations, "urlopen", serve_csv)
    res = operations.download_analysis_data("1", output_dir=str(root))
    assert res["ok"] is False
    assert "symlink" in res["error"], res
    assert victim.read_text(encoding="utf-8") == "keep"


def test_measure_xml_symlink_outside_tenant_refused(monkeypatch, tmp_path):
    # Regression: the measure dir was gated but measure.xml inside it was not, so a symlink to
    # another tenant's measure.xml was parsed and its metadata returned
    root = _http_tenant(monkeypatch, tmp_path)
    bob_xml = root.parent / "bob" / "measure.xml"
    bob_xml.write_text(_measure_xml("bobs_secret_measure"), encoding="utf-8")
    (root / "m").mkdir()
    (root / "m" / "measure.xml").symlink_to(bob_xml)
    with pytest.raises(ValueError, match=r"measure.xml is not allowed"):
        operations._read_measure_metadata(root / "m")


def _package_layout(pkg: Path) -> None:
    for sub in ("seeds", "weather", "scripts/data_point", "lib", "measures/SetWWR"):
        (pkg / sub).mkdir(parents=True)
    (pkg / "seeds" / "example.osm").write_bytes(b"OSM seed contents")
    (pkg / "weather" / "example.epw").write_text("weather", encoding="utf-8")
    (pkg / "scripts" / "data_point" / "initialization.sh").write_text("exit 0\n", encoding="utf-8")
    (pkg / "measures" / "SetWWR" / "measure.rb").write_text("class SetWWR; end", encoding="utf-8")
    (pkg / "measures" / "SetWWR" / "measure.xml").write_text(
        _measure_xml("set_wwr", class_name="SetWWR"), encoding="utf-8",
    )


def _fake_ready_preflight(monkeypatch) -> None:
    def preflight(**kwargs):
        manifest = {
            "ok": True, "ready": True, "run_id": "run_seed_preflight_123",
            "seed_sha256": hashlib.sha256(b"OSM seed contents").hexdigest(),
            "basic_qaqc": {"passed": True, "issues": []},
        }
        Path(kwargs["manifest_path"]).write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    monkeypatch.setattr(operations, "preflight_seed_for_analysis_package", preflight)


def test_package_zip_never_follows_symlink_into_sibling_tenant(monkeypatch, tmp_path):
    # Regression: archive.write() followed lib/stolen.txt -> bob's file, so another tenant's
    # content landed in alice's package zip as a regular member (invisible to later zip checks)
    root = _http_tenant(monkeypatch, tmp_path)
    _fake_ready_preflight(monkeypatch)
    common = tmp_path / "common_measures"
    for name in ("view_model", "openstudio_results", "generic_qaqc"):
        (common / name).mkdir(parents=True)
        (common / name / "measure.rb").write_text(f"class {name}; end", encoding="utf-8")
        (common / name / "measure.xml").write_text(_measure_xml(name), encoding="utf-8")
    monkeypatch.setenv("COMMON_MEASURES_DIR", str(common))
    secret = root.parent / "bob" / "secret.txt"
    secret.write_text("BOBSECRET", encoding="utf-8")
    pkg = root / "package"
    _package_layout(pkg)
    (pkg / "lib" / "stolen.txt").symlink_to(secret)
    out = root / "analysis.zip"
    res = operations.prepare_analysis_package(package_dir=str(pkg), output_zip_path=str(out))
    assert res["ok"] is False
    assert res["error"] == "package member is a symlink (not allowed): lib/stolen.txt"
    assert not out.exists()


def test_foundational_copy_refuses_symlinked_measures_dir(monkeypatch, tmp_path):
    # Regression: package/measures planted as a symlink into bob's root made the foundational
    # measure copy rmtree() and copytree() inside bob's directory
    root = _http_tenant(monkeypatch, tmp_path)
    _fake_ready_preflight(monkeypatch)
    bob_measures = root.parent / "bob" / "measures"
    (bob_measures / "view_model").mkdir(parents=True)
    (bob_measures / "view_model" / "keep.rb").write_text("keep", encoding="utf-8")
    pkg = root / "package"
    _package_layout(pkg)
    import shutil

    shutil.rmtree(pkg / "measures")
    (pkg / "measures").symlink_to(bob_measures, target_is_directory=True)
    res = operations.prepare_analysis_package(package_dir=str(pkg), output_zip_path=str(root / "analysis.zip"))
    assert res["ok"] is False
    assert "symlink" in res["foundational_measures"]["error"], res
    assert sorted(p.name for p in bob_measures.rglob("*")) == ["keep.rb", "view_model"]


def test_submit_returns_error_for_unusable_server_analysis_id(monkeypatch, tmp_path):
    # Regression: an analysis id of '..' returned by the server reached _seg() outside any
    # handler when building the upload URL, so submit_analysis raised through MCP
    _stdio_env(monkeypatch)
    osa_path = tmp_path / "osa.json"
    operations.create_osa_json(str(osa_path), "Upload Me", seed="./seed.osm", weather_file="./w.epw")
    pkg_zip = tmp_path / "pkg.zip"
    with zipfile.ZipFile(pkg_zip, "w") as archive:
        archive.writestr("seeds/example.osm", "seed")
    monkeypatch.setattr(operations, "validate_analysis_package", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(operations, "urlopen", lambda *_a, **_k: _FakeResponse(b'{"_id": ".."}'))
    res = operations.submit_analysis(
        project_id="p", osa_json_path=str(osa_path), server_url="http://osa:8080", upload_zip_path=str(pkg_zip),
    )
    assert res["ok"] is False
    assert "invalid identifier '..'" in res["error"], res
    assert res["analysis_id"] == ".."


def test_measure_metadata_and_manifest_gated_by_tenant_root(monkeypatch, tmp_path):
    # Regression: measure.xml reads and manifest writes accepted paths outside the tenant root
    root = _http_tenant(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="not allowed"):
        operations._read_measure_metadata(tmp_path / "m")
    seed = root / "s.osm"
    seed.write_text("x", encoding="utf-8")
    res = operations.preflight_seed_for_analysis_package(
        str(seed), manifest_path=str(tmp_path / "m" / "m.json"),
    )
    assert res["ok"] is False
    assert "not writable/allowed" in res["error"], res
    assert not (tmp_path / "m").exists()
