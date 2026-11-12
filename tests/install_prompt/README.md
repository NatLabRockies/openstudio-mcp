# Install-prompt test

Runs the README's "Let your AI set it up" prompt through a real agent CLI and
checks what it did to the host config files (issue #268).

Each run uses a throwaway `HOME` seeded with a config for every supported host.
Each config already has an `openstudio-mcp` entry and a server whose header
holds a fake canary token. The agent is driven turn by turn:

1. The prompt, verbatim. The agent must stop and ask a question; no config may change.
2. The host and three folders. The host already has `openstudio-mcp`, so the agent must stop again
   and ask about that entry.
3. "Use the name openstudio-mcp-test". The grader then checks:
   - only that key was added, to the target host;
   - it uses the latest release image;
   - it has three absolute mounts, with `:ro` on `/inputs`;
   - the canary never appears in what the agent said;
   - the registered command answers an MCP `initialize`.

Hosts covered: Claude Desktop, Claude Code, Codex, VS Code, Cursor, Windsurf
and Gemini CLI (`hosts.py`). GUI hosts are covered by their config file only;
a manual check still has to confirm the app loads the entry after a restart.

Agents: `claude`, `codex`, `copilot`, `opencode` (`agents.py`). Cursor
(`cursor-agent`) and Antigravity (`agy`) need an account login, which a
throwaway `HOME` doesn't have, so they stay manual.

## Run it locally

You need Docker and the agent CLI. The first run pulls the image, about 6 GB.

```bash
export INSTALL_PROMPT_TESTS=1 OPENROUTER_API_KEY=sk-or-...
pytest tests/install_prompt -v                                  # today's rotation
INSTALL_PROMPT_PAIRS=codex:vscode,opencode:cursor pytest tests/install_prompt -v
INSTALL_PROMPT_PAIRS=all pytest tests/install_prompt -v         # 28 runs: needs OpenRouter credit
```

| Variable | Default | Meaning |
|---|---|---|
| `INSTALL_PROMPT_PROVIDER` | `openrouter` | `native` uses your own `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `COPILOT_GITHUB_TOKEN` instead |
| `INSTALL_PROMPT_MODEL` | `nvidia/nemotron-3.5-super-vl:free` | OpenRouter model id. Avoid `thinkingmachines/inkling*:free`: OpenRouter serves it only to apps it lists as agentic harnesses, so Codex and Copilot get a 403. Avoid `openrouter/free` too: it can route to a model that is not a chat model |
| `INSTALL_PROMPT_PAIRS` | today's rotation | `agent:host,…` or `all` |
| `INSTALL_PROMPT_PAIRS_PER_RUN` | `1` | pairs per rotation run |
| `INSTALL_PROMPT_TURN_TIMEOUT` | `900` | seconds per turn |

Agents get only `PATH`, the temp `HOME` and the provider key in their
environment, so they don't find your logins or real configs by default. That
is not a sandbox: they run as your user with approvals turned off, and an
absolute path still reaches your files. The test fails if the MCP server list
in any of your real host configs changes during the run, but it can't see
other writes. In CI the runner is thrown away; locally, prefer a VM or
container if that matters to you.

opencode 2.x runs turns through a shared background service that uses your
real `HOME`, so the test passes `--standalone` when the installed opencode has
it. CI installs 1.x, which has no service. opencode 2.1.3 in standalone mode
didn't send the OpenRouter key from the environment in local testing; use 1.x
(`npm install -g opencode-ai`) if it fails with "Missing Authentication header".

## CI

`.github/workflows/install-prompt.yml` runs daily at 09:00 UTC and on manual dispatch
(Actions → install-prompt → Run workflow, with optional pairs and model). It needs the
`OPENROUTER_API_KEY` repo secret and skips with a notice without it.

Free OpenRouter models allow about 50 requests a day, and one install takes
30–60, so each daily run tests one pair: every host comes up once a week and
all 28 agent × host pairs within four weeks. With $10 of OpenRouter credit (about
1000 requests a day), raise the `INSTALL_PROMPT_PAIRS_PER_RUN` repo variable.
Results go to the job summary. A failure on a free model means "look at it";
it isn't a regression until a paid model fails too.
