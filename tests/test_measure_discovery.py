"""Unit tests for measure discovery behavior."""
from __future__ import annotations

import importlib
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
    assert result["archive_path"] == str(bcl_root / "test_measure.zip")
    assert result["extract_dir"] == str(bcl_root / "test_measure")
    assert measure_dir.joinpath("measure.rb").is_file()
    assert calls[0][0].full_url == "https://bcl.nrel.gov/api/measure/download/test_measure.zip"
    assert calls[0][0].headers["User-agent"] == "openstudio-mcp/measure-downloader"
    assert calls[0][1] == 12


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
