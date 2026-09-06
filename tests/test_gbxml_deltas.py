"""Unit-style tests for find_gbxml_geometry_deltas (mcp_server/skills/geometry/gbxml_deltas.py)
and the session stash it reads through (mcp_server/skills/gbxml_import/gbxml_source_state.py).

Uses small hand-built synthetic gbXML + a matching in-memory OSM rather than a
full Revit export — this is the pure comparison function, not the gbXML
translation pipeline (that's covered end-to-end in test_gbxml_import.py's
repair_and_validate_gbxml_geometry wiring test). No mocking: real openstudio
SDK objects throughout, just minimal ones instead of a multi-megabyte fixture.
"""
import tracemalloc
import uuid
from pathlib import Path

import pytest

openstudio = pytest.importorskip("openstudio")

from mcp_server import model_manager  # noqa: E402
from mcp_server.config import user_run_root  # noqa: E402
from mcp_server.skills.gbxml_import.gbxml_source_state import get_source_for_model, set_source  # noqa: E402
from mcp_server.skills.geometry.gbxml_deltas import (  # noqa: E402
    _parse_gbxml_space_geometry,
    find_gbxml_geometry_deltas,
)

# Imports the real openstudio SDK (importorskip above) — integration tier, must not
# be collected by the unit run.
pytestmark = pytest.mark.integration


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


def _build_model_and_load(tmp_dir: Path) -> openstudio.model.Model:
    """Build the synthetic OSM matching SYNTHETIC_GBXML, load it as the current session
    model, and return that loaded session model."""
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
    return model_manager.load_model(osm_path)


def test_find_gbxml_geometry_deltas_detects_area_and_volume_mismatch():
    # Regression: a space whose model floor area/volume drifted from the gbXML source
    # (e.g. via weld_coincident_vertices/merge_coplanar_sliver_surfaces) must be flagged.
    tmp_dir = _allowed_tmp_dir()
    model = _build_model_and_load(tmp_dir)
    gbxml_path = tmp_dir / "synthetic.xml"
    gbxml_path.write_text(SYNTHETIC_GBXML, encoding="utf-8")

    result = find_gbxml_geometry_deltas(str(gbxml_path), model)

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
    model = _build_model_and_load(tmp_dir)
    gbxml_path = tmp_dir / "synthetic.xml"
    gbxml_path.write_text(SYNTHETIC_GBXML, encoding="utf-8")

    result = find_gbxml_geometry_deltas(str(gbxml_path), model)

    flagged_spaces = {d["space"] for d in result["gbxml_area_deltas"]} | \
        {d["space"] for d in result["gbxml_volume_deltas"]}
    assert "Space B" not in flagged_spaces
    assert "Space C" not in flagged_spaces


def test_find_gbxml_geometry_deltas_compares_the_model_it_is_given():
    # Regression: the helper used to re-fetch the session model after parsing the XML, so a
    # concurrent load_model on the same session could swap the model out from under the
    # caller and the check would compare the NEW model against the OLD model's gbXML. It
    # must compare exactly the model it is handed, even when the session's current model
    # is a different one.
    tmp_dir = _allowed_tmp_dir()
    _build_model_and_load(tmp_dir)  # session's current model: 5 spaces, 3 matchable
    gbxml_path = tmp_dir / "synthetic.xml"
    gbxml_path.write_text(SYNTHETIC_GBXML, encoding="utf-8")

    other = openstudio.model.Model()  # never loaded into the session
    only_space = openstudio.model.Space(other)
    only_space.setName("Other-model space")
    only_space.setGBXMLId("sp-clean")
    only_space.setFloorArea(30.0)  # gbXML says 20.0 -> 50% delta the session model does NOT have

    result = find_gbxml_geometry_deltas(str(gbxml_path), other)

    assert result["ok"] is True
    assert result["gbxml_spaces_checked_count"] == 1, "must count the given model's spaces, not the session's 3"
    assert result["gbxml_spaces_skipped_no_gbxml_id_count"] == 0
    assert result["gbxml_area_delta_count"] == 1
    assert result["gbxml_area_deltas"][0]["space"] == "Other-model space"
    assert result["gbxml_area_deltas"][0]["osm_area_m2"] == 30.0


