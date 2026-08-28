---
name: osaf-analysis
description: OpenStudio Analysis Framework (OSAF) workflows, algorithm selection, validation, submission, and result download. Use when the user asks about OSAF, OpenStudio Server analyses, sampling, sweeps, optimization, calibration, or OSA JSON configs.
disable-model-invocation: true
---

# OSAF Analysis Workflows

Use this skill when working with OpenStudio Server / OSAF analysis JSON,
support ZIPs, sampling sweeps, optimization, calibration, or server smoke tests.

## Defaults That Matter

- Omit `output_variables` when creating OSA JSON unless the user explicitly
  asks for a custom set — the tools then include the foundational OpenStudio
  Results outputs (EUI, site energy, peak demand, unmet hours, per-fuel end
  uses) with export+visualize enabled so OSAF plots work. Use
  `openstudio_analysis_default_output_variables` to inspect or extend the
  default payload.
- The OSA seed weather file is an **EPW**. DDY/STAT files are support files —
  never set one as the analysis weather file.

## Discover Algorithms

For “list OSAF algorithms” or “what is this algorithm best for”, call:

```
openstudio_analysis_algorithms
```

Filter by category or analysis type when useful:

```
openstudio_analysis_algorithms category="sampling"
openstudio_analysis_algorithms category="lhs"
```

The tool returns analysis types, categories, best-fit use cases, caveats,
typical algorithm keys, and the correct start sequence.

## Algorithm Selection

Common choices:

| Need | Prefer |
|---|---|
| Check server/config/package with one run | single_run |
| One-variable or general parameter sweep | lhs |
| Full-factorial style experiment with 2+ variables | doe |
| Screening many variables cheaply | morris |
| Formal variance-based sensitivity | sobol |
| Multi-objective Pareto calibration/design | nsga_nrel or spea_nrel |
| Continuous calibration/search | pso or rgenoud |
| Debugging repeatability or bounds | repeat_run or preflight |

Do not use DOE for only one real variable. Use LHS for one-variable sweeps.

## Validate Existing Configs

For existing OpenStudio-server/spec OSA JSON configs, call:

```
openstudio_analysis_validate_osa_json
```

Raw validation is schema-focused by default and accepts legacy server config
patterns. Use `require_foundational_measures=true` when validating an
MCP-generated analysis that is about to be packaged/submitted.

## Create and Submit MCP Analyses

Create OSA JSON from measures:

```
openstudio_analysis_create_osa_json_from_measures
```

Before uploading a support ZIP:

```
openstudio_analysis_prepare_package
openstudio_analysis_validate_package
```

Submit and upload:

```
openstudio_analysis_submit
```

Generated analysis JSON files and support ZIP packages always include the
foundational measures:

- view_model
- openstudio_results
- generic_qaqc

Default output variables are exported and visualized so OSAF plots can show
OpenStudio Results whole-building metrics and electricity/natural gas end uses.

## Start Order

OSAF sampled analyses need two start actions:

1. Start the algorithm action first, such as lhs, sobol, morris, pso, or nsga_nrel.
2. Start batch_run to simulate the generated datapoints.

Prefer:

```
openstudio_analysis_start_sampled_run
```

For a single-run smoke test, start single_run first, then batch_run.
