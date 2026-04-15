# Token Context & Performance Impact

This document covers the measurable cost of connecting openstudio-mcp to an LLM client: how many tokens the 142 tools consume, how different clients handle that load, and what strategies reduce the overhead.

Schema measurements are live — extracted directly from the running MCP server via `tools/list` JSON-RPC (see [Measuring Schema Size](#measuring-schema-size) below). LLM accuracy figures are from the three-model benchmark sweep (180 tests, zero retries; see [`docs/knowledge/tool-discovery-and-llm-testing.md`](../knowledge/tool-discovery-and-llm-testing.md)).

---

## What Adds to Context

When an MCP client connects to openstudio-mcp, the following items may enter the model's context window:

| Item | Size | When loaded |
|------|------|-------------|
| Tool schemas (all 142) — full JSON | ~117K chars / **~29K tokens** | On first tool call or session start |
| Server instructions (`NEVER`/`ALWAYS` rules) | ~550 tokens | Once per session |
| Skill guide content (`get_skill()` output) | 1–4K tokens per guide | When explicitly requested |
| MCP prompts / resources | ~0.5K tokens each | When explicitly invoked |
| Conversation history | Grows per turn | Accumulates throughout session |

**Total fixed overhead on first tool call: ~30–32K tokens.**

For comparison, a full simulation run (create building → simulate → extract results → compare) takes approximately **15K total tokens** in conversation — about half the schema overhead alone.

> **Note on schema token counting:** Early measurements reported ~61K chars / ~15K tokens. That figure counted **names + descriptions only** and omitted the JSON input schemas (parameter names, types, enums, defaults). The full JSON payload an LLM actually receives is 117K chars / ~29K tokens. Both figures are accurate for their stated scope; use the full-JSON number for context budget planning.

---

## Schema Size History

The schema size has been measured at multiple points in the project:

| Date | Tools | Schema Chars (full JSON) | Est. Tokens | Change |
|------|-------|--------------------------|-------------|--------|
| Feb 2026 | 62 | ~54K | ~13.5K | Initial |
| Mar 2026 | 126 | ~175K | ~44K | +64 tools |
| Mar 2026 (post-compress) | 127 | ~108K | ~27K | 30% description compression |
| Apr 2026 | 142 | **117K** | **~29K** | +15 tools; measured live |

Breakdown of the Apr 2026 117K chars:
- Names: ~2.7K chars (~673 tokens)
- Descriptions: ~58.7K chars (~14.7K tokens)
- Input schemas (params/types/enums): ~36.1K chars (~9K tokens)
- JSON structure overhead: ~19.5K chars (~4.9K tokens)

Key lesson: description compression reduced schema size but harmed ToolSearch accuracy (compressed descriptions had fewer keywords for BM25 matching). The current schema is a deliberate balance between size and discoverability.

---

## Per-Client Context Budget

### Context windows

Measured April 2026 from live `tools/list` response (117,047 chars / 142 tools):

| Client / Model | Context Window | Schema Tokens | Overhead % | Notes |
|----------------|---------------|---------------|-----------|-------|
| Claude Code (Sonnet 4.7) | 200K tokens | **~1K tokens*** | **~0.5%*** | ToolSearch defers all; 3–5 tools/turn |
| Claude Desktop (Sonnet 4.7) | 200K tokens | ~29K tokens | ~14.6% | All 142 schemas in context |
| VS Code Copilot (GPT-4.1) | 128K tokens | ~28K tokens† | ~22.0%† | 128-tool cap enforced |
| VS Code Copilot (Claude Sonnet 4.7) | 200K tokens | ~28K tokens† | ~14.1% | 128-tool cap enforced |
| VS Code Copilot (Gemini 2.5 Flash) | 1M tokens | ~28K tokens† | ~2.8% | 128-tool cap enforced |
| Windsurf / 80-tool curated | 200K tokens | ~16.5K tokens | ~8.2% | Manual curation required |
| Gemini CLI (Gemini 2.5 Pro) | 1M tokens | ~29K tokens | ~2.9% | Use `includeTools` to reduce |

\* Claude Code ToolSearch defers all tools; only 3–5 schemas (~820–1,030 tokens at ~205 tokens/tool avg) load per turn.  
† VS Code Copilot enforces a 128-tool cap; 14 smallest tools excluded, saving ~1.1K tokens. The 14 excluded tools (based on schema size) are: `get_run_period`, `get_versions`, `get_server_status`, `get_weather_info`, `match_surfaces`, `get_simulation_control`, `cancel_run`, `enable_ideal_air_loads`, `set_lifecycle_cost_params`, `extract_hvac_sizing`, `extract_zone_summary`, `get_run_artifacts`, `extract_envelope_summary`, `get_zone_hvac_details`.

### When Context Pressure Becomes a Problem

Claude Code triggers ToolSearch automatically when schemas exceed 10% of context. For other clients, the model itself must manage context. Signs of context pressure:

- Model begins truncating or paraphrasing earlier in the conversation
- Tool calls start failing to pass correct parameter values (model "forgets" schema details)
- Model stops using tools entirely and falls back to explaining what it would do
- Long simulation chains: after 20+ turns with large intermediate results, accuracy drops

**Practical guideline:** At ~29K tokens of schema overhead, Claude Desktop and VS Code Copilot (GPT-4.1 on 128K context) already spend ~15–22% of their budget before any conversation. Plan for 10–15 high-quality turns on complex workflows. Start a new conversation and reference `/runs/` output paths to continue.

---

## How Clients Handle 142 Tools

### Claude Code: ToolSearch (Deferred Loading)

ToolSearch indexes all 142 tools at image build time using BM25/regex on names and descriptions. When schemas exceed 10% of context, tools are deferred. Per turn:
- ~3–5 tool schemas load into context (~1K tokens, ~97% reduction vs. 29K)
- Schema overhead per turn: ~1,030 tokens (5 tools × ~205 tokens/tool avg)
- Works because the ToolSearch index holds the full schema catalog outside context

**Benchmark result:** 94.4% pass rate (Sonnet/Opus, 180 tests, zero retries). ToolSearch calls: avg 1.9/test.

### Claude Desktop / VS Code Copilot: Brute-Force Load

All enabled tool schemas load into context on the first tool call. No deferred loading, no filtering. Performance effect:
- First response in a new session has ~14–22% context already consumed (vs. ~0.5% for Claude Code)
- Accuracy stays high for shorter sessions (5–10 turns)
- Long sessions may show degradation as conversation history + schema + results approach the context limit
- VS Code Copilot with GPT-4.1 (128K window) is most constrained: ~22% of context consumed before the first user message

### Windsurf: Per-Tool Toggle (Manual Curation)

Cascade enforces 100 tools hard. User selects which tools are enabled. With a curated 80-tool set (~16.5K tokens), the overhead is ~43% lower than loading all 142. Manual curation adds setup friction but produces the most focused tool surface.

### Gemini CLI: Large Context Buffer

1M token context window means schema overhead (~29K tokens = ~2.9%) is low even at full load. The practical concern is accuracy per turn, not context exhaustion — presenting all 142 tools at once can confuse the model. Use `includeTools` to keep per-turn tool count under ~40.

---

## Strategies to Reduce Context Overhead

### 1. Use `list_skills` + `get_skill` First (Universal)

Instead of letting the model search all 142 tools, ask it to follow a skill guide. The guide gives explicit tool names and order, bypassing tool discovery entirely:

```
"Use the new-building skill to create a medium office building in Boston."
```

vs.

```
"Create a medium office building in Boston."  ← model must select from 142 tools
```

Both work, but the first produces fewer ToolSearch calls and more predictable tool sequences.

### 2. Enable `defer_loading` (OpenAI-Compatible Clients)

For clients that support the OpenAI `defer_loading` flag, set it on the server config. This exposes only a search tool by default and loads schemas on demand. Reduces first-call overhead by ~85%.

### 3. Use `includeTools` / Per-Tool Toggles (Windsurf, Gemini CLI)

Configure a focused tool subset matching your current workflow phase. A 30-tool simulation workflow subset (~4–5K tokens) is well within any client's context budget and produces cleaner responses than exposing all 142.

### 4. Reference `/runs/` Paths, Not Inline Results

Instead of asking the model to read and summarize large simulation outputs inline, reference them by path:

```
"The simulation output is at /runs/run-20260415/. Extract the EUI."
```

This lets `extract_summary_metrics` and `extract_end_use_breakdown` do targeted extraction rather than streaming the full HTML report into context.

### 5. Split Long Workflows Across Conversations (Claude Desktop)

Save model state at key checkpoints with `save_osm_model`. Start a fresh conversation for the next phase. Reference saved files by path. This resets conversation history overhead while preserving all model changes.

---

## Tool Call Latency

Measured April 2026 via OpenLLMetry traces (Jaeger). Environment: Apple M3 Max, Docker amd64 emulation, openstudio-mcp:tracing image.

### Cold Start (first tool call per Docker container)

Includes: Docker container launch + Python server init + first `import openstudio`.

| Phase | Latency |
|-------|---------|
| Container start → MCP `initialize` response | ~1.8–2.1s |
| First `import openstudio` (cold) | included above |
| tools/list (full 142 schema, 117K chars) | ~1s (bundled at init) |

### Warm Tool Call Latency (in-session, OpenStudio already loaded)

| Tool | Avg latency | Notes |
|------|-------------|-------|
| `get_server_status` | ~3ms | No OpenStudio ops |
| `list_skills` | ~1ms | File read only |
| `validate_model` | ~3ms | Model checks |
| `list_spaces` / `list_thermal_zones` / `list_air_loops` | 1–5ms | In-memory iteration |
| `list_weather_files` | ~12ms | EPW file scan |
| `get_building_info` | ~5–15ms | Model introspection |
| `get_model_summary` | ~8–23ms | Full object count |
| `get_versions` | ~150–220ms | OpenStudio SDK call |
| `create_example_osm` | ~200–215ms | Model build from scratch |

> **Note:** These latencies reflect the MCP server's processing time. Client-visible latency adds the LLM inference time on top (typically 1–10s for tool call generation + JSON parse). The server itself is fast; bottlenecks in multi-step workflows are almost always LLM inference, not tool execution.

### Running Traces Yourself

```bash
# 1. Start Jaeger
docker compose -f docker/docker-compose.tracing.yml up -d

# 2. Build tracing image
docker build --build-arg TELEMETRY=1 -t openstudio-mcp:tracing -f docker/Dockerfile .

# 3. Connect your client with tracing env vars (see compose file header)
# Traces appear at http://localhost:16686
```

---

## LLM Accuracy vs. Tool Count

From internal benchmarks and published research:

| Tools Presented Per Turn | Accuracy | Source |
|--------------------------|----------|--------|
| 5–7 | ~92% | Jenova.ai |
| 10–15 | sweet spot | Multiple |
| 3–5 (ToolSearch output) | 94.4% | openstudio-mcp sweep |
| 40+ (all visible, no deferral) | Degraded | Allen Chan / IBM |
| 100+ (no retrieval) | ~13–14% | RAG-MCP |
| 100+ (with semantic retrieval) | ~43% | RAG-MCP |

The openstudio-mcp benchmark shows 94.4% at 142 tools **because ToolSearch reduces the per-turn visible set to 3–5**. Without ToolSearch (e.g., Claude Desktop), the effective tool count visible to the model per turn is still all 142, but Claude's reasoning capability keeps accuracy high for sessions under ~20 turns.

---

## Local LLM Benchmark: llama3.2:3b vs gemma3:4b

Measured April 2026 on Apple M3 Max (14 CPU, 36 GB RAM, no GPU) via Ollama v0.20.7 + [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness) 0.4.11. Tasks: **GSM8K** (math / chain-of-thought reasoning) and **IFEval** (instruction following). 100 samples per task, zero-shot.

| Model | GSM8K flexible-extract | IFEval prompt loose | IFEval inst loose | Runtime | Disk |
|---|---|---|---|---|---|
| llama3.2:3b (Meta, US) | **0.67** | 0.630 | 0.767 | 9m35s | 2.0 GB |
| gemma3:4b (Google DeepMind, US) | 0.55 | **0.750** | **0.828** | 16m39s | 3.3 GB |

**Takeaways:**
- `llama3.2:3b` wins on math/reasoning (0.67 vs 0.55 GSM8K).
- `gemma3:4b` wins on instruction following (0.750 vs 0.630 IFEval prompt-level loose) — more relevant for agentic tool use.
- `gemma3:4b` **does not support native tool calling in Ollama** — the `/api/chat` endpoint returns HTTP 400 for any `tools` field. This makes it unsuitable for measuring MCP schema overhead or running tool-calling benchmarks with Ollama.
- **`llama3.2:3b` is the recommended model for CI-based MCP overhead benchmarks**: native tool calling, 2.0 GB fits comfortably on GitHub Actions `ubuntu-latest` (16 GB RAM), and is from a US-based company.

### How to Reproduce

```bash
# Pull both models
ollama pull llama3.2:3b
ollama pull gemma3:4b

# Start server
ollama serve &

# Install deps
pip install lm_eval langdetect immutabledict nltk
python3 -c "import nltk; nltk.download('punkt_tab'); nltk.download('stopwords')"

# Run benchmark (100 samples each, ~10 min for llama3.2:3b)
python3 -m lm_eval \
  --model local-chat-completions \
  --model_args "model=llama3.2:3b,base_url=http://localhost:11434/v1/chat/completions,num_concurrent=1,max_retries=3,tokenized_requests=False" \
  --tasks gsm8k,ifeval \
  --num_fewshot 0 \
  --limit 100 \
  --apply_chat_template \
  --output_path /tmp/lmeval_results/llama32_3b
```

> **Note:** Use `--model local-chat-completions` (not `openai-chat-completions`). The `base_url` must be the full chat completions path. Loglikelihood tasks (ARC, HellaSwag, MMLU) raise `NotImplementedError` for chat models; only `generate_until` tasks like `gsm8k` and `ifeval` work.

---

## Token Overhead by Scenario (Ollama Measurement)

Measured April 2026 using Ollama `prompt_eval_count` — the actual number of prompt tokens processed. Prompt: "What is the total floor area of the current building?" Three runs per scenario, median reported.

| Scenario | Tools | llama3.2:3b tokens | Delta | First-call latency |
|---|---|---|---|---|
| No tools (baseline) | 0 | 36 | — | 0.14s |
| 5 tools | 5 | 529 | +493 | 0.07s |
| 30 tools | 30 | 2,579 | +2,543 | 0.09s |
| 142 tools (synthetic, compact) | 142 | 11,763 | +11,727 | 0.19s |
| **142 tools (real openstudio-mcp)** | **142** | **~29,000** | **~28,964** | ~0.2s |

The synthetic tools used in the Ollama benchmark averaged ~83 tokens each (compact schema). Real openstudio-mcp tools average **~204 tokens each** (detailed descriptions + parameter schemas), so the real delta scales to approximately **~29K tokens** — consistent with the live server measurements above.

**gemma3:4b:** baseline only (36 → 20 tokens, no-tools prompt). All tool-bearing requests returned HTTP 400 — `gemma3:4b` does not support tool calling in Ollama's `/api/chat` endpoint. Cannot measure MCP overhead with this model via Ollama.

---

## Measuring Schema Size

To reproduce the schema measurements in this document, run against the live MCP server:

```python
import subprocess, json

cmd = ["docker", "run", "--rm", "-i", "-e", "OPENSTUDIO_MCP_MODE=prod",
       "openstudio-mcp:dev", "openstudio-mcp"]

init_msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
               "clientInfo": {"name": "measure", "version": "1.0"}}}) + "\n"
list_msg = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
    "params": {}}) + "\n"

proc = subprocess.run(cmd, input=(init_msg + list_msg).encode(),
                      capture_output=True, timeout=30)
for line in proc.stdout.decode().split("\n"):
    try:
        obj = json.loads(line)
        if obj.get("id") == 2:
            tools = obj["result"]["tools"]
            schema_json = json.dumps(tools)
            print(f"Tools: {len(tools)}")
            print(f"Full JSON chars: {len(schema_json):,}")
            print(f"Est tokens: {len(schema_json)//4:,}")
            desc_chars = sum(len(t.get("description","")) for t in tools)
            print(f"Descriptions only: {desc_chars:,} chars / ~{desc_chars//4:,} tokens")
    except Exception:
        pass
```

---

## Evaluation Checklist

When comparing client performance against openstudio-mcp, measure:

- [ ] **First tool call latency** — time from prompt to first tool invocation
- [ ] **Schema token overhead** — use the script above; compare to client's token counter
- [ ] **ToolSearch calls per workflow** — how often the model searches before acting
- [ ] **Accuracy at turn 5 vs. turn 20** — does accuracy degrade in long sessions?
- [ ] **Failure mode when context is full** — does the model warn, truncate, or silently fail?
- [ ] **`list_skills` adherence** — does the model follow the skill guide or guess tool params?
- [ ] **Trace latency** — instrument with `TRACELOOP_BASE_URL` + Jaeger to see per-tool call times (see [`docker/docker-compose.tracing.yml`](../../docker/docker-compose.tracing.yml))

See [`docs/testing/advanced-evaluation-template.md`](../testing/advanced-evaluation-template.md) for a full structured evaluation form.
