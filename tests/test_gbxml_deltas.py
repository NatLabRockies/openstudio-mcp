"""Unit-style tests for find_gbxml_geometry_deltas (mcp_server/skills/geometry/gbxml_deltas.py).

Uses small hand-built synthetic gbXML + a matching in-memory OSM rather than a
full Revit export — this is the pure comparison function, not the gbXML
translation pipeline (that's covered end-to-end in test_gbxml_import.py's
repair_and_validate_gbxml_geometry wiring test). No mocking: real openstudio
SDK objects throughout, just minimal ones instead of a multi-megabyte fixture.
"""
import uuid
from pathlib import Path

import pytest

openstudio = pytest.importorskip("openstudio")

from mcp_server import model_manager  # noqa: E402
from mcp_server.config import user_run_root  # noqa: E402
from mcp_server.skills.geometry.gbxml_deltas import find_gbxml_geometry_deltas  # noqa: E402


def _allowed_tmp_dir() -> Path:
    """A writable dir is_path_allowed() accepts — pytest's own tmp_path (/tmp) is outside
    this server's sandbox roots, and find_gbxml_geometry_deltas correctly rejects it."""
    d = user_run_root() / "pytest_gbxml_deltas" / uuid.uuid4().hex[:10]
    d.mkdir(parents=True, exist_ok=True)
    return d

SYNTHETIC_GBXML = """<?xml version="1.0" encoding="UTF-8"?>
<gbXML areaUnit="SquareMeters" volumeUnit="CubicMeters" xmlns="http://www.gbxml.org/schema">
  <Campus>
    <Building>
      <Space id="sp-match-area">
        <Area>50.0</Area>
        <Volume>150.0</Volume>
      </Space>
      <Space id="sp-clean">
        <Area>20.0</Area>
      </Space>
      <Space id="sp-empty"></Space>
    </Building>
  </Campus>
</gbXML>
"""


def _build_model_and_load(tmp_dir: Path) -> None:
    """Build the synthetic OSM matching SYNTHETIC_GBXML and load it as the current session model."""
    model = openstudio.model.Model()

    space_a = openstudio.model.Space(model)
    space_a.setName("Space A")
    space_a.setGBXMLId("sp-match-area")
    space_a.setFloorArea(80.0)  # gbXML says 50.0 -> 60% area delta; volume stays 0.0 vs gbXML's 150.0

    space_b = openstudio.model.Space(model)
    space_b.setName("Space B")
    space_b.setGBXMLId("sp-clean")
    space_b.setFloorArea(20.0)  # exact match to gbXML's 20.0 -> no area delta; no <Volume> to compare

    space_c = openstudio.model.Space(model)
    space_c.setName("Space C")
    space_c.setGBXMLId("sp-empty")
    space_c.setFloorArea(999.0)  # gbXML id exists but has neither Area nor Volume -> nothing to compare

    space_d = openstudio.model.Space(model)
    space_d.setName("Space D")
    space_d.setGBXMLId("sp-not-in-file")  # id absent from the gbXML entirely

    space_e = openstudio.model.Space(model)
    space_e.setName("Space E")
    # no setGBXMLId() call at all -> gbXMLId() stays uninitialized

    osm_path = tmp_dir / "synthetic.osm"
    model.save(str(osm_path), True)
    model_manager.load_model(osm_path)


def test_find_gbxml_geometry_deltas_detects_area_and_volume_mismatch():
    # Regression: a space whose model floor area/volume drifted from the gbXML source
    # (e.g. via weld_coincident_vertices/merge_coplanar_sliver_surfaces) must be flagged.
    tmp_dir = _allowed_tmp_dir()
    _build_model_and_load(tmp_dir)
    gbxml_path = tmp_dir / "synthetic.xml"
    gbxml_path.write_text(SYNTHETIC_GBXML, encoding="utf-8")

    result = find_gbxml_geometry_deltas(str(gbxml_path))

    assert result["ok"] is True
    assert result["gbxml_spaces_checked_count"] == 3
    assert result["gbxml_spaces_skipped_no_source_data_count"] == 1
    assert result["gbxml_spaces_skipped_no_gbxml_id_count"] == 1

    assert result["gbxml_area_delta_count"] == 1
    area_delta = result["gbxml_area_deltas"][0]
    assert area_delta["space"] == "Space A"
    assert area_delta["gbxml_area_m2"] == 50.0
    assert area_delta["osm_area_m2"] == 80.0
    assert area_delta["delta_pct"] == pytest.approx(60.0, abs=0.01)

    assert result["gbxml_volume_delta_count"] == 1
    volume_delta = result["gbxml_volume_deltas"][0]
    assert volume_delta["space"] == "Space A"
    assert volume_delta["gbxml_volume_m3"] == 150.0
    assert volume_delta["osm_volume_m3"] == 0.0
    assert volume_delta["delta_pct"] == pytest.approx(100.0, abs=0.01)


def test_find_gbxml_geometry_deltas_clean_space_not_reported():
    # Validates: an exact area match, and a space with no comparable gbXML data at all,
    # never appear in either delta list — only genuine mismatches are reported.
    tmp_dir = _allowed_tmp_dir()
    _build_model_and_load(tmp_dir)
    gbxml_path = tmp_dir / "synthetic.xml"
    gbxml_path.write_text(SYNTHETIC_GBXML, encoding="utf-8")

    result = find_gbxml_geometry_deltas(str(gbxml_path))

    flagged_spaces = {d["space"] for d in result["gbxml_area_deltas"]} | \
        {d["space"] for d in result["gbxml_volume_deltas"]}
    assert "Space B" not in flagged_spaces
    assert "Space C" not in flagged_spaces


def test_find_gbxml_geometry_deltas_missing_file():
    # Validates: a bad path returns ok=False with a specific error, not an exception
    result = find_gbxml_geometry_deltas("/does/not/exist.xml")
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_find_gbxml_geometry_deltas_unsupported_units():
    # Validates: an areaUnit/volumeUnit this parser doesn't know is reported, not guessed at
    gbxml_path = _allowed_tmp_dir() / "weird_units.xml"
    gbxml_path.write_text(
        '<?xml version="1.0"?>\n'
        '<gbXML areaUnit="Hectares" volumeUnit="CubicMeters" '
        'xmlns="http://www.gbxml.org/schema"></gbXML>\n',
        encoding="utf-8",
    )
    result = find_gbxml_geometry_deltas(str(gbxml_path))
    assert result["ok"] is False
    assert "Hectares" in result["error"]
