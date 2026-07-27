"""Parse EnergyPlus .err files into structured categories."""
from __future__ import annotations

# Known failure signatures mapped to actionable guidance. Matched against
# fatal + severe message text (post continuation-merge).
_HINT_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "Missing required property 'control_zone_name'",
        "A SetpointManager:SingleZone:* lost its control zone — usually a "
        "leftover from another tool taking over that zone's air system (#83). "
        "Run validate_model to identify it, then delete the old air loop or "
        "the orphaned setpoint manager.",
    ),
    (
        "is not connected to any zone",
        "An air loop serves no thermal zones — usually a leftover after its "
        "zones were moved to a new system (#83). Run validate_model to "
        "identify it, then delete_object the empty air loop.",
    ),
)


def _collect_hints(messages: list[str]) -> list[str]:
    hints: list[str] = []
    for signature, hint in _HINT_PATTERNS:
        if hint not in hints and any(signature in m for m in messages):
            hints.append(hint)
    return hints


def parse_err_file(err_text: str, max_warnings: int = 20) -> dict:
    """Parse EnergyPlus .err text into structured categories.

    Returns:
        {fatal: [str], severe: [str], warning_count: int,
         warnings: [str] (capped at max_warnings), hints: [str], summary: str}
    """
    fatal: list[str] = []
    severe: list[str] = []
    warnings: list[str] = []
    warning_count = 0

    current_msg: str | None = None
    current_list: list[str] | None = None

    for line in err_text.splitlines():
        stripped = line.strip()

        # Continuation line — append to preceding message
        if stripped.startswith("**   ~~~   **"):
            cont = stripped.replace("**   ~~~   **", "").strip()
            if current_msg is not None and current_list is not None:
                current_msg += " " + cont
                # Update the last entry in current_list
                if current_list:
                    current_list[-1] = current_msg
            continue

        # New message — classify by severity prefix. EnergyPlus pads severity
        # labels to equal width, so real files write "**  Fatal  **" with TWO
        # spaces; accept the single-space form too.
        if stripped.startswith(("**  Fatal  **", "** Fatal  **")):
            msg = stripped.replace("**  Fatal  **", "").replace("** Fatal  **", "").strip()
            fatal.append(msg)
            current_msg = msg
            current_list = fatal

        elif stripped.startswith("** Severe  **"):
            msg = stripped.replace("** Severe  **", "").strip()
            severe.append(msg)
            current_msg = msg
            current_list = severe

        elif stripped.startswith("** Warning **"):
            msg = stripped.replace("** Warning **", "").strip()
            warning_count += 1
            if len(warnings) < max_warnings:
                warnings.append(msg)
                current_msg = msg
                current_list = warnings
            else:
                # Still track continuations for the last capped warning
                current_msg = None
                current_list = None

        else:
            # Not a severity line — reset continuation tracking
            current_msg = None
            current_list = None

    # Build summary
    parts = []
    if fatal:
        parts.append(f"{len(fatal)} Fatal")
    if severe:
        parts.append(f"{len(severe)} Severe")
    if warning_count:
        parts.append(f"{warning_count} Warning{'s' if warning_count != 1 else ''}")
    summary = ", ".join(parts) if parts else "No errors"

    return {
        "fatal": fatal,
        "severe": severe,
        "warnings": warnings,
        "warning_count": warning_count,
        "hints": _collect_hints(fatal + severe),
        "summary": summary,
    }
