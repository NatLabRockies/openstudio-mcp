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
    SANDBOX_GID,
    SANDBOX_MODE,
    SANDBOX_RLIMIT_AS,
    SANDBOX_RLIMIT_CPU,
    SANDBOX_RLIMIT_FSIZE,
    SANDBOX_RLIMIT_NOFILE,
    SANDBOX_RLIMIT_NPROC,
    SANDBOX_UID,
)

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


def active_tier() -> str:
    """The confinement tier actually in effect — surfaced in tool output."""
    if not enabled():
        return "off"
    return "posix"  # later increments: "landlock" / "bwrap"


def build_env(work_dir: Path | str) -> dict[str, str]:
    """Environment for a confined subprocess.

    Disabled → full passthrough (``os.environ.copy()``), preserving today's
    behaviour. Enabled → only allowlisted variables survive and HOME/TMPDIR are
    pinned into the work dir, so no host secret reaches measure code and caches
    stay inside the run directory (which the FS backend will later confine).
    """
    if not enabled():
        return os.environ.copy()
    work = Path(work_dir)
    env = {
        k: v for k, v in os.environ.items()
        if k in _ENV_ALLOW_EXACT or k.startswith(_ENV_ALLOW_PREFIXES)
    }
    env["HOME"] = str(work)
    tmp = work / "tmp"
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(tmp)
    except OSError:
        pass
    return env


def wrap_cmd(cmd: list[str]) -> list[str]:
    """Wrap a subprocess argv to run under the privilege-dropping exec shim.

    Disabled → returns the command unchanged (today's behaviour). Enabled → runs
    it via `python3 -m mcp_server._sandbox_exec`, which drops to the unprivileged
    sandbox uid, applies rlimits, sets no_new_privs, then execs the command (so
    the pid is preserved and the dispatcher's kill-by-pid path still works).
    """
    if not enabled():
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
    return [*wrapped, "--", *cmd]


def prepare_workdir(work_dir: Path | str) -> None:
    """Hand the work dir to the sandbox account so the dropped process can write.

    No-op when confinement is off. The server is root, so it chowns the run dir
    (recursively) to the sandbox uid before exec; the root server still reads the
    outputs afterwards. Bind mounts that ignore ownership (e.g. Docker Desktop)
    make this a harmless no-op there — confinement still holds for in-image paths.
    """
    if not enabled():
        return
    work = Path(work_dir)
    with contextlib.suppress(OSError):
        os.chown(work, SANDBOX_UID, SANDBOX_GID)
    for path in work.rglob("*"):
        with contextlib.suppress(OSError):
            os.chown(path, SANDBOX_UID, SANDBOX_GID)
