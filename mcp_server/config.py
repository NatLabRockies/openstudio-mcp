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
# gbXML-to-OpenStudio measures (Revit gbXML -> OSM translation) + their empty seed
# model. Baked in at a pinned release tag (see GBXML_TO_OS_TAG in docker/Dockerfile) —
# bumping to a newer measures release is a one-line Dockerfile ARG change + rebuild.
GBXML_MEASURES_DIR = Path(os.environ.get("GBXML_MEASURES_DIR", "/opt/gbxml-to-openstudio-measures"))
GBXML_SEED_OSM = Path(os.environ.get("GBXML_SEED_OSM", "/opt/gbxml-to-openstudio-seed_empty.osm"))
# Mount root for per-user measures. Each principal is scoped to MEASURES_DIR/<key>
# (see user_measures_root); custom + bcl live under that, never at the bare root.
# No per-subdir env overrides: a flat override would silently break tenant scoping.
USER_MEASURES_DIR = Path(os.environ.get("OPENSTUDIO_MCP_MEASURES_DIR", "/measures"))
MEASURES_DIR = USER_MEASURES_DIR
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

# Wall-clock cap for the gbXML measure-workflow subprocess (import_gbxml). <= 0 = no cap,
# matching SIM_TIMEOUT_SECONDS — the call site gates on > 0, so a negative from a
# misconfigured env var disables the cap rather than reaching subprocess.run.
# Configurable because the runtime is almost entirely one measure's single-threaded surface
# matching, so it tracks the host's per-core speed and nothing else. A hardcoded literal was
# raised 300 -> 600 once already and then went marginal again; measured on the Austin fixture on
# one slower host, the same import took 622-687s run on its own but 1228s when the rest of
# tests/test_gbxml_import.py ran alongside it in the same container. 1800 covers that observed
# worst case with margin instead of landing just above it, which is how the previous two values
# each became too tight.
GBXML_IMPORT_TIMEOUT_SECONDS = _safe_float(
    os.environ.get("OPENSTUDIO_MCP_GBXML_IMPORT_TIMEOUT_SECONDS",
                   os.environ.get("OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS", "1800")),
    1800.0,
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

# Per-user quota for pip-installed Python plugin packages (install_plugin_packages).
# Hard cap: an install that lands over this clears the dir and errors. 0 = unlimited.
OSMCP_PKGS_QUOTA_MB = _safe_int(os.environ.get("OSMCP_PKGS_QUOTA_MB", "250"), 250)

# Shared roots are read-only for everyone; the only per-user writable areas are
# RUN_ROOT/<user_key> (runs) and MEASURES_DIR/<user_key> (measures) — see
# user_run_root / user_measures_root. Writes elsewhere are denied. The measures tree
# is deliberately NOT listed here: it is per-user, not a global shared dir. Adding it
# would expose every tenant's authored measures to every other tenant (see
# docs/security-isolation.md).
_SHARED_READ_ROOTS = [
    Path("/repo").resolve(),
    INPUT_ROOT,
    COMSTOCK_MEASURES_DIR.resolve(),
    COMMON_MEASURES_DIR.resolve(),
    GBXML_MEASURES_DIR.resolve(),
    SKILLS_DIR.resolve(),
]

# Server-bundled weather data (openstudio-standards gem). list_weather_files
# advertises these paths, so the read allowlist must accept them — a tool
# must not list paths a sibling tool's gate rejects (issue #121). Read-only
# baked image data; same version-proof glob the weather skill uses.
_SHARED_READ_ROOTS += [
    p.resolve()
    for p in Path(OSCLI_GEM_PATH).glob(
        "ruby/*/gems/openstudio-standards-*/data/weather")
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


def pkgs_root_for(key: str) -> Path:
    """Python-plugin site-packages dir for an EXPLICIT user key (not auto-created).

    Lives inside the user's run root, so is_path_allowed already scopes it per
    tenant. The sim dispatcher (which has the run's user key but no request
    identity) uses this to grant the dir read-only to the sandboxed EnergyPlus
    child — plugins import third-party packages from here via
    PythonPlugin:SearchPaths.
    """
    from mcp_server.identity import LOCAL
    root = RUN_ROOT if key == LOCAL else RUN_ROOT / key
    pkgs = root / "python_packages"
    # Belt: resolve() would launder a symlink planted here into a path later
    # treated as trusted (pip --target write, sandbox read-only grant).
    if pkgs.is_symlink():
        raise RuntimeError(
            f"python_packages dir for '{key}' is a symlink — refusing to use it")
    return pkgs.resolve()


def user_pkgs_root() -> Path:
    """The caller's Python-plugin site-packages dir (not auto-created)."""
    from mcp_server.identity import user_key
    return pkgs_root_for(user_key())


def user_measures_root() -> Path:
    """The caller's private measures root (MEASURES_DIR/<user_key>), created if missing.

    Unlike user_run_root(), EVERY principal is keyed — including the local single user
    (MEASURES_DIR/local). Nobody owns the bare MEASURES_DIR, so no identity can reach
    another tenant's measures, and the fixed `custom`/`bcl` leaf names can never alias
    a user key. Measures is a new feature, so there is no legacy layout to preserve.
    See docs/security-isolation.md.
    """
    from mcp_server.identity import user_key
    root = (MEASURES_DIR / user_key()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_custom_measures_dir() -> Path:
    """The caller's private authored-measures dir (MEASURES_DIR/<user_key>/custom)."""
    d = (user_measures_root() / "custom").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_bcl_measures_dir() -> Path:
    """The caller's private downloaded-BCL-measures dir (MEASURES_DIR/<user_key>/bcl)."""
    d = (user_measures_root() / "bcl").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


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


def path_denied_hint() -> str:
    """One-line hint appended to file-path error messages.

    Agents on filesystem-capable clients routinely pass HOST-side paths
    (C:\\..., /home/...) that don't exist in the server's filesystem, then
    burn their turn budget retrying variants — a terse "not found"/"not
    allowed" never tells them the path namespace is wrong (issue #119).
    """
    shared = ", ".join(sorted(str(r) for r in _SHARED_READ_ROOTS))
    return (
        "Paths are SERVER-side — a path from your local machine will not "
        f"resolve here. Readable roots: {shared}. Your writable run area is "
        f"under {RUN_ROOT}. Use list_files to enumerate available files."
    )


def is_path_allowed(p: Path, *, write: bool = False) -> bool:
    """Whether the caller may access path `p`.

    - Own run root (RUN_ROOT/<user_key>): read + write.
    - Own measures root (MEASURES_DIR/<user_key>): read + write.
    - Elsewhere under RUN_ROOT or MEASURES_DIR (another user's area): always denied.
    - Shared roots (repo, inputs, bundled measures, skills): read-only.
    """
    rp = p.resolve()
    if _under(rp, user_run_root()):
        return True
    if _under(rp, RUN_ROOT):
        return False  # another user's run area
    if _under(rp, user_measures_root()):
        return True
    if _under(rp, MEASURES_DIR):
        return False  # another user's measures area
    if write:
        return False  # shared roots are read-only
    return any(_under(rp, root) for root in _SHARED_READ_ROOTS)