SCOPED_GBXML = """<?xml version="1.0" encoding="UTF-8"?>
<gbXML areaUnit="SquareMeters" volumeUnit="CubicMeters" xmlns="http://www.gbxml.org/schema">
  <Campus>
    <Location><Name>Somewhere</Name></Location>
    <Building id="bldg-1" buildingType="Office">
      <Area>9999.0</Area>
      <Space id="sp-match-area">
        <Name>Room 101</Name>
        <CADObjectId>abc</CADObjectId>
        <ShellGeometry id="sg-1">
          <ClosedShell>
            <PolyLoop>
              <CartesianPoint><Coordinate>0</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
              <CartesianPoint><Coordinate>5</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
              <CartesianPoint><Coordinate>5</Coordinate><Coordinate>10</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
            </PolyLoop>
          </ClosedShell>
        </ShellGeometry>
        <Area>50.0</Area>
        <Volume>150.0</Volume>
        <PlanarGeometry>
          <PolyLoop>
            <CartesianPoint><Coordinate>0</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
          </PolyLoop>
        </PlanarGeometry>
      </Space>
    </Building>
    <Surface id="su-1" surfaceType="ExteriorWall">
      <AdjacentSpaceId spaceIdRef="sp-match-area"/>
      <PlanarGeometry>
        <PolyLoop>
          <CartesianPoint><Coordinate>0</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
        </PolyLoop>
      </PlanarGeometry>
    </Surface>
  </Campus>
</gbXML>
"""


def test_find_gbxml_geometry_deltas_reads_only_the_space_scoped_area_and_volume():
    # Validates: the streaming parser frees every element outside an open <Space> as it
    # closes — so a Space's Area/Volume must still be read correctly when they sit AFTER
    # other children (Name, ShellGeometry polyloops), when a <Building> carries its own
    # <Area>, and when <Surface> siblings follow the spaces. Reading the Building's 9999
    # or dropping the Space's children before its end event would each change the delta.
    tmp_dir = _allowed_tmp_dir()
    model = _build_model_and_load(tmp_dir)
    gbxml_path = tmp_dir / "scoped.xml"
    gbxml_path.write_text(SCOPED_GBXML, encoding="utf-8")

    result = find_gbxml_geometry_deltas(str(gbxml_path), model)

    assert result["ok"] is True, result
    assert result["gbxml_spaces_checked_count"] == 1
    assert result["gbxml_area_delta_count"] == 1
    assert result["gbxml_area_deltas"][0]["gbxml_area_m2"] == 50.0
    assert result["gbxml_area_deltas"][0]["osm_area_m2"] == 80.0
    assert result["gbxml_volume_delta_count"] == 1
    assert result["gbxml_volume_deltas"][0]["gbxml_volume_m3"] == 150.0


_SURFACE_TEMPLATE = (
    '<Surface id="su-{i}" surfaceType="ExteriorWall"><AdjacentSpaceId spaceIdRef="sp-1"/>'
    '<PlanarGeometry><PolyLoop>'
    '<CartesianPoint><Coordinate>0</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>'
    '<CartesianPoint><Coordinate>5</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>'
    '<CartesianPoint><Coordinate>5</Coordinate><Coordinate>10</Coordinate><Coordinate>0</Coordinate></CartesianPoint>'
    '</PolyLoop></PlanarGeometry></Surface>\n'
)


