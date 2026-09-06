"""Cross-check OpenStudio-computed space geometry against the gbXML source.

`repair_and_validate_gbxml_geometry` confirms a space is enclosed
(`isEnclosedVolume()`), but not that it is still the shape Revit exported —
vertex snapping in `weld_coincident_vertices` or surface consolidation in
`merge_coplanar_sliver_surfaces` can silently shrink or balloon a room's
footprint while it still closes cleanly. Revit's own per-Space Area/Volume,
embedded in the gbXML file itself, is the closest thing to ground truth
available: this re-parses the source .xml (not the translated OSM) and
compares those declared values against `Space.floorArea()`/`Space.volume()`
on the model it is handed.

Report only, like every sibling check in this package (see
ground_contact.py's module docstring) — a delta means "look at this space,"
not "the gbXML value is right and the model is wrong." A Revit room-boundary
bug can just as easily be the actual source of a mismatch.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.parsers import expat

import openstudio

from mcp_server.config import is_path_allowed

# gbXML files declare this namespace on the root <gbXML> element. The expat
# parser below is created with namespace processing, so element names arrive
# as "<uri>}<local>" (bare "Space" would never match).
_GBXML_NS_URI = "http://www.gbxml.org/schema"
_SPACE_TAG = _GBXML_NS_URI + "}Space"
_AREA_TAG = _GBXML_NS_URI + "}Area"
_VOLUME_TAG = _GBXML_NS_URI + "}Volume"

# gbXML's areaUnit/volumeUnit root attributes name the units every <Area>/
# <Volume> element in the file is expressed in — SquareMeters/CubicMeters is
# the overwhelmingly common case (and the only one seen in this project's own
# fixtures), but the schema also allows SquareFeet/CubicFeet.
_AREA_UNIT_TO_M2 = {
    "SquareMeters": 1.0,
    "SquareFeet": 0.09290304,
}
_VOLUME_UNIT_TO_M3 = {
    "CubicMeters": 1.0,
    "CubicFeet": 0.028316846592,
}

# Same 2% used nowhere else in this file's siblings as a named constant, but
# chosen for the same reason PLANE_TOLERANCE/MIN_OVERLAP_AREA_M2 are: loose
# enough to tolerate ordinary weld/merge float noise, tight enough to catch a
# repair that actually changed a room's footprint.
AREA_VOLUME_DELTA_THRESHOLD = 0.02
# Keep the response small — same cap style as gbxml_import/operations.py's
# MAX_REPORTED_ISSUES.
MAX_REPORTED_DELTAS = 20


class _UnsupportedGbxmlUnits(ValueError):
    """areaUnit/volumeUnit on the root element is one this check can't convert."""


class _RejectedGbxml(ValueError):
    """The file uses XML features this check refuses to process (DTD / entity declarations)."""


def _reject_dtd(*_args: Any) -> None:
    # Fires on the first <!DOCTYPE or <!ENTITY token, before any entity is
    # expanded — "billion laughs" style payloads never get to run.
    raise _RejectedGbxml(
        "gbXML with a DOCTYPE/DTD or entity declarations is not accepted: "
        "entity expansion is not allowed in this server process",
    )


def _refuse_external_entity(*_args: Any) -> int:
    # Returning 0 makes expat fail the parse instead of fetching the reference.
    return 0


class _SpaceGeometryReader:
    """expat callback target that keeps only each <Space>'s Area/Volume text.

    No element tree is ever built: the parser hands each start/end/text event
    to these methods and discards it, so peak memory is independent of the
    file size (a Revit export can run to hundreds of MB of <Surface> polyloops
    this check never reads) and this runs safely inside the long-lived server
    process.

    Only <Area>/<Volume> that are direct children of a <Space> are read —
    <Building> carries its own <Area>, and a Space's polyloops carry
    coordinates in other elements — matching what the schema defines.
    gbXML Area/Volume are both optional per the schema even though every
    fixture in this repo happens to populate them — a Space with either one
    absent is recorded as None, never treated as a false 0%/100% delta.
    """

    def __init__(self) -> None:
        self.spaces: dict[str, dict[str, float | None]] = {}
        self._area_factor = 1.0
        self._volume_factor = 1.0
        self._depth = 0
        self._space_depth: int | None = None  # depth of the open <Space>, None outside one
        self._space_id: str | None = None
        self._space_area: str | None = None
        self._space_volume: str | None = None
        self._text_tag: str | None = None  # the <Area>/<Volume> whose text is being collected
        self._text: list[str] = []

    def start(self, name: str, attrs: dict[str, str]) -> None:
        self._depth += 1
        if self._depth == 1:
            # Root attributes: fail on bad units before streaming a possibly huge file.
            area_unit = attrs.get("areaUnit", "SquareMeters")
            volume_unit = attrs.get("volumeUnit", "CubicMeters")
            area_factor = _AREA_UNIT_TO_M2.get(area_unit)
            volume_factor = _VOLUME_UNIT_TO_M3.get(volume_unit)
            if area_factor is None or volume_factor is None:
                raise _UnsupportedGbxmlUnits(
                    f"Unsupported gbXML units (areaUnit={area_unit!r}, volumeUnit={volume_unit!r})",
                )
            self._area_factor = area_factor
            self._volume_factor = volume_factor
        elif self._space_depth is None:
            if name == _SPACE_TAG:
                self._space_depth = self._depth
                self._space_id = attrs.get("id")
                self._space_area = None
                self._space_volume = None
        elif self._depth == self._space_depth + 1 and name in (_AREA_TAG, _VOLUME_TAG):
            self._text_tag = name
            self._text = []

    def data(self, text: str) -> None:
        if self._text_tag is not None:
            self._text.append(text)

    def end(self, name: str) -> None:
        if name == self._text_tag:
            raw = "".join(self._text).strip()
            if name == _AREA_TAG:
                self._space_area = raw
            else:
                self._space_volume = raw
            self._text_tag = None
        elif self._space_depth == self._depth and name == _SPACE_TAG:
            if self._space_id:
                self.spaces[self._space_id] = {
                    "area_m2": float(self._space_area) * self._area_factor if self._space_area else None,
                    "volume_m3": float(self._space_volume) * self._volume_factor if self._space_volume else None,
                }
            self._space_depth = None
        self._depth -= 1


