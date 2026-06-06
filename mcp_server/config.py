from __future__ import annotations

import os
from pathlib import Path

RUN_ROOT = Path(os.environ.get("OPENSTUDIO_MCP_RUN_ROOT", os.environ.get("OSMCP_RUN_ROOT", "/runs"))).resolve()
RUN_ROOT.mkdir(parents=True, exist_ok=True)

def _safe_int(env_val: str, default: int) -> int:
    try:
        return int(env_val)
    except (ValueError, TypeError):
        return default

def _safe_float(env_val: str, default: float) -> float:
    try:
        return float(env_val)
    except (ValueError, TypeError):
        return default

_raw_concurrency = os.environ.get("OPENSTUDIO_MCP_MAX_CONCURRENCY", os.environ.get("OSMCP_MAX_CONCURRENCY", "1"))
MAX_CONCURRENCY = _safe_int(_raw_concurrency, 1)

# Optional per-user fairness cap on simultaneous sims (0 = no per-user limit).
_raw_per_user = os.environ.get(
    "OPENSTUDIO_MCP_MAX_CONCURRENCY_PER_USER",
    os.environ.get("OSMCP_MAX_CONCURRENCY_PER_USER", "0"),
)
MAX_CONCURRENCY_PER_USER = _safe_int(_raw_per_user, 0)

_raw_tail = os.environ.get("OPENSTUDIO_MCP_DEFAULT_LOG_TAIL", os.environ.get("OSMCP_LOG_TAIL_DEFAULT", "200"))
LOG_TAIL_DEFAULT = _safe_int(_raw_tail, 200)

# Run-dir retention (whole-container garbage collection). OFF by default — the
# background sweeper only runs when explicitly enabled, via the `--gc` / `--gc-days`
# CLI flag or by setting RUN_RETENTION_DAYS > 0. When on, it deletes run dirs older
# than RUN_RETENTION_DAYS. Age = run_record.json `ended_at` (fallback: dir mtime).
# Pinned and queued/running runs are never swept. Only run dirs are targeted —
# saved models under examples/ are left alone.
_raw_retention = os.environ.get(
    "OPENSTUDIO_MCP_RUN_RETENTION_DAYS", os.environ.get("OSMCP_RUN_RETENTION_DAYS", "0"),
)
RUN_RETENTION_DAYS = _safe_float(_raw_retention, 0.0)

_raw_sweep = os.environ.get(
    "OPENSTUDIO_MCP_RETENTION_SWEEP_SECONDS", os.environ.get("OSMCP_RETENTION_SWEEP_SECONDS", "3600"),
)
RETENTION_SWEEP_SECONDS = _safe_float(_raw_sweep, 3600.0)

OSCLI_GEMFILE = os.environ.get("OSCLI_GEMFILE", "/var/oscli/Gemfile")
OSCLI_GEM_PATH = os.environ.get("OSCLI_GEM_PATH", "/var/oscli/gems")

COMSTOCK_MEASURES_DIR = Path(os.environ.get("COMSTOCK_MEASURES_DIR", "/opt/comstock-measures"))
COMMON_MEASURES_DIR = Path(os.environ.get("COMMON_MEASURES_DIR", "/opt/common-measures"))
SKILLS_DIR = Path(os.environ.get("SKILLS_DIR", "/skills"))

INPUT_ROOT = Path(os.environ.get("OPENSTUDIO_MCP_INPUT_ROOT", "/inputs")).resolve()

ENABLE_CODE_MODE = os.environ.get("OSMCP_CODE_MODE", "").lower() in ("1", "true")

# Subprocess confinement for measure/simulation execution (see mcp_server/sandbox.py).
#   off    — full passthrough (explicit escape hatch for trusted/local-tooling use)
#   posix  — clean-env allowlist + UID drop (if root) + rlimits
#   auto   — best confinement available (default): clean-env + Landlock FS +
#            seccomp net-deny + rlimits, plus UID drop when running as root.
# Secure by default. Degrades loudly: the unprivileged layers (Landlock/seccomp)
# apply even for a non-root local server; on a platform without a kernel backend
# (macOS/Windows bare installs) it falls back to clean-env only and logs a notice.
SANDBOX_MODE = os.environ.get("OSMCP_SANDBOX", "auto").strip().lower()
# Network policy for confined subprocesses: deny (default) blocks outbound TCP
# once the seccomp backend lands; allow leaves it open (trusted/BCL deployments).
SANDBOX_NET = os.environ.get("OSMCP_SANDBOX_NET", "deny").strip().lower()

