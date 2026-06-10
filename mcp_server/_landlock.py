"""Minimal Landlock (LSM) filesystem confinement via raw syscalls (ctypes).

Three syscalls, no external dependency (house style: grepable, owned). Applies a
read-deny-by-default policy to the current process and all its children: only the
enumerated read-only paths are readable/executable, and only the run dir is
writable. Requires no_new_privs (set by the caller) for unprivileged use; works
inside default-seccomp Docker >= 23.0 (the landlock_* syscalls are allowlisted
there). Returns the applied ABI, or 0 when Landlock is unavailable — the caller
degrades loudly rather than failing the run.
"""
from __future__ import annotations

import ctypes
import os
import stat

# Generic syscall table numbers (identical on x86_64 and aarch64).
_NR_CREATE_RULESET = 444
_NR_ADD_RULE = 445
_NR_RESTRICT_SELF = 446

_CREATE_RULESET_VERSION = 1  # query the ABI instead of creating a ruleset
_RULE_PATH_BENEATH = 1

# access_fs rights (bit positions). 0..12 = ABI 1, REFER = ABI 2, TRUNCATE = ABI 3.
_A_EXECUTE = 1 << 0
_A_WRITE_FILE = 1 << 1
_A_READ_FILE = 1 << 2
_A_READ_DIR = 1 << 3
_A_REMOVE_DIR = 1 << 4
_A_REMOVE_FILE = 1 << 5
_A_MAKE_CHAR = 1 << 6
_A_MAKE_DIR = 1 << 7
_A_MAKE_REG = 1 << 8
_A_MAKE_SOCK = 1 << 9
_A_MAKE_FIFO = 1 << 10
_A_MAKE_BLOCK = 1 << 11
_A_MAKE_SYM = 1 << 12
_A_REFER = 1 << 13      # ABI >= 2
_A_TRUNCATE = 1 << 14   # ABI >= 3
_A_IOCTL_DEV = 1 << 15  # ABI >= 5 — governs ioctl() on device files

_RO = _A_EXECUTE | _A_READ_FILE | _A_READ_DIR
_RW_BASE = (
    _A_EXECUTE | _A_WRITE_FILE | _A_READ_FILE | _A_READ_DIR
    | _A_REMOVE_DIR | _A_REMOVE_FILE | _A_MAKE_CHAR | _A_MAKE_DIR | _A_MAKE_REG
    | _A_MAKE_SOCK | _A_MAKE_FIFO | _A_MAKE_BLOCK | _A_MAKE_SYM
)
# Rights that are meaningful on a non-directory. Landlock's add_rule returns
# EINVAL if a rule on a FILE carries directory-only rights (READ_DIR, MAKE_*,
# REMOVE_*), so a per-file rule (e.g. /dev/null) MUST be masked to these.
_FILE_ONLY = _A_EXECUTE | _A_WRITE_FILE | _A_READ_FILE | _A_TRUNCATE | _A_IOCTL_DEV


class _RulesetAttr(ctypes.Structure):
    # Only handled_access_fs — 8 bytes, valid on every ABID (kernel reads the
    # field set implied by `size`); avoids the ABI>=4 net field tripping abi3.
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    # MUST be packed (12 bytes). The kernel UAPI declares
    #   struct landlock_path_beneath_attr { __u64 allowed_access; __s32 parent_fd; }
    #   __attribute__((packed));
    # so _pack_=1 matches the kernel exactly. Do NOT "fix" this to natural
    # alignment (16 bytes) — that would mismatch the kernel struct. Verified by
    # the integration tests, which only pass if add_rule parsed this correctly.
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def restrict(ro_paths: list[str], rw_paths: list[str]) -> int:
    """Confine the filesystem to ro_paths (read+exec) and rw_paths (read+write).

    Returns the applied Landlock ABI (>=1), or 0 if Landlock is unavailable or
    the ruleset could not be enforced. Missing paths are skipped silently.
    """
    libc = ctypes.CDLL("libc.so.6", use_errno=True)

    abi = libc.syscall(_NR_CREATE_RULESET, None, 0, _CREATE_RULESET_VERSION)
    if abi <= 0:
        return 0

    handled = _RW_BASE
    if abi >= 2:
        handled |= _A_REFER
    if abi >= 3:
        handled |= _A_TRUNCATE
    if abi >= 5:
        handled |= _A_IOCTL_DEV  # govern device ioctls (esp. with /dev writable)

    attr = _RulesetAttr(handled_access_fs=handled)
    rs_fd = libc.syscall(_NR_CREATE_RULESET, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if rs_fd < 0:
        return 0

    def _add(path: str, access: int) -> bool:
        """True if the path is absent (optional, skip) or its rule was added;
        False only if a PRESENT path's rule failed (a broken ruleset)."""
        try:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
        except OSError:
            return True  # absent path — optional, not a failure
        try:
            acc = access & handled
            # A rule on a non-directory (e.g. /dev/null) must carry only file
            # rights — dir-only bits make add_rule fail with EINVAL.
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                acc &= _FILE_ONLY
            pba = _PathBeneathAttr(allowed_access=acc, parent_fd=fd)
            return libc.syscall(_NR_ADD_RULE, rs_fd, _RULE_PATH_BENEATH, ctypes.byref(pba), 0) == 0
        finally:
            os.close(fd)

    ok = True
    for p in ro_paths:
        ok = _add(p, _RO) and ok
    for p in rw_paths:
        ok = _add(p, handled) and ok  # full set for the writable run dir
    if not ok:
        # A present path's rule was rejected → enforce nothing rather than a
        # half-applied policy; the caller (auto tier) fails closed on a 0 return.
        os.close(rs_fd)
        return 0

    # no_new_privs is set by the caller; restrict_self enforces the ruleset on
    # this process and everything it execs/forks.
    rc = libc.syscall(_NR_RESTRICT_SELF, rs_fd, 0)
    os.close(rs_fd)
    return abi if rc == 0 else 0
