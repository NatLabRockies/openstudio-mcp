# Research: MCP Tool Discovery at Scale

Source thread: https://www.reddit.com/r/mcp/comments/1r0egn7/how_do_you_handle_discovery_when_you_have_dozens/
Fetched: 2026-04-05 | Score: 8 (91% upvote) | 24 comments | r/mcp (103K subscribers)

---

## Original Post (u/Sea-Perception1619)

> As MCP adoption grows, I keep running into the same question: how does a client find the right server when there are many of them?
>
> Right now it seems like most setups hardcode server connections in the client config. That works with 3-5 servers but what happens when you have 30? Or when servers are maintained by different teams? Or when you want an agent to dynamically discover which MCP server has the tool it needs?
>
> How are you all handling this? Is anyone building a discovery layer on top of MCP, or is the expectation that clients just know their servers upfront?

---

## All Comments (verbatim, organized by thread)

### 1. u/owlpellet (score: 2)
> ["Tool Search Tool"](https://www.anthropic.com/engineering/advanced-tool-use) pattern, or [dynamic tool discovery](https://spring.io/blog/2025/12/11/spring-ai-tool-search-tools-tzolov), reduces token bloat and improves outcomes by using user-scenario clues to choose which tools to expose to an LLM.

### 2. u/ParamedicAble225 (score: 3)
> The same way you handle one mcp server that has 100s of tools: MODES! And depending on the mode, the AI system instructions, available tools, and goals change. Then have an orchestrator LLM that commands all of the MODED AI's around and uses them as needed. Modularity.

### 3. u/Loose_Rip359 (score: 3)
> Claude Code handles this with a deferred tool pattern -- tools aren't loaded into context until the agent runs a semantic search against a tool registry. Keeps token usage low and avoids overwhelming the model with 100+ tool definitions upfront. Works well in practice once you have good tool descriptions. The key insight is treating discovery as a tool itself.

### 4. u/Raplaplaf (score: 1) -- Registry + Trust Layer

> The issue is real, I started working on a registry after asking myself the same question and did some research beforehand:
> - registry.modelcontextprotocol.io -- pretty raw (no KYC, no quality assessment, no privacy/security management)
> - Kong MCP Registry -- very enterprise oriented and proprietary
> - Google Cloud API Registry -- well, it's Google
>
> What I found missing across all of them is a trust layer -- not just "which servers exist" but "which ones can I actually trust with my data and which one is the best choice (quality and token wise) for a given task (or subtask)." So I've been combining the registry work with a data handling spec (ADHP) that lets servers declare their privacy practices.
>
> - registry: https://github.com/StevenJohnson998/agent-registry
> - adhp: https://github.com/StevenJohnson998/agent-data-handling-policy

**Reply chain:**

- **u/Sea-Perception1619 (OP):** Trust gap is the core issue. Static registries solve "what exists" but not "what should I trust" or "what's best for this specific task." Asks: once trust requirements pass, how route to the *best* server dynamically based on performance, load, and capability match?

- **u/Raplaplaf:** Long-term vision is dedicated agents that learn to direct swarms of LLM/Agents, using all those bricks autonomously to achieve the best result for minimal cost within acceptable security/privacy.

- **u/Sea-Perception1619 (OP):** Claims to be building exactly that -- routing protocol with independent scoring functions at each node, adaptive parallel search when confidence is low. Working in simulation at 500 nodes, 97% discovery availability, sub-200ms latency. Says ADHP could be the policy filter layer, manifest schema the capability description format.

- **u/Raplaplaf:** "Let's make sci-fi a reality. :)"

### 5. u/GentoroAI (score: 1) -- Gateway Pattern

> Hardcoding breaks fast. The pattern I'm seeing is a registry/gateway: clients connect to one MCP endpoint, and the gateway owns the server list, auth, health checks, versioning, and a searchable tool catalog. If you want dynamic discovery, do it there (semantic routing over tool metadata), not in every client.
>
> OneMCP: https://github.com/Gentoro-OneMCP/onemcp

**Reply chain:**

- **u/Sea-Perception1619 (OP):** Gateway works when one team owns the stack. What about cross-org? Company A's procurement agent discovers Company B's invoicing agent, neither wants to register in the other's gateway. Who runs the shared gateway?

- **u/owlpellet:** "I believe Agent2Agent is intended to address the public listing case."

- **u/GentoroAI:** Proposes federation -- each company runs its own gateway/registry, publishes signed "service descriptors" into a neutral directory (DNS-style). Discovery via directory, traffic/auth stays end-to-end (mTLS/OIDC, partner-scoped creds, allowlisted egress).

### 6. u/BC_MARO (score: 1) -- 20+ Server Operator

> Running 20+ MCP servers right now and the config management alone is painful. What worked for me was grouping servers by domain (data, code, infra) and having a thin proxy that exposes a unified tool list. The proxy handles health checks and failover so the client just sees one endpoint.
>
> The registry problem is real though. Right now there's no standard way for a client to ask "who can do X?" at runtime. Closest thing I've seen is tool-level semantic search over descriptions, but that falls apart when servers have overlapping capabilities.

**Reply chain:**

- **u/Sea-Perception1619 (OP):** Overlapping capabilities is the interesting problem. Semantic search gives ranked list, but when 3 servers score similarly, how do you pick? Describes routing approach: independent scoring functions evaluate candidates on axes (past success rate, load, novelty, reliability). When they agree -> top pick. When they disagree -> parallel-query multiple candidates, let results compete. Disagreement = signal for more exploration.

- **u/BC_MARO:** Currently first-healthy + manual pinning. Likes disagreement-as-signal. Asks: how to measure "quality" automatically? Structured outputs are straightforward (schema validation), but freeform is fuzzy.

- **u/Sea-Perception1619 (OP):** Quality measurement approach: let the *caller* decide. After discovery+invocation, caller reports success/failure. Over time that feedback shifts routing. Not evaluating output quality directly -- tracking *outcome quality* from caller perspective. For freeform, caller-reported outcomes "get you surprisingly far if you have enough query volume." Building an SDK around this pattern.

- **u/BC_MARO:** "Yeah I'd be down to try it. The caller-reported feedback loop is practical since you skip the LLM-as-judge overhead entirely."

### 7. u/beycom99 (score: 1) -- OneTool

> Give OneTool a try. It is my solution to this problem.
> - https://onetool.beycom.online/
> - https://onetool.beycom.online/about/about-onetool/

### 8. u/xrxie (score: 1) -- ToolIQ Gateway

> The MCP gateway we use has a clever tool discovery service. We can still connect to individual MCP servers, but have option of configuring agents to point to a single MCP server that sits in front of a group of MCP servers with tools for searching, describing, and executing the tools. This alone trims down the context window considerably. Combined with custom MD files context can be even sharper.
>
> https://barndoor.ai/introducing-tooliq-mcp-tool-optimization/

### 9. u/dinkinflika0 (score: 1) -- Bifrost Gateway

> We solve this in Bifrost -- gateway acts as discovery layer. Connect all MCP servers once, clients talk to gateway. It routes tool calls to the right server automatically. Also lets you filter which tools are available per agent using virtual keys.
>
> Docs: https://getmax.im/bifrostdocs

### 10. u/makinggrace (score: 1) -- Pragmatic Multi-Layer Approach

> Don't duplicate coverage of capabilities. Prune so you have the best tool for a specific task.
>
> Right now using a single gateway (fastmcp) and the profiles feature released in the 3.0 beta per client but I may try to change that up to per agent type.
>
> Usually I build MCP usage into skills and call the skill. This works the best for coding.
>
> More generally agents get list_tools to choose from the most commonly used tools in the client's profile. It also returns something like "use more_tools for more tools." (This prompt was hell to get right and I still am annoyed that I can't make it work in one call.)
>
> more_tools calls the toolmaster. That's literally a llm call to google genai who matches the request to a markdown file of every other mcp I have available with keywords and use cases. (Having a frontier model write this and not me made it work flawlessly.)
>
> In my own clients that hot swaps MCPs, the toolmaster also enables and disables MCP availability when it recommends a tool. Failure to do that in any commercial client thus far sadly.
>
> Tl;dr consider using a tiny llm call to manage the mcps that are infrequently used.

