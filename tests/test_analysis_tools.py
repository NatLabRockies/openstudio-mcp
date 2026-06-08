import json
from io import BytesIO

from mcp_server.skills.analysis import operations


def test_create_and_validate_osa_json(tmp_path):
    path = tmp_path / "osa.json"

    created = operations.create_osa_json(
        output_path=str(path),
        analysis_name="Baseline Analysis",
        analysis_type="single_run",
        workflow=[{"name": "openstudio_results", "arguments": []}],
        output_variables=[{"name": "openstudio_results.electricity_ip"}],
        algorithm={"debug_messages": 1},
    )

    assert created["ok"] is True
    assert created["osa_json_path"] == str(path.resolve())

    data = json.loads(path.read_text())
    assert data["analysis"]["display_name"] == "Baseline Analysis"
    assert data["analysis"]["name"] == "baseline_analysis"
    assert data["analysis"]["problem"]["analysis_type"] == "single_run"

    validation = operations.validate_osa_json(str(path))
    assert validation["ok"] is True
    assert validation["issues"] == []
    assert validation["analysis_type"] == "single_run"


def test_validate_osa_json_reports_missing_required_fields(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"analysis": {"problem": {}}}))

    validation = operations.validate_osa_json(str(path))

    assert validation["ok"] is False
    assert "analysis.name is missing." in validation["issues"]
    assert "analysis.uuid is missing." in validation["issues"]
    assert "analysis.problem.analysis_type is missing." in validation["issues"]


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
    assert data["analysis"]["problem"]["analysis_type"] == "batch_run"
    assert data["analysis"]["problem"]["algorithm"] == {"sampling_algorithm": "full_factorial"}
    assert len(workflow) == 1

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
    step = data["analysis"]["problem"]["workflow"][0]
    assert step["arguments"][0]["name"] == "building_name"
    assert step["arguments"][0]["value"] == "Fixed Name"
    assert step["variables"] == []


def test_submit_analysis_posts_to_project_endpoint(monkeypatch, tmp_path):
    osa_path = tmp_path / "osa.json"
    operations.create_osa_json(str(osa_path), "Submit Me")
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
