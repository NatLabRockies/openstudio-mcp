"""Confinement for the measure / simulation subprocesses (Codex-style, tiered).

Everything an applied measure or a simulation runs goes through three subprocess
sites — `apply_measure`, `test_measure`, and the sim dispatcher's `_launch`.
They used to inherit the server's full environment via ``os.environ.copy()``.
This module is the single chokepoint that confines them.

`OSMCP_SANDBOX` (config.SANDBOX_MODE) selects the mode (default `auto`):
  off    — full passthrough (explicit escape hatch for trusted/local-tooling use)
  posix  — clean-env allowlist + UID drop (when root) + rlimits
  auto   — best available: posix + Landlock FS policy + seccomp net-deny (Linux)

`off` is a true passthrough so an operator can deliberately disable confinement
(the Codex ``danger-full-access`` model); the security PoC suite pins it to prove
the holes still exist when off.

The unprivileged layers (clean-env, Landlock, seccomp, rlimits) apply even when
the server runs non-root; only the UID drop is root-gated and skipped otherwise.
`OSMCP_SANDBOX_NET=allow` opts out of the network deny. On a platform with no
kernel backend (macOS/Windows bare installs) `wrap_cmd` degrades to clean-env
only and warns once. `active_tier()` reports what is actually in effect so
degradation is visible (never silent).
"""
from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

from mcp_server.config import (
    COMMON_MEASURES_DIR,
    COMSTOCK_MEASURES_DIR,
    SANDBOX_MODE,
    SANDBOX_NET,
    SANDBOX_RLIMIT_AS,
    SANDBOX_RLIMIT_CPU,
    SANDBOX_RLIMIT_FSIZE,
    SANDBOX_RLIMIT_NOFILE,
    SANDBOX_RLIMIT_NPROC,
    SKILLS_DIR,
    sandbox_ids,
)

# Read-only roots the confined subprocess legitimately needs (Landlock grants
# read+exec here, nothing else; the run dir is the only writable path). Read-deny
# by default: anything not listed — another user's run, /tmp, arbitrary host
# files — is unreadable. Missing paths are skipped by the Landlock layer.
_FULL_MODES = ("auto", "full", "landlock")
# /proc is deliberately NOT granted (H1): with /proc readable a confined measure
# could read /proc/<pid>/environ and, on a non-root server (measure uid == server
# uid), recover the server's secrets that clean-env stripped — including HTTP auth
# tokens — and inspect peer tenants' processes. OpenStudio/EnergyPlus run without
# it. /sys/<...> hardware info stays (no secrets; some libs read CPU topology).
_RO_SYSTEM = ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc",
              "/opt/venv", "/usr/local", "/var/oscli", "/sys")

# Specific device files the confined process needs — granted individually instead
# of the whole /dev directory. A `/dev` rw grant also exposes writable /dev/shm and
# /dev/mqueue (shared storage / IPC outside the run dir) and permits mknod. These
# are file-level Landlock rules, so only the file-access bits apply — no directory
# powers. Read-write: the bit-bucket + zero source; read-only: the entropy sources.
_DEV_RW = ("/dev/null", "/dev/zero")
_DEV_RO = ("/dev/urandom", "/dev/random")

_warned_no_backend = False  # one-shot log when no kernel backend (non-Linux)

# Environment the OpenStudio CLI / bundler / EnergyPlus / measure code legitimately
# needs. Everything else — notably any host secret — is dropped in confined modes.
_ENV_ALLOW_EXACT = frozenset({
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TZ", "TERM", "RUBYOPT",
    "RUBYLIB", "RUBY_VERSION", "ENERGYPLUS_EXE_PATH",
    "OS_BUNDLER_VERSION", "RC_RELEASE",
    "VENV_PATH", "PYTHONUNBUFFERED",
    "COMSTOCK_MEASURES_DIR", "COMMON_MEASURES_DIR", "SKILLS_DIR",
    "OSCLI_GEMFILE", "OSCLI_GEM_PATH",
    "OSMCP_RUN_ROOT", "OPENSTUDIO_MCP_RUN_ROOT",
    # Bundler / RubyGems config — EXPLICIT safe names only. A broad BUNDLE_/GEM_
    # prefix would leak credential vars (e.g. GEM_HOST_API_KEY, or per-host
    # BUNDLE_<HOST>__<COM> auth tokens) into untrusted measure code.
    "BUNDLE_WITHOUT", "BUNDLE_PATH", "BUNDLE_GEMFILE", "BUNDLE_FROZEN",
    "BUNDLE_DEPLOYMENT", "GEM_HOME", "GEM_PATH",
    # Standard POSIX locale categories ONLY — enumerated, never prefix-matched: a
    # bare LC_ prefix would also copy a host secret named e.g. LC_API_TOKEN.
    "LC_CTYPE", "LC_NUMERIC", "LC_TIME", "LC_COLLATE", "LC_MONETARY",
    "LC_MESSAGES", "LC_PAPER", "LC_NAME", "LC_ADDRESS", "LC_TELEPHONE",
    "LC_MEASUREMENT", "LC_IDENTIFICATION",
})
_ENV_ALLOW_PREFIXES: tuple[str, ...] = ()  # no prefix matching — exact names only


