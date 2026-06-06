"""Privilege-dropping exec shim for confined measure / simulation subprocesses.

Invoked by mcp_server.sandbox.wrap_cmd as::

    python3 -m mcp_server._sandbox_exec --uid N --gid N \
        [--rlimit-fsize BYTES] [--rlimit-nproc N] [--rlimit-nofile N] \
        [--rlimit-cpu SECONDS] [--rlimit-as BYTES] \
        [--landlock-ro PATH ...] [--landlock-rw PATH ...] [--seccomp-net] \
        -- CMD [ARG...]

Applies, in order: rlimits, ``prctl(no_new_privs)``, Landlock FS policy and a
seccomp network-deny filter (when their flags are given), then drops to the
unprivileged uid/gid **only when running as root** (a non-root local server keeps
its uid — the FS/network confinement is unprivileged and still applies), and
finally ``execvp``s CMD. A standalone exec — NOT a Popen ``preexec_fn`` — so
there is no fork-safety hazard in the threaded server, and the exec'd image keeps
the same pid (so the dispatcher's terminate/kill-by-pid path still works).
"""
from __future__ import annotations

import argparse
import ctypes
import os
import resource
import sys

# Imported up-front (before any Landlock restriction is applied below) so the
# module files are read while the filesystem is still unconfined.
from mcp_server import _landlock, _seccomp

_RLIMITS = {
    "cpu": resource.RLIMIT_CPU,        # CPU-seconds
    "fsize": resource.RLIMIT_FSIZE,    # max single-file bytes
    "nproc": resource.RLIMIT_NPROC,    # processes/threads for the uid
    "nofile": resource.RLIMIT_NOFILE,  # open file descriptors
    "as": resource.RLIMIT_AS,          # virtual address space bytes
}

_PR_SET_NO_NEW_PRIVS = 38


def _set_no_new_privs() -> None:
    """Promise the kernel we will never gain privileges via setuid binaries.

    Prerequisite for the unprivileged Landlock/seccomp backends landing next; set
    here so the contract holds from the POSIX tier onward.
    """
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_NO_NEW_PRIVS) failed")


def main(argv: list[str]) -> int:
    if "--" not in argv:
        print("sandbox-exec: missing '-- CMD'", file=sys.stderr)
        return 2
    sep = argv.index("--")
    cmd = argv[sep + 1:]
    if not cmd:
        print("sandbox-exec: empty command", file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--uid", type=int, required=True)
    ap.add_argument("--gid", type=int, required=True)
    for name in _RLIMITS:
        ap.add_argument(f"--rlimit-{name}", type=int, default=0)
    ap.add_argument("--landlock-ro", action="append", default=[])
    ap.add_argument("--landlock-rw", action="append", default=[])
    ap.add_argument("--seccomp-net", action="store_true")
    ns = ap.parse_args(argv[:sep])

    # rlimits first, while still privileged (lowering hard limits is always ok).
    for name, res_id in _RLIMITS.items():
        val = getattr(ns, f"rlimit_{name}")
        if val and val > 0:
            try:
                resource.setrlimit(res_id, (val, val))
            except (ValueError, OSError) as e:
                print(f"sandbox-exec: rlimit {name}={val} failed: {e}", file=sys.stderr)

    _set_no_new_privs()

    # Filesystem + network confinement (after no_new_privs, before the uid drop;
    # both persist across setuid + exec and are inherited by children). Degrade
    # loudly — a backend that cannot engage prints a notice and the run proceeds
    # with whatever confinement did apply (the POSIX floor always holds).
    # Fail CLOSED: if a kernel backend was requested (auto/full tier) but cannot
    # engage, refuse to run rather than execute untrusted code unconfined. An
    # operator who knowingly wants weaker confinement selects OSMCP_SANDBOX=posix
    # (UID drop + rlimits, no kernel FS/net) or off — neither requests these flags.
    if (ns.landlock_ro or ns.landlock_rw) and not _landlock.restrict(ns.landlock_ro, ns.landlock_rw):
        print("sandbox-exec: FATAL Landlock requested but unavailable — refusing to run "
              "unconfined (use OSMCP_SANDBOX=posix or off to accept weaker confinement)",
              file=sys.stderr)
        return 3
    if ns.seccomp_net and not _seccomp.install_net_deny():
        print("sandbox-exec: FATAL seccomp net-deny requested but unavailable — refusing to "
              "run unconfined (use OSMCP_SANDBOX=posix or off)", file=sys.stderr)
        return 3

    # Drop privileges only when we have them (root). The FS/network confinement
    # above is unprivileged and already applied — so a non-root local server still
    # gets Landlock + seccomp + rlimits; only the uid-drop (a defence-in-depth /
    # multi-tenant layer) is skipped. Order matters: groups, gid, then uid.
    if os.geteuid() == 0:
        os.setgroups([ns.gid])
        os.setgid(ns.gid)
        os.setuid(ns.uid)
        if os.getuid() != ns.uid or os.geteuid() != ns.uid:
            print("sandbox-exec: uid drop did not stick", file=sys.stderr)
            return 2
    elif os.getuid() != ns.uid:
        print(f"sandbox-exec: not root (uid {os.getuid()}) — keeping uid; "
              "FS/network confinement still applied", file=sys.stderr)

    try:
        os.execvp(cmd[0], cmd)  # noqa: S606 - intentional shell-less exec of the confined command
    except OSError as e:
        print(f"sandbox-exec: exec {cmd[0]} failed: {e}", file=sys.stderr)
        return 127
    return 0  # unreachable


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