---

## Approaches/Solutions Summary

| Approach | Who | How it works |
|----------|-----|-------------|
| **Deferred/Tool Search** | Claude Code, Anthropic | Tools not loaded until agent semantic-searches a registry. 85% context reduction. |
| **Modes + Orchestrator** | u/ParamedicAble225 | Define modes with different tool subsets; orchestrator LLM selects mode per task. |
| **Gateway/Proxy** | u/GentoroAI (OneMCP), u/dinkinflika0 (Bifrost), u/xrxie (ToolIQ), u/BC_MARO | Single endpoint fronts all servers; gateway owns routing, health, auth, catalog. |
| **Registry + Trust Layer** | u/Raplaplaf | Registry with ADHP (Agent Data Handling Policy) for servers to declare privacy practices. |
| **Federation** | u/GentoroAI | Cross-org: each company runs own gateway, publishes signed service descriptors to neutral DNS-style directory. |
| **Two-tier discovery** | u/makinggrace | Common tools in initial list_tools; "more_tools" triggers LLM call to match request against full catalog markdown. Hot-swaps MCP availability. |
| **Capability routing + feedback** | u/Sea-Perception1619 (OP) | Independent scoring functions evaluate candidates; disagreement triggers parallel query; caller-reported outcomes improve routing over time. |
| **Semantic vector retrieval** | arxiv:2603.20313 | Dense embeddings index tools; retrieve top 3-5 per query. 99.6% token reduction, 97.1% hit@3, sub-100ms. |
| **Prune + deduplicate** | u/makinggrace | Don't duplicate capabilities across servers. Best tool for each task, period. |

