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
_BPF_JSET_K = 0x05 | 0x40 | 0x00     # BPF_JMP | BPF_JSET | BPF_K (bit test)
_BPF_RET_K = 0x06 | 0x00             # BPF_RET | BPF_K

# seccomp return actions
_SECCOMP_RET_ALLOW = 0x7FFF0000
_SECCOMP_RET_ERRNO = 0x00050000
_SECCOMP_RET_KILL_PROCESS = 0x80000000
_X32_SYSCALL_BIT = 0x40000000  # x86_64 x32 ABI marks syscall nrs with this bit

# seccomp_data field offsets (nr@0, arch@4, ip@8, args[0]@16 ...; little-endian)
_OFF_NR = 0
_OFF_ARCH = 4
_OFF_ARG0 = 16

# AUDIT_ARCH + syscall numbers per arch. io_uring_setup is blocked too: io_uring
# can create/connect sockets via submission-queue ops, bypassing a socket()-only
# filter — denying its setup closes that hole (no measure legitimately uses it).
_AUDIT_ARCH = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}
_NR_SOCKET = {"x86_64": 41, "aarch64": 198}
_NR_IO_URING_SETUP = {"x86_64": 425, "aarch64": 425}  # generic syscall number

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
    nr_io_uring = _NR_IO_URING_SETUP[mach]
    deny_net = _SECCOMP_RET_ERRNO | (errno.EAFNOSUPPORT & 0xFFFF)
    deny_enosys = _SECCOMP_RET_ERRNO | (errno.ENOSYS & 0xFFFF)  # io_uring "unavailable"

    # Instruction layout (jt/jf are offsets from the NEXT instruction). Unexpected
    # architectures (e.g. a 32-bit i386 binary, different AUDIT_ARCH) and x32-ABI
    # syscalls (x86_64 syscall nr with the 0x40000000 bit) are KILLed rather than
    # allowed — otherwise they'd issue unfiltered socket() calls (fail-open).
    #    0  load arch
    #    1  arch == ours ?            -> 2          : KILL(9)
    #    2  load nr
    #    3  nr & x32_bit ?            -> KILL(9)    : 4
    #    4  nr == io_uring_setup ?    -> ENOSYS(10) : 5
    #    5  nr == socket ?            -> 6          : ALLOW(12)
    #    6  load args[0] (domain)
    #    7  domain == AF_INET  ?      -> DENY_NET(11): 8
    #    8  domain == AF_INET6 ?      -> DENY_NET(11): ALLOW(12)
    #    9  RET kill
    #   10  RET enosys
    #   11  RET deny_net (EAFNOSUPPORT)
    #   12  RET allow
    program = b"".join([
        _stmt(_BPF_LD_W_ABS, _OFF_ARCH),
        _jump(_BPF_JEQ_K, audit_arch, 0, 7),
        _stmt(_BPF_LD_W_ABS, _OFF_NR),
        _jump(_BPF_JSET_K, _X32_SYSCALL_BIT, 5, 0),
        _jump(_BPF_JEQ_K, nr_io_uring, 5, 0),
        _jump(_BPF_JEQ_K, nr_socket, 0, 6),
        _stmt(_BPF_LD_W_ABS, _OFF_ARG0),
        _jump(_BPF_JEQ_K, _AF_INET, 3, 0),
        _jump(_BPF_JEQ_K, _AF_INET6, 2, 3),
        _stmt(_BPF_RET_K, _SECCOMP_RET_KILL_PROCESS),
        _stmt(_BPF_RET_K, deny_enosys),
        _stmt(_BPF_RET_K, deny_net),
        _stmt(_BPF_RET_K, _SECCOMP_RET_ALLOW),
    ])
    n = len(program) // 8
    buf = ctypes.create_string_buffer(program, len(program))
    fprog = _SockFprog(len=n, filter=ctypes.cast(buf, ctypes.c_void_p))

    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    rc = libc.prctl(_PR_SET_SECCOMP, _SECCOMP_MODE_FILTER, ctypes.byref(fprog), 0, 0)
    return rc == 0
