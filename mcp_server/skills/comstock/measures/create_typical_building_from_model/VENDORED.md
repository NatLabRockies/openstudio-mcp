# Vendored fork: create_typical_building_from_model

openstudio-mcp carries its own copy of the ComStock `create_typical_building_from_model`
measure plus the openstudio-standards library function it wraps. The Docker build
deletes the upstream measure dir pulled from the ComStock tarball and overlays this
one (`docker/Dockerfile`, right after the ComStock curl step), so every path that
resolves `COMSTOCK_MEASURES_DIR/create_typical_building_from_model` gets the fork.

## Sources

| File | Upstream | Version |
|---|---|---|
| `measure.rb`, `LICENSE.md`, `README.md` | `NatLabRockies/ComStock` `resources/measures/create_typical_building_from_model/` | tag `2025-3` |
| `resources/create_typical_vendored.rb` | `NatLabRockies/openstudio-standards` `lib/openstudio-standards/create_typical/create_typical.rb` | `v0.8.5`, commit `4b15daf` (the gem in `/var/oscli`) |
| `measure.xml` | regenerated with `openstudio measure -u`; **own uid** `281b45c3-f594-4347-8015-1b4eb619fc11` (upstream is `339a2e3a-...`) | |

Commit 1 of the fork branch holds the verbatim copies; the fork edits are the next
commit, so `git log --follow` on either file shows the exact diff against upstream.

## Why

`hvac_only=True` on `create_typical_building` pins every `add_*` section off except
HVAC and expects only the HVAC to change. Upstream does not honor that:

| Step | Upstream gate | Effect on an HVAC-only swap |
|---|---|---|
| NIST infiltration (`model_set_nist_infiltration`) | `add_infiltration`, a library kwarg the measure never exposes (always true) | replaces the model's infiltration **before** the sizing run; EUI 27 to 67 kBtu/ft2 on the SystemD test model |
| F-factor / C-factor ground constructions | none | slab constructions replaced before the sizing run |
| `OutputControl:ReportingTolerances` | none | unmet-hours metric changes (1 R vs model value) |
| `purgeUnusedResourceObjects` | `remove_objects` (also drives HVAC removal) | shading controls, blinds, schedules deleted |
| Night-cycle managers to 1.9999 / Thermostat | none | pre-existing managers rewritten |
| `SimulationControl` HVAC sizing sim off | none | sizing behavior changed |
| `model_apply_hvac_efficiency_standard` | `add_hvac` | also retunes retained SWH equipment; handled in Python (`hvac_only_guard.py`), not here |

The first two matter most: the new HVAC is autosized against whatever infiltration and
ground constructions are in the model at sizing run SR1, and the post-SR1 steps bake
those results in. Restoring the envelope after the measure returns cannot undo that,
which is why the gates live in the measure.

## What changed (all defaults reproduce upstream behavior)

`measure.rb`
- `require_relative 'resources/create_typical_vendored'`; the run call targets
  `OsmcpCreateTypical.create_typical_building_from_model`.
- New arguments: `add_infiltration` (true), `airtightness_value` (0 = standard default
  13.8 m3/h-m2 at 75 Pa; multiply cfm/ft2 by 18.288), `airtightness_area_covered`
  (`5-sided`; `4-sided` / `6-sided`), `air_barrier` (false), `set_ground_constructions`
  (true), `set_unmet_hours_tolerance` (true), `modify_night_cycle_managers` (true),
  `purge_unused_resources` (true), `set_sim_control` (true).
- Description mentions the fork.

`resources/create_typical_vendored.rb`
- Module renamed `OpenstudioStandards::CreateTypical` -> `OsmcpCreateTypical`. Every
  helper the function calls (`get_templates`, `HVAC.add_cbecs_hvac_system`,
  `Infiltration.*`, the standards classes) still comes from the gem.
- Signature gains the nine kwargs above; the seven steps are wrapped in `if` gates.
  `modify_night_cycle_managers: false` still applies the 1.9999 K / Thermostat values to
  managers created during the run (the new HVAC), and only skips managers that existed
  before it (pre-existing handles are recorded at the start). Without that, a swap on a
  typical-built model diverged from the full build by ~150 unmet heating hours.
  `purge_unused_resources` is ANDed with `remove_objects`, so per-section removal
  (including `model_remove_prm_hvac`) keeps working with the purge off.
- `model_set_nist_infiltration` receives `airtightness_value`,
  `airtightness_area_covered`, `air_barrier`; nil falls back to the standard defaults.
- The unused second function `create_space_types_and_constructions` is dropped.

Every edit is marked with an `openstudio-mcp fork` comment. Rule 1 (file size) does
not apply to vendored third-party code, same as the grandfathering clause.

## Re-sync procedure (owner: whoever bumps `COMSTOCK_TAG` or the standards gem)

1. In the new dev image: copy `/opt/comstock-measures/create_typical_building_from_model/{measure.rb,LICENSE.md,README.md}`
   and the gem's `create_typical/create_typical.rb` (as `resources/create_typical_vendored.rb`) over this dir. Commit verbatim.
2. Re-apply the fork diff: `git diff <verbatim-commit-1>..<fork-commit-2> -- mcp_server/skills/comstock/measures | git apply -3`.
   Resolve conflicts by hand; every gate is a small `if` block with an `openstudio-mcp fork` comment.
3. `ruby -c` both files, then `openstudio measure -u .` in the image to refresh `measure.xml`
   (keep this fork's uid; the tool only bumps `version_id` and checksums).
4. Update the Sources table above and the Dockerfile comment next to `COMSTOCK_TAG`.
5. Run `tests/test_comstock_vendored_parity.py`, `tests/test_hvac_only_preservation.py`,
   `tests/test_hvac_only_swap.py` and `tests/test_comstock.py`.

## Retiring the fork

Upstream changes that would let this dir go away: openstudio-standards gating the
F-factor, tolerance, night-cycle and SimulationControl steps behind arguments and
limiting `model_apply_hvac_efficiency_standard` to newly added HVAC; the ComStock
measure exposing `add_infiltration` and the airtightness inputs. Draft issues are in
`plan-hvac-only-non-hvac-preservation.md` section 7.
