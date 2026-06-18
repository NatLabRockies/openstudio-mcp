"""Unit tests for measure discovery behavior."""
from __future__ import annotations

import importlib
import json
import os
import sys
import types
import zipfile
from io import BytesIO
from pathlib import Path

import pytest


BCL_CONTENT_URL = "https://bcl.nlr.gov/content/c567a0bf-a7d9-4a06-afe9-bf7df79e6bf8"


def _import_measure_ops(monkeypatch, run_root: Path):
    fake_openstudio = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "openstudio", fake_openstudio)
    monkeypatch.setenv("OPENSTUDIO_MCP_RUN_ROOT", str(run_root))
    sys.modules.pop("mcp_server.config", None)
    sys.modules.pop("mcp_server.skills.measures.operations", None)
    return importlib.import_module("mcp_server.skills.measures.operations")


def _import_real_measure_ops():
    sys.modules.pop("mcp_server.skills.measures.operations", None)
    return importlib.import_module("mcp_server.skills.measures.operations")


def _make_measure(root, name):
    measure_dir = root / name
    measure_dir.mkdir(parents=True)
    (measure_dir / "measure.rb").write_text("# test measure\n", encoding="utf-8")
    return measure_dir


class _FakeDownloadResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False

    def read(self):
        return self.payload


def _measure_zip() -> bytes:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("downloaded_measure/measure.rb", "# downloaded test measure\n")
        archive.writestr("downloaded_measure/measure.xml", "<measure></measure>\n")
    return payload.getvalue()


def test_list_local_measures_prefers_checkouts_before_bcl(monkeypatch, tmp_path):
    # Regression: measure discovery should search local/common/ComStock checkouts
    # before BCL caches so agents do not jump to BCL for measures already bundled.
    ops = _import_measure_ops(monkeypatch, tmp_path / "runs")

    custom_root = tmp_path / "custom"
    mounted_root = tmp_path / "measures"
    input_root = tmp_path / "inputs"
    run_root = tmp_path / "runs"
    common_root = tmp_path / "common"
    comstock_root = tmp_path / "comstock"
    bcl_root = tmp_path / "bcl"

    _make_measure(common_root, "aedg_small_office")
    _make_measure(comstock_root, "change_building_location")
    _make_measure(bcl_root, "aedg_small_office")

    monkeypatch.setattr(ops, "CUSTOM_MEASURES_DIR", custom_root)
    monkeypatch.setattr(ops, "MEASURES_DIR", mounted_root)
    monkeypatch.setattr(ops, "INPUT_ROOT", input_root)
    monkeypatch.setattr(ops, "RUN_ROOT", run_root)
    monkeypatch.setattr(ops, "COMMON_MEASURES_DIR", common_root)
    monkeypatch.setattr(ops, "COMSTOCK_MEASURES_DIR", comstock_root)
    monkeypatch.setattr(ops, "BCL_MEASURES_DIR", bcl_root)
    monkeypatch.setattr(ops, "is_path_allowed", lambda _path: True)
    monkeypatch.setattr(
        ops,
        "_measure_entry",
        lambda path, source: {"name": path.name, "measure_dir": str(path), "source": source},
    )

    result = ops.list_local_measures()

    assert result["ok"] is True
    assert [m["source"] for m in result["measures"]] == ["common", "comstock", "bcl"]


def test_download_measure_archive_pulls_bcl_zip(monkeypatch, tmp_path):
    # Regression: the downloader must accept the real BCL/NREL host, fetch the
    # archive into the default BCL cache, safely extract it, and return
    # discovered measure_dir values.
    ops = _import_measure_ops(monkeypatch, tmp_path / "runs")
    calls = []
    bcl_root = tmp_path / "measures" / "bcl"

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return _FakeDownloadResponse(_measure_zip())

    monkeypatch.setattr(ops, "BCL_MEASURES_DIR", bcl_root)
    monkeypatch.setattr(ops, "is_path_allowed", lambda _path: True)
    monkeypatch.setattr(ops, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        ops,
        "_measure_entry",
        lambda path, source: {"name": path.name, "measure_dir": str(path), "source": source},
    )

    result = ops.download_measure_archive(
        url="https://bcl.nrel.gov/api/measure/download/test_measure.zip",
        timeout_seconds=12,
    )

    assert result["ok"] is True
    assert result["count"] == 1
    measure_dir = bcl_root / "test_measure" / "downloaded_measure"
    assert result["measures"] == [{
        "name": "downloaded_measure",
        "measure_dir": str(measure_dir.resolve()),
        "source": "requested",
    }]
    assert result["measure_dir"] == str(measure_dir.resolve())
    assert result["selected_measure_dir"] == str(measure_dir.resolve())
    assert result["selected_measure"]["measure_dir"] == str(measure_dir.resolve())
    assert result["next"]["apply"]["arguments"]["measure_dir"] == str(measure_dir.resolve())
    assert result["archive_path"] == str(bcl_root / "test_measure.zip")
    assert result["extract_dir"] == str(bcl_root / "test_measure")
    assert measure_dir.joinpath("measure.rb").is_file()
    assert calls[0][0].full_url == "https://bcl.nrel.gov/api/measure/download/test_measure.zip"
    assert calls[0][0].headers["User-agent"] == "openstudio-mcp/measure-downloader"
    assert calls[0][1] == 12


