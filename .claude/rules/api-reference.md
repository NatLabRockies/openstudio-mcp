---
description: OpenStudio SDK, CLI, and external resource references
---

## OpenStudio SDK (3.11.0)
- `openstudio.model` (70+ classes), `openstudio.osversion.VersionTranslator`, `openstudio.BCLMeasure`
- SDK docs: https://openstudio-sdk-documentation.s3.amazonaws.com/index.html

## OpenStudio CLI
- `openstudio run -w <osw>` — run simulation
- `openstudio run --measures_only -w <osw>` — run measures only

## External Resources
- **openstudio-resources** — HVAC wiring patterns, baseline model geometry
  https://github.com/NatLabRockies/OpenStudio-resources/tree/develop/model/simulationtests
- **ComStock measures** (~61 bundled) — standards-based templates for typical buildings
  https://github.com/NatLabRockies/ComStock (tag: `2025-3`, installed at `/opt/comstock-measures`)
