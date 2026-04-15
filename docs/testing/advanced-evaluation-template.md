# OpenStudio-MCP: Advanced Evaluation & Workflow Log

**Date:** [YYYY-MM-DD]  
**Evaluator:** [Your Name]  
**Session ID/Commit:** [Insert branch or commit hash]

---

## How to Use This Template

This template guides manual evaluation of the `openstudio-mcp` server across six areas.
Use it alongside the automated test suite — the tests cover deterministic behavior;
this template captures LLM-specific behavior that cannot be unit tested.

**Suggested time allocation (20-hour eval):**

| Hours | Focus |
|---|---|
| 1–5 | Sections 1 & 2 — Does the LLM use Skills correctly? |
| 6–12 | Sections 4 & 5 — Long-session state stability + practitioner workflows |
| 13–17 | Section 3 — Artifact size limits, where does it break? |
| 18–20 | Section 6 + write-up, draft SECURITY.md updates if gaps found |

---

## 1. Environment & Setup Adherence

Testing the "onboarding" experience. Does the LLM correctly identify the environment
and its capabilities?

| MCP Client | LLM Model | Initial Tool Discovery | Did it call `list_skills`? | Setup Friction |
|---|---|---|---|---|
| Claude Desktop | Claude 3.5 Sonnet | Ad-hoc / Skills-based | [Yes/No] | [e.g. README missing deps] |
| Cursor | GPT-4o | Ad-hoc / Skills-based | [Yes/No] | [e.g. Prompting issues] |

**Automated coverage:** `tests/test_skill_registration.py`, `tests/test_skill_docs.py`

---

## 2. The "Skills" Orchestration Layer

Instead of consolidating tools, we test how well the LLM uses the provided Markdown "Skills"
to navigate 126+ specialized tools.

**Test Goal:** Does the agent follow the "Skill" guide or try to "guess" tool parameters?

| Target Workflow | Skill Used | Adherence Score (1–5) | Observation / Hallucination |
|---|---|---|---|
| HVAC Swap | `add-hvac` | [Score] | [e.g. LLM ignored skill and guessed VAV parameters] |
| Geometry Edit | `tool-workflows` | [Score] | [e.g. Successfully followed skill sequence] |
| Simulation Run | `tool-workflows` (simulate) | [Score] | [e.g. Tried to run sim before loading model] |
| Baseline Generation | `ashrae-baseline-guide` | [Score] | [e.g. Wrong system type selected] |
| QAQC | `qaqc` | [Score] | [e.g. Ran checks on unsimulated model] |

**Scoring guide:**
- 5 — Followed skill verbatim, correct tool order, correct parameters
- 4 — Minor deviation (e.g., skipped one optional step), correct outcome
- 3 — Partial adherence; required correction prompt
- 2 — Mostly guessed; skill ignored
- 1 — Completely wrong tool sequence or hallucinated parameters

**Automated coverage:** `tests/llm/` suite (tool selection, routing, progressive workflows)

---

## 3. Data & Artifact Management (Breaking Points)

Testing the limits of `read_file` vs. `copy_file` for large Building Energy Modeling outputs.

| Artifact Type | File Size | Tool Used | Result (Success/Truncated/Crash) | Context Usage |
|---|---|---|---|---|
| `eplusout.err` | [e.g. 50 KB] | `read_file` | Success | [Token Count] |
| `eplusout.html` | [e.g. 2.5 MB] | `read_file` | [e.g. Truncated at 50 KB] | [Token Count] |
| `eplusout.html` | [e.g. 2.5 MB] | `copy_file` | [e.g. Successful Local Copy] | N/A |
| `eplusout.eso` | [e.g. 15 MB] | `read_file` | [e.g. Truncated] | [Token Count] |
| `eplusout.eso` | [e.g. 15 MB] | `copy_file` | [e.g. Successful Local Copy] | N/A |

**Note on Artifact Limits:** At what point did the LLM lose the ability to analyze
simulation errors? Document the exact file size and token count where analysis degraded.

**Key behavior to verify:**
- `read_file` returns `truncated: true` and `bytes_read` when file exceeds `max_bytes` (default 50 KB)
- `copy_file` always succeeds for large files (no size limit) — use when analysis requires full content
- Chunked reading via `offset` parameter allows paginating through large files

**Automated coverage:** `tests/test_artifact_limits.py`

---

## 4. In-Memory Session & State Persistence

Testing the reliability of the SWIG-wrapped in-memory model manager over long,
high-turn conversations.

| Total Turns | Model Size (.osm) | Persistence Check | Did it "drop" the model state? |
|---|---|---|---|
| 5 Turns | 120 KB | Pass — Changes Kept | No |
| 15 Turns | 120 KB | [Pass/Fail] | [e.g. Session timed out/cleared] |
| 25+ Turns | [Size] | [Pass/Fail] | [e.g. SWIG Memory Leak Warning Observed] |

**What to watch for:**
- "No model loaded" errors appearing mid-session after successful model operations
- SWIG `memory leak of type 'boost::optional...'` warnings in stderr
- Model state diverging (e.g., a zone renamed in turn 3 showing original name in turn 20)

**Automated coverage:** `tests/test_session_persistence.py` (20+ sequential operations)

---

## 5. BEM Practitioner Workflow (Visual Case Study)

### Workflow Name: [e.g. ASHRAE 90.1 Baseline Generation]

**Objective:** [Briefly describe the practitioner's goal]

**Step-by-Step Execution:**

1. **User Request:** [Insert Prompt]
2. **Skill Triggered:** [Insert Skill Name]
3. **Tool Chain:** [List tools called in sequence]
4. **Outcome:** [Brief summary of BEM result]

**Visual Documentation:**

> *Screenshot: LLM following the "Skill" Markdown instructions.*  
> `![Skill Adherence](./images/skill_ui.png)`

> *Screenshot: Final BEM result or 3D visualization verification.*  
> `![BEM Verification](./images/result_viz.png)`

---

## 6. Security & Path Validation

Quick check for path-traversal vulnerabilities or container leaks.

- **[ ]** Attempted path traversal (`../../etc/passwd`) via `file_path`? **Result:** [Blocked/Allowed]
- **[ ]** Attempted path traversal in `copy_file` `destination`? **Result:** [Blocked/Allowed]
- **[ ]** Verified that `copy_file` stays within mounted volume? **Result:** [Yes/No]
- **[ ]** Attempted to read `/repo` source code via `read_file`? **Result:** [Blocked/Allowed — note: `/repo` is in allowed roots for skill guide access]
- **[ ]** Attempted `seed_file: "../../model.osm"` in OSW? **Result:** [Path flattened to basename]

**Automated coverage:** `tests/test_path_safety.py`, `tests/test_artifact_limits.py`
(see `TestCopyFilePathSafety` class)

---

## Summary & Recommendations

| Finding | Severity | Recommended Action |
|---|---|---|
| [e.g. LLM skips list_skills on HVAC tasks] | Medium | [e.g. Add skill reminder to tool descriptions] |
| [e.g. 2.5 MB HTML truncated, analysis lost] | High | [e.g. LLM should proactively use copy_file for >50 KB] |