def test_parse_gbxml_space_geometry_peak_memory_is_flat_in_surface_count():
    # Regression: the streaming parser cleared each finished <Surface> but left its empty
    # shell attached to <Campus>, so peak memory still grew ~80 bytes per surface (about
    # 1.75 MB at the 20k surfaces below, 4 MB at 50k). Detaching finished subtrees from
    # their parent holds the peak at ~0.15 MB regardless of surface count; the 1 MB cap
    # sits well clear of both.
    n_surfaces = 20_000
    gbxml_path = _allowed_tmp_dir() / "many_surfaces.xml"
    with gbxml_path.open("w", encoding="utf-8") as f:
        f.write(
            '<?xml version="1.0"?>\n'
            '<gbXML areaUnit="SquareMeters" volumeUnit="CubicMeters" xmlns="http://www.gbxml.org/schema">'
            '<Campus><Building><Space id="sp-1"><Area>50.0</Area><Volume>150.0</Volume></Space></Building>\n',
        )
        for i in range(n_surfaces):
            f.write(_SURFACE_TEMPLATE.format(i=i))
        f.write("</Campus></gbXML>\n")

    tracemalloc.start()
    try:
        spaces = _parse_gbxml_space_geometry(gbxml_path)
        _current, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert spaces == {"sp-1": {"area_m2": 50.0, "volume_m3": 150.0}}
    assert peak_bytes < 1_000_000, f"peak {peak_bytes / 1e6:.2f} MB for {n_surfaces} surfaces: shells retained"


def test_find_gbxml_geometry_deltas_converts_imperial_units():
    # Validates: areaUnit="SquareFeet"/volumeUnit="CubicFeet" files are converted to SI
    # before comparing — 215.278 ft2 is exactly Space B's 20.0 m2, so no delta; without
    # the conversion this would report a ~976% area delta.
    tmp_dir = _allowed_tmp_dir()
    model = _build_model_and_load(tmp_dir)
    gbxml_path = tmp_dir / "imperial.xml"
    gbxml_path.write_text(
        '<?xml version="1.0"?>\n'
        '<gbXML areaUnit="SquareFeet" volumeUnit="CubicFeet" xmlns="http://www.gbxml.org/schema">'
        '<Campus><Building>'
        '<Space id="sp-clean"><Area>215.27820833</Area></Space>'
        '</Building></Campus></gbXML>\n',
        encoding="utf-8",
    )

    result = find_gbxml_geometry_deltas(str(gbxml_path), model)

    assert result["ok"] is True, result
    assert result["gbxml_spaces_checked_count"] == 1
    assert result["gbxml_area_delta_count"] == 0, result["gbxml_area_deltas"]


def test_find_gbxml_geometry_deltas_missing_file():
    # Validates: a bad path returns ok=False with a specific error, not an exception
    result = find_gbxml_geometry_deltas("/does/not/exist.xml", openstudio.model.Model())
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
    result = find_gbxml_geometry_deltas(str(gbxml_path), openstudio.model.Model())
    assert result["ok"] is False
    assert "Hectares" in result["error"]


def test_gbxml_source_stash_is_bound_to_the_generation_it_was_recorded_for():
    # Regression: the stash used to read model_generation() itself when set, so a
    # concurrent load_model between import_gbxml's own load and the stash write bound the
    # gbXML path to the NEXT model's generation, and the delta check then compared the
    # wrong model against it. The stash now takes the generation the load returned, answers
    # only for that generation, and never lets an older import overwrite a newer one.
    tmp_dir = _allowed_tmp_dir()
    first_osm = tmp_dir / "first.osm"
    openstudio.model.Model().save(str(first_osm), True)
    second_osm = tmp_dir / "second.osm"
    openstudio.model.Model().save(str(second_osm), True)

    _first, first_gen = model_manager.load_model_with_generation(first_osm)
    set_source("/runs/first/gbxmls/first.xml", first_gen)
    assert get_source_for_model(first_gen) == "/runs/first/gbxmls/first.xml"

    _second, second_gen = model_manager.load_model_with_generation(second_osm)
    assert second_gen > first_gen
    assert get_source_for_model(second_gen) is None, "a reload must not inherit the previous import's source"
    assert get_source_for_model(first_gen) == "/runs/first/gbxmls/first.xml", \
        "a caller still holding the first model must still resolve its own source"

    set_source("/runs/second/gbxmls/second.xml", second_gen)
    set_source("/runs/late/gbxmls/late.xml", first_gen)  # a slower, older import finishing last
    assert get_source_for_model(second_gen) == "/runs/second/gbxmls/second.xml", \
        "an older generation's late write must not clobber the newer import's stash"
    assert get_source_for_model(first_gen) is None


