# Codex Security Review: `develop`

Reviewed June 7, 2026.

## Findings

### Critical: Arbitrary measure code runs with the MCP container's authority

Measures and tests execute arbitrary Ruby/Python as the container user, with
the full environment and all container mounts. `apply_measure` invokes
`openstudio` directly with `os.environ.copy()`.

`test_measure` directly runs `pytest` or Ruby. Since the image has no `USER`,
this is probably root inside the container.

### Critical: `run_osw` is also arbitrary-code execution

An OSW can contain measure steps. `run_osw` accepts an unrestricted path,
copies the OSW's entire parent directory, and executes it. It must be sandboxed
exactly like `apply_measure`.

### Critical: Simulation paths bypass the established path policy

`run_simulation` accepts unrestricted OSM and EPW paths. A caller can cause an
arbitrary readable file to be copied into their run directory. This bypasses
the otherwise established `is_path_allowed()` policy.

### Critical: `test_measure` modifies and executes in the source directory

`test_measure` writes `tests/test_model.osm`, runs tests in the caller-provided
measure directory, and updates `measure.xml`. If the directory is under
`/repo`, `/inputs`, or another host mount, untrusted code can modify host files.

### High: Writable bind mounts expose the host filesystem

The documented launch configuration mounts `/inputs` and `/runs` read-write.
Docker bind mounts are host filesystem access; container processes can modify
or delete host files unless the mounts are read-only.

### High: The container lacks basic runtime hardening

The container has no non-root `USER`, read-only root filesystem, capability
drop, `no-new-privileges`, network restriction, PID limit, or memory/CPU limit.

### High: Documentation describes sandbox controls absent from `develop`

The sandbox plan claims several protections are complete, but the referenced
`sandbox.py`, Landlock, seccomp, and execution shim are absent from the
`develop` checkout. This creates dangerous false assurance.

### Medium: Process lifecycle controls are incomplete

Simulations have no enforced wall-clock timeout and cancellation kills only
the recorded parent PID, not the complete process group or cgroup.

### Medium: Generated Ruby strings permit interpolation

Ruby string generation does not escape `#{...}` interpolation. Metadata fields
could execute expressions when `openstudio measure -u` evaluates the generated
measure.

## Recommended Architecture

Do not run untrusted code as a subprocess inside the long-lived MCP container.
Use two components:

```text
MCP control plane
  |
  | job manifest + staged files
  v
Job runner/orchestrator
  |
  v
Ephemeral sandbox worker
  - one job only
  - input mount read-only
  - private output mount read-write
  - no /repo, shared /runs, /inputs, home, or Docker socket
  - no network
  - destroyed after completion
```

The MCP server should:

1. Validate requested paths.
2. Copy only explicitly referenced OSM, EPW, measure, and OSW files into a
   private job input directory.
3. Submit an immutable job manifest containing hashes and limits.
4. Receive only approved result artifacts.
5. Never receive the Docker socket. A separate trusted runner should create
   worker containers.

The worker should use controls equivalent to:

```text
--runtime=runsc
--network=none
--read-only
--user=10001:10001
--cap-drop=ALL
--security-opt=no-new-privileges=true
--pids-limit=256
--memory=<appropriate limit>
--cpus=<appropriate limit>
--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=...
input:/job/input:ro
output:/job/output:rw
```

Also use the default or tighter seccomp profile, AppArmor/SELinux policy, a
hard wall timeout, storage quotas, and kill the entire worker container on
cancellation.

## Tool Policy

- `run_simulation`: sandboxed worker, with an internally generated OSW
  containing no measure steps.
- `run_osw`: sandboxed worker; disabled by default for remote users or reject
  measure steps unless explicitly authorized.
- `apply_measure`: sandboxed worker.
- `test_measure`: sandboxed worker operating on a staged copy.
- `openstudio measure -u`: sandboxed worker because it loads measure code.
- Syntax checks: sandboxed too. Tests and imports can execute code through
  plugins and startup behavior.

Measure authoring itself can remain in the control plane if it only writes text
into a private user directory. Any evaluation of that text must leave the
control plane.

## Deployment Priority

1. Immediately mount `/inputs` and `/repo` read-only; mount only a dedicated
   output directory read-write.
2. Run the MCP image as non-root and add Docker resource/security flags.
3. Disable `run_osw`, `apply_measure`, and `test_measure` in remote deployments
   until isolated execution exists.
4. Add `is_path_allowed()` checks to every simulation and measure path.
5. Stage inputs into private job directories and reject symlinks and escaping
   OSW references.
6. Implement ephemeral worker containers.
7. Use gVisor `runsc` for untrusted multi-user workloads; use microVMs if the
   threat model includes determined hostile tenants.
8. Add attack tests proving filesystem escape, environment leakage, network
   access, fork exhaustion, and cross-user access succeed without the sandbox
   and fail with it.

Rootless Docker or user-namespace remapping reduces host impact, but neither
replaces per-job isolation. Static measure scanning and human approval are
useful secondary controls, not containment.

## Sources

- [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)
- [Docker container security options](https://docs.docker.com/reference/cli/docker/container/run)
- [Docker seccomp](https://docs.docker.com/engine/security/seccomp/)
- [Docker rootless mode](https://docs.docker.com/engine/security/rootless/)
- [gVisor](https://gvisor.dev/docs/)
- [gVisor with Docker](https://gvisor.dev/docs/user_guide/quick_start/docker/)
