"""MCP tools for attributing standards space types to conditioned spaces.

Run after gbXML import + repair_and_validate_gbxml_geometry, when spaces have
real geometry (and often real space-level loads) but no SpaceType. Two paths:
assign_space_type_simple for a single uniform combo, or the wizard tools
(start/choose/status/assign/finish/cancel) for mixed-use buildings.
"""
from __future__ import annotations

from mcp_server.skills.space_type_assignment.operations import (
    assign_space_type_batch,
    assign_space_type_simple,
    cancel_space_type_wizard,
    choose_space_type_building_types,
    choose_space_type_templates,
    finish_space_type_wizard,
    get_space_type_wizard_status,
    start_space_type_wizard,
)


def register(mcp):
    @mcp.tool(tags={"space_types", "core"}, name="assign_space_type_simple")
    def assign_space_type_simple_tool(
        standards_template: str,
        standards_building_type: str,
        standards_space_type: str,
    ):
        """Attribute ONE standards space type to every conditioned space in one shot.

        Use for single-use buildings (e.g. after gbXML import): creates one
        new SpaceType tagged with the given (template, building_type,
        space_type) — with no loads attached — and assigns it to every Space
        whose ThermalZone is conditioned (has a heating+cooling thermostat).
        Reuses an existing SpaceType if one with the same three fields
        already exists. For mixed-use buildings needing different space
        types per space, use start_space_type_wizard instead.

        Args:
            standards_template: e.g. "90.1-2019". See start_space_type_wizard's
                available_templates for the full list.
            standards_building_type: e.g. "Office", "Hospital".
            standards_space_type: e.g. "WholeBuilding - Sm Office", "OpenOffice".
        """
        return assign_space_type_simple(
            standards_template=standards_template,
            standards_building_type=standards_building_type,
            standards_space_type=standards_space_type,
        )

    @mcp.tool(tags={"space_types", "core"}, name="start_space_type_wizard")
    def start_space_type_wizard_tool():
        """Start the multi-turn space-type assignment wizard for mixed-use buildings.

        Scans every Space in a conditioned ThermalZone and stores them
        server-side as the wizard's pending table (never sent to the caller
        in full). Returns just the conditioned space count and the list of
        available standards templates. Next call choose_space_type_templates.
        Starting again replaces any wizard already in progress for this
        session (already-assigned spaces are not undone).
        """
        return start_space_type_wizard()

    @mcp.tool(tags={"space_types"}, name="choose_space_type_templates")
    def choose_space_type_templates_tool(templates: list[str] | str):
        """Narrow the active wizard to one or more standards templates.

        Returns the union of standards building types available across the
        chosen templates. Next call choose_space_type_building_types.

        Args:
            templates: One or more standards templates, e.g. ["90.1-2016", "90.1-2019"].
        """
        return choose_space_type_templates(templates=templates)

    @mcp.tool(tags={"space_types"}, name="choose_space_type_building_types")
    def choose_space_type_building_types_tool(
        building_types: list[str] | str,
        page: int = 1,
        page_size: int = 40,
    ):
        """Narrow the active wizard to building types, then show the space table.

        Computes every valid (template, building_type, space_type) combo for
        the chosen templates x building types (validated server-side by
        assign_space_type_batch — never dumped here). Returns a compact
        page of the remaining space table: one pipe-delimited row per
        space, keyed by a small stable index (see table_header).

        Args:
            building_types: One or more standards building types, e.g. ["Office"].
            page: 1-indexed page of the remaining space table.
            page_size: Rows per page.
        """
        return choose_space_type_building_types(
            building_types=building_types, page=page, page_size=page_size,
        )

    @mcp.tool(tags={"space_types"}, name="get_space_type_wizard_status")
    def get_space_type_wizard_status_tool(page: int = 1, page_size: int = 40):
        """Get wizard progress and a page of the remaining (unassigned) space table.

        Args:
            page: 1-indexed page of the remaining space table.
            page_size: Rows per page.
        """
        return get_space_type_wizard_status(page=page, page_size=page_size)

    @mcp.tool(tags={"space_types"}, name="assign_space_type_batch")
    def assign_space_type_batch_tool(
        standards_template: str,
        standards_building_type: str,
        standards_space_type: str,
        space_indices: list[int] | str,
    ):
        """Assign one standards space type to a batch of space indices in the active wizard.

        Creates (or reuses) a SpaceType for the combo and assigns it to each
        space, removing those indices from the remaining table. The combo
        must be one of the valid combos computed by
        choose_space_type_building_types — an invalid combo returns
        did_you_mean suggestions instead of failing silently.

        Args:
            standards_template: e.g. "90.1-2019".
            standards_building_type: e.g. "Office".
            standards_space_type: e.g. "OpenOffice".
            space_indices: Space indices from the wizard table, e.g. [0, 3, 7].
        """
        return assign_space_type_batch(
            standards_template=standards_template,
            standards_building_type=standards_building_type,
            standards_space_type=standards_space_type,
            space_indices=space_indices,
        )

    @mcp.tool(tags={"space_types"}, name="finish_space_type_wizard")
    def finish_space_type_wizard_tool(force: bool = False):
        """Save the model and end the active wizard, once every space is assigned.

        Fails with remaining_count if conditioned spaces are still
        unassigned, unless force=True.

        Args:
            force: Save and end the wizard even if some conditioned spaces
                are still unassigned.
        """
        return finish_space_type_wizard(force=force)

    @mcp.tool(tags={"space_types"}, name="cancel_space_type_wizard")
    def cancel_space_type_wizard_tool():
        """Cancel the active wizard, clearing its tracking state.

        Does NOT undo any assign_space_type_batch calls already made — those
        are live model mutations. Use to abandon wizard bookkeeping and
        start over with start_space_type_wizard.
        """
        return cancel_space_type_wizard()