def enabled() -> bool:
    """True when any confinement is active (i.e. OSMCP_SANDBOX is not 'off')."""
    return SANDBOX_MODE not in ("", "off", "0", "false", "no")


def _full() -> bool:
    """True when the full tier (Landlock FS + seccomp net-deny) is requested."""
    return SANDBOX_MODE in _FULL_MODES


def _has_backend() -> bool:
    """True where the kernel confinement shim can run (Landlock/seccomp = Linux)."""
    return sys.platform.startswith("linux")


def active_tier() -> str:
    """The confinement tier actually in effect — surfaced in tool output."""
    if not enabled():
        return "off"
    if not _has_backend():
        return "clean-env"  # env stripping only; no kernel backend on this platform
    return "landlock" if _full() else "posix"


def _ro_paths() -> list[str]:
    """Read-only roots the confined subprocess may read/execute.

    /repo is deliberately NOT granted: the measure runs from the copied run dir,
    and the shim imports mcp_server before applying Landlock — so the run never
    needs to read the source tree (which could hold a host .env).

    INPUT_ROOT (/inputs) is deliberately NOT granted either: it is a SHARED,
    multi-tenant dir, so granting it would let one tenant's confined measure read
    another's inputs. Inputs are staged into the run dir before execution, so the
    confined process reads the staged copy, never /inputs directly.

    The broad system roots (/etc, /proc, /sys) are intentional and DAC-mitigated:
    OpenStudio/Ruby/EnergyPlus need bits of each (certs, nsswitch, /proc/self,
    cpuinfo), and the uid-1001 drop means the kernel already blocks reads of
    non-world-readable secrets (/etc/shadow) and other users' /proc/<pid>/environ.
    Landlock here is defense-in-depth on top of DAC, not the only barrier.
    """
    return [
        *_RO_SYSTEM,
        str(COMSTOCK_MEASURES_DIR), str(COMMON_MEASURES_DIR),
        str(SKILLS_DIR),
    ]


def build_env(work_dir: Path | str, *, redirect_tmp: bool = True) -> dict[str, str]:
    """Environment for a confined subprocess.

    Disabled → full passthrough (``os.environ.copy()``), preserving today's
    behaviour. Enabled → only allowlisted variables survive, so no host secret
    reaches measure code.

    redirect_tmp (default) pins HOME/TMPDIR into work_dir/tmp, keeping temp +
    caches inside the run dir so the Landlock backend (which makes only that dir
    writable) permits them. Pass redirect_tmp=False for the non-Landlocked
    test_measure path: pytest's capture uses an unlinked tempfile, which the
    Docker-Desktop bind mount can't keep open — so it must stay on /tmp.
    """
    if not enabled():
        return os.environ.copy()
    env = {
        k: v for k, v in os.environ.items()
        if k in _ENV_ALLOW_EXACT or k.startswith(_ENV_ALLOW_PREFIXES)
    }
    if redirect_tmp:
        work = Path(work_dir)
        env["HOME"] = str(work)
        tmp = work / "tmp"
        try:
            tmp.mkdir(parents=True, exist_ok=True)
            env["TMPDIR"] = str(tmp)
        except OSError:
            pass
    return env


