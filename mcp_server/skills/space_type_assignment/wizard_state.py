"""Session-scoped state for the multi-turn space-type assignment wizard.

Stored in model_manager's generic per-session `extra` dict (see
mcp_server.model_manager.get_session_extra) so the wizard's lifetime is tied
to its model's TTL/LRU eviction — if the model session is dropped, this state
is dropped with it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from mcp_server import model_manager

_KEY = "space_type_assignment"


@dataclass
class PendingRow:
    handle: str
    name: str
    floor_area_m2: float
    peak_people: float
    lpd_w_per_m2: float
    epd_w_per_m2: float
    floor_elevation_m: float
    exterior_wall_area_m2: float


@dataclass
class WizardState:
    # model_manager.model_generation() at wizard start — any reload bumps the
    # session's counter, invalidating this wizard (its handles/indices are
    # snapshots of the old model).
    model_generation: int
    pending: dict[int, PendingRow] = field(default_factory=dict)
    assigned: dict[int, str] = field(default_factory=dict)
    templates: list[str] = field(default_factory=list)
    building_types: list[str] = field(default_factory=list)
    valid_combos: set[tuple[str, str, str]] = field(default_factory=set)


def get() -> WizardState | None:
    """Return the current session's wizard state, or None if no wizard is active."""
    return model_manager.get_session_extra().get(_KEY)


def set_state(state: WizardState) -> None:
    """Store wizard state for the current session, replacing any prior wizard."""
    model_manager.get_session_extra()[_KEY] = state


def clear() -> None:
    """Drop the current session's wizard state, if any."""
    model_manager.get_session_extra().pop(_KEY, None)