# Wall-clock cap for a single simulation (run_osw/run_simulation). 0 = no cap.
SIM_TIMEOUT_SECONDS = _safe_float(
    os.environ.get("OPENSTUDIO_MCP_SIM_TIMEOUT_SECONDS",
                   os.environ.get("OSMCP_SIM_TIMEOUT_SECONDS", "7200")),
    7200.0,
)

# Unprivileged account confined subprocesses drop to (baked into the image as
# `sandbox`). See mcp_server/_sandbox_exec.py.
SANDBOX_UID = _safe_int(os.environ.get("OSMCP_SANDBOX_UID", "1001"), 1001)
SANDBOX_GID = _safe_int(os.environ.get("OSMCP_SANDBOX_GID", "1001"), 1001)

# rlimit backstops for confined subprocesses (0 = off). Generous by design — they
# catch runaway bombs, not tune normal use. CPU/AS default off: a CPU-second cap
# would kill long annual sims, and RLIMIT_AS (virtual address space) breaks
# EnergyPlus/allocators — real memory control belongs to the container cgroup.
_GB = 1024 ** 3
SANDBOX_RLIMIT_FSIZE = _safe_int(os.environ.get("OSMCP_SANDBOX_RLIMIT_FSIZE", str(10 * _GB)), 10 * _GB)
SANDBOX_RLIMIT_NPROC = _safe_int(os.environ.get("OSMCP_SANDBOX_RLIMIT_NPROC", "1024"), 1024)
SANDBOX_RLIMIT_NOFILE = _safe_int(os.environ.get("OSMCP_SANDBOX_RLIMIT_NOFILE", "0"), 0)
SANDBOX_RLIMIT_CPU = _safe_int(os.environ.get("OSMCP_SANDBOX_RLIMIT_CPU", "0"), 0)
SANDBOX_RLIMIT_AS = _safe_int(os.environ.get("OSMCP_SANDBOX_RLIMIT_AS", "0"), 0)

# Shared roots are read-only for everyone; the only per-user writable area is
# RUN_ROOT/<user_key> (see user_run_root). Writes elsewhere are denied.
_SHARED_READ_ROOTS = [
    Path("/repo").resolve(),
    INPUT_ROOT,
    COMSTOCK_MEASURES_DIR.resolve(),
    COMMON_MEASURES_DIR.resolve(),
    SKILLS_DIR.resolve(),
]


def user_run_root() -> Path:
    """The caller's private run root, created if missing.

    Identity is resolved per-call, so one code path serves every user. The local
    single-user (stdio / off-request) owns the whole RUN_ROOT — preserving the
    original /runs/<run_id> layout — while each HTTP user is scoped to
    RUN_ROOT/<user_key>.
    """
    from mcp_server.identity import LOCAL, user_key
    key = user_key()
    root = (RUN_ROOT if key == LOCAL else RUN_ROOT / key).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _under(p: Path, root: Path) -> bool:
    return p == root or str(p).startswith(str(root) + os.sep)


def is_path_allowed(p: Path, *, write: bool = False) -> bool:
    """Whether the caller may access path `p`.

    - Own run root (RUN_ROOT/<user_key>): read + write.
    - Elsewhere under RUN_ROOT (another user's runs): always denied.
    - Shared roots (repo, inputs, measures, skills): read-only.
    """
    rp = p.resolve()
    if _under(rp, user_run_root()):
        return True
    if _under(rp, RUN_ROOT):
        return False  # another user's run area
    if write:
        return False  # shared roots are read-only
    return any(_under(rp, root) for root in _SHARED_READ_ROOTS)
