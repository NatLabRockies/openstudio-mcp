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

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.config import is_path_allowed

# gbXML files declare this namespace on the root <gbXML> element; every
# element lookup below needs it (bare "Space" would never match).
_GBXML_NS = "{http://www.gbxml.org/schema}"
_SPACE_TAG = f"{_GBXML_NS}Space"
_AREA_TAG = f"{_GBXML_NS}Area"
_VOLUME_TAG = f"{_GBXML_NS}Volume"

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


def _parse_gbxml_space_geometry(path: Path) -> dict[str, dict[str, float | None]]:
    """Stream the gbXML and return {space id: {"area_m2", "volume_m3"}} in SI.

    Streams with iterparse() rather than materializing the whole tree: this
    runs inside the long-lived MCP server process, a Revit export can run to
    hundreds of MB, and a full ElementTree costs several times the file size
    — almost all of it <Surface> polyloops this check never reads. Only the
    <Space> currently open is held to completion (it is tiny: Area/Volume/
    Name plus one polyloop); everything else is freed the moment it closes,
    and detached from its parent — elem.clear() alone leaves an empty shell
    attached to <Campus> for every <Surface>, ~80 bytes each, so peak memory
    would still grow with the surface count. Measured flat at ~0.15 MB from
    1k to 50k surfaces with the detach; ~4 MB at 50k without it.

    gbXML Area/Volume are both optional per the schema even though every
    fixture in this repo happens to populate them — a Space with either one
    absent is recorded as None, never treated as a false 0%/100% delta.
    <Building> also carries an <Area> child, so only elements inside an open
    <Space> are ever read.

    Raises ET.ParseError on malformed XML and _UnsupportedGbxmlUnits on units
    outside the two tables above.
    """
    spaces: dict[str, dict[str, float | None]] = {}
    root = None
    open_space = None
    area_factor = volume_factor = 1.0
    # Open ancestors of the element being parsed, so a finished element can be
    # removed from its parent (iterparse gives no parent pointer).
    ancestors: list[ET.Element] = []
    # is_path_allowed() in the caller puts this on the same trust boundary as the rest of
    # this server's file access, and the file was already parsed once by the real gbXML
    # translator during import_gbxml_op; defusedxml isn't a dependency this project
    # otherwise carries.
    for event, elem in ET.iterparse(str(path), events=("start", "end")):  # noqa: S314
        if event == "start":
            if root is None:
                # Root attributes are complete at its start event; fail on bad units
                # before streaming a possibly huge file for nothing.
                root = elem
                area_unit = root.get("areaUnit", "SquareMeters")
                volume_unit = root.get("volumeUnit", "CubicMeters")
                area_factor = _AREA_UNIT_TO_M2.get(area_unit)
                volume_factor = _VOLUME_UNIT_TO_M3.get(volume_unit)
                if area_factor is None or volume_factor is None:
                    raise _UnsupportedGbxmlUnits(
                        f"Unsupported gbXML units (areaUnit={area_unit!r}, volumeUnit={volume_unit!r})",
                    )
            elif open_space is None and elem.tag == _SPACE_TAG:
                open_space = elem
            ancestors.append(elem)
            continue

        ancestors.pop()
        if elem is open_space:
            # End of the open <Space>: its children are complete and untouched.
            space_id = elem.get("id")
            if space_id:
                area_el = elem.find(_AREA_TAG)
                volume_el = elem.find(_VOLUME_TAG)
                spaces[space_id] = {
                    "area_m2": float(area_el.text) * area_factor
                    if area_el is not None and area_el.text else None,
                    "volume_m3": float(volume_el.text) * volume_factor
                    if volume_el is not None and volume_el.text else None,
                }
            open_space = None
        elif open_space is not None:
            # Inside an open <Space>: keep its subtree intact until it closes.
            continue
        if ancestors:
            # Finished with this subtree (a <Surface>, a <Building>'s own <Area>, a closed
            # <Space>, ...): drop its contents AND unlink it from its parent, so the parent's
            # child list stays at one entry instead of one shell per surface. The root has no
            # parent and is left alone.
            elem.clear()
            ancestors[-1].remove(elem)
    return spaces


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
        except ET.ParseError as e:
            return {"ok": False, "error": f"Could not parse gbXML: {e}"}
        except _UnsupportedGbxmlUnits as e:
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
