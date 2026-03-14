"""Parse EnergyPlus .err files into structured categories."""
from __future__ import annotations


def parse_err_file(err_text: str, max_warnings: int = 20) -> dict:
    """Parse EnergyPlus .err text into structured categories.

    Returns:
        {fatal: [str], severe: [str], warning_count: int,
         warnings: [str] (capped at max_warnings), summary: str}
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

        # New message — classify by severity prefix
        if stripped.startswith("** Fatal  **"):
            msg = stripped.replace("** Fatal  **", "").strip()
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
        "summary": summary,
    }
