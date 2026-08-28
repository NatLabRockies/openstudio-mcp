## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Write a Ruby OpenStudio measure named reduce_lpd that lowers lighting power density by ten percent" | create_measure | name=reduce_lpd, description present, run_body present, language present |
| "Create a Python model measure named report_zone_count that reports how many thermal zones exist" | create_measure | name=report_zone_count, description present, run_body present, language present |
| "Build a custom reporting measure named annual_peak_report for simulation results" | create_measure | name=annual_peak_report, measure_type=ReportingMeasure |
| "Revise the existing reduce_lpd measure so its run method also logs the final lighting power" | edit_measure | measure_name=reduce_lpd, run_body present |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "Apply the existing measure at /measures/ReduceLightingLoads to the loaded model" | create_measure, edit_measure | apply_measure |
| "What custom measures have already been created?" | create_measure, edit_measure | list_custom_measures |
| "Test the measure at /measures/custom/reduce_lpd against the loaded model" | create_measure, edit_measure | test_measure |
