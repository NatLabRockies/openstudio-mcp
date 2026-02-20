"""Air terminal replacement logic for HVAC systems."""

from __future__ import annotations

from typing import Any

import openstudio


def replace_terminals(
    model,
    air_loop,
    terminal_type: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Replace all terminals on an air loop with new type.

    This function operates on ALL zones served by the specified air loop.
    It removes existing terminals and creates new ones of the requested type.
    This is useful for converting an entire VAV system from reheat to PFP boxes,
    or changing terminal configurations across a whole air loop.

    Args:
        model: OpenStudio model
        air_loop: AirLoopHVAC object to modify
        terminal_type: Type of terminals to create (VAV_Reheat, PFP_Electric, etc.)
        options: Terminal-specific configuration options (e.g., min_airflow_fraction)

    Returns:
        dict with replacement results including:
        - ok: True/False
        - air_loop: dict with name, terminals_replaced count, old/new types, zones list
        - error: error message if ok=False
    """
    try:
        air_loop_name = air_loop.nameString()

        # Step 1: Collect zones and existing terminals BEFORE removing
        # This preserves zone connections so we can reconnect them with new terminals
        zones_and_terminals = _get_zones_and_terminals(air_loop)

        if len(zones_and_terminals) == 0:
            return {
                "ok": False,
                "error": f"No thermal zones connected to air loop '{air_loop_name}'",
            }

        # Record old terminal type for reporting
        old_terminal_type = zones_and_terminals[0]["terminal_type"] if zones_and_terminals else "None"

        # Step 2: Extract just the zones (we'll reuse these after removing branches)
        zones = [item["zone"] for item in zones_and_terminals]

        # Step 3: Remove zone branches from air loop
        # This cleanly disconnects zones and removes existing terminals
        # Must be done before adding new terminals to avoid conflicts
        for zone in zones:
            air_loop.removeBranchForZone(zone)

        # Step 4: Create new terminals based on requested type
        # Each helper function creates the terminal, configures it, and connects it to the air loop
        new_terminals = []
        for zone in zones:
            # Route to appropriate terminal creation function based on type
            if terminal_type == "VAV_Reheat":
                result = _create_vav_reheat_terminal(model, air_loop, zone, options)
            elif terminal_type == "VAV_NoReheat":
                result = _create_vav_no_reheat_terminal(model, air_loop, zone, options)
            elif terminal_type == "PFP_Electric":
                result = _create_pfp_electric_terminal(model, air_loop, zone, options)
            elif terminal_type == "PFP_HotWater":
                result = _create_pfp_hw_terminal(model, air_loop, zone, options)
            elif terminal_type == "CAV":
                result = _create_cav_terminal(model, air_loop, zone, options)
            else:
                return {
                    "ok": False,
                    "error": f"Unknown terminal_type: {terminal_type}",
                }

            # If terminal creation failed (e.g., missing HW loop), propagate error immediately
            if not result.get("ok"):
                return result

            new_terminals.append(result["terminal"])

        return {
            "ok": True,
            "air_loop": {
                "name": air_loop_name,
                "terminals_replaced": len(new_terminals),
                "old_terminal_type": old_terminal_type,
                "new_terminal_type": terminal_type,
                "zones": [zone.nameString() for zone in zones],
            },
        }

    except Exception as e:
        return {"ok": False, "error": f"Failed to replace terminals: {e}"}


def _get_zones_and_terminals(air_loop) -> list[dict[str, Any]]:
    """Extract zones and their terminals from an air loop.

    Walks the demand side of the air loop to find all thermal zones
    and their associated air terminals. This is needed to preserve
    zone connections when replacing terminals.

    Returns:
        List of dicts with keys:
        - zone: ThermalZone object
        - terminal: AirTerminal object
        - terminal_type: String name of terminal class (e.g., "AirTerminalSingleDuctVAVReheat")
    """
    result = []

    # Walk through all components on the demand side of the air loop
    for component in air_loop.demandComponents():
        # Check if it's a thermal zone
        zone = component.to_ThermalZone()
        if zone.is_initialized():
            zone_obj = zone.get()

            # Find terminal serving this zone
            # A zone can have multiple equipment (terminals, baseboard, etc.)
            # We need to find the air terminal connected to our specific air loop
            for equip in zone_obj.equipment():
                # OpenStudio uses dynamic casting - try each terminal type to see what we have
                terminal = None
                terminal_type = "Unknown"

                # Try casting to each known air terminal type
                if equip.to_AirTerminalSingleDuctVAVReheat().is_initialized():
                    terminal = equip.to_AirTerminalSingleDuctVAVReheat().get()
                    terminal_type = "AirTerminalSingleDuctVAVReheat"
                elif equip.to_AirTerminalSingleDuctVAVNoReheat().is_initialized():
                    terminal = equip.to_AirTerminalSingleDuctVAVNoReheat().get()
                    terminal_type = "AirTerminalSingleDuctVAVNoReheat"
                elif equip.to_AirTerminalSingleDuctParallelPIUReheat().is_initialized():
                    terminal = equip.to_AirTerminalSingleDuctParallelPIUReheat().get()
                    terminal_type = "AirTerminalSingleDuctParallelPIUReheat"
                elif equip.to_AirTerminalSingleDuctUncontrolled().is_initialized():
                    terminal = equip.to_AirTerminalSingleDuctUncontrolled().get()
                    terminal_type = "AirTerminalSingleDuctUncontrolled"
                elif equip.to_AirTerminalSingleDuctConstantVolumeNoReheat().is_initialized():
                    terminal = equip.to_AirTerminalSingleDuctConstantVolumeNoReheat().get()
                    terminal_type = "AirTerminalSingleDuctConstantVolumeNoReheat"

                if terminal is not None:
                    # Verify this terminal belongs to the air loop we're modifying
                    # (zones can have multiple terminals from different systems)
                    if terminal.airLoopHVAC().is_initialized():
                        if terminal.airLoopHVAC().get().handle() == air_loop.handle():
                            result.append(
                                {
                                    "zone": zone_obj,
                                    "terminal": terminal,
                                    "terminal_type": terminal_type,
                                },
                            )
                            break  # Found the terminal for this zone on this air loop, move to next zone

    return result


def _create_vav_reheat_terminal(
    model,
    air_loop,
    zone,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Create VAV terminal with hot water reheat coil.

    VAV reheat terminals modulate airflow based on cooling load, then provide
    heating via a hot water coil when needed. Requires a hot water plant loop.

    Args:
        model: OpenStudio model
        air_loop: AirLoopHVAC to connect terminal to
        zone: ThermalZone to serve
        options: Configuration dict (min_airflow_fraction)

    Returns:
        dict with ok=True and terminal object, or ok=False and error message
    """
    try:
        # Find hot water loop - required for reheat coil
        hw_loop = _find_hot_water_loop(model)
        if hw_loop is None:
            return {
                "ok": False,
                "error": "VAV_Reheat requires a hot water plant loop. None found in model.",
            }

        always_on = model.alwaysOnDiscreteSchedule()

        # Create hot water reheat coil and connect to HW plant loop
        reheat_coil = openstudio.model.CoilHeatingWater(model, always_on)
        reheat_coil.setName(f"{zone.nameString()} Reheat Coil")
        hw_loop.addDemandBranchForComponent(reheat_coil)

        # Create VAV terminal with reheat coil
        terminal = openstudio.model.AirTerminalSingleDuctVAVReheat(
            model,
            always_on,
            reheat_coil,
        )
        terminal.setName(f"{zone.nameString()} VAV Reheat Terminal")

        # Set minimum airflow fraction (cooling mode minimum)
        # ASHRAE 90.1 default is 0.3 (30% minimum airflow)
        if "min_airflow_fraction" in options:
            terminal.setZoneMinimumAirFlowFraction(options["min_airflow_fraction"])
        else:
            terminal.setZoneMinimumAirFlowFraction(0.3)

        # Connect terminal to air loop and zone
        air_loop.addBranchForZone(zone, terminal)

        return {"ok": True, "terminal": terminal}

    except Exception as e:
        return {"ok": False, "error": f"Failed to create VAV reheat terminal: {e}"}


def _create_vav_no_reheat_terminal(
    model,
    air_loop,
    zone,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Create VAV terminal without reheat."""
    try:
        always_on = model.alwaysOnDiscreteSchedule()

        # Create terminal
        terminal = openstudio.model.AirTerminalSingleDuctVAVNoReheat(model, always_on)
        terminal.setName(f"{zone.nameString()} VAV NoReheat Terminal")

        # VAVNoReheat doesn't have setZoneMinimumAirFlowFraction - it uses constant min flow
        if "min_airflow_fraction" in options:
            # Set via constant minimum air flow fraction method if available
            if hasattr(terminal, "setConstantMinimumAirFlowFraction"):
                terminal.setConstantMinimumAirFlowFraction(options["min_airflow_fraction"])

        # Connect to air loop
        air_loop.addBranchForZone(zone, terminal)

        return {"ok": True, "terminal": terminal}

    except Exception as e:
        return {"ok": False, "error": f"Failed to create VAV no-reheat terminal: {e}"}


def _create_pfp_electric_terminal(
    model,
    air_loop,
    zone,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Create parallel fan-powered terminal with electric reheat."""
    try:
        always_on = model.alwaysOnDiscreteSchedule()

        # Create fan
        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f"{zone.nameString()} PFP Fan")

        # Create electric reheat coil
        reheat_coil = openstudio.model.CoilHeatingElectric(model, always_on)
        reheat_coil.setName(f"{zone.nameString()} Electric Reheat Coil")

        # Create terminal
        terminal = openstudio.model.AirTerminalSingleDuctParallelPIUReheat(
            model,
            always_on,
            fan,
            reheat_coil,
        )
        terminal.setName(f"{zone.nameString()} PFP Electric Terminal")

        # Set min airflow fraction if specified
        if "min_airflow_fraction" in options:
            terminal.setMinimumPrimaryAirFlowFraction(options["min_airflow_fraction"])
        else:
            terminal.setMinimumPrimaryAirFlowFraction(0.5)  # Higher for PFP

        # Connect to air loop
        air_loop.addBranchForZone(zone, terminal)

        return {"ok": True, "terminal": terminal}

    except Exception as e:
        return {"ok": False, "error": f"Failed to create PFP electric terminal: {e}"}


def _create_pfp_hw_terminal(
    model,
    air_loop,
    zone,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Create parallel fan-powered terminal with hot water reheat."""
    try:
        # Get hot water loop
        hw_loop = _find_hot_water_loop(model)
        if hw_loop is None:
            return {
                "ok": False,
                "error": "PFP_HotWater requires a hot water plant loop. None found in model.",
            }

        always_on = model.alwaysOnDiscreteSchedule()

        # Create fan
        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f"{zone.nameString()} PFP Fan")

        # Create HW reheat coil
        reheat_coil = openstudio.model.CoilHeatingWater(model, always_on)
        reheat_coil.setName(f"{zone.nameString()} HW Reheat Coil")
        hw_loop.addDemandBranchForComponent(reheat_coil)

        # Create terminal
        terminal = openstudio.model.AirTerminalSingleDuctParallelPIUReheat(
            model,
            always_on,
            fan,
            reheat_coil,
        )
        terminal.setName(f"{zone.nameString()} PFP HW Terminal")

        # Set min airflow fraction if specified
        if "min_airflow_fraction" in options:
            terminal.setMinimumPrimaryAirFlowFraction(options["min_airflow_fraction"])
        else:
            terminal.setMinimumPrimaryAirFlowFraction(0.5)

        # Connect to air loop
        air_loop.addBranchForZone(zone, terminal)

        return {"ok": True, "terminal": terminal}

    except Exception as e:
        return {"ok": False, "error": f"Failed to create PFP HW terminal: {e}"}


def _create_cav_terminal(
    model,
    air_loop,
    zone,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Create constant air volume terminal (uncontrolled)."""
    try:
        always_on = model.alwaysOnDiscreteSchedule()

        # Create terminal
        terminal = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
        terminal.setName(f"{zone.nameString()} CAV Terminal")

        # Connect to air loop
        air_loop.addBranchForZone(zone, terminal)

        return {"ok": True, "terminal": terminal}

    except Exception as e:
        return {"ok": False, "error": f"Failed to create CAV terminal: {e}"}


def replace_zone_terminal(
    model,
    zone,
    terminal_type: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Replace the air terminal on a single zone.

    Finds the zone's existing air terminal, removes it via removeBranchForZone,
    then creates a new terminal of the requested type and reconnects the zone.

    Args:
        model: OpenStudio model
        zone: ThermalZone object
        terminal_type: Type of terminal to create
        options: Terminal-specific configuration options

    Returns:
        dict with replacement results or error
    """
    try:
        zone_name = zone.nameString()

        # Find existing air terminal on this zone
        old_terminal_type = "None"
        air_loop = None

        for equip in zone.equipment():
            terminal, ttype = _try_cast_terminal(equip)
            if terminal is not None and terminal.airLoopHVAC().is_initialized():
                old_terminal_type = ttype
                air_loop = terminal.airLoopHVAC().get()
                break

        if air_loop is None:
            return {
                "ok": False,
                "error": f"Zone '{zone_name}' is not connected to any air loop",
            }

        air_loop_name = air_loop.nameString()

        # Remove zone branch (disconnects zone + removes old terminal)
        air_loop.removeBranchForZone(zone)

        # Create new terminal via existing helpers
        creators = {
            "VAV_Reheat": _create_vav_reheat_terminal,
            "VAV_NoReheat": _create_vav_no_reheat_terminal,
            "PFP_Electric": _create_pfp_electric_terminal,
            "PFP_HotWater": _create_pfp_hw_terminal,
            "CAV": _create_cav_terminal,
        }
        creator = creators.get(terminal_type)
        if creator is None:
            return {"ok": False, "error": f"Unknown terminal_type: {terminal_type}"}

        result = creator(model, air_loop, zone, options)
        if not result.get("ok"):
            return result

        new_terminal = result["terminal"]

        return {
            "ok": True,
            "zone": {
                "name": zone_name,
                "air_loop": air_loop_name,
                "old_terminal_type": old_terminal_type,
                "new_terminal_type": terminal_type,
                "new_terminal_name": new_terminal.nameString(),
            },
        }

    except Exception as e:
        return {"ok": False, "error": f"Failed to replace zone terminal: {e}"}


def _try_cast_terminal(equip):
    """Try casting equipment to a known air terminal type.

    Returns (terminal_object, type_string) or (None, None).
    """
    casts = [
        ("to_AirTerminalSingleDuctVAVReheat", "AirTerminalSingleDuctVAVReheat"),
        ("to_AirTerminalSingleDuctVAVNoReheat", "AirTerminalSingleDuctVAVNoReheat"),
        ("to_AirTerminalSingleDuctParallelPIUReheat", "AirTerminalSingleDuctParallelPIUReheat"),
        ("to_AirTerminalSingleDuctUncontrolled", "AirTerminalSingleDuctUncontrolled"),
        ("to_AirTerminalSingleDuctConstantVolumeNoReheat", "AirTerminalSingleDuctConstantVolumeNoReheat"),
    ]
    for method_name, type_name in casts:
        opt = getattr(equip, method_name)()
        if opt.is_initialized():
            return opt.get(), type_name
    return None, None


def _find_hot_water_loop(model) -> openstudio.model.PlantLoop | None:
    """Find first hot water plant loop in model.

    Searches for a heating plant loop to supply hot water reheat coils.
    Returns the first heating loop found (models typically have one HW loop).

    Returns:
        PlantLoop with loopType="Heating", or None if no HW loop exists
    """
    for loop in model.getPlantLoops():
        sizing = loop.sizingPlant()
        if sizing.loopType() == "Heating":
            return loop
    return None
