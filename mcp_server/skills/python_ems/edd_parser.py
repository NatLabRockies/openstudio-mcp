"""Parse eplusout.edd — the EMS actuator/internal-variable availability dictionary.

Produced by an EnergyPlus run when the model contains Output:EnergyManagementSystem
with Verbose reporting. Pure string parsing; no openstudio import.
"""
from __future__ import annotations

_ACTUATOR_PREFIX = "EnergyManagementSystem:Actuator Available"
_INTERNAL_PREFIX = "EnergyManagementSystem:InternalVariable Available"


def parse_edd(text: str) -> dict[str, list[dict[str, str]]]:
    """Parse .edd content into actuator triples and internal variables.

    Actuator lines: `EnergyManagementSystem:Actuator Available,<unique key>,
    <component type>,<control type>,[units]`. EnergyPlus reports names uppercase.
    """
    actuators: list[dict[str, str]] = []
    internal: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if parts[0] == _ACTUATOR_PREFIX and len(parts) >= 5:
            actuators.append({
                "actuator_key": parts[1],
                "component_type": parts[2],
                "control_type": parts[3],
                "units": parts[4].strip("[] "),
            })
        elif parts[0] == _INTERNAL_PREFIX and len(parts) >= 4:
            internal.append({
                "key": parts[1],
                "type": parts[2],
                "units": parts[3].strip("[] "),
            })
    return {"actuators": actuators, "internal_variables": internal}