---

## Tools, Libraries, and Projects Mentioned

| Name | URL | Description |
|------|-----|-------------|
| **Anthropic Tool Search** | https://www.anthropic.com/engineering/advanced-tool-use | Deferred tool loading + semantic search in Claude Code |
| **Spring AI Tool Search** | https://spring.io/blog/2025/12/11/spring-ai-tool-search-tools-tzolov | Dynamic tool discovery for Spring AI |
| **Agent Registry** | https://github.com/StevenJohnson998/agent-registry | MCP server registry with trust layer |
| **ADHP** | https://github.com/StevenJohnson998/agent-data-handling-policy | Agent Data Handling Policy spec |
| **OneMCP** | https://github.com/Gentoro-OneMCP/onemcp | Single runtime boundary + dynamic tool selection |
| **OneTool** | https://onetool.beycom.online/ | Tool aggregation/discovery solution |
| **ToolIQ (Barndoor)** | https://barndoor.ai/introducing-tooliq-mcp-tool-optimization/ | MCP gateway with tool discovery service |
| **Bifrost** | https://getmax.im/bifrostdocs | MCP gateway with virtual key filtering per agent |
| **FastMCP** | (profiles feature in 3.0 beta) | Gateway with per-client profiles |
| **Agent2Agent** | (Google, mentioned by u/owlpellet) | Cross-org agent discovery protocol |
| **MCP Hierarchical Mgmt** | https://github.com/orgs/modelcontextprotocol/discussions/532 | Proposal: categories, lazy loading, dynamic registration |
| **Semantic Tool Discovery** | https://arxiv.org/abs/2603.20313 | Academic paper: vector-based MCP tool selection |
| **RAG-MCP** | https://writer.com/engineering/rag-mcp/ | Writer.com: semantic retrieval for tool selection |
| **MCPX (Lunar)** | https://www.lunar.dev/post/why-dynamic-tool-discovery-solves-the-context-management-problem | Tool Groups + policy gating + auto-refresh |
| **Cloudflare Code Mode** | (mentioned in agentpmt.com) | Compresses 2500+ endpoints into 2 tools (~1K tokens) |
| **ToolHive MCP Optimizer** | (Stacklok, mentioned in agentpmt.com) | Dynamic toolset optimization |
| **Speakeasy** | (mentioned in agentpmt.com) | Up to 160x token reduction, 100% success 40-400 tools |

---

## Key Numbers from Broader Research

| Metric | Value | Source |
|--------|-------|--------|
| Token cost per tool definition | ~400-500 tokens | MCP Discussion #532 |
| 50 tools upfront context cost | ~20-25K tokens | MCP Discussion #532 |
| 5-server setup (GitHub+Slack+Sentry+Grafana+Splunk) | ~55K tokens | agentpmt.com |
| GitHub MCP server alone | ~46K tokens (91 tools) | atcyrus.com |
| Tool Search context reduction | 85% (77K -> 8.7K) | Anthropic |
| Tool Search accuracy improvement | Opus 4: 49%->74%, Opus 4.5: 79.5%->88.1% | Anthropic |
| Semantic vector retrieval hit rate | 97.1% at K=3, 0.91 MRR | arxiv:2603.20313 |
| Semantic vector token reduction | 99.6% | arxiv:2603.20313 |
| Selection accuracy degradation threshold | >30-50 tools visible | Multiple sources |
| Auto-activation threshold (Claude Code) | >10K tokens in tool descriptions | Anthropic |
| Cloudflare compression | 2500+ endpoints -> 2 tools (~1K tokens) | agentpmt.com |
| Speakeasy reduction | up to 160x | agentpmt.com |

---

## Relevance to openstudio-mcp (142 tools)

Our server has 142 tools -- well past the 30-50 tool accuracy degradation threshold. At ~400 tokens/tool, that is ~57K tokens of tool definitions. Key takeaways:

1. **Claude Code's deferred loading already helps us** -- our tools are auto-deferred when >10K token threshold is hit. The question is whether our tool *descriptions* are good enough for semantic search to find the right tool.

2. **Two-tier discovery (u/makinggrace) maps to our skills system** -- `list_skills()` and `get_skill()` are the "common tools" tier; the full 142 tools are the "more_tools" tier.

3. **Pruning overlapping capabilities matters** -- we should audit for tools that overlap (e.g., `set_weather_file` vs `change_building_location`) and either consolidate or make descriptions disambiguate clearly.

4. **Modes/profiles could help** -- grouping tools by workflow phase (geometry, HVAC, simulation, results) so the agent context only loads the relevant subset.

5. **Tool naming is critical for search** -- names like `github_create_issue` beat `create`. Our `_tool` suffix convention + MCP-visible names should be keyword-rich and searchable.
