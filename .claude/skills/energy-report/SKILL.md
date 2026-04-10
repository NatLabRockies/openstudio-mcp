---
name: energy-report
description: Generate comprehensive energy analysis report from simulation results. Use when user asks for "energy report", "full results", or "detailed analysis".
disable-model-invocation: true
---

# Comprehensive Energy Report

Extract all result categories from a completed simulation and present a structured report.

## Steps

1. Identify the run. If user provides a run_id, use it. Otherwise check for the most recent simulation.

2. For an HTML report with ~25 sections (fastest):
   ```
   generate_results_report(run_id=<id>)
   ```

3. Or extract individual categories for custom analysis:
   ```
   extract_summary_metrics(run_id=<id>)
   extract_end_use_breakdown(run_id=<id>)
   extract_envelope_summary(run_id=<id>)
   extract_hvac_sizing(run_id=<id>)
   extract_zone_summary(run_id=<id>)
   extract_component_sizing(run_id=<id>)
   extract_simulation_errors(run_id=<id>)
   ```

4. For before/after comparison:
   ```
   compare_runs(baseline_run_id=<id1>, retrofit_run_id=<id2>)
   ```

5. Optionally run QA/QC:
   ```
   run_qaqc_checks()
   ```

4. Present structured report with these sections:

### Report Sections

**Overview**
- Total site energy, EUI, peak demand
- Unmet heating/cooling hours
- Conditioned floor area

**End-Use Breakdown**
- Energy by end use (heating, cooling, interior lighting, equipment, fans, pumps, SHW)
- Energy by fuel type (electricity, natural gas, district)

**Envelope Performance**
- Opaque surface U-values and areas
- Fenestration U-values, SHGC, areas
- Window-to-wall ratio

**HVAC Sizing**
- Zone-level heating/cooling capacities
- System-level airflow and capacities
- Design day conditions

**Zone Summary**
- Per-zone areas, volumes, multipliers
- Zone heating/cooling loads

**QA/QC Flags** (if run)
- Any warnings or compliance issues
