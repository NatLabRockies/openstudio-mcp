# Escape annotations — host-side activity per test, all pilots

Reconstructed from raw transcripts (old legs lack host_tool_counts in
benchmark.json). `escape=True` = host tools used with ZERO MCP calls —
the agent bypassed the MCP layer entirely. Legs marked `cwd=repo` ran
the pre-sandbox harness (agent started inside the server repo): treat
starred results as contaminated by host access. Sandboxed legs report
host activity inside an empty sandbox (contained).

| leg | harness | test | host calls | mcp | escape | outcome |
|---|---|---|---|---|---|---|
| pilot-3/gpt-5.4_noskills_r1 | cwd=repo (escape-capable) | import_floorplan_L1 | LocalShellx1 | 5 | False | tool_error |
| pilot-3/gpt-5.4_noskills_r1 | cwd=repo (escape-capable) | import_floorplan_L2 | LocalShellx8 | 6 | False | tool_error |
| pilot-3/sonnet_full_r1 | cwd=repo (escape-capable) | python_ems_control_L2 | Grepx2 | 11 | False | wrong_tool |
| pilot-3/sonnet_full_r1 | cwd=repo (escape-capable) | python_ems_control_L3 | Grepx4 Readx3 | 6 | False | wrong_tool |
| pilot-3/sonnet_noskills_r1 | cwd=repo (escape-capable) | python_ems_control_L1 | Grepx2 Bashx1 | 9 | False | tool_error |
| pilot-3/sonnet_noskills_r1 | cwd=repo (escape-capable) | python_ems_control_L2 | Grepx2 Bashx1 PowerShellx1 | 9 | False | tool_error |
| pilot-3/sonnet_noskills_r1 | cwd=repo (escape-capable) | python_ems_control_L3 | Grepx3 | 11 | False | wrong_tool |
| pilot-3b/gpt-5.4_full_r1 | cwd=repo (escape-capable) | import_floorplan_L1 | LocalShellx7 | 8 | False | tool_error |
| pilot-3b/gpt-5.4_noskills_r1 | cwd=repo (escape-capable) | import_floorplan_L1 | LocalShellx2 | 5 | False | pass |
| pilot-3b/sonnet_full_r1 | cwd=repo (escape-capable) | python_ems_control_L1 | Grepx1 Bashx2 | 10 | False | pass |
| pilot-3b/sonnet_full_r1 | cwd=repo (escape-capable) | python_ems_control_L3 | Grepx2 | 8 | False | wrong_tool |
| pilot-3b/sonnet_noskills_r1 | cwd=repo (escape-capable) | import_floorplan_L1 | Readx1 | 2 | False | pass |
| pilot-3b/sonnet_noskills_r1 | cwd=repo (escape-capable) | python_ems_control_L2 | Grepx1 Globx3 Bashx1 | 9 | False | wrong_tool |
| pilot-3b/sonnet_noskills_r1 | cwd=repo (escape-capable) | python_ems_control_L3 | Grepx1 Readx1 | 7 | False | wrong_tool |
| pilot-4/gpt-5.4-mini_full_r1 | cwd=repo (escape-capable) | import_floorplan_L1 | LocalShellx10 | 2 | False | tool_error |
| pilot-4/gpt-5.4-mini_full_r1 | cwd=repo (escape-capable) | import_floorplan_L2 | LocalShellx2 | 2 | False | tool_error |
| pilot-4/gpt-5.4-mini_full_r1 | cwd=repo (escape-capable) | measure_replace_terminals_L1 | LocalShellx2 | 9 | False | wrong_tool |
| pilot-4/gpt-5.4-mini_full_r1 | cwd=repo (escape-capable) | python_ems_control_L3 | LocalShellx9 | 4 | False | wrong_tool |
| pilot-4/gpt-5.4-mini_full_r1 | cwd=repo (escape-capable) | roof_insulation_L1 | LocalShellx1 | 19 | False | pass |
| pilot-4/gpt-5.4-mini_noskills_r1 | cwd=repo (escape-capable) | import_floorplan_L1 | LocalShellx11 | 3 | False | tool_error |
| pilot-4/gpt-5.4-mini_noskills_r1 | cwd=repo (escape-capable) | import_floorplan_L2 | LocalShellx1 | 3 | False | tool_error |
| pilot-4/gpt-5.4-mini_noskills_r1 | cwd=repo (escape-capable) | python_ems_control_L2 | LocalShellx1 | 11 | False | tool_error |
| pilot-4/gpt-5.4-mini_noskills_r1 | cwd=repo (escape-capable) | roof_insulation_L1 | LocalShellx17 | 4 | False | wrong_tool |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | add_hvac_L1 | Agentx1 | 4 | False | pass |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | add_hvac_L2 | Bashx3 PowerShellx3 | 3 | False | pass |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | import_floorplan_L2 | Bashx18 Agentx1 Readx4 | 3 | False | tool_error |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | measure_replace_terminals_L1 | Bashx12 | 1 | False | pass |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | measure_replace_terminals_L2 | Bashx1 | 5 | False | pass |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | measure_replace_terminals_L3 | Agentx1 | 2 | False | pass |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | python_ems_control_L1 | Agentx1 | 4 | False | pass |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | python_ems_control_L2 | Agentx2 Bashx5 Grepx2 Readx4 | 3 | False | wrong_tool |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | roof_insulation_L1 | Bashx7 Globx1 | 10 | False | pass |
| pilot-4/haiku_full_r1 **\*** | cwd=repo (escape-capable) | roof_insulation_L3 | Bashx6 Agentx1 Readx1 | 0 | True | no_mcp_tool |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | test_create_baseline_with_hvac | Agentx1 | 1 | False | pass |
| pilot-4/haiku_full_r1 **\*** | cwd=repo (escape-capable) | zone_equipment_priority_L1 | Bashx10 Readx5 Globx1 Grepx1 | 0 | True | no_mcp_tool |
| pilot-4/haiku_full_r1 | cwd=repo (escape-capable) | zone_equipment_priority_L2 | Bashx5 Agentx1 | 5 | False | pass |
| pilot-4/haiku_noskills_r1 **\*** | cwd=repo (escape-capable) | add_hvac_L1 | Agentx1 Bashx11 Readx2 Globx2 Writex1 | 0 | True | no_mcp_tool |
| pilot-4/haiku_noskills_r1 | cwd=repo (escape-capable) | add_hvac_L2 | Bashx4 | 4 | False | pass |
| pilot-4/haiku_noskills_r1 | cwd=repo (escape-capable) | measure_replace_terminals_L1 | Bashx3 Agentx2 Readx4 Grepx1 | 2 | False | wrong_tool |
| pilot-4/haiku_noskills_r1 | cwd=repo (escape-capable) | measure_replace_terminals_L2 | Bashx12 Agentx1 Readx2 PowerShellx1 | 1 | False | wrong_tool |
| pilot-4/haiku_noskills_r1 **\*** | cwd=repo (escape-capable) | roof_insulation_L1 | Agentx1 Bashx15 Readx1 PowerShellx4 | 0 | True | wrong_tool |
| pilot-4/haiku_noskills_r1 **\*** | cwd=repo (escape-capable) | roof_insulation_L2 | Bashx2 | 0 | True | no_mcp_tool |
| pilot-4/haiku_noskills_r1 | cwd=repo (escape-capable) | test_create_baseline_model | Bashx1 Agentx1 | 1 | False | pass |
| pilot-4/haiku_noskills_r1 **\*** | cwd=repo (escape-capable) | test_create_baseline_with_hvac | Bashx8 | 0 | True | no_mcp_tool |
| pilot-4/haiku_noskills_r1 **\*** | cwd=repo (escape-capable) | zone_equipment_priority_L2 | Bashx6 | 0 | True | no_mcp_tool |
| pilot-4/haiku_noskills_r1 **\*** | cwd=repo (escape-capable) | zone_equipment_priority_L3 | Bashx3 | 0 | True | no_mcp_tool |
| pilot-5/haiku_full_r1 | cwd=repo (escape-capable) | add_hvac_L1 | Bashx1 Agentx1 | 4 | False | pass |
| pilot-5/haiku_full_r1 **\*** | cwd=repo (escape-capable) | add_hvac_L2 | Bashx12 Readx3 | 0 | True | no_mcp_tool |
| pilot-5/haiku_full_r1 | cwd=repo (escape-capable) | import_floorplan_L2 | Agentx1 Bashx14 Readx1 | 4 | False | tool_error |
| pilot-5/haiku_full_r1 **\*** | cwd=repo (escape-capable) | measure_replace_terminals_L1 | Bashx18 Readx4 | 0 | True | no_mcp_tool |
| pilot-5/haiku_full_r1 | cwd=repo (escape-capable) | measure_replace_terminals_L3 | Bashx5 | 8 | False | pass |
| pilot-5/haiku_full_r1 **\*** | cwd=repo (escape-capable) | python_ems_control_L1 | Agentx1 Bashx7 PowerShellx1 Globx1 Readx3 Writex1 Grepx1 Editx3 | 0 | True | wrong_tool |
| pilot-5/haiku_full_r1 **\*** | cwd=repo (escape-capable) | python_ems_control_L2 | Bashx3 Agentx2 | 0 | True | no_mcp_tool |
| pilot-5/haiku_full_r1 | cwd=repo (escape-capable) | roof_insulation_L1 | Bashx1 | 10 | False | pass |
| pilot-5/haiku_full_r1 **\*** | cwd=repo (escape-capable) | roof_insulation_L3 | Bashx14 Readx1 | 0 | True | no_mcp_tool |
| pilot-5/haiku_full_r1 | cwd=repo (escape-capable) | test_create_baseline_model | Agentx1 | 1 | False | pass |
| pilot-5/haiku_full_r1 | cwd=repo (escape-capable) | zone_equipment_priority_L1 | Bashx5 | 5 | False | pass |
| pilot-5/haiku_full_r1 | cwd=repo (escape-capable) | zone_equipment_priority_L2 | Bashx6 | 5 | False | pass |
| pilot-5/haiku_full_r1 **\*** | cwd=repo (escape-capable) | zone_equipment_priority_L3 | Bashx4 PowerShellx5 Writex1 Editx2 Readx3 | 0 | True | wrong_tool |
| pilot-5/haiku_full_r2 | cwd=repo (escape-capable) | add_hvac_L1 | Bashx1 | 8 | False | pass |
| pilot-5/haiku_full_r2 | cwd=repo (escape-capable) | add_hvac_L2 | Bashx3 | 3 | False | pass |
| pilot-5/haiku_full_r2 | cwd=repo (escape-capable) | import_floorplan_L2 | Readx1 | 2 | False | pass |
| pilot-5/haiku_full_r2 | cwd=repo (escape-capable) | measure_replace_terminals_L2 | Bashx1 | 2 | False | pass |
| pilot-5/haiku_full_r2 **\*** | cwd=repo (escape-capable) | python_ems_control_L2 | Agentx1 Bashx1 Readx3 Globx2 | 0 | True | no_mcp_tool |
| pilot-5/haiku_full_r2 | cwd=repo (escape-capable) | roof_insulation_L1 | Agentx1 Bashx6 | 31 | False | pass |
| pilot-5/haiku_full_r2 | cwd=repo (escape-capable) | roof_insulation_L3 | Bashx3 | 10 | False | pass |
| pilot-5/haiku_full_r2 | cwd=repo (escape-capable) | test_create_baseline_model | Agentx1 | 1 | False | pass |
| pilot-5/haiku_full_r2 | cwd=repo (escape-capable) | zone_equipment_priority_L1 | Bashx4 Agentx1 | 6 | False | pass |
| pilot-5/haiku_full_r2 **\*** | cwd=repo (escape-capable) | zone_equipment_priority_L2 | Bashx12 Readx2 Globx1 Writex1 Editx2 Grepx1 | 0 | True | no_mcp_tool |
| pilot-5/haiku_full_r3 **\*** | cwd=repo (escape-capable) | import_floorplan_L2 | Agentx2 Bashx1 | 0 | True | no_mcp_tool |
| pilot-5/haiku_full_r3 **\*** | cwd=repo (escape-capable) | test_create_baseline_model | Bashx12 Readx6 Writex1 Editx2 | 0 | True | no_mcp_tool |
| pilot-5/haiku_full_r3 **\*** | cwd=repo (escape-capable) | test_create_baseline_with_hvac | Agentx1 Bashx7 Readx4 Writex1 Editx1 | 0 | True | timeout |
| pilot-5/haiku_noskills_r1 **\*** | cwd=repo (escape-capable) | import_floorplan_L2 | Bashx13 Agentx1 Writex1 PowerShellx1 Readx2 | 0 | True | wrong_tool |
| pilot-5/haiku_noskills_r1 **\*** | cwd=repo (escape-capable) | measure_replace_terminals_L1 | Bashx8 | 0 | True | no_mcp_tool |
| pilot-5/haiku_noskills_r1 **\*** | cwd=repo (escape-capable) | measure_replace_terminals_L2 | Bashx19 PowerShellx1 Writex1 Editx4 Readx2 | 0 | True | wrong_tool |
| pilot-5/haiku_noskills_r1 | cwd=repo (escape-capable) | measure_replace_terminals_L3 | Bashx3 | 2 | False | pass |
| pilot-5/haiku_noskills_r1 | cwd=repo (escape-capable) | python_ems_control_L1 | Bashx2 | 6 | False | pass |
| pilot-5/haiku_noskills_r1 | cwd=repo (escape-capable) | roof_insulation_L1 | Bashx2 | 12 | False | pass |
| pilot-5/haiku_noskills_r1 | cwd=repo (escape-capable) | roof_insulation_L2 | Agentx1 | 14 | False | pass |
| pilot-5/haiku_noskills_r1 | cwd=repo (escape-capable) | test_create_baseline_model | Bashx1 | 1 | False | pass |
| pilot-5/haiku_noskills_r1 | cwd=repo (escape-capable) | test_create_baseline_with_hvac | Bashx1 | 1 | False | pass |
| pilot-5/haiku_noskills_r1 | cwd=repo (escape-capable) | zone_equipment_priority_L2 | Bashx5 | 5 | False | pass |
| pilot-5/haiku_noskills_r2 **\*** | cwd=repo (escape-capable) | add_hvac_L1 | Bashx14 | 0 | True | no_mcp_tool |
| pilot-5/haiku_noskills_r2 | cwd=repo (escape-capable) | import_floorplan_L2 | Bashx1 | 1 | False | pass |
| pilot-5/haiku_noskills_r2 | cwd=repo (escape-capable) | measure_replace_terminals_L2 | Bashx11 PowerShellx2 Agentx1 Readx1 | 3 | False | pass |
| pilot-5/haiku_noskills_r2 | cwd=repo (escape-capable) | measure_replace_terminals_L3 | Readx1 Bashx2 | 8 | False | pass |
| pilot-5/haiku_noskills_r2 **\*** | cwd=repo (escape-capable) | python_ems_control_L1 | Agentx1 Bashx6 Globx1 Grepx2 Readx2 | 0 | True | no_mcp_tool |
| pilot-5/haiku_noskills_r2 **\*** | cwd=repo (escape-capable) | python_ems_control_L2 | Bashx14 Readx4 Globx1 | 0 | True | no_mcp_tool |
| pilot-5/haiku_noskills_r2 | cwd=repo (escape-capable) | python_ems_control_L3 | Bashx1 | 3 | False | pass |
| pilot-5/haiku_noskills_r2 | cwd=repo (escape-capable) | roof_insulation_L2 | Agentx1 | 9 | False | pass |
| pilot-5/haiku_noskills_r2 **\*** | cwd=repo (escape-capable) | roof_insulation_L3 | Bashx10 Writex1 | 0 | True | no_mcp_tool |
| pilot-5/haiku_noskills_r2 | cwd=repo (escape-capable) | test_create_baseline_with_hvac | Agentx1 | 1 | False | pass |
| pilot-5/haiku_noskills_r2 | cwd=repo (escape-capable) | zone_equipment_priority_L1 | Bashx1 | 8 | False | pass |
| pilot-5/haiku_noskills_r2 **\*** | cwd=repo (escape-capable) | zone_equipment_priority_L3 | Bashx14 Readx2 | 0 | True | no_mcp_tool |
| pilot-5/haiku_noskills_r3 | sandboxed | add_hvac_L1 | Bashx1 | 6 | False | pass |
| pilot-5/haiku_noskills_r3 | sandboxed | add_hvac_L2 | Bashx2 | 3 | False | pass |
| pilot-5/haiku_noskills_r3 | sandboxed | import_floorplan_L2 | Bashx2 Agentx1 | 1 | False | pass |
| pilot-5/haiku_noskills_r3 | sandboxed | measure_replace_terminals_L2 | Bashx5 | 10 | False | pass |
| pilot-5/haiku_noskills_r3 | sandboxed | python_ems_control_L3 | Bashx12 Agentx1 Grepx1 | 5 | False | tool_error |
| pilot-5/haiku_noskills_r3 | sandboxed | roof_insulation_L1 | Bashx13 Readx1 | 0 | True | no_mcp_tool |
| pilot-5/haiku_noskills_r3 | sandboxed | test_create_baseline_model | Bashx4 Agentx1 | 1 | False | pass |
| pilot-5/haiku_noskills_r3 | sandboxed | test_create_baseline_with_hvac | Bashx1 | 1 | False | pass |
| pilot-5/sonnet_nodiscovery-noskills_r1 | sandboxed | python_ems_control_L1 | Grepx1 Bashx1 PowerShellx1 | 10 | False | pass |
| pilot-5/sonnet_nodiscovery-noskills_r1 | sandboxed | python_ems_control_L2 | Grepx3 | 12 | False | tool_error |
| pilot-5/sonnet_nodiscovery-noskills_r1 | sandboxed | python_ems_control_L3 | Grepx4 | 7 | False | pass |
| pilot-5/sonnet_nodiscovery_r1 | sandboxed | python_ems_control_L1 | Grepx2 Bashx1 | 12 | False | pass |
| pilot-5/sonnet_nodiscovery_r1 | sandboxed | python_ems_control_L2 | Grepx1 Bashx5 | 9 | False | pass |

**\*** = escape on the escape-capable harness: result untrustworthy
(agent may have read server source / grading tests, or acted
out-of-band; see haiku_full_r3 fabricated-success case).
