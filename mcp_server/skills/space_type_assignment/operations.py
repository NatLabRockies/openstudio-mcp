"""Attribute OpenStudio standards space types to conditioned spaces.

Two paths:
- assign_space_type_simple: one (template, building_type, space_type) triple
  applied to every space in a conditioned zone.
- The wizard (start/choose/status/assign/finish/cancel): a multi-turn flow for
  mixed-use buildings, narrowing to chosen templates/building types, then
  matching space indices to valid combos in batches.

Standards data (templates/building types/space types) is read directly from
the OpenStudio SDK's own SpaceType.suggestedStandards*() methods via a
throwaway SpaceType (created, queried, removed) — no external file needed.
"""
from __future__ import annotations

import difflib
from typing import Any

import openstudio

from mcp_server.model_manager import get_model, model_generation
from mcp_server.osm_helpers import fetch_object, is_conditioned_zone, parse_str_list
from mcp_server.skills.model_management.operations import save_osm_model
from mcp_server.skills.space_type_assignment import wizard_state
from mcp_server.skills.space_type_assignment.wizard_state import PendingRow, WizardState

_TABLE_HEADER = "idx|floor_area_m2|peak_people|lpd_w_m2|epd_w_m2|floor_elev_m|ext_wall_area_m2"


# ---------------------------------------------------------------------------
# Model introspection helpers
# ---------------------------------------------------------------------------

def _list_conditioned_spaces(model) -> list:
    """Every Space whose ThermalZone is conditioned (dual-setpoint thermostat)."""
    spaces = []
    for zone in model.getThermalZones():
        if not is_conditioned_zone(zone):
            continue
        spaces.extend(zone.spaces())
    return spaces


def _extract_conditioned_space_row(space) -> dict[str, Any]:
    """7-column row for one conditioned space, from native Space aggregation methods."""
    story = space.buildingStory()
    if story.is_initialized() and story.get().nominalZCoordinate().is_initialized():
        elevation = float(story.get().nominalZCoordinate().get())
    else:
        elevation = float(space.zOrigin())
    return {
        "handle": str(space.handle()),
        "name": space.nameString(),
        "floor_area_m2": float(space.floorArea()),
        "peak_people": float(space.numberOfPeople()),
        "lpd_w_per_m2": float(space.lightingPowerPerFloorArea()),
        "epd_w_per_m2": float(space.electricEquipmentPowerPerFloorArea()),
        "floor_elevation_m": elevation,
        "exterior_wall_area_m2": float(space.exteriorWallArea()),
    }


def _all_templates(model) -> list[str]:
    scratch = openstudio.model.SpaceType(model)
    try:
        return sorted(scratch.suggestedStandardsTemplates())
    finally:
        scratch.remove()


def _building_types_for_template(model, template: str) -> list[str]:
    scratch = openstudio.model.SpaceType(model)
    try:
        scratch.setStandardsTemplate(template)
        return sorted(scratch.suggestedStandardsBuildingTypes())
    finally:
        scratch.remove()


def _space_types_for(model, template: str, building_type: str) -> list[str]:
    scratch = openstudio.model.SpaceType(model)
    try:
        scratch.setStandardsTemplate(template)
        scratch.setStandardsBuildingType(building_type)
        return sorted(scratch.suggestedStandardsSpaceTypes())
    finally:
        scratch.remove()


def _get_or_create_space_type(model, template: str, building_type: str, space_type: str):
    """Find an existing SpaceType with matching standards fields, else create one.

    A newly created SpaceType has no loads attached — setting the standards
    fields alone does not create People/Lights/ElectricEquipment.

    Returns (SpaceType, reused_existing: bool).
    """
    for st in model.getSpaceTypes():
        t, b, s = st.standardsTemplate(), st.standardsBuildingType(), st.standardsSpaceType()
        if (t.is_initialized() and t.get() == template
                and b.is_initialized() and b.get() == building_type
                and s.is_initialized() and s.get() == space_type):
            return st, True
    st = openstudio.model.SpaceType(model)
    st.setName(f"{template} - {building_type} - {space_type}")
    st.setStandardsTemplate(template)
    st.setStandardsBuildingType(building_type)
    st.setStandardsSpaceType(space_type)
    return st, False


def _validate_combo(model, template: str, building_type: str, space_type: str) -> dict[str, Any] | None:
    """Validate a standards triple against the SDK's suggested lists.

    Returns an ok=False error dict with did_you_mean suggestions, or None if valid.
    """
    templates = _all_templates(model)
    if template not in templates:
        return {
            "ok": False,
            "error": f"'{template}' is not a known standards_template",
            "did_you_mean": difflib.get_close_matches(template, templates, n=5),
        }
    building_types = _building_types_for_template(model, template)
    if building_type not in building_types:
        return {
            "ok": False,
            "error": f"'{building_type}' is not a valid standards_building_type for {template}",
            "did_you_mean": difflib.get_close_matches(building_type, building_types, n=5),
        }
    space_types = _space_types_for(model, template, building_type)
    if space_type not in space_types:
        return {
            "ok": False,
            "error": f"'{space_type}' is not a valid standards_space_type for ({template}, {building_type})",
            "did_you_mean": difflib.get_close_matches(space_type, space_types, n=5),
        }
    return None


