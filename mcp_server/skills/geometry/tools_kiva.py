"""MCP tools for EnergyPlus Kiva foundation modelling.

Split out of geometry/tools.py, which was already at ~389 lines against the ~400 budget
(CLAUDE.md rule 1) — the same sub-registrar pattern loop_operations/tools_air_loop.py uses.
"""
from __future__ import annotations

from mcp_server.skills.geometry.kiva_apply import set_kiva_foundation
from mcp_server.skills.geometry.kiva_foundation import get_foundation_options


def register_kiva_tools(mcp) -> None:
    @mcp.tool(tags={"geometry"}, name="get_foundation_options")
    def get_foundation_options_tool(include_adiabatic: bool = False):
        """List the foundation modelling choices for this model before applying Kiva to it.

        Call this before set_kiva_foundation. It reports which floors and below-grade walls
        EnergyPlus would accept as Kiva surfaces, why each rejected surface was rejected, the
        exposed perimeter computed from the building footprint, and the five foundation archetypes
        with their full parameter sets — so the user can be shown the actual numbers rather than an
        opaque name.

        The archetype insulation R-values are conventional starting points, not derived from a code
        table or a vendored dataset, and each archetype says so in its `basis`. The ASHRAE 90.1
        F-factor / C-factor targets for the model's climate zone are reported alongside as a
        cross-check, not as their source.

        Also reports how many separate Kiva 2D domains would be created: EnergyPlus allows only one
        floor per Foundation object, so a forty-slab model means forty domains and a much slower
        simulation.

        Read-only — creates no objects, including no FoundationKivaSettings.

        Args:
            include_adiabatic: Also consider Adiabatic surfaces. Off by default because
                patch_missing_surfaces sets that condition deliberately on facets it could not
                identify, and burying them would undo that decision.

        Returns:
            eligible_floors, eligible_walls, blocked, eligible_floor_count,
            kiva_domains_if_applied, existing_kiva, archetypes, climate_zone, code_targets,
            ground_temperatures, warnings, next_step
        """
        return get_foundation_options(include_adiabatic=include_adiabatic)

    @mcp.tool(tags={"geometry"}, name="set_kiva_foundation")
    def set_kiva_foundation_tool(
        archetype: str,
        floor_surface_names: list[str] | str | None = None,
        include_below_grade_walls: bool = True,
        include_adiabatic: bool = False,
        exposed_perimeter_method: str = "auto",
        exposed_perimeter_m: float | None = None,
        exposed_perimeter_fraction: float | None = None,
        wall_height_above_grade_m: float | None = None,
        wall_depth_below_slab_m: float | None = None,
        footing_depth_m: float | None = None,
        interior_horizontal_insulation_r_si: float | None = None,
        interior_horizontal_insulation_width_m: float | None = None,
        exterior_vertical_insulation_r_si: float | None = None,
        exterior_vertical_insulation_depth_m: float | None = None,
        soil_conductivity_w_mk: float | None = None,
        soil_density_kg_m3: float | None = None,
        soil_specific_heat_j_kgk: float | None = None,
        epw_path: str | None = None,
        confirm_many_domains: bool = False,
        overwrite: bool = False,
        dry_run: bool = False,
    ):
        """Model foundation heat transfer with EnergyPlus Kiva, a 2D finite-difference soil solver.

        The detailed alternative to set_ground_temperatures. A surface converted here gets the
        Foundation boundary condition and a solved soil domain including slab-edge losses and
        insulation geometry — and it then IGNORES Site:GroundTemperature:BuildingSurface entirely.
        Use this when slab-edge heat transfer matters or the foundation is what is being studied;
        use set_ground_temperatures for screening runs and models with no foundation information.

        Ask the user which archetype describes their foundation before calling this, showing them
        the parameter values from get_foundation_options. The insulation R-values are conventional
        starting points rather than sourced figures; every applied value reports its provenance
        (user / archetype / epw_header / openstudio_default / computed_geometry) so nothing implies
        precision it does not have.

        Costs and constraints worth knowing: EnergyPlus creates one 2D domain per floor and refuses
        to run Kiva without a weather file; a Kiva surface may not carry windows or doors, may not
        use massless construction layers, and a wall may not exceed four vertices. Ineligible
        surfaces are refused with a reason rather than half-applied.

        Changes the in-memory model — call save_osm_model to persist.

        Args:
            archetype: One of slab_on_grade_uninsulated, slab_on_grade_perimeter_insulated,
                heated_basement_insulated, unheated_basement, crawlspace_vented.
            floor_surface_names: Floors to convert. Defaults to every eligible floor.
            include_below_grade_walls: Also attach below-grade walls that share an edge with a
                converted floor. Walls pairing to no floor are reported and skipped.
            include_adiabatic: Consider Adiabatic surfaces as candidates.
            exposed_perimeter_method: "auto" computes it from the building footprint (recommended),
                "total" uses exposed_perimeter_m, "fraction" uses exposed_perimeter_fraction.
            exposed_perimeter_m: Measured exposed perimeter in metres; single floor only.
            exposed_perimeter_fraction: Fraction of the slab edge exposed, 0 to 1.
            wall_height_above_grade_m: Override the archetype's foundation wall height above grade.
            wall_depth_below_slab_m: Override the footing stem depth below the slab. Note this is
                not the basement depth, which comes from the below-grade wall geometry.
            footing_depth_m: Override the footing depth.
            interior_horizontal_insulation_r_si: Under-slab insulation R-value, m2K/W. Adding it
                to an archetype that has no interior-horizontal layer also requires the width.
            interior_horizontal_insulation_width_m: How far it extends inward from the wall.
                EnergyPlus refuses an interior-horizontal material without it.
            exterior_vertical_insulation_r_si: Outside-face wall insulation R-value, m2K/W. Adding
                it to an archetype that has no exterior-vertical layer also requires the depth.
            exterior_vertical_insulation_depth_m: How far down it runs, measured from the WALL TOP
                (the EnergyPlus definition), not from grade. EnergyPlus refuses an
                exterior-vertical material without it.
            soil_conductivity_w_mk: Override the soil conductivity, W/m-K.
            soil_density_kg_m3: Override the soil density.
            soil_specific_heat_j_kgk: Override the soil specific heat.
            epw_path: EPW to read soil properties from. Defaults to the model's own weather file.
            confirm_many_domains: Required to proceed past 20 eligible floors.
            overwrite: Replace foundations on floors that already carry one.
            dry_run: Return the plan without changing anything.

        Returns:
            plan, applied, warnings, code_targets, ground_temperature_interaction
        """
        return set_kiva_foundation(
            archetype=archetype,
            floor_surface_names=floor_surface_names,
            include_below_grade_walls=include_below_grade_walls,
            include_adiabatic=include_adiabatic,
            exposed_perimeter_method=exposed_perimeter_method,
            exposed_perimeter_m=exposed_perimeter_m,
            exposed_perimeter_fraction=exposed_perimeter_fraction,
            wall_height_above_grade_m=wall_height_above_grade_m,
            wall_depth_below_slab_m=wall_depth_below_slab_m,
            footing_depth_m=footing_depth_m,
            interior_horizontal_insulation_r_si=interior_horizontal_insulation_r_si,
            interior_horizontal_insulation_width_m=interior_horizontal_insulation_width_m,
            exterior_vertical_insulation_r_si=exterior_vertical_insulation_r_si,
            exterior_vertical_insulation_depth_m=exterior_vertical_insulation_depth_m,
            soil_conductivity_w_mk=soil_conductivity_w_mk,
            soil_density_kg_m3=soil_density_kg_m3,
            soil_specific_heat_j_kgk=soil_specific_heat_j_kgk,
            epw_path=epw_path,
            confirm_many_domains=confirm_many_domains,
            overwrite=overwrite,
            dry_run=dry_run,
        )