def wrap_cmd(cmd: list[str], work_dir: Path | str,
             extra_rw: tuple[str, ...] = ()) -> list[str]:
    """Wrap a subprocess argv to run under the privilege-dropping exec shim.

    Disabled → returns the command unchanged (today's behaviour). Enabled → runs
    it via `python3 -m mcp_server._sandbox_exec`, which drops to the unprivileged
    sandbox uid (when root), applies rlimits, sets no_new_privs, then execs the
    command (the pid is preserved so the dispatcher's kill-by-pid path still
    works). Full tier additionally confines the filesystem (Landlock: read-only
    system roots, writable only `work_dir` + `extra_rw`) and — unless
    OSMCP_SANDBOX_NET=allow — denies outbound IP networking (seccomp).

    extra_rw: additional writable Landlock roots (e.g. a private TMPDIR off the
    bind mount for tools that need unlinked tempfiles).
    """
    if not enabled():
        return list(cmd)
    if not _has_backend():
        # macOS/Windows bare installs: no kernel sandbox shim. Run unwrapped
        # (clean-env from build_env still strips secrets); warn once.
        global _warned_no_backend
        if not _warned_no_backend:
            print(f"[sandbox] no kernel confinement backend on {sys.platform}; "
                  "running unwrapped (clean-env only) — use the Docker image for "
                  "full FS/network confinement", file=sys.stderr)
            _warned_no_backend = True
        return list(cmd)
    # Per-tenant uid/gid: each remote caller drops to its own uid (private NPROC
    # budget + DAC isolation); the local single user keeps the base uid. Resolved
    # here so it matches the chown prepare_workdir does for the same request.
    uid, gid = sandbox_ids()
    wrapped = [
        sys.executable, "-m", "mcp_server._sandbox_exec",
        "--uid", str(uid), "--gid", str(gid),
    ]
    for flag, value in (
        ("--rlimit-fsize", SANDBOX_RLIMIT_FSIZE),
        ("--rlimit-nproc", SANDBOX_RLIMIT_NPROC),
        ("--rlimit-nofile", SANDBOX_RLIMIT_NOFILE),
        ("--rlimit-cpu", SANDBOX_RLIMIT_CPU),
        ("--rlimit-as", SANDBOX_RLIMIT_AS),
    ):
        if value and value > 0:
            wrapped += [flag, str(value)]
    if _full():
        for path in (*_ro_paths(), *_DEV_RO):
            wrapped += ["--landlock-ro", path]
        # rw: the run dir (+ caller extras) + the writable device FILES only — NOT
        # the whole /dev dir (which would also expose writable /dev/shm, /dev/mqueue
        # and permit mknod). See _DEV_RW / _DEV_RO above.
        for path in (str(work_dir), *_DEV_RW, *extra_rw):
            wrapped += ["--landlock-rw", path]
        # Network deny is the default; OSMCP_SANDBOX_NET=allow opts out (trusted
        # deployments that legitimately fetch e.g. BCL components).
        if SANDBOX_NET != "allow":
            wrapped += ["--seccomp-net"]
    return [*wrapped, "--", *cmd]


def prepare_workdir(work_dir: Path | str) -> None:
    """Hand the work dir to the sandbox account so the dropped process can write.

    No-op when confinement is off. The server is root, so it chowns the run dir
    (recursively) to the sandbox uid before exec; the root server still reads the
    outputs afterwards. Bind mounts that ignore ownership (e.g. Docker Desktop)
    make this a harmless no-op there — confinement still holds for in-image paths.
    """
    # Only the root server needs to hand the dir to the sandbox uid; when not root
    # the shim keeps the current uid, which already owns the dir it created.
    if not enabled() or not (hasattr(os, "geteuid") and os.geteuid() == 0):
        return
    work = Path(work_dir)
    # Per-tenant uid/gid (matches the shim's setuid for this same request) so the
    # dropped process owns its run dir and tenants are DAC-isolated from each other.
    uid, gid = sandbox_ids()
    # follow_symlinks=False (lchown): never let a symlink inside the dir redirect
    # the chown to a target outside it (symlink-traversal privilege issue).
    with contextlib.suppress(OSError):
        os.chown(work, uid, gid, follow_symlinks=False)
    for path in work.rglob("*"):
        with contextlib.suppress(OSError):
            os.chown(path, uid, gid, follow_symlinks=False)
