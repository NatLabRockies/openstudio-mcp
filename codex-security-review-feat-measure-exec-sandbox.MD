# Codex Security Review: `feat/measure-exec-sandbox`

Reviewed June 7, 2026.

## Verdict

The branch makes substantial, technically sound improvements over `develop`.
Landlock, seccomp, environment filtering, UID dropping, path checks, symlink
checks, rlimits, and simulation process-group termination materially reduce the
blast radius of authored measures.

It is a good defense-in-depth sandbox for a local or trusted single-container
deployment. It is not yet a sufficient hostile multi-tenant boundary. One
critical post-test sandbox escape remains, and process/resource isolation is
still weaker than a per-job container or microVM.

## Findings

### Critical: sandboxed tests are followed by unsandboxed Ruby execution

After `test_measure_op` runs untrusted tests in the sandbox, it calls
`_update_measure_xml(mdir, language)`. That helper executes:

```text
openstudio measure -u <measure_dir>
```

without `sandbox.build_env()`, `sandbox.prepare_workdir()`, or
`sandbox.wrap_cmd()`.

A sandboxed test has write access to its measure directory. It can replace
`measure.rb` with top-level Ruby code, finish successfully, and rely on the
root MCP process to load that modified file during the XML update. This crosses
the sandbox boundary and restores arbitrary code execution with the server's
authority.

Required fix:

- Never evaluate a file after it has been writable by untrusted code using an
  unsandboxed process.
- Run `openstudio measure -u` through the sandbox.
- Prefer running it on a fresh private copy and copying only validated
  `measure.xml` metadata back.
- Alternatively, update checksums/metadata with a non-executing XML writer.

### High: measure and test timeout handling can leave descendants alive

`apply_measure`, reporting-measure tests, and normal measure tests use
`subprocess.run(..., timeout=...)` without a new session or cgroup. On timeout,
Python terminates the immediate wrapper process, but forked or daemonized
children can survive.

Those descendants retain their inherited Landlock/seccomp policy, but they can
continue consuming CPU, PIDs, memory, and storage. They can also interfere with
other sandbox workers that share UID 1001.

Required fix:

- Start every untrusted execution in a new session/process group.
- On timeout, send TERM and then KILL to the complete process group.
- Prefer a per-job cgroup or container and destroy that unit on completion.

### High: shared UID and PID namespace weaken cross-user isolation

Every worker uses UID 1001 in the same container and PID namespace. `/proc` is
also granted read access. Concurrent jobs can observe process metadata and may
signal same-UID processes. Depending on kernel ptrace policy, they may also
inspect or manipulate peer processes.

The default simulation concurrency of one does not cover concurrent
`apply_measure` or `test_measure` calls.

Required fix:

- Use a separate PID namespace or container for each job.
- At minimum, deny `ptrace`, `process_vm_readv`, `process_vm_writev`, and
  cross-worker signaling where practical.
- Use per-job UIDs if multiple jobs remain in one PID namespace.
- Do not grant the host/container-wide `/proc`; mount a private proc filesystem.

### High: broad `/etc`, `/proc`, and `/sys` read grants expose unnecessary data

The Landlock policy grants all of `/etc`, `/proc`, and `/sys` read access.
Dropped UID permissions block some sensitive files, but world-readable
configuration, process metadata, mounted configuration secrets, kernel details,
and service information remain visible.

Required fix:

- Determine the exact runtime files OpenStudio requires and grant only those.
- Stage required certificates, locale data, timezone data, and configuration
  into a minimal runtime root.
- Use mount/PID namespaces where broad compatibility paths are unavoidable.

### Medium: runtime hardening is not part of the documented default launch

The image adds a sandbox UID, but the long-lived MCP server still runs as root.
The README launch example does not apply `--read-only`, `--cap-drop=ALL`,
`no-new-privileges`, PID/memory/CPU limits, or read-only input mounts.

The subprocess sandbox reduces measure risk, but ordinary MCP server bugs still
execute with root authority inside a container with writable host mounts.

Recommended fix:

