"""Minimal seccomp-BPF network deny via raw syscalls (ctypes), no dependency.

Installs a classic-BPF seccomp filter that fails ``socket(AF_INET|AF_INET6, ...)``
with EAFNOSUPPORT and leaves AF_UNIX (and every other syscall) untouched —
blocking outbound IP networking from measure code while local IPC / the bundler
still work. The program is built for the running arch (the shim executes on the
workload's arch), so there is no cross-arch branching to get wrong; an unexpected
arch makes install a no-op. Requires no_new_privs (set by the caller).

Returns True if the filter was installed, False if unavailable — the caller
degrades loudly rather than failing the run.
"""
from __future__ import annotations

import ctypes
import errno
import platform
import struct

# BPF opcodes
_BPF_LD_W_ABS = 0x00 | 0x00 | 0x20   # BPF_LD | BPF_W | BPF_ABS
_BPF_JEQ_K = 0x05 | 0x10 | 0x00      # BPF_JMP | BPF_JEQ | BPF_K
_BPF_RET_K = 0x06 | 0x00             # BPF_RET | BPF_K

# seccomp return actions
_SECCOMP_RET_ALLOW = 0x7FFF0000
_SECCOMP_RET_ERRNO = 0x00050000

# seccomp_data field offsets (nr@0, arch@4, ip@8, args[0]@16 ...; little-endian)
_OFF_NR = 0
_OFF_ARCH = 4
_OFF_ARG0 = 16

# AUDIT_ARCH + __NR_socket per arch
_AUDIT_ARCH = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}
_NR_SOCKET = {"x86_64": 41, "aarch64": 198}

_AF_INET = 2
_AF_INET6 = 10

_PR_SET_SECCOMP = 22
_SECCOMP_MODE_FILTER = 2


def _stmt(code: int, k: int) -> bytes:
    return struct.pack("=HBBI", code, 0, 0, k)


def _jump(code: int, k: int, jt: int, jf: int) -> bytes:
    return struct.pack("=HBBI", code, jt, jf, k)


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


def install_net_deny() -> bool:
    mach = platform.machine()
    if mach not in _AUDIT_ARCH:
        return False
    audit_arch = _AUDIT_ARCH[mach]
    nr_socket = _NR_SOCKET[mach]
    deny = _SECCOMP_RET_ERRNO | (errno.EAFNOSUPPORT & 0xFFFF)

    # Instruction layout (jt/jf are offsets from the NEXT instruction):
    #   0 load arch
    #   1 arch == ours ? -> 2 : ALLOW(8)
    #   2 load nr
    #   3 nr == socket ? -> 4 : ALLOW(8)
    #   4 load args[0] (domain)
    #   5 domain == AF_INET  ? DENY(7) : 6
    #   6 domain == AF_INET6 ? DENY(7) : ALLOW(8)
    #   7 RET deny
    #   8 RET allow
    program = b"".join([
        _stmt(_BPF_LD_W_ABS, _OFF_ARCH),
        _jump(_BPF_JEQ_K, audit_arch, 0, 6),
        _stmt(_BPF_LD_W_ABS, _OFF_NR),
        _jump(_BPF_JEQ_K, nr_socket, 0, 4),
        _stmt(_BPF_LD_W_ABS, _OFF_ARG0),
        _jump(_BPF_JEQ_K, _AF_INET, 1, 0),
        _jump(_BPF_JEQ_K, _AF_INET6, 0, 1),
        _stmt(_BPF_RET_K, deny),
        _stmt(_BPF_RET_K, _SECCOMP_RET_ALLOW),
    ])
    n = len(program) // 8
    buf = ctypes.create_string_buffer(program, len(program))
    fprog = _SockFprog(len=n, filter=ctypes.cast(buf, ctypes.c_void_p))

    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    rc = libc.prctl(_PR_SET_SECCOMP, _SECCOMP_MODE_FILTER, ctypes.byref(fprog), 0, 0)
    return rc == 0