# ---------------------------------------------------------------------------
# Path A — simple, one shot
# ---------------------------------------------------------------------------

def assign_space_type_simple(
    standards_template: str,
    standards_building_type: str,
    standards_space_type: str,
) -> dict[str, Any]:
    """Create one standards space type and assign it to every conditioned space."""
    try:
        model = get_model()
        spaces = _list_conditioned_spaces(model)
        if not spaces:
            return {"ok": False, "error": "No conditioned (heated and cooled) zones found in the model."}

        invalid = _validate_combo(model, standards_template, standards_building_type, standards_space_type)
        if invalid:
            return invalid

        space_type, reused = _get_or_create_space_type(
            model, standards_template, standards_building_type, standards_space_type,
        )
        for space in spaces:
            space.setSpaceType(space_type)

        return {
            "ok": True,
            "space_type": space_type.nameString(),
            "reused_existing": reused,
            "spaces_assigned": len(spaces),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to assign space type: {e}"}


# ---------------------------------------------------------------------------
# Path B — wizard
# ---------------------------------------------------------------------------

def _require_wizard() -> tuple[WizardState | None, dict[str, Any] | None]:
    state = wizard_state.get()
    if state is None:
        return None, {"ok": False, "error": "No space type wizard active. Call start_space_type_wizard first."}
    if state.model_generation != model_generation():
        return None, {
            "ok": False,
            "error": "Model changed since the wizard started (reloaded/replaced). Call start_space_type_wizard again.",
        }
    return state, None


def _render_table_page(state: WizardState, page: int, page_size: int) -> dict[str, Any]:
    page = max(1, page)
    page_size = max(1, page_size)
    items = sorted(state.pending.items())
    total = len(items)
    start = (page - 1) * page_size
    chunk = items[start:start + page_size]
    rows = "\n".join(
        f"{idx}|{row.floor_area_m2:.2f}|{row.peak_people:.2f}|{row.lpd_w_per_m2:.2f}|"
        f"{row.epd_w_per_m2:.2f}|{row.floor_elevation_m:.2f}|{row.exterior_wall_area_m2:.2f}"
        for idx, row in chunk
    )
    return {
        "assigned_count": len(state.assigned),
        "remaining_count": total,
        "page": page,
        "page_size": page_size,
        "has_more": start + page_size < total,
        "table_header": _TABLE_HEADER,
        "table_rows": rows,
    }


def start_space_type_wizard() -> dict[str, Any]:
    """Scan the model and start a fresh space-type assignment wizard."""
    try:
        model = get_model()
        spaces = _list_conditioned_spaces(model)
        pending = {
            idx: PendingRow(**_extract_conditioned_space_row(space))
            for idx, space in enumerate(sorted(spaces, key=lambda s: s.nameString()))
        }
        wizard_state.set_state(WizardState(model_generation=model_generation(), pending=pending))
        return {
            "ok": True,
            "conditioned_space_count": len(pending),
            "available_templates": _all_templates(model),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to start space type wizard: {e}"}


def choose_space_type_templates(templates: list[str] | str) -> dict[str, Any]:
    """Narrow the wizard to one or more standards templates."""
    try:
        model = get_model()
        state, err = _require_wizard()
        if err:
            return err

        names = parse_str_list(templates) or []
        if not names:
            return {"ok": False, "error": "Provide at least one standards_template."}

        available = _all_templates(model)
        bad = [t for t in names if t not in available]
        if bad:
            return {
                "ok": False,
                "error": f"Unknown standards_template(s): {', '.join(bad)}",
                "available_templates": available,
            }

        # Changing templates invalidates the narrower choices made under the
        # old ones — force choose_space_type_building_types to be re-run.
        if set(names) != set(state.templates):
            state.building_types = []
            state.valid_combos = set()
        state.templates = names
        building_types: set[str] = set()
        for template in names:
            building_types.update(_building_types_for_template(model, template))

        return {
            "ok": True,
            "templates": names,
            "available_building_types": sorted(building_types),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to choose templates: {e}"}


def choose_space_type_building_types(
    building_types: list[str] | str,
    page: int = 1,
    page_size: int = 40,
) -> dict[str, Any]:
    """Narrow the wizard to one or more building types, then show the space table."""
    try:
        model = get_model()
        state, err = _require_wizard()
        if err:
            return err
        if not state.templates:
            return {"ok": False, "error": "Call choose_space_type_templates first."}

        names = parse_str_list(building_types) or []
        if not names:
            return {"ok": False, "error": "Provide at least one standards_building_type."}

        available: set[str] = set()
        for template in state.templates:
            available.update(_building_types_for_template(model, template))
        bad = [b for b in names if b not in available]
        if bad:
            return {
                "ok": False,
                "error": f"Unknown standards_building_type(s) for chosen templates: {', '.join(bad)}",
                "available_building_types": sorted(available),
            }

        state.building_types = names
        combos: set[tuple[str, str, str]] = set()
        for template in state.templates:
            for building_type in names:
                for space_type in _space_types_for(model, template, building_type):
                    combos.add((template, building_type, space_type))
        state.valid_combos = combos

        return {
            "ok": True,
            "building_types": names,
            "valid_combo_count": len(combos),
            **_render_table_page(state, page, page_size),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to choose building types: {e}"}


def get_space_type_wizard_status(page: int = 1, page_size: int = 40) -> dict[str, Any]:
    """Status + a paginated page of the remaining (unassigned) space table."""
    try:
        get_model()  # raise if no model loaded; keeps the session touched
        state, err = _require_wizard()
        if err:
            return err
        return {
            "ok": True,
            "templates": state.templates,
            "building_types": state.building_types,
            "valid_combo_count": len(state.valid_combos),
            **_render_table_page(state, page, page_size),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get wizard status: {e}"}


def assign_space_type_batch(
    standards_template: str,
    standards_building_type: str,
    standards_space_type: str,
    space_indices: list[int] | str,
) -> dict[str, Any]:
    """Assign one (template, building_type, space_type) combo to a batch of space indices."""
    try:
        model = get_model()
        state, err = _require_wizard()
        if err:
            return err
        if not state.valid_combos:
            return {
                "ok": False,
                "error": "Call choose_space_type_templates and choose_space_type_building_types first.",
            }

        combo = (standards_template, standards_building_type, standards_space_type)
        if combo not in state.valid_combos:
            same_scope = [
                c[2] for c in state.valid_combos
                if c[0] == standards_template and c[1] == standards_building_type
            ]
            candidates = same_scope or [c[2] for c in state.valid_combos]
            return {
                "ok": False,
                "error": f"'{standards_space_type}' is not a valid standards_space_type for "
                         f"({standards_template}, {standards_building_type})",
                "did_you_mean": difflib.get_close_matches(standards_space_type, candidates, n=5),
            }

        raw_indices = parse_str_list(space_indices) if isinstance(space_indices, str) else list(space_indices)
        try:
            indices = list(dict.fromkeys(int(i) for i in raw_indices))  # dedupe, keep order
        except (TypeError, ValueError):
            return {"ok": False, "error": "space_indices must be a list of integers."}
        if not indices:
            return {"ok": False, "error": "Provide at least one space index."}

        for idx in indices:
            if idx in state.assigned:
                return {"ok": False, "error": f"Space index {idx} was already assigned to '{state.assigned[idx]}'."}
            if idx not in state.pending:
                return {"ok": False, "error": f"Space index {idx} is not a pending space index."}

        # Resolve every space before mutating anything, so a stale handle
        # fails the whole batch instead of leaving it half-applied.
        resolved = []
        for idx in indices:
            row = state.pending[idx]
            space = fetch_object(model, "Space", handle=row.handle)
            if space is None:
                return {
                    "ok": False,
                    "error": f"Space '{row.name}' (index {idx}) no longer exists in the model; "
                             "no assignments were made.",
                }
            resolved.append((idx, space))

        space_type, reused = _get_or_create_space_type(
            model, standards_template, standards_building_type, standards_space_type,
        )
        for idx, space in resolved:
            space.setSpaceType(space_type)
            del state.pending[idx]
            state.assigned[idx] = space_type.nameString()

        return {
            "ok": True,
            "space_type": space_type.nameString(),
            "reused_existing": reused,
            "assigned_this_batch": len(indices),
            "remaining_count": len(state.pending),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to assign space type batch: {e}"}


def finish_space_type_wizard(force: bool = False) -> dict[str, Any]:
    """Save the model and end the wizard, once every conditioned space is assigned."""
    try:
        get_model()  # raise if no model loaded; save_osm_model re-fetches it
        state, err = _require_wizard()
        if err:
            return err
        if state.pending and not force:
            return {
                "ok": False,
                "error": f"{len(state.pending)} conditioned spaces still unassigned.",
                "remaining_count": len(state.pending),
            }

        save_result = save_osm_model()
        if not save_result.get("ok"):
            return save_result

        summary = {
            "ok": True,
            "osm_path": save_result["osm_path"],
            "spaces_assigned": len(state.assigned),
            "spaces_left_unassigned": len(state.pending),
            "space_types_created": sorted(set(state.assigned.values())),
        }
        wizard_state.clear()
        return summary
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to finish space type wizard: {e}"}


def cancel_space_type_wizard() -> dict[str, Any]:
    """Clear wizard bookkeeping. Does not undo any assignments already made."""
    state = wizard_state.get()
    if state is None:
        return {"ok": False, "error": "No space type wizard active."}
    wizard_state.clear()
    return {"ok": True, "cleared": True}
