from __future__ import annotations

import math
import os
import sys
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
        v = float(env_val)
    except (ValueError, TypeError):
        return default
    # Reject NaN/inf: a non-finite SIM_TIMEOUT would make both `<= 0` and the
    # elapsed-time comparison false, silently disabling timeout enforcement.
    if not math.isfinite(v):
        return default
    return v

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
_SANDBOX_OFF_ALIASES = frozenset({"", "off", "0", "false", "no"})
_SANDBOX_ON_MODES = frozenset({"posix", "auto", "full", "landlock"})


def _normalize_sandbox_mode(raw: str) -> str:
    """Map OSMCP_SANDBOX to a known mode, FAIL-CLOSED on an unrecognized value.

    A typo like ``atuo`` would otherwise leave ``enabled()`` True but ``_full()``
    False — silently downgrading from the default Landlock+seccomp tier to
    posix-only. To never weaken confinement on a typo, force the most-restrictive
    ``auto`` and warn loudly. Off-aliases are honored as-is (disabling is explicit).
    """
    v = (raw or "").strip().lower()
    if v in _SANDBOX_OFF_ALIASES or v in _SANDBOX_ON_MODES:
        return v
    print(f"[sandbox] unknown OSMCP_SANDBOX={raw!r}; falling back to 'auto' "
          "(fail-closed). Valid values: off, posix, auto, full, landlock.",
          file=sys.stderr)
    return "auto"


SANDBOX_MODE = _normalize_sandbox_mode(os.environ.get("OSMCP_SANDBOX", "auto"))
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
def _safe_sandbox_id(env_val: str, default: int) -> int:
    """A positive uid/gid. Rejects <=0 (esp. 0=root) so a bad override can never
    leave confined code running as root after the setuid 'drop'."""
    v = _safe_int(env_val, default)
    return v if v > 0 else default


SANDBOX_UID = _safe_sandbox_id(os.environ.get("OSMCP_SANDBOX_UID", "1001"), 1001)
SANDBOX_GID = _safe_sandbox_id(os.environ.get("OSMCP_SANDBOX_GID", "1001"), 1001)

# Per-tenant uid derivation (multi-user hardening). Every distinct remote caller
# (HTTP session / auth principal) gets its OWN sandbox uid so that:
#   - RLIMIT_NPROC — which the kernel counts PER REAL UID — is a private budget,
#     so one tenant's fork bomb can't starve every other tenant's runs; and
#   - DAC isolates tenants' run dirs from each other even in the posix tier
#     (no Landlock), since the dirs are chowned to, and processes run as,
#     different uids.
# The local single user (stdio / off-request) keeps the baked-in SANDBOX_UID,
# preserving today's behavior. Derived uids sit above the system/sandbox range
# and below `nobody`, and are never root.
_PER_TENANT_UID_BASE = 2000
_PER_TENANT_UID_SPAN = 60000  # uids 2000..61999


def _derive_tenant_uid(key: str) -> int:
    """Stable, process-independent uid for a tenant key.

    Uses hashlib (NOT the salted builtin hash()) so chown (server) and setuid
    (shim, a separate process) derive the SAME uid for a request across restarts.
    """
    import hashlib
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return _PER_TENANT_UID_BASE + (int.from_bytes(digest[:4], "big") % _PER_TENANT_UID_SPAN)


def sandbox_ids() -> tuple[int, int]:
    """(uid, gid) the CURRENT caller's confined subprocess drops to.

    Resolved per-call from caller identity (same key in → same uid out, so a
    request's prepare_workdir chown and the shim's setuid agree). LOCAL → the
    baked SANDBOX_UID/GID; each remote tenant → its own derived uid (gid==uid).
    """
    from mcp_server.identity import LOCAL, user_key
    key = user_key()
    if key == LOCAL:
        return (SANDBOX_UID, SANDBOX_GID)
    uid = _derive_tenant_uid(key)
    return (uid, uid)

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

# --- Remote file transfer (HTTP deployment) -----------------------------------
# Over HTTP the user's files live on their laptop, not the server. Bytes move
# out-of-band via signed PUT/GET routes (see skills/file_transfer); these knobs
# bound and locate that channel. All sizes are megabytes.
OSMCP_MAX_UPLOAD_MB = _safe_int(os.environ.get("OSMCP_MAX_UPLOAD_MB", "200"), 200)
# Per-user cap on total bytes resident under their uploads/ dir (0 = unlimited).
OSMCP_USER_QUOTA_MB = _safe_int(os.environ.get("OSMCP_USER_QUOTA_MB", "4096"), 4096)
# How long a minted upload/download URL stays valid (seconds).
OSMCP_UPLOAD_URL_TTL = _safe_int(os.environ.get("OSMCP_UPLOAD_URL_TTL", "300"), 300)
# Zip-bomb backstops for auto-extracted archives.
OSMCP_MAX_ARCHIVE_UNCOMPRESSED_MB = _safe_int(
    os.environ.get("OSMCP_MAX_ARCHIVE_UNCOMPRESSED_MB", "1024"), 1024)
OSMCP_MAX_ARCHIVE_ENTRIES = _safe_int(os.environ.get("OSMCP_MAX_ARCHIVE_ENTRIES", "5000"), 5000)
# Externally reachable base URL of THIS server (e.g. https://box.example). The
# server can't know its own proxy-fronted URL, so when unset request_upload
# returns a relative path and the client prepends the same host it uses for /mcp.
OSMCP_PUBLIC_BASE_URL = os.environ.get("OSMCP_PUBLIC_BASE_URL", "").rstrip("/")

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


def run_root_for(key: str) -> Path:
    """Run root for an EXPLICIT user key (no identity context needed).

    The signed file-transfer routes run outside MCP request context, so they
    can't call user_run_root() (which resolves identity per-call). They pass the
    key carried in the verified URL signature here instead. LOCAL owns the whole
    RUN_ROOT, matching user_run_root().
    """
    from mcp_server.identity import LOCAL
    root = (RUN_ROOT if key == LOCAL else RUN_ROOT / key).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_path_allowed_for(key: str, p: Path, *, write: bool = False) -> bool:
    """is_path_allowed but for an EXPLICIT user key (used by signed routes)."""
    rp = p.resolve()
    own = run_root_for(key)
    if _under(rp, own):
        return True
    if _under(rp, RUN_ROOT):
        return False
    if write:
        return False
    return any(_under(rp, root) for root in _SHARED_READ_ROOTS)


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
