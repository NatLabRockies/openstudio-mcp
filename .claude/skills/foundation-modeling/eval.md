## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Model the foundation heat transfer properly with Kiva" | get_foundation_options | — |
| "What foundation modelling options does this model have?" | get_foundation_options | — |
| "This is a heated basement — set up Kiva for it" | set_kiva_foundation | archetype |
| "Add R-20 perimeter insulation to the slab and model it with Kiva" | set_kiva_foundation | exterior_vertical_insulation_r_si |
| "Show me what Kiva would change before applying it" | set_kiva_foundation | dry_run |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "Set the ground temperatures from the project weather file" | set_kiva_foundation | set_ground_temperatures |
| "Which surfaces are missing ground contact?" | set_kiva_foundation, get_foundation_options | repair_and_validate_gbxml_geometry |
| "Make the below-grade walls adiabatic" | set_kiva_foundation | set_surface_boundary_conditions |
| "What is the EUI of this model?" | get_foundation_options, set_kiva_foundation | extract_summary_metrics |