def test_ensure_generation_unchanged_raises_once_the_model_is_replaced():
    # Validates: the end-of-operation guard repair_and_validate_gbxml_geometry relies on —
    # silent while the captured generation is still current, a RuntimeError naming the
    # generation change once another load has replaced the session model, so one response
    # can never mix results from two models.
    tmp_dir = _allowed_tmp_dir()
    first_osm = tmp_dir / "first.osm"
    openstudio.model.Model().save(str(first_osm), True)
    second_osm = tmp_dir / "second.osm"
    openstudio.model.Model().save(str(second_osm), True)

    _model, generation = model_manager.load_model_with_generation(first_osm)
    model_manager.ensure_generation_unchanged(generation)  # must not raise

    _model, replaced_generation = model_manager.load_model_with_generation(second_osm)
    with pytest.raises(RuntimeError, match=rf"replaced by another tool call.*{generation} -> {replaced_generation}"):
        model_manager.ensure_generation_unchanged(generation)


def test_generation_is_not_reused_after_session_eviction():
    # Regression: the generation was a per-_SessionState counter, so after TTL/LRU eviction
    # dropped a session's state the next load on that same session started again at 1. An
    # in-flight operation that had captured generation 1 then saw the replacement model at
    # generation 1: ensure_generation_unchanged() passed, and a fresh import's gbXML stash
    # recorded under generation 1 answered for the OLD model. Tokens are process-wide now,
    # so a load after eviction can never alias the generation a caller still holds.
    tmp_dir = _allowed_tmp_dir()
    first_osm = tmp_dir / "first.osm"
    openstudio.model.Model().save(str(first_osm), True)
    second_osm = tmp_dir / "second.osm"
    openstudio.model.Model().save(str(second_osm), True)

    model_manager.clear_model()  # fresh session state: a per-session counter would start at 1 here
    _first, held_generation = model_manager.load_model_with_generation(first_osm)
    model_manager.clear_model()  # same registry pop that _sweep_idle()/_evict_if_needed() perform
    _second, after_eviction = model_manager.load_model_with_generation(second_osm)

    assert after_eviction > held_generation, "a load after eviction must not reuse a generation still held by a caller"
    with pytest.raises(RuntimeError, match="replaced by another tool call"):
        model_manager.ensure_generation_unchanged(held_generation)
    set_source("/runs/after/gbxmls/after.xml", after_eviction)
    assert get_source_for_model(held_generation) is None, "the new import's stash must not answer for the evicted model"


def test_get_model_with_generation_matches_load_model_with_generation():
    # Validates: the generation get_model_with_generation() pairs with the model is the
    # same one load_model_with_generation() reported for it — the two ends of the
    # stash-and-verify contract agree, and the returned model is the loaded one.
    tmp_dir = _allowed_tmp_dir()
    osm = tmp_dir / "gen.osm"
    probe_model = openstudio.model.Model()
    openstudio.model.Space(probe_model).setName("gen-probe")
    probe_model.save(str(osm), True)

    loaded, load_gen = model_manager.load_model_with_generation(osm)
    current, current_gen = model_manager.get_model_with_generation()

    assert current_gen == load_gen
    assert current_gen == model_manager.model_generation()
    assert [s.nameString() for s in current.getSpaces()] == ["gen-probe"]
    # Same underlying Model, not merely equal content: a rename through one handle is
    # visible through the other.
    loaded.getSpaces()[0].setName("renamed-via-loaded")
    assert [s.nameString() for s in current.getSpaces()] == ["renamed-via-loaded"]
