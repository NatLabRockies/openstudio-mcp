# Measure-exec sandbox: keep the tools, confine the subprocess

**Status:** researched, proposed · **Supersedes** the deny-tools approach in
`safe-mode-disabled-tools.md` as the primary answer to external-review point 4.
(Denylist stays as an operator opt-out knob, but it removes core functionality —
not a real solution.)

## Decision: follow the Codex CLI model

Adopt OpenAI Codex CLI's architecture as the template (it solves our exact
problem: confine a native subprocess inside a container we don't control), with
one tightening:

- **Landlock for the filesystem** — but **read-deny-by-default** (stricter than
  Codex's read-allow-all). We can enumerate the few dirs `openstudio run` needs,
  so we afford the stronger posture without breaking the happy path.
- **seccomp BPF to block network** — deny `socket(AF_INET/AF_INET6)`, allow
  `AF_UNIX`. This is how Codex blocks net on kernels < 6.7. **Key consequence:
  net-deny works at ANY Landlock ABI (incl. our WSL2 abi3), unprivileged, no
  launch flags** — installing a seccomp filter needs only `no_new_privs` (which
  we already set for Landlock), and `seccomp`/`prctl` are in Docker's default
  allowlist.
- **no_new_privs + setuid drop + rlimits** underneath (the POSIX floor).
- **bwrap** only as an opportunistic upgrade (adds mount/PID/net namespaces)
  where a startup userns probe passes — never the baseline.
- **Degrade loudly** — probe at startup, stamp the active tier into every exec's
  audit line + tool output; `OSMCP_SANDBOX=off` must be explicit and is logged.

Why Codex over Anthropic `sandbox-runtime`: srt's primary primitive is
bwrap/userns — exactly what stock Linux Docker seccomp blocks. Codex's
Landlock+seccomp needs no privileges and no launch flags, so it runs in the
operator's unmodified container. srt's richer egress allowlist (external proxy)
is overkill — we want net-deny, which a seccomp filter gives for free.

**This collapses the tiers**: FS confinement (Landlock) + net-deny (seccomp) +
UID/rlimits (POSIX) all run together in stock Docker ≥23.0 with zero launch
flags. bwrap is a bonus, not a requirement.

## Insight

All arbitrary-code execution already funnels through 3 subprocess sites:

| Site | Location | Cmd | Today |
|---|---|---|---|
| `apply_measure` | `skills/measures/operations.py:248` | `openstudio run --measures_only -w` | timeout 300s, full env, root |
| `test_measure` | `skills/measure_authoring/operations.py:1015` | `pytest` / `ruby` | timeout 60s, full env, root |
| `run_osw`/`run_simulation` | `skills/simulation/operations.py:265` (`_launch`) | `openstudio run -w` | **no timeout**, full env, root |

The subprocess needs: ro on OpenStudio/EnergyPlus install, `/var/oscli` gems,
`/opt/*-measures`, `/inputs`, `/repo`; rw ONLY on its run dir. Nothing else.
That maps 1:1 onto a filesystem sandbox policy. Wrap these 3 sites → full
functionality, contained blast radius.

## Why not the alternatives

- **WASM (pydantic mcp-run-python style):** can't run native EnergyPlus/Ruby. Out.
- **microVMs (E2B/Modal/Firecracker/gVisor):** need host control / KVM; we're a
  process inside someone's container. Host-level gVisor stays a docs recommendation.
- **Static analysis of measure code:** bypassable, not security.
- **NREL OpenStudio-server prior art:** none — zero sandboxing, single-tenant trust
  model. We'd be ahead of upstream.
- **Closest prior art:** OpenAI Codex CLI (Landlock + seccomp, bwrap where possible,
  explicit degrade) and Anthropic sandbox-runtime (bwrap + seccomp + net proxy).

## Design: tiered sandbox, probed at startup, best tier wins

One wrapper at the 3 chokepoints, e.g. `mcp_server/sandbox_exec.py` (or a
`sandboxed_run()` drop-in for `subprocess.run`/`Popen`):

**Tier 0 — POSIX floor (always on):**
- Drop root → dedicated `sandbox` UID via wrapper exec (`setpriv --reuid --regid
  --clear-groups --no-new-privs`) — NOT `preexec_fn` (fork-safety in threaded server)
- Run dirs `0700` sandbox-owned; install/mounts root-owned ro
- rlimits: `RLIMIT_CPU`, `RLIMIT_FSIZE` (caps SQL/ESO blowups), `RLIMIT_NPROC`,
  `RLIMIT_AS` (generous — EnergyPlus legitimately uses GBs), `RLIMIT_NOFILE`
- Clean env: pass explicit allowlist (`PATH`, `RUBYLIB`, `ENERGYPLUS_EXE_PATH`,
  bundler vars, `HOME=<run_dir>`, `TMPDIR=<run_dir>/tmp`) — today
  `os.environ.copy()` leaks everything
- `start_new_session=True` + kill process group on timeout/cancel

**Tier 1 — Landlock LSM (default kernel sandbox):**
- Works inside default-seccomp Docker ≥23.0, unprivileged, zero launch flags —
  the only kernel sandbox with that property (`landlock_*` syscalls allowlisted
  since moby 2022; verified in current default profile)
- Policy: ro+exec `/usr`, `/lib*`, `/usr/local/openstudio-*`, `/var/oscli`,
  `/opt/comstock-measures`, `/opt/common-measures`, `/inputs`, `/repo`;
  rw only `<run_dir>`; requires `prctl(PR_SET_NO_NEW_PRIVS)` first
- Landlock ABI ≥4 (kernel 6.7) can also deny TCP natively; WSL2 dev kernel =
  ABI 3 (FS only, verified). We do NOT rely on this for network — see seccomp.
- Implement: ~100-line ctypes module we own (PyPI `landlock` pkg is 27★/dev
  release; `landrun` CLI is Go binary) — syscall surface is 3 calls

**Tier 1b — seccomp BPF net-deny (rides with Landlock):**
- BPF filter returning `EAFNOSUPPORT` for `socket(AF_INET/AF_INET6)`, allowing
  `AF_UNIX` (so the OpenStudio bundler / local IPC still works). Installed in the
  same wrapper right after `no_new_privs`.
- Works at ANY kernel/ABI in stock Docker — this is our network control, not
  Landlock-abi4 or bwrap. (Codex's exact mechanism.)
- Implement: raw BPF in the wrapper shim, or `pyseccomp`/libseccomp if we accept
  the dep. Lean raw-BPF to stay dep-free and grepable.

**Tier 2 — bubblewrap (opportunistic upgrade):**
- `bwrap --unshare-all --clearenv --die-with-parent` + ro-binds + run-dir bind:
  adds mount-ns illusions + **network-ns (no net even on ABI 3 kernels)**
- Blocked by stock Docker seccomp on Linux hosts (`clone(CLONE_NEWUSER)` denied
  without CAP_SYS_ADMIN; moby#42441 still open). Docker Desktop/WSL2 ships
  seccomp-unconfined → works there today (probed and confirmed in our dev container)
- Enable only when startup userns probe passes; document operator flags
  (custom seccomp profile > `--cap-add SYS_ADMIN`; Ubuntu 24.04 hosts also need
  AppArmor userns relief) for Linux deployments that want tier 2

**Probe at startup, audit one `sandbox_tier` event, and report the active tier
in tool responses** (`"sandbox": "bwrap" | "landlock-abi3" | "posix" | "none"`)
— degradation must be visible, never silent (Codex pattern).

## Orthogonal quick wins (do regardless)

1. `is_path_allowed()` check on `apply_measure(measure_dir=...)` — today accepts
   any path holding a `measure.rb` (other users' runs!)
2. Timeout (or operator-config max walltime) on `run_osw`/`run_simulation` —
   only manual cancel today
3. Clean env allowlist (tier 0 item, but ship first — trivial, closes secret leakage)

## Optional human gate (HITL, not containment)

MCP elicitation: FastMCP `ctx.elicit()` ≥2.10; Claude Code supports it ≥v2.1.76,
Claude Desktop does NOT yet. Pattern: show measure code diff → accept/decline
before exec. Fallback for non-supporting clients: return
`{"needs_approval": true, "code_sha256": ...}` → second call with
`approved_sha256=`. Complements sandbox; doesn't replace it (the LLM writes the
code the human skims). Defer to v2 unless an operator asks.

## Relation to safe-mode denylist

Keep `OSMCP_DISABLED_TOOLS` / `OSMCP_SAFE_MODE` as a small operator knob
(some deployments genuinely want measure-authoring off), but the sandbox is the
primary control: tools stay on by default because their execution is confined.

## Implementation order

1. Quick wins (env allowlist, `measure_dir` path check, sim timeout) — small
   **— DONE (increment 1):** `OSMCP_SANDBOX` knob + `mcp_server/sandbox.py`
   clean-env allowlist wired into all 3 exec sites (`apply_measure`,
   `test_measure`, sim `_launch`); unconditional `is_path_allowed` check on
   `apply_measure(measure_dir=)`; `OSMCP_SIM_TIMEOUT_SECONDS` config added.
   No Docker rebuild (pure Python). Default `off` = passthrough, so the existing
   suite is untouched. Verified: clean-env hides the canary under `posix` and a
   normal run still succeeds; traversal rejected; `test_measures` green.
   **Still pending in this bucket:** wire the sim-timeout *enforcement* into the
   dispatcher (config constant exists; `_launch`/dispatch loop must kill runs
   past the cap via the existing SIGTERM→SIGKILL path).
2. POSIX floor: setuid `sandbox` user + rlimits via `setpriv` wrapper — small/med
   (needs Docker rebuild: `useradd sandbox`). Closes runs-as-root + rlimits.
3. Landlock ctypes module + seccomp net-deny + probe + tier reporting — medium.
   Closes filesystem escape + network exfil.
4. bwrap backend + userns probe + operator docs — medium
5. Elicitation gate — defer
6. Flip default `OSMCP_SANDBOX` off → `auto` once the full suite passes confined.

## Testing strategy

Goal: tests that (a) **prove the holes exist today** without touching anything
real, and (b) **prove each is closed** after the fix. Both halves run in CI.

**Status (confirm-now half landed):** `tests/test_sandbox.py` — 3 integration
tests, CI shard 2, all passing in ~11s. Confirms today (OSMCP_SANDBOX=off):
measures run as root (uid 0), the server's env secret leaks in, reads/writes
escape the run dir, network exfil to a localhost canary succeeds, and
`apply_measure` accepts a `measure_dir` outside all allowed roots. Probes are
generated at runtime via `create_measure` (Ruby + Python) so the real
create→apply path is exercised. The `OSMCP_SANDBOX=auto` "blocked" counterparts
are added with the fix.

### Core principle — dual-run falsifiability

Every security test runs the SAME attack measure twice:
- `OSMCP_SANDBOX=off` → attack must **SUCCEED**. Proves the hole is real today
  AND proves the attack mechanism actually fires. A sandbox test that can't show
  the attack succeeding unsandboxed is vacuous (green for the wrong reason).
- `OSMCP_SANDBOX=auto` (best active tier) → attack must be **BLOCKED**, with the
  violation visible in tool output.

A fix is "proven" only when the off-run breaches and the on-run blocks. The
off-run is the regression guard against vacuous-green.

### Safety — canaries + decoys, never real targets

No test touches a real secret, real sensitive file, or real network:
- **Decoy "victim" run** — fixture creates `runs/_decoy_victim/{run_record.json,
  secret.txt}` (known content), a SIBLING of the granted run_dir → reading/writing
  it from inside the sandbox is a genuine escape, but it sits on the disposable
  runs volume and the fixture deletes it. (cross-user read/write.)
- **Canary env secret** — launch the test server with
  `OSMCP_CANARY_SECRET=do-not-leak-<rand>`. A fake value, never a real credential.
  (the `os.environ.copy()` leak.)
- **Localhost canary listener** — throwaway TCP server on `127.0.0.1:<port>`;
  measure tries to POST the canary to it. Nothing leaves the machine. (net exfil.)
- **Bounded resource probes (critical)** — the off/control run must NEVER run an
  unbounded bomb. Fork test forks a fixed modest N (e.g. 64) and checks they
  succeed → infers "no NPROC cap" without a real fork bomb. Disk test writes a
  fixed small file in the control to confirm "no FSIZE cap" without filling disk.
  CPU/memory controls are SKIPPED (can't bound an unlimited spin/alloc safely);
  on-runs allocate/spin just past the configured cap and assert the cap fires.
  Outer pytest timeout + an outer rlimit on the test process backstop everything.

All attack measures are committed fixtures under `tests/assets/sandbox_probes/`,
run only inside the disposable container.

### How a probe measure reports outcome

Each attack measure attempts the action, rescues the error, and
`runner.registerInfo("PROBE <name> result=<ok|errno>")` — `apply_measure` returns
runner messages, so the test asserts on them. The AUTHORITATIVE check is external
ground truth (decoy file untouched / listener received nothing / recorded euid),
not the measure's self-report. Two independent assertions per test.

### Per-issue test matrix

| # | Issue | Attack measure does | off (today) | on (fixed) | min tier |
|---|---|---|---|---|---|
| 1 | Write escape | `File.write` to decoy sibling dir | write succeeds, decoy modified | EACCES, decoy unchanged | landlock |
| 2 | Read other user's run | `File.read` decoy `secret.txt` | returns known content | EACCES, content absent from output | landlock |
| 3 | Env secret leak | dump ENV to run_dir | canary present | canary absent | posix (clean env) |
| 4 | Runs as root | record `Process.uid` | uid==0 | uid==1001 (sandbox) | posix |
| 5 | Network exfil | TCP connect+POST canary to 127.0.0.1 | listener receives canary | connection refused, nothing received | seccomp |
| 6 | Fork storm | fork N=64 (bounded) | all succeed | blocked past NPROC cap | posix (rlimit) |
| 7 | Disk bomb | write past FSIZE cap in run_dir | (control: small file, no cap) | SIGXFSZ/EFBIG at cap | posix (rlimit) |
| 8 | CPU spin | busy loop | (control skipped) | SIGXCPU at CPU cap | posix (rlimit) |
| 9 | Memory bomb | alloc past AS cap | (control skipped) | ENOMEM at cap | posix (rlimit) |
| 10 | No sim timeout | sleep 60s, cap=5s | (control: outer timeout) | killed ~5s, status failed/timeout | walltime mgr |
| 11 | measure_dir traversal | `apply_measure(measure_dir=<decoy victim>)` | copies/executes | `{ok:false, "not allowed"}` | path check (no exec) |

### Tier-awareness (honest skips, not vacuous passes)

Active tier depends on the runner's kernel/Docker:
- Local WSL2 = landlock-abi3 + seccomp (+ bwrap if userns probe passes on Docker
  Desktop's unconfined daemon).
- CI ubuntu-24.04 = Docker ≥23 / kernel 6.x → landlock-abi4 + seccomp; bwrap
  blocked by default seccomp.

Each test declares its min tier (matrix col). If active tier < needed → **SKIP
with a loud reason** ("net confinement needs seccomp; active=posix"), never
silent-pass. Plus a **guard test**: in the integration env assert active tier ∈
{landlock-abi3, landlock-abi4, bwrap}; FAIL if posix/none — that would mean the
sandbox silently didn't engage and the whole suite is vacuous.

### Tier-probe unit tests

Force each tier path, assert the correct argv is built (setpriv / landlock-shim /
bwrap) and that the probe downgrades correctly when a syscall is stubbed to fail.
Unit tier (no `openstudio` import).

### Repo compliance

- Integration tier (real `openstudio` CLI, mock nothing),
  `RUN_OPENSTUDIO_INTEGRATION=1`, AAA structure, `# Regression:`/`# Validates:`
  comments, exact assertions incl. error-message text, `parametrize` the issue
  set, add to the lightest CI shard.
- New file `tests/test_sandbox.py` + fixtures `tests/assets/sandbox_probes/`.

## Resolved decisions (defaults)

Net effect: works in stock Docker, no launch flags, blast radius = the run dir,
with operator knobs for looser (trusted/BCL) or tighter (cgroup memory) needs.

1. **Min Docker version → don't gate; probe-and-degrade. Document 23.0 as the FS
   line.** seccomp + UID + rlimits work on ~any Docker (those syscalls
   default-allowed for years); only Landlock FS confinement needs ≥23.0. A hard
   minimum would block legit operators for no safety gain — on old Docker you
   lose FS-deny but keep net-deny + UID + rlimits, and the tier report says so.

2. **One shared `sandbox` UID for v1, not per-run ephemeral.** Landlock isolates
   the filesystem *per process* — two runs sharing UID 1001 each get a ruleset
   granting only their own run_dir, so cross-run file access is blocked by
   Landlock, not DAC; the UID barely matters for the main threat. Per-run UIDs
   add a UID pool + chown + cleanup for little gain at `MAX_CONCURRENCY=1`
   (current default). Close the same-UID residual (ptrace/signal between
   concurrent runs) by adding `ptrace` to the seccomp deny list. Shared
   `RLIMIT_NPROC` accounting is a minor co-tenant DoS, irrelevant at concurrency
   1. **Upgrade trigger:** revisit per-run UIDs only if a multi-user deployment
   raises per-user concurrency > 1.

3. **seccomp net-deny via libseccomp (`pyseccomp`), not hand-rolled BPF.**
   Security-critical filter, and we ship **amd64 + arm64** — raw BPF must
   hand-handle `AUDIT_ARCH` + per-arch syscall numbers for both, and a
   subtly-wrong filter fails open. libseccomp is what Docker itself uses,
   abstracts the arch mess, and `libseccomp2` is already in the base image. The
   repo's dep-minimization rule targets heavyweight *unnecessary* deps (the
   OpenLLMetry case), not reimplementing a security primitive across two arches.
   (Raw BPF acceptable ONLY with explicit amd64+arm64 AUDIT_ARCH handling + a
   fail-closed test per arch — not worth it.)

4. **rlimits = generous anti-runaway backstops, operator-tunable env vars; not
   tight quotas.** A tight cap silently breaks real sims (EnergyPlus uses GBs,
   annual SQL is hundreds of MB–GB) — worse than no cap for the modeler.
   - `RLIMIT_AS`: **avoid as primary** — counts virtual address space (mmap'd
     libs), breaks allocators. Unset or ~24 GB backstop; push real memory control
     to container cgroup (`docker run --memory`), document that.
   - `RLIMIT_FSIZE`: ~10 GB per-file runaway guard. Real disk control = retention
     GC + per-run-dir quota (cgroup/quota territory, rlimit can't express).
   - `RLIMIT_NPROC` ~512, `RLIMIT_NOFILE` ~4096, `RLIMIT_CPU` ~2× the existing
     300 s measure timeout.

5. **Sim walltime cap: add `OSMCP_SIM_TIMEOUT_SECONDS`, default 7200 (2 h),
   0 = unlimited.** Real gap today (sims hang forever; manual cancel only). 2 h
   is a hang-catcher, not a tight bound — big annual/parametric runs take
   10–30+ min, so a low default would silently kill legit work. Reuse the
   dispatcher's existing SIGTERM→SIGKILL path (`cancel_run`). Fire loudly:
   status=`timeout`, clear error.

6. **Own ctypes Landlock module, don't vendor `landrun`.** 3 syscalls, ~100
   lines, fully grepable/auditable — matches house style ("everything direct,
   visible in stack traces"). `landrun` is a young (Mar 2025) external Go binary
   = supply-chain dep + vendoring across 2 arches + another thing to track, for
   security-critical code we should own. PyPI `landlock` pkg is dev-release/27★ —
   don't depend on that either. (Per-arch syscall-number care as in #3, but
   Landlock numbers are stable.)

7. **Sandbox `test_measure` too, same wrapper.** pytest/ruby on LLM-authored
   measure code is the same arbitrary-exec threat as `apply_measure` — "test this
   measure" *is* the trust-the-code moment. Its legit needs (own test fixtures,
   test model) live in granted dirs. Caveat: a test that legitimately hits the
   network (BCL download) breaks under net-deny — see #8.

8. **Default net-deny; expose `OSMCP_SANDBOX_NET=deny|allow`; confirm
   empirically.** `openstudio run -w` runs EnergyPlus locally and `--bundle`
   resolves from the offline gem path → should need no AF_INET, so net-deny
   shouldn't break normal runs — **but verify, don't assume** (smoke test: a
   normal sim succeeds under net-deny). The real exception is BCL-downloading
   measures (need AF_INET); blocking them is *correct* for untrusted mode but
   trusted deployments want them — hence the toggle. AF_UNIX always allowed
   (local IPC/bundler).

## Still open (need your input)

- Exact rlimit/timeout default *values* above — sane for your largest real
  models? (chosen as backstops, not measured against a worst-case OSM)
- Container-level memory cgroup: document-only, or ship a recommended
  `--memory` in compose / run docs?
- Per-run-dir disk quota — out of scope for v1, or needed now? (rlimit can't do
  it; needs cgroup/quota)