- Run the control-plane server as non-root where OpenStudio permits it.
- Make `/inputs`, `/repo`, and `/skills` read-only.
- Apply container resource limits and capability restrictions.
- Keep only a dedicated output/job directory writable.

### Medium: sandbox status is not actually surfaced

`active_tier()` exists but is not included in tool responses or audit events.
It infers the tier from platform/configuration rather than a successful backend
probe. Full mode does fail closed at execution time, which is good, but
operators cannot inspect the effective state before submitting work.

Recommended fix:

- Probe Landlock/seccomp at startup.
- Expose the result in `get_server_status`, audit logs, and every execution
  result.
- Distinguish requested mode from verified active controls.

### Medium: public `run_osw` still copies the entire parent directory

Path and escaping-symlink checks close the arbitrary-host-file issue, but
copying the whole parent directory is still unnecessarily broad. An OSW in a
large allowed directory can copy unrelated data and consume substantial disk.

Recommended fix:

- Parse the OSW and stage only explicitly referenced seed, weather, measure,
  file, and companion resources.
- Reject absolute and parent-traversing references unless separately authorized.
- Apply file-count and byte limits during staging.

### Low: rlimit installation failures do not fail closed

The shim logs an rlimit failure and continues. Landlock and seccomp correctly
fail closed, but resource backstops can silently be absent.

Recommended fix:

- Treat configured mandatory limits as fatal.
- Record applied limits in the execution result.

## Changes That Correctly Address `develop`

- `apply_measure`, reporting-measure tests, normal tests, and simulations now
  pass through a common sandbox wrapper.
- The subprocess environment is explicitly allowlisted instead of inheriting
  server secrets.
- Full mode fails closed if Landlock or seccomp cannot engage.
- Landlock is read-deny-by-default and limits writes to the job directory.
- `/repo` and shared `/inputs` are no longer granted to the confined process.
- `/dev` is reduced to specific device files.
- Seccomp denies IPv4/IPv6 sockets and handles unexpected architectures and x32
  fail-closed.
- `io_uring_setup` is denied to prevent a network-filter bypass.
- The child drops to a validated non-root UID/GID and sets `no_new_privs`.
- Public simulation/OSW paths now use `is_path_allowed()`.
- Escaping symlinks are rejected before staging.
- Shared measures are copied before tests mutate them.
- Simulation wall-clock timeout and process-group cancellation are implemented.
- Ruby interpolation and generated argument identifiers are validated.
- Unknown sandbox modes and non-finite timeout values no longer silently weaken
  policy.
- Security tests use dual-run canaries to prove both the original vulnerability
  and the confined behavior.

## How I Would Design It Differently

For untrusted or remote multi-user use, I would make the process sandbox a
secondary control and use a per-job worker as the primary boundary:

```text
non-root MCP control plane
  -> validated immutable job manifest
  -> trusted runner service
  -> ephemeral worker container using gVisor/runsc
```

Each worker would receive:

- One read-only staged input directory containing only referenced files.
- One private writable output directory.
- No `/repo`, shared `/runs`, `/inputs`, user home, credentials, or Docker
  socket.
- `--network=none`.
- A read-only root filesystem and bounded tmpfs.
- Non-root UID, all capabilities dropped, `no-new-privileges`.
- Dedicated PID, mount, IPC, user, and network namespaces.
- Cgroup limits for memory, CPU, PIDs, I/O, and wall time.
- Automatic destruction on success, failure, cancellation, or timeout.

The control plane would validate and copy back only expected artifacts. It
would never execute generated Ruby or Python after a worker has modified it.

This costs more operationally, but it gives a much clearer security claim:
arbitrary measure code can compromise only an ephemeral worker and its private
job data, not the long-lived MCP process or another user's execution.

## Verification

Focused Windows-compatible tests:

```text
46 passed, 16 skipped, 1 deselected
```

The excluded test directly exercises Linux non-root Landlock behavior and
cannot run on Windows. Docker integration could not be rerun during this review
because access to the local Docker Desktop engine was denied.
