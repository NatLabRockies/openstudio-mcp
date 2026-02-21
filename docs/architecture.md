# OpenStudio MCP Server System Diagram

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      USER'S LOCAL MACHINE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────┐       │
│  │               CLAUDE DESKTOP                         │       │
│  │            (MCP Client Host)                         │       │
│  │                                                      │       │
│  │  • User sends queries about OpenStudio models        │       │
│  │  • Claude calls MCP tools (load_osm, run_sim)        │       │
│  │  • Receives tool results from MCP server             │       │
│  └───────────┬──────────────────────────────────────────┘       │
│              │                        │                         │
│              │ stdio/JSON-RPC         │ HTTPS                   │
│              │ (MCP Protocol)         │ (Anthropic API)         │
│              │                        │                         │
│              ▼                        ▼                         │
│  ┌──────────────────────────────────────────────────┐           │
│  │        DOCKER: openstudio-mcp-server             │           │
│  │        ┌───────────────────────────────┐         │           │
│  │        │  MCP Server Process (Python)  │         │           │
│  │        │  • Receives tool calls        │         │           │
│  │        │  • Loads/manipulates models   │         │           │
│  │        │  • Runs EnergyPlus sims       │         │           │
│  │        │  • Returns results as JSON    │         │           │
│  │        └───────────┬───────────────────┘         │           │
│  │                    │                             │           │
│  │                    │ reads/writes                │           │
│  │                    ▼                             │           │
│  │        ┌───────────────────────────────┐         │           │
│  │        │   CONTAINER FILESYSTEM        │         │           │
│  │        │                               │         │           │
│  │        │  /inputs/   ◄──┐ (vol mount)  │         │           │
│  │        │    ├─ *.osm    │ Drop files   │         │           │
│  │        │    └─ *.epw    │              │         │           │
│  │        │                │              │         │           │
│  │        │  /runs/   ◄────┤ (vol mount)  │         │           │
│  │        │    └─ run_xyz/ │ Outputs      │         │           │
│  │        │       ├─ *.osm │              │         │           │
│  │        │       ├─ out.osw              │         │           │
│  │        │       └─ reports/             │         │           │
│  │        │          └─ *.html            │         │           │
│  │        └───────────────────────────────┘         │           │
│  └──────────────┬──────────────┬────────────────────┘           │
│                 │              │                                │
│    Volume Mount │              │ Volume Mount                   │
│                 ▼              ▼                                │
│  ┌────────────────────────────────────────────────┐             │
│  │         LOCAL FILESYSTEM DIRECTORIES           │             │
│  │                                                │             │
│  │  ~/openstudio-mcp/inputs/  ~/openstudio-mcp/   │             │
│  │  ├─ baseline_office.osm         /runs/         │             │
│  │  ├─ weather_chicago.epw    ├─ run_abc123/      │             │
│  │  └─ custom_model.osm       │   ├─ in.osm       │             │
│  │                            │   ├─ out.osw      │             │
│  │         ▲                  │   └─ reports/     │             │
│  │         │                  │     └─ *.html     │             │
│  │         │ User manually    │         ▼         │             │
│  │         │ copies files     │   User downloads  │             │
│  │         │                  │   results         │             │
│  └─────────┴──────────────────┴───────────────────┘             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ HTTPS (Encrypted)
                            │ Claude API Calls
                            │
                            ▼
               ┌────────────────────────────┐
               │    ANTHROPIC CLOUD         │
               │                            │
               │  • Claude AI Model         │
               │  • Processes messages      │
               │  • Decides tool calls      │
               │  • Returns responses       │
               └────────────────────────────┘