def _parse_gbxml_space_geometry(path: Path) -> dict[str, dict[str, float | None]]:
    """Stream the gbXML and return {space id: {"area_m2", "volume_m3"}} in SI.

    Drives pyexpat directly with the callbacks in _SpaceGeometryReader, so
    nothing is retained beyond the current <Space>'s two numbers. The parser
    is hardened for user-supplied input outside the sandbox: any DOCTYPE/DTD
    or entity declaration aborts the parse at that token, external entity
    references are refused, and parameter entities are never parsed. That
    is a stricter stance than the bundled expat's own amplification cap
    (2.4.1+) and needs no defusedxml dependency. Revit never emits a DTD.

    Raises expat.ExpatError on malformed XML, _RejectedGbxml on a DTD/entity
    declaration, and _UnsupportedGbxmlUnits on units outside the tables above.
    """
    reader = _SpaceGeometryReader()
    parser = expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _reject_dtd
    parser.EntityDeclHandler = _reject_dtd
    parser.ExternalEntityRefHandler = _refuse_external_entity
    parser.StartElementHandler = reader.start
    parser.EndElementHandler = reader.end
    parser.CharacterDataHandler = reader.data
    with path.open("rb") as f:
        parser.ParseFile(f)
    return reader.spaces


def find_gbxml_geometry_deltas(gbxml_path: str, model: openstudio.model.Model) -> dict[str, Any]:
    """Compare each Space's gbXML-declared Area/Volume to the model's current values.

    Args:
        gbxml_path: Path to the gbXML file `model` was translated from — the
            staged copy import_gbxml_op stashed, not the caller's input, which
            may since have been deleted or overwritten.
        model: The exact Model to compare. Passed in rather than re-fetched
            from model_manager: sync tools on one session run concurrently, so
            a load landing between the caller's own get_model() and a second
            fetch here would compare the *new* model against the *old* model's
            source file.
    """
    try:
        path = Path(gbxml_path)
        if not path.is_file():
            return {"ok": False, "error": f"gbXML file not found: {gbxml_path}"}
        if not is_path_allowed(path):
            return {"ok": False, "error": f"gbXML path not allowed: {gbxml_path}"}
        try:
            gbxml_by_id = _parse_gbxml_space_geometry(path)
        except expat.ExpatError as e:
            return {"ok": False, "error": f"Could not parse gbXML: {e}"}
        except (_RejectedGbxml, _UnsupportedGbxmlUnits) as e:
            return {"ok": False, "error": str(e)}

        area_deltas: list[dict[str, Any]] = []
        volume_deltas: list[dict[str, Any]] = []
        checked = 0
        skipped_no_id = 0
        skipped_no_source = 0

        for space in model.getSpaces():
            opt_gid = space.gbXMLId()
            if not opt_gid.is_initialized():
                skipped_no_id += 1
                continue
            src = gbxml_by_id.get(opt_gid.get())
            if src is None:
                skipped_no_source += 1
                continue

            name = space.nameString()
            gbxml_area = src["area_m2"]
            if gbxml_area is not None and gbxml_area > 0:
                osm_area = float(space.floorArea())
                delta = abs(gbxml_area - osm_area) / gbxml_area
                if delta > AREA_VOLUME_DELTA_THRESHOLD:
                    area_deltas.append({
                        "space": name,
                        "gbxml_area_m2": round(gbxml_area, 4),
                        "osm_area_m2": round(osm_area, 4),
                        "delta_pct": round(delta * 100, 2),
                    })

            gbxml_volume = src["volume_m3"]
            if gbxml_volume is not None and gbxml_volume > 0:
                osm_volume = float(space.volume())
                delta = abs(gbxml_volume - osm_volume) / gbxml_volume
                if delta > AREA_VOLUME_DELTA_THRESHOLD:
                    volume_deltas.append({
                        "space": name,
                        "gbxml_volume_m3": round(gbxml_volume, 4),
                        "osm_volume_m3": round(osm_volume, 4),
                        "delta_pct": round(delta * 100, 2),
                    })

            checked += 1

        area_deltas.sort(key=lambda d: d["delta_pct"], reverse=True)
        volume_deltas.sort(key=lambda d: d["delta_pct"], reverse=True)

        result: dict[str, Any] = {
            "ok": True,
            "gbxml_deltas_checked": True,
            "gbxml_spaces_checked_count": checked,
            "gbxml_spaces_skipped_no_gbxml_id_count": skipped_no_id,
            "gbxml_spaces_skipped_no_source_data_count": skipped_no_source,
            "gbxml_area_delta_count": len(area_deltas),
            "gbxml_area_deltas": area_deltas[:MAX_REPORTED_DELTAS],
            "gbxml_volume_delta_count": len(volume_deltas),
            "gbxml_volume_deltas": volume_deltas[:MAX_REPORTED_DELTAS],
        }
        if len(area_deltas) > MAX_REPORTED_DELTAS:
            result["gbxml_area_deltas_truncated"] = True
        if len(volume_deltas) > MAX_REPORTED_DELTAS:
            result["gbxml_volume_deltas_truncated"] = True
        return result
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"gbXML delta check failed: {e}"}
