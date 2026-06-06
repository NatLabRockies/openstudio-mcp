"""Confinement for the measure / simulation subprocesses (Codex-style, tiered).

Everything an applied measure or a simulation runs goes through three subprocess
sites — `apply_measure`, `test_measure`, and the sim dispatcher's `_launch`.
They used to inherit the server's full environment via ``os.environ.copy()``.
This module is the single chokepoint that confines them.

`OSMCP_SANDBOX` (config.SANDBOX_MODE) selects the mode:
  off    — full passthrough (current behaviour / explicit escape hatch)
  posix  — clean-env allowlist (this increment); UID drop + rlimits + Landlock
           FS policy + seccomp net-deny arrive in later increments, same knob
  auto   — best confinement available (currently == posix)

`off` is a true passthrough so an operator can deliberately disable confinement
(the Codex ``danger-full-access`` model); the security PoC suite pins it to prove
the holes still exist when off.

Increment status: clean-env floor (build_env) + UID drop & rlimits (wrap_cmd /
prepare_workdir, via _sandbox_exec). Landlock FS rules + seccomp net-deny land in
_sandbox_exec next. `active_tier()` reports what is in effect so degradation is
visible (never silent).
"""
from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

from mcp_server.config import (
    COMMON_MEASURES_DIR,
    COMSTOCK_MEASURES_DIR,
    INPUT_ROOT,
    SANDBOX_GID,
    SANDBOX_MODE,
    SANDBOX_RLIMIT_AS,
    SANDBOX_RLIMIT_CPU,
    SANDBOX_RLIMIT_FSIZE,
    SANDBOX_RLIMIT_NOFILE,
    SANDBOX_RLIMIT_NPROC,
    SANDBOX_UID,
    SKILLS_DIR,
)

# Read-only roots the confined subprocess legitimately needs (Landlock grants
# read+exec here, nothing else; the run dir is the only writable path). Read-deny
# by default: anything not listed — another user's run, /tmp, arbitrary host
# files — is unreadable. Missing paths are skipped by the Landlock layer.
_FULL_MODES = ("auto", "full", "landlock")
_RO_SYSTEM = ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc",
              "/opt/venv", "/usr/local", "/var/oscli", "/proc", "/sys")

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
})
_ENV_ALLOW_PREFIXES = ("BUNDLE_", "GEM_", "LC_")


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
    """Read-only roots the confined subprocess may read/execute."""
    return [
        *_RO_SYSTEM,
        str(COMSTOCK_MEASURES_DIR), str(COMMON_MEASURES_DIR),
        str(INPUT_ROOT), str(SKILLS_DIR), "/repo",
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


def wrap_cmd(cmd: list[str], work_dir: Path | str) -> list[str]:
    """Wrap a subprocess argv to run under the privilege-dropping exec shim.

    Disabled → returns the command unchanged (today's behaviour). Enabled → runs
    it via `python3 -m mcp_server._sandbox_exec`, which drops to the unprivileged
    sandbox uid, applies rlimits, sets no_new_privs, then execs the command (so
    the pid is preserved and the dispatcher's kill-by-pid path still works).
    Full tier additionally confines the filesystem (Landlock: read-only system
    roots, writable only `work_dir`) and denies outbound IP networking (seccomp).
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
    wrapped = [
        sys.executable, "-m", "mcp_server._sandbox_exec",
        "--uid", str(SANDBOX_UID), "--gid", str(SANDBOX_GID),
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
        for path in _ro_paths():
            wrapped += ["--landlock-ro", path]
        # rw: the run dir, plus /dev for /dev/null & /dev/urandom (node creation
        # there is still barred by DAC for the unprivileged uid).
        for path in (str(work_dir), "/dev"):
            wrapped += ["--landlock-rw", path]
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
    with contextlib.suppress(OSError):
        os.chown(work, SANDBOX_UID, SANDBOX_GID)
    for path in work.rglob("*"):
        with contextlib.suppress(OSError):
            os.chown(path, SANDBOX_UID, SANDBOX_GID)