```

## Security Analysis

### What Leaves Your Machine (to Anthropic Cloud)

| Transmitted | Description                                                                                  |
| ----------- | -------------------------------------------------------------------------------------------- |
| Yes         | User messages/queries (encrypted HTTPS)                                                      |
| Yes         | MCP tool call results (model summaries, simulation metrics)                                  |
| Yes         | File metadata (paths, sizes) from `list_files` tool                                          |
| Yes         | Simulation output file contents via `read_run_artifact` (text up to 400KB, binary as base64) |
| No          | Raw OSM/EPW files (unless explicitly loaded and queried)                                     |

### Current Development Defaults

The default Docker configuration prioritizes ease of development. The container:

| Default                  | Detail                                                                                        |
| ------------------------ | --------------------------------------------------------------------------------------------- |
| Runs as root             | No `USER` directive in Dockerfile                                                             |
| Has network access       | No `--network none` flag                                                                      |
| Read/write volume mounts | `/inputs` and `/runs` are both writable                                                       |
| Path validation enforced | `is_path_allowed()` restricts access to `/inputs`, `/runs`, `/repo`, `/opt/comstock-measures` |

### Path Traversal Protection (Built-in)

The server validates all file paths at runtime via `config.py`:

- `is_path_allowed()` resolves symlinks and checks against an allowlist
- Rejects paths containing `..` traversal
- Only permits access to `/inputs`, `/runs`, `/repo`, `/opt/comstock-measures`

### Potential Security Concerns

#### MCP tool results are transmitted to Anthropic Cloud

- **Risk:** Could include proprietary building data, energy metrics, or file contents
- **Mitigation:** Review what data tools return before enabling; `read_run_artifact` sends file contents

#### Volume mounts are read/write

- **Risk:** Malicious code could fill disk or corrupt outputs
- **Mitigation:** Disk quotas, read-only `/inputs` mount (see hardening below)

#### EnergyPlus/OpenStudio run user-provided files

- **Risk:** Malicious OSM could exploit vulnerabilities
- **Mitigation:** Container isolation, keep software updated

## Recommended Hardening for Production / Sensitive Environments

The defaults above are fine for local development. For production deployments or when handling sensitive building data, apply these additional restrictions:

### 1. Docker Configuration

```bash
docker run --network none \              # No internet access
           --read-only \                  # Read-only root filesystem
           --tmpfs /tmp \                 # Writable temp space
           -v ~/inputs:/inputs:ro \       # Read-only inputs
           -v ~/runs:/runs \              # Writable outputs only
           --user 1000:1000 \             # Non-root user
           --memory="4g" \                # Memory limit
           --cpus="2" \                   # CPU limit
           openstudio-mcp-server
```

### 2. Data Transmission

- Review tool return values before shipping
- `read_run_artifact` transmits file contents — restrict access if handling sensitive data
- Summarize metrics only (EUI, unmet hours) when possible
- Consider Anthropic's data retention controls

### 3. User Awareness

- User controls what files go in `/inputs`
- User should review what Claude sees in responses
- `read_run_artifact` can return full simulation output files through MCP

## Typical Workflow

### Step 1: User drops files into local /inputs/

User places `baseline_office.osm` into `~/openstudio-mcp/inputs/`

### Step 2: Claude Desktop calls MCP Server

```
User: "Load the baseline office model"
Claude calls: load_osm_model(osm_path="/inputs/baseline_office.osm")
```

### Step 3: MCP Server (inside Docker)

- Reads `/inputs/baseline_office.osm` (mounted volume)
- Loads model into memory using OpenStudio SDK
- Returns: `{"ok": true, "spaces": 10, "zones": 5...}`

### Step 4: Claude Desktop responds to User

```
"I've loaded the baseline office model. It has 5 thermal zones..."
```

### Step 5: User requests simulation

```
User: "Run a simulation with Chicago weather"
Claude calls: run_simulation(osm_path="/inputs/baseline_office.osm",
                             epw_path="/inputs/weather_chicago.epw")
```

### Step 6: MCP Server writes to /runs/

- Creates `/runs/run_xyz123/` directory
- Copies model, weather file
- Executes EnergyPlus simulation
- Writes outputs to `/runs/run_xyz123/`

### Step 7: Results returned through MCP

```
Returns: {"run_id": "xyz123", "status": "completed", "EUI": 45.2}
Claude: "Simulation complete! EUI is 45.2 kBtu/ft²/yr"
```

### Step 8: User accesses local /runs/

User opens `~/openstudio-mcp/runs/run_xyz123/reports/eplustbl.html` for detailed results.

## Key Design Points

- **Container isolation:** MCP server can only access designated mount directories (enforced by path validation)
- **Volume mounts:** Explicit `/inputs` and `/runs` bridge the host-container boundary
- **`list_files` tool:** Helps users discover available files without exposing contents
- **Persistent storage:** `/runs` survives container restarts
- **Claude Desktop is the only component talking to the internet** — the MCP server processes local files and returns results through the MCP protocol