def test_bcl_search_urls_use_wildcard_results_query(monkeypatch, tmp_path):
    # BCL UI searches use /results/*query*?fq=bundle:measure&page=0.
    # The MCP tool uses the matching JSON API path while returning the browser
    # results URL for verification.
    ops = _import_measure_ops(monkeypatch, tmp_path / "runs")

    api_url, results_url = ops._bcl_search_urls(
        "Replace Chiller with Air Source Heat Pumps Measure Details",
        page=0,
        show_rows=30,
    )

    assert api_url == (
        "https://bcl.nlr.gov/api/search/"
        "*Replace%20Chiller%20with%20Air%20Source%20Heat%20Pumps%20Measure%20Details*"
        ".json?fq=bundle:measure&page=0&show_rows=30"
    )
    assert results_url == (
        "https://bcl.nlr.gov/results/"
        "*Replace%20Chiller%20with%20Air%20Source%20Heat%20Pumps%20Measure%20Details*"
        "?fq=bundle:measure&page=0"
    )


def test_find_measure_returns_local_match_before_bcl(monkeypatch, tmp_path):
    # The high-level finder must prefer an existing local/bundled measure over
    # BCL, even if the query came from a BCL page title ending in "Measure Details".
    ops = _import_measure_ops(monkeypatch, tmp_path / "runs")
    local_root = tmp_path / "common"
    _make_measure(local_root, "replace_chiller_with_air_source_heat_pumps")

    monkeypatch.setattr(ops, "CUSTOM_MEASURES_DIR", tmp_path / "custom")
    monkeypatch.setattr(ops, "MEASURES_DIR", tmp_path / "measures")
    monkeypatch.setattr(ops, "INPUT_ROOT", tmp_path / "inputs")
    monkeypatch.setattr(ops, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(ops, "COMMON_MEASURES_DIR", local_root)
    monkeypatch.setattr(ops, "COMSTOCK_MEASURES_DIR", tmp_path / "comstock")
    monkeypatch.setattr(ops, "BCL_MEASURES_DIR", tmp_path / "bcl")
    monkeypatch.setattr(ops, "is_path_allowed", lambda _path: True)
    monkeypatch.setattr(
        ops,
        "_measure_entry",
        lambda path, source: {
            "name": path.name,
            "display_name": "Replace Chiller with Air Source Heat Pumps",
            "measure_dir": str(path),
            "source": source,
        },
    )

    def fail_bcl(*_args, **_kwargs):
        raise AssertionError("BCL should not be searched when local match is strong")

    monkeypatch.setattr(ops, "search_bcl_measures", fail_bcl)

    result = ops.find_measure("Replace Chiller with Air Source Heat Pumps Measure Details")

    assert result["ok"] is True
    assert result["source"] == "local"
    assert result["downloaded"] is False
    assert result["match"]["source"] == "common"
    assert result["measure_dir"] == str(local_root / "replace_chiller_with_air_source_heat_pumps")
    assert result["selected_measure_dir"] == str(local_root / "replace_chiller_with_air_source_heat_pumps")
    assert result["selected_measure"]["measure_dir"] == str(local_root / "replace_chiller_with_air_source_heat_pumps")
    assert result["next"]["list_arguments"]["arguments"]["measure_dir"] == result["measure_dir"]
    assert result["next"]["apply"]["arguments"]["measure_dir"] == result["measure_dir"]


def test_find_measure_searches_bcl_and_downloads_good_match(monkeypatch, tmp_path):
    # If local discovery cannot find the requested measure, the high-level
    # finder searches BCL, scores the candidates, and downloads only a good match.
    ops = _import_measure_ops(monkeypatch, tmp_path / "runs")
    bcl_root = tmp_path / "measures" / "bcl"

    monkeypatch.setattr(ops, "CUSTOM_MEASURES_DIR", tmp_path / "custom")
    monkeypatch.setattr(ops, "MEASURES_DIR", tmp_path / "measures")
    monkeypatch.setattr(ops, "INPUT_ROOT", tmp_path / "inputs")
    monkeypatch.setattr(ops, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(ops, "COMMON_MEASURES_DIR", tmp_path / "common")
    monkeypatch.setattr(ops, "COMSTOCK_MEASURES_DIR", tmp_path / "comstock")
    monkeypatch.setattr(ops, "BCL_MEASURES_DIR", bcl_root)
    monkeypatch.setattr(ops, "is_path_allowed", lambda _path: True)
    monkeypatch.setattr(
        ops,
        "_measure_entry",
        lambda path, source: {"name": path.name, "measure_dir": str(path), "source": source},
    )

    bcl_payload = {
        "result": [
            {
                "measure": {
                    "name": "radiant_slab_with_doas",
                    "display_name": "Radiant Slab with DOAS",
                    "uuid": "not-the-one",
                    "download_url": "https://bcl.nlr.gov/api/download?uids=not-the-one",
                }
            },
            {
                "measure": {
                    "name": "replace_chiller_with_air_source_heat_pumps",
                    "display_name": "Replace Chiller with Air Source Heat Pumps",
                    "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "description": (
                        "Replaces the water-cooled chiller with an air-source "
                        "heat pump for cooling."
                    ),
                    "download_url": "https://bcl.nlr.gov/api/download?uids=a1b2c3d4-e5f6",
                }
            },
        ]
    }
    search_calls = []

    def fake_read_url(url, _timeout_seconds):
        if "/api/search/" in url:
            search_calls.append(url)
            return json.dumps(bcl_payload).encode("utf-8"), "application/json"
        if "/api/download" in url:
            return _measure_zip(), "application/zip"
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(ops, "_read_url", fake_read_url)

    result = ops.find_measure("Replace Chiller with Air Source Heat Pumps Measure Details")

    assert result["ok"] is True
    assert result["source"] == "bcl"
    assert result["downloaded"] is True
    assert result["match"]["name"] == "replace_chiller_with_air_source_heat_pumps"
    assert result["match"]["match_score"] >= 0.72
    assert result["measure_dir"].endswith("downloaded_measure")
    assert result["selected_measure_dir"] == result["measure_dir"]
    assert result["selected_measure"]["measure_dir"] == result["measure_dir"]
    assert result["selected_measure"]["downloaded_name"] == "downloaded_measure"
    assert result["next"]["apply"]["arguments"]["measure_dir"] == result["measure_dir"]
    assert Path(result["measure_dir"], "measure.rb").is_file()
    assert search_calls[0].startswith(
        "https://bcl.nlr.gov/api/search/"
        "*Replace%20Chiller%20with%20Air%20Source%20Heat%20Pumps%20Measure%20Details*"
        ".json?"
    )
    assert "fq=bundle:measure" in search_calls[0]
    assert "page=0" in search_calls[0]


@pytest.mark.integration
def test_download_measure_archive_real_bcl_content_url():
    # Validates the live BCL content page flow: fetch content page, resolve its
    # versioned /api/download link, download the archive, and discover measure.rb.
    if os.environ.get("RUN_OPENSTUDIO_INTEGRATION", "").strip() not in ("1", "true", "TRUE", "yes", "YES"):
        pytest.skip("integration disabled")

    ops = _import_real_measure_ops()
    measure_name = "set_window_to_wall_ratio_by_facade"

    result = ops.download_measure_archive(
        url=BCL_CONTENT_URL,
        measure_name=measure_name,
        timeout_seconds=60,
    )

    assert result["ok"] is True, result
    assert result["download_url"].startswith("https://bcl.nlr.gov/api/download?")
    assert "release_tag=v0.12.2" in result["download_url"]
    assert result["count"] == 1
    measure = result["measures"][0]
    assert measure["name"] == "SetWindowToWallRatioByFacade"
    assert measure["has_measure_xml"] is True
    assert measure["measure_type"] == "ModelMeasure"
    assert measure["num_arguments"] == 8
    assert result["extract_dir"] == str(ops.BCL_MEASURES_DIR.resolve() / measure_name)
    assert Path(result["extract_dir"]).is_dir()
    assert Path(measure["measure_dir"]).is_relative_to(ops.BCL_MEASURES_DIR.resolve())
    assert Path(measure["measure_dir"], "measure.rb").is_file()
