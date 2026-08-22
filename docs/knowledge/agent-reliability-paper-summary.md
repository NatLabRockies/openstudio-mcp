# Towards a Science of AI Agent Reliability — Paper Summary

**Paper:** Rabanser, Kapoor, Kirgis, Liu, Utpala, Narayanan (Princeton, Feb 2026)
**arXiv:** [2602.16666](https://arxiv.org/abs/2602.16666) | **Dashboard:** [hal.cs.princeton.edu/reliability](https://hal.cs.princeton.edu/reliability/) | **Harness code:** [steverab/hal-harness](https://github.com/steverab/hal-harness)
**Source post:** [normaltech.ai](https://www.normaltech.ai/p/new-paper-towards-a-science-of-ai)

---

## Core Thesis

Standard agent benchmarks compress behavior into a single accuracy number, which hides critical operational flaws. The authors argue that **reliability is a separate dimension from accuracy**, and that 18 months of rapid capability gains have produced only modest reliability improvements. They decompose reliability into 4 dimensions and 12 concrete metrics, grounded in practices from safety-critical engineering (aviation, nuclear, automotive).

## The Capability–Reliability Gap

- Accuracy on standard benchmarks has improved substantially across OpenAI, Google, and Anthropic models over 18 months.
- Reliability, measured across their 12 metrics, has improved only modestly.
- All three major providers cluster together — this is an industry-wide limitation, not a single-vendor problem.
- This gap may explain why economic impacts of AI agents have been gradual despite strong benchmark scores.

## Four Dimensions of Reliability (12 Metrics)

### 1. Consistency

Can the agent produce the same correct outcome when run multiple times under identical conditions?

| Metric | What it measures |
|---|---|
| **Outcome consistency** | Does the agent reach the same final answer across repeated runs with identical inputs? Scores ranged 30–75%. |
| **Trajectory consistency** | Does the agent follow similar reasoning/action paths, or wildly different strategies each time? |
| **Self-consistency** | When the agent re-evaluates its own output, does it agree with itself? |

**Key finding:** Agents that *can* solve a task often fail on repeated attempts. Bigger models sometimes show *more* run-to-run variability due to richer behavioral repertoires.

### 2. Robustness

Does the agent degrade gracefully when conditions aren't perfect?

| Metric | What it measures |
|---|---|
| **Instruction robustness** | Does performance hold when instructions are paraphrased with equivalent semantic meaning? (Performance drops substantially.) |
| **Tool/environment fault tolerance** | Can the agent handle server crashes, API timeouts, missing data? (Most models do this fairly well.) |
| **Input perturbation robustness** | How does the agent handle noisy, incomplete, or slightly malformed inputs? |

**Key finding:** Models handle genuine technical failures (crashes, timeouts) gracefully, but paraphrased instructions cause significant performance drops.

### 3. Predictability (Calibration)

Does the agent know when it's wrong?

| Metric | What it measures |
|---|---|
| **Confidence calibration** | When the agent says it's 90% confident, is it right ~90% of the time? |
| **Selective accuracy** | Can the agent abstain on tasks it's likely to fail, improving accuracy on the rest? |
| **Discrimination** | Can the agent distinguish its correct outputs from incorrect ones? |

**Key finding:** This is the **weakest dimension** across the board. On one benchmark, most models couldn't distinguish correct from incorrect predictions better than chance. Self-reported confidence carries little signal.

### 4. Safety (Bounded Failure Severity)

When the agent fails, how bad is the failure?

| Metric | What it measures |
|---|---|
| **Constraint adherence** | Does the agent respect explicit operational constraints and guardrails? |
| **Error severity distribution** | Are errors minor/fixable, or catastrophic/irreversible? |
| **Financial error rate** | Specifically for tasks involving money — does the agent make incorrect charges, double-charges, etc.? |

**Key finding:** Recent models are noticeably better at avoiding constraint violations. Financial errors (incorrect charges) remain a common failure mode. The authors note they are still iterating on safety measurement and report it separately from the aggregate reliability score.

## Experimental Setup

- **14 models** tested across OpenAI, Google, Anthropic (spanning 18 months of releases)
- **2 benchmarks:** GAIA (general assistant) and TauBench (customer service simulation)
- **5 runs per task** with paraphrased instructions
- **Fault injection** into tools and environment for robustness testing
- **Confidence elicitation** after each task for calibration measurement
- **~500 total benchmark runs**
- Reproducible via the [HAL harness](https://github.com/steverab/hal-harness) — a unified CLI (`hal-eval`) with support for Docker, local conda, and Azure VM execution

## Key Recommendations

### For deployers

- **Distinguish automation from augmentation.** Copilots get a reliability "discount" because humans review output. Autonomous agents in unattended workflows need much higher reliability.
- **Set reliability thresholds** before promoting agents from sandbox to production, analogous to aviation certification.
- **Build incident-reporting culture** around agent failures.
- **Build internal evaluations** tailored to specific context and datasets — don't rely solely on public benchmarks.

### For researchers / developers

- **Report reliability profiles alongside accuracy.** Running a benchmark once is like stress-testing a car once in perfect weather.
- **Run multiple times** (test for variance), **under different conditions** (test adaptability), and **on an ongoing basis** (re-test as models change).
- **Focus on consistency and predictability** — these are the biggest gaps.
- Agents should be able to **recognize when they are likely to fail** and say so, and **recover gracefully** when they do fail.
- Explore agents that **try different strategies during development but follow a consistent execution plan in production** (bridging the agents-vs-workflows spectrum).

## Caveats the Authors Acknowledge

1. **Subjectivity in metrics** — they grounded choices in engineering fields and finalized metrics *before* experiments, but welcome alternatives.
2. **Maybe accuracy is enough** — if agents hit 99.9%+ accuracy, reliability concerns diminish. Authors think LLM-based agents aren't on track for 3–5 nines.
3. **Linear extrapolation is misleading** — projecting current trends suggests 100% reliability in 3 years, but each order of magnitude decrease in *un*reliability is likely as hard as the previous one.

---

## Relevance to openstudio-mcp / BEM MCP Test Suites

The framework maps well to building energy modeling agent workflows. Here's how each dimension applies and what we could test:

### Consistency — direct analog to BEM reproducibility

- **Run the same building creation + simulation workflow 5× with identical inputs.** Does `create_baseline_osm` → `run_simulation` → `extract_summary_metrics` yield the same EUI, unmet hours, system sizing every time?
- **Trajectory consistency:** Does the agent use the same tool sequence, or does it sometimes skip `set_weather_file`, sometimes add design days in different order?
- This is especially relevant for QA/QC — if the agent produces different results on identical inputs, that's a reliability failure regardless of whether any single run is "correct."

### Robustness — rephrased prompts and degraded environments

- **Instruction robustness:** Ask for the same building in different ways ("100k sqft office in Baltimore" vs. "a two-story office building, roughly 100,000 square feet, located in Baltimore, MD"). Does the agent produce equivalent models?
- **Tool fault injection:** What happens when `run_simulation` fails due to a missing weather file? Does the agent recover, retry with `set_weather_file`, or silently continue? (We already know `run_qaqc_checks` silently fails due to missing SQL — this is exactly the kind of thing this framework is designed to surface.)
- **Input perturbation:** Slightly malformed ASHRAE system numbers (e.g., `"7"` instead of `"07"`), partial weather file paths, ambiguous building types.

### Predictability — does the agent know when BEM results are wrong?

- **Confidence calibration:** After a simulation run, can the agent correctly assess whether results are plausible? (e.g., EUI of 500 kBtu/ft² for an office should trigger low confidence.)
- **Selective accuracy:** Can the agent flag when `extract_summary_metrics` returns null unmet hours or 0.0 conditioned floor area as likely errors, rather than reporting them as results?
- This maps to the **QA/QC gap** we've already identified — the agent should know its own tools are broken.

### Safety — bounded failure severity for BEM

- **Constraint adherence:** Does the agent respect ASHRAE 90.1 baseline requirements? Does it apply the correct system type for the building size and type?
- **Error severity:** A wrong weather file is worse than a slightly off floor area. We could classify BEM errors by severity tier: catastrophic (wrong climate zone, wrong building type), major (wrong HVAC system, missing design days), minor (slight geometry mismatch).
- **Financial proxy:** In a BEM context, "financial error" maps to energy cost miscalculation — does the agent correctly report utility costs, or does it silently return malformed EUI units?

### Concrete test suite ideas borrowing from this framework

| Test Category | What to Run | Metric Targeted |
|---|---|---|
| **Repeated baseline creation** | Same building spec × 5 runs, compare OSM checksums + simulation results | Outcome consistency |
| **Paraphrased prompts** | 3–5 semantically equivalent building descriptions | Instruction robustness |
| **Tool fault injection** | Delete weather file mid-workflow, corrupt SQL output, return timeout from EnergyPlus | Tool fault tolerance |
| **Confidence elicitation** | After each workflow, ask "how confident are you these results are correct?" then compare to ground truth | Calibration |
| **Known-bad detection** | Feed the agent simulation results with obviously wrong EUI (10× expected) and see if it flags them | Selective accuracy / discrimination |
| **Constraint compliance** | Specify ASHRAE 90.1 Appendix G requirements, verify agent selects correct system type, schedules, etc. | Constraint adherence |
| **Error severity scoring** | Categorize all failures from a test battery into severity tiers | Error severity distribution |
| **Cross-MCP consistency** | Run equivalent workflows through openstudio-mcp vs. EnergyPlus-MCP vs. openstudio-standards-mcp and compare | Trajectory + outcome consistency across tools |

### The HAL harness itself

The [hal-harness](https://github.com/steverab/hal-harness) repo provides a standardized evaluation CLI (`hal-eval`) with Docker support, parallelized runs, Weave logging for cost tracking, and encrypted trace uploads. It supports GAIA, TauBench, SWE-bench, and others. The architecture — unified CLI, benchmark plugins, configurable agents, multiple-run support — is a reasonable template for a BEM-specific evaluation harness. We wouldn't use it directly (it's tuned for their benchmarks), but the patterns are worth borrowing:

- **Benchmark as plugin:** Each benchmark defines task loading, agent interaction, and scoring. We'd define BEM tasks similarly.
- **Multiple runs with paraphrasing:** Built into the framework. We'd adapt this to BEM prompt variants.
- **Weave integration:** Automatic cost and token tracking per run — useful for comparing MCP server efficiency.
- **`hal-upload` for trace sharing:** Encrypted trace uploads to HuggingFace. We could do something similar for sharing BEM agent traces across the NLR team.

### Related work worth tracking

- **AI Agents that Matter** (Kapoor et al., 2024) — the predecessor paper on agent eval gaps
- **HELM** (Liang et al., 2022) — 7 metrics including calibration and robustness for LMs
- **CLEAR framework** (arxiv 2511.14136) — enterprise-focused eval with Cost, Latency, Efficacy, Assurance, Reliability
- **HAL Leaderboard** ([hal.cs.princeton.edu](https://hal.cs.princeton.edu)) — the interactive dashboard + leaderboard for tracking results
