from __future__ import annotations

import contextlib
import hashlib
import json
import mimetypes
import os
import re
import stat
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections.abc import Iterable
from http.client import HTTPException
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import (
    HTTPDefaultErrorHandler,
    HTTPErrorProcessor,
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    OpenerDirector,
    Request,
    UnknownHandler,
)

from jsonschema import Draft4Validator, SchemaError
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable

from mcp_server.confined_copy import copy_tree_confined, remove_tree_confined
from mcp_server.confined_fs import DirHandle, open_confined
from mcp_server.model_bundle import MAX_BUNDLE_OSM_BYTES, combine_resource_hashes, resources_digest
from mcp_server.resources import (
    MAX_RESOURCE_FILE_BYTES,
    MAX_RESOURCE_FILES,
    MAX_RESOURCE_TOTAL_BYTES,
    copy_resources,
    resource_dir_issue,
    resource_sources,
)
from mcp_server.util import (
    copy_regular_file_nofollow,
    is_regular_file_inside,
    open_nofollow_for_write,
    read_file_bounded,
    read_file_in_dir_nofollow,
    resolve_run_dir,
    sha256_regular_file_nofollow,
    write_text_in_dir_nofollow,
)

DOWNLOAD_FORMATS = ("csv", "rdata")  # the only formats OpenStudio Server's download_data serves
DONE_STATUSES = {"completed", "complete", "succeeded", "success", "finished"}
FAILED_STATUSES = {"failed", "error", "cancelled", "canceled"}
SUPPORTED_DISTRIBUTIONS = {"discrete", "uniform", "triangle", "normal", "lognormal", "integer_sequence"}
OSA_SCHEMA_ENV_VARS = ("OPENSTUDIO_OSA_SCHEMA_PATH", "OSAF_SCHEMA_PATH")
DEFAULT_OSA_SCHEMA_PATH = Path(__file__).with_name("osa_server_schema.json")
REQUIRED_ANALYSIS_PACKAGE_ROOTS = frozenset({"measures", "weather", "seeds", "scripts", "lib"})
SEED_SUFFIXES = frozenset({".osm", ".osw"})
WEATHER_SUFFIXES = frozenset({".epw", ".ddy", ".stat"})
SEED_QAQC_MANIFEST = "lib/seed_simulation_qaqc.json"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024  # an OSA JSON, schema or results document read by the server
MAX_PACKAGE_FILE_BYTES = 1024 * 1024 * 1024  # one member of the support zip
MAX_PACKAGE_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # a package zip posted to OpenStudio Server
# What identifies a seed simulation: the OSM, the effective EPW and the resource set
# (see model_bundle.resources_digest). The preflight manifest and run_simulation's run
# record both carry the three; a cached run or manifest is reused only on all three.
IDENTITY_KEYS = ("seed_sha256", "weather_sha256", "resources_sha256")
MAX_RUN_RECORD_BYTES = 64 * 1024
FOUNDATIONAL_ANALYSIS_MEASURES: tuple[dict[str, Any], ...] = (
    {
        "measure_name": "view_model",
        "arguments": {"use_geometry_diagnostics": False},
        "instance_name": "view_model",
        "display_name": "View Model",
    },
    {
        "measure_name": "openstudio_results",
        "arguments": {"units": "IP"},
        "instance_name": "openstudio_results",
        "display_name": "OpenStudio Results",
    },
    {
        "measure_name": "generic_qaqc",
        # All checks off by default (#96): with checks on, generic_qaqc emits
        # ~19MB of warnings per real multi-zone datapoint, blowing the server's
        # 16MB BSON document cap after a successful simulation. Seed-level
        # QA/QC already validates the package; add an explicit generic_qaqc
        # step to the workflow to re-enable checks for an analysis.
        "arguments": {
            "template": "90.1-2019",
            "check_mech_sys_part_load_eff": False,
            "check_mech_sys_capacity": False,
            "check_simultaneous_heating_and_cooling": False,
            "check_internal_loads": False,
            "check_schedules": False,
            "check_envelope_conductance": False,
            "check_domestic_hot_water": False,
            "check_mech_sys_efficiency": False,
            "check_mech_sys_type": False,
            "check_supply_air_and_thermostat_temp_difference": False,
        },
        "instance_name": "generic_qaqc",
        "display_name": "Generic QAQC",
    },
)
# Applied to every generated OSA unless the caller overrides (#96): when these
# keys are absent, openstudio-analysis/OS-server defaults enable --debug and
# --verbose CLI logging plus per-datapoint artifact downloads, which pushed
# successful datapoints over Mongo's 16MB BSON cap and corrupted R-driven
# analyses.
SAFE_ANALYSIS_FIELD_DEFAULTS: dict[str, Any] = {
    "cli_debug": "",
    "cli_verbose": "",
    "download_reports": False,
    "download_osw": False,
    "download_osm": False,
    "download_zip": False,
}
END_USE_CATEGORIES: tuple[str, ...] = (
    "cooling",
    "exterior_equipment",
    "exterior_lighting",
    "fans",
    "generators",
    "heat_recovery",
    "heat_rejection",
    "heating",
    "humidification",
    "interior_equipment",
    "interior_lighting",
    "pumps",
    "refrigeration",
    "water_systems",
)
END_USE_FUELS: tuple[str, ...] = ("electricity", "natural_gas")
WHOLE_BUILDING_OUTPUT_VARIABLE_NAMES: tuple[str, ...] = (
    "electricity_ip",
    "natural_gas_ip",
    "eui",
    "total_site_eui",
    "net_site_energy",
    "annual_peak_electric_demand",
    "unmet_hours_during_cooling",
    "unmet_hours_during_heating",
    "unmet_hours_during_occupied_cooling",
    "unmet_hours_during_occupied_heating",
)


def _openstudio_results_output_variable(display_name: str, name: str) -> dict[str, Any]:
    return {
        "objective_function": False,
        "objective_function_index": None,
        "objective_function_target": None,
        "objective_function_group": None,
        "scaling_factor": None,
        "display_name": display_name,
        "display_name_short": display_name,
        "metadata_id": None,
        "name": name,
        "visualize": True,
        "export": True,
        "variable_type": "double",
    }


def _default_end_use_output_variables() -> tuple[dict[str, Any], ...]:
    variables: list[dict[str, Any]] = []
    for fuel in END_USE_FUELS:
        for category in END_USE_CATEGORIES:
            display_name = f"{fuel}_{category}_ip"
            variables.append(
                _openstudio_results_output_variable(
                    display_name=display_name,
                    name=f"openstudio_results.{display_name}",
                )
            )
    return tuple(variables)


DEFAULT_SUMMARY_OUTPUT_VARIABLES: tuple[dict[str, Any], ...] = (
    *(
        _openstudio_results_output_variable(
            display_name=variable_name,
            name=f"openstudio_results.{variable_name}",
        )
        for variable_name in WHOLE_BUILDING_OUTPUT_VARIABLE_NAMES
    ),
)
DEFAULT_OUTPUT_VARIABLES: tuple[dict[str, Any], ...] = (
    *DEFAULT_SUMMARY_OUTPUT_VARIABLES,
    *_default_end_use_output_variables(),
)
OSAF_ALGORITHMS: tuple[dict[str, Any], ...] = (
    {
        "analysis_type": "single_run",
        "category": "smoke_test",
        "summary": "Generate and run one datapoint.",
        "best_for": "Server configuration checks, baseline runs, and validating one complete workflow before larger studies.",
        "avoid_when": "You need parameter exploration, sensitivity indices, or optimization.",
        "start_sequence": ["single_run", "batch_run"],
        "typical_algorithm_keys": ["number_of_samples"],
        "notes": "Use this for the OSAF smoke test path. It creates one datapoint, then batch_run simulates it.",
    },
    {
        "analysis_type": "lhs",
        "category": "sampling",
        "summary": "Latin Hypercube Sampling over one or more uncertain variables.",
        "best_for": "Small to medium sweeps, one-variable studies, broad sampling of continuous or discrete measure variables.",
        "avoid_when": "You need formal variance decomposition or a full factorial design.",
        "start_sequence": ["lhs", "batch_run"],
        "typical_algorithm_keys": ["number_of_samples", "sample_method", "seed", "objective_functions"],
        "notes": "For OSAF, start lhs first to generate datapoints, then start batch_run to simulate them.",
    },
    {
        "analysis_type": "sobol",
        "category": "sensitivity",
        "summary": "Variance-based global sensitivity analysis.",
        "best_for": "Quantifying first-order or higher-order sensitivity when you can afford enough samples.",
        "avoid_when": "You only need a quick smoke test or very small sample count.",
        "start_sequence": ["sobol", "batch_run"],
        "typical_algorithm_keys": ["number_of_samples", "random_seed", "random_seed_2", "order", "nboot", "conf", "type"],
        "notes": "Use for defensible sensitivity ranking; results need more samples than simple LHS sweeps.",
    },
    {
        "analysis_type": "morris",
        "category": "sensitivity",
        "summary": "Morris elementary-effects screening.",
        "best_for": "Low-cost screening to identify influential variables before a larger Sobol or optimization run.",
        "avoid_when": "You need precise variance contributions.",
        "start_sequence": ["morris", "batch_run"],
        "typical_algorithm_keys": ["r", "levels", "grid_jump", "check_boundary", "type"],
        "notes": "Good first pass when many variables make Sobol too expensive.",
    },
    {
        "analysis_type": "fast99",
        "category": "sensitivity",
        "summary": "Fourier Amplitude Sensitivity Test.",
        "best_for": "Global sensitivity analysis with periodic sampling assumptions.",
        "avoid_when": "You need the simpler screening behavior of Morris or the more common Sobol indices.",
        "start_sequence": ["fast99", "batch_run"],
        "typical_algorithm_keys": ["n", "M", "seed", "norm_type", "p_power"],
        "notes": "Less commonly used than Morris/Sobol in typical OSAF workflows.",
    },
    {
        "analysis_type": "doe",
        "category": "sampling",
        "summary": "Design of experiments, commonly full factorial.",
        "best_for": "Structured experiments across two or more variables with discrete levels.",
        "avoid_when": "You have only one variable; use lhs or single_run instead.",
        "start_sequence": ["doe", "batch_run"],
        "typical_algorithm_keys": ["experiment_type"],
        "notes": "MCP validation blocks DOE with fewer than two real measure variables because OSAF startup fails later.",
    },
    {
        "analysis_type": "diag",
        "category": "diagnostic",
        "summary": "Diagnostic/diagonal sampling.",
        "best_for": "Quick algorithmic diagnostic runs or diagonal perturbation-style checks.",
        "avoid_when": "You need a general-purpose sweep or optimization.",
        "start_sequence": ["diag", "batch_run"],
        "typical_algorithm_keys": ["experiment_type", "run_baseline"],
        "notes": "Specialized analysis type retained for server compatibility.",
    },
    {
        "analysis_type": "nsga_nrel",
        "category": "multi_objective_optimization",
        "summary": "NREL NSGA-II multi-objective evolutionary optimization.",
        "best_for": "Calibration or design optimization with multiple competing objectives and Pareto fronts.",
        "avoid_when": "You only have one objective or cannot afford many simulations.",
        "start_sequence": ["nsga_nrel", "batch_run"],
        "typical_algorithm_keys": [
            "number_of_samples",
            "generations",
            "tournament_size",
            "cprob",
            "xover_dist_idx",
            "mu_dist_idx",
            "mprob",
            "objective_functions",
        ],
        "notes": "Commonly used for calibration examples with objective_functions from reporting measures.",
    },
    {
        "analysis_type": "spea_nrel",
        "category": "multi_objective_optimization",
        "summary": "SPEA2-style multi-objective evolutionary optimization.",
        "best_for": "Alternative Pareto optimization behavior for multi-objective calibration/design studies.",
        "avoid_when": "A simple LHS or single-objective optimizer is sufficient.",
        "start_sequence": ["spea_nrel", "batch_run"],
        "typical_algorithm_keys": ["number_of_samples", "generations", "tournament_size", "cprob", "cidx", "midx", "mprob", "objective_functions"],
        "notes": "Similar use case to nsga_nrel, with different evolutionary selection mechanics.",
    },
    {
        "analysis_type": "pso",
        "category": "optimization",
        "summary": "Particle Swarm Optimization.",
        "best_for": "Continuous parameter calibration and search when swarm behavior is appropriate.",
        "avoid_when": "You need exhaustive sampling or formal sensitivity metrics.",
        "start_sequence": ["pso", "batch_run"],
        "typical_algorithm_keys": ["npart", "maxit", "maxfn", "lambda", "c1", "c2", "c_1", "c_2", "boundary", "topology", "xini", "vini", "method"],
        "notes": "Schema accepts both c1/c2 and legacy c_1/c_2 keys used in OpenStudio-server fixtures.",
    },
    {
        "analysis_type": "rgenoud",
        "category": "optimization",
        "summary": "Genetic optimization with derivative-based local search support.",
        "best_for": "Calibration/search problems that benefit from evolutionary search plus optional BFGS-style refinement.",
        "avoid_when": "You need a transparent grid/sampling study.",
        "start_sequence": ["rgenoud", "batch_run"],
        "typical_algorithm_keys": ["popsize", "generations", "wait_generations", "bfgsburnin", "bfgs", "solution_tolerance", "r_genoud_debug_flag"],
        "notes": "Schema accepts numeric, boolean, and string r_genoud_debug_flag values for legacy compatibility.",
    },
    {
        "analysis_type": "ga",
        "category": "optimization",
        "summary": "Single-population genetic algorithm.",
        "best_for": "Evolutionary search over discrete or mixed parameter spaces.",
        "avoid_when": "You need multi-objective Pareto optimization; use nsga_nrel or spea_nrel.",
        "start_sequence": ["ga", "batch_run"],
        "typical_algorithm_keys": ["popSize", "maxiter", "run", "pcrossover", "pmutation", "elitism"],
        "notes": "Use when a conventional GA is enough and islands/Pareto fronts are not needed.",
    },
    {
        "analysis_type": "gaisl",
        "category": "optimization",
        "summary": "Island-model genetic algorithm.",
        "best_for": "Evolutionary search where island populations and migration may improve exploration.",
        "avoid_when": "You need a small, quick, deterministic sampling run.",
        "start_sequence": ["gaisl", "batch_run"],
        "typical_algorithm_keys": ["popSize", "numIslands", "migrationRate", "migrationInterval", "maxiter", "run"],
        "notes": "More complex GA variant; tune population and migration settings carefully.",
    },
    {
        "analysis_type": "optim",
        "category": "optimization",
        "summary": "Local numerical optimization.",
        "best_for": "Smooth-ish calibration/design problems where local search is acceptable.",
        "avoid_when": "The response surface is discontinuous, highly multimodal, or dominated by discrete variables.",
        "start_sequence": ["optim", "batch_run"],
        "typical_algorithm_keys": ["method", "maxit", "factr", "pgtol", "epsilongradient"],
        "notes": "Usually needs good initial conditions and well-scaled objective functions.",
    },
    {
        "analysis_type": "preflight",
        "category": "diagnostic",
        "summary": "Preflight runs at min/max/mode or pivot samples.",
        "best_for": "Checking variable bounds and workflow viability before a larger run.",
        "avoid_when": "You need production results or final optimization.",
        "start_sequence": ["preflight", "batch_run"],
        "typical_algorithm_keys": ["run_min", "run_max", "run_mode", "run_all_samples_for_pivots"],
        "notes": "Useful as a guard before expensive studies.",
    },
    {
        "analysis_type": "repeat_run",
        "category": "diagnostic",
        "summary": "Repeated runs of the same or similar datapoint.",
        "best_for": "Debugging stochastic behavior, queue stability, or reproducibility.",
        "avoid_when": "You need parameter exploration.",
        "start_sequence": ["repeat_run", "batch_run"],
        "typical_algorithm_keys": ["number_of_runs"],
        "notes": "Mostly diagnostic and infrastructure-oriented.",
    },
    {
        "analysis_type": "baseline_perturbation",
        "category": "sampling",
        "summary": "Perturb variables around a baseline.",
        "best_for": "Exploring local changes from a known baseline model/configuration.",
        "avoid_when": "You need a broad global sample over full variable ranges.",
        "start_sequence": ["baseline_perturbation", "batch_run"],
        "typical_algorithm_keys": ["number_of_samples", "seed"],
        "notes": "Specialized compatibility analysis type.",
    },
)


class _NoRedirect(HTTPRedirectHandler):
    """Refuse redirects: a hostile server could bounce a request (and its auth header) elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, f"redirect to {newurl} refused", headers, fp)


def urlopen(req, timeout):
    """http(s)-only, redirect-free urlopen (no file://, ftp://, data:)."""
    opener = OpenerDirector()
    handlers = (
        HTTPHandler(),
        HTTPSHandler(),
        HTTPDefaultErrorHandler(),
        HTTPErrorProcessor(),
        UnknownHandler(),
        _NoRedirect(),
    )
    for handler in handlers:
        opener.add_handler(handler)
    return opener.open(req, timeout=timeout)


def _configured_server_url() -> str | None:
    url = (os.environ.get("OPENSTUDIO_SERVER_URL") or os.environ.get("OS_SERVER_URL") or "").strip()
    return url.rstrip("/") or None


def _api_token() -> str | None:
    return os.environ.get("OPENSTUDIO_API_TOKEN") or os.environ.get("OS_SERVER_API_TOKEN") or None


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    return parts.scheme, (parts.hostname or "").lower(), port


def _allowed_entry_matches(entry: str, origin: tuple[str, str, int | None]) -> bool:
    """One OSMCP_ANALYSIS_ALLOWED_HOSTS entry: `host`, `host:port` or `scheme://host[:port]`.

    A missing scheme or port matches any; a present one is pinned. Compared as origins,
    so `osa` == `osa:80` == `http://osa`.
    """
    raw = entry.strip().lower()
    if not raw:
        return False
    try:
        parts = urlsplit(raw if "://" in raw else "//" + raw)
        entry_port = parts.port
    except ValueError:
        return False
    scheme, host, port = origin
    if not parts.hostname or parts.hostname != host:
        return False
    if parts.scheme and parts.scheme != scheme:
        return False
    return entry_port is None or entry_port == port


def _same_server(a: str, b: str) -> bool:
    """Same origin AND same path prefix: `http://osa/admin` is not the configured `http://osa/prefix`."""
    return _origin(a) == _origin(b) and urlsplit(a).path.rstrip("/") == urlsplit(b).path.rstrip("/")


def _server_url_allowed(url: str) -> bool:
    """May a caller-supplied server_url be used on the shared HTTP server?"""
    origin = _origin(url)
    configured = _configured_server_url()
    if configured and _origin(configured) == origin:
        # The operator's server: only its exact base, so a caller cannot aim the
        # bearer token at another path on the same host.
        return _same_server(url, configured)
    extra = os.environ.get("OSMCP_ANALYSIS_ALLOWED_HOSTS", "")
    return any(_allowed_entry_matches(entry, origin) for entry in extra.split(","))


def _server_url(server_url: str | None = None) -> str:
    from mcp_server.identity import _is_http_transport

    configured = _configured_server_url()
    url = (server_url or configured or "").strip()
    if not url:
        raise ValueError("Missing server_url. Pass server_url or set OPENSTUDIO_SERVER_URL / OS_SERVER_URL.")
    # urlsplit silently drops tab/newline (WHATWG), but http.client then raises InvalidURL
    # on the raw string; refuse up front instead of surfacing a socket-layer error.
    if any(ch in url for ch in "\t\r\n "):
        raise ValueError(f"server_url must not contain whitespace, got {url!r}")
    if not url.isascii():  # http.client would raise UnicodeEncodeError on the request target
        raise ValueError(f"server_url must be ASCII, got {url!r}")
    url = url.rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"server_url must be an absolute http(s) URL, got {url!r}")
    # Endpoint paths are appended to this base; a '?' or '#' would push them into the
    # query/fragment and send the request (and token) to the caller's path instead.
    if "?" in url or "#" in url:
        raise ValueError(f"server_url must not contain a query or fragment, got {url!r}")
    try:
        _ = parts.port  # a non-numeric port raises here
    except ValueError:
        raise ValueError(f"server_url has an invalid port, got {url!r}") from None
    # The bearer token is only ever sent to the configured server; without one, a token
    # would be silently withheld and every call would fail with an unexplained 401.
    if not configured and _api_token():
        raise ValueError(
            "OPENSTUDIO_API_TOKEN is set but OPENSTUDIO_SERVER_URL is not. The token is only "
            "sent to the configured server, so set OPENSTUDIO_SERVER_URL to the server it belongs to.",
        )
    # On the shared HTTP server a tenant must not aim the server's network access at
    # arbitrary hosts (SSRF); only the operator-configured server or allowlisted hosts.
    if _is_http_transport() and not _server_url_allowed(url):
        raise ValueError(
            "server_url is not permitted on this server; use the operator-configured "
            "OPENSTUDIO_SERVER_URL (or a host in OSMCP_ANALYSIS_ALLOWED_HOSTS).",
        )
    return url


def _auth_headers(server_url: str) -> dict[str, str]:
    """Bearer header, sent only to the operator-configured server (never to a caller-chosen host)."""
    token = _api_token()
    configured = _configured_server_url()
    if not token or not configured or not _same_server(server_url, configured):
        return {}
    return {"Authorization": f"Bearer {token}"}


def _seg(value: Any) -> str:
    """One URL path segment: quote everything, including '/', so ids cannot traverse.

    quote() leaves '.' alone, and '.'/'..' segments are collapsed by servers and proxies,
    so dot-only (or empty) identifiers are refused outright.
    """
    text = str(value)
    if not text or set(text) <= {"."}:
        raise ValueError(f"invalid identifier {text!r}")
    return quote(text, safe="")


def _url(server_url: str, path: str) -> str:
    return f"{server_url}/{path.lstrip('/')}"


def _is_http_mode() -> bool:
    from mcp_server.identity import _is_http_transport

    return _is_http_transport()


def _is_analysis_path_allowed(path: Path, *, write: bool = False) -> bool:
    from mcp_server.config import is_path_allowed

    if is_path_allowed(path, write=write):
        return True
    from mcp_server.identity import _is_http_transport

    if _is_http_transport():
        return False  # /tmp is shared between tenants
    temp_root = Path(tempfile.gettempdir()).resolve()
    return path == temp_root or str(path).startswith(str(temp_root) + os.sep)


def _read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not _is_analysis_path_allowed(p):
        raise ValueError(f"JSON path is not allowed: {p}")
    # Opened by descriptor from the tenant root (#190): a component swapped for a link after
    # the check above fails the read instead of serving another tree's file.
    try:
        raw = read_file_bounded(p, MAX_JSON_BYTES)
    except ValueError as e:
        raise ValueError(f"JSON file not found or not readable: {p} ({e})") from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Invalid JSON in {p}: {e}") from None
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {p}")
    return data


def _write_json(path: str | Path, data: dict[str, Any]) -> str:
    p = Path(path).expanduser().resolve()
    if not _is_analysis_path_allowed(p, write=True):
        raise ValueError(f"Output path is not writable/allowed: {p}")
    # Parents created and the file written through the descriptor walk (#190): a component
    # swapped for a link after the check above is refused, nothing is created through it.
    try:
        DirHandle.open(p.parent, create=True).close()
        with open_nofollow_for_write(p) as fh:
            fh.write(json.dumps(data, indent=2) + "\n")
    except (OSError, ValueError) as e:
        raise ValueError(f"Output path is not writable: {p} ({e})") from None
    return str(p)


def _sha256_file(path: str | Path) -> str:
    """Hash of a seed or weather file; opened by descriptor, never through a link (#190)."""
    return sha256_regular_file_nofollow(Path(path).expanduser(), MAX_PACKAGE_FILE_BYTES)


# What reading one member of a tenant-built zip can raise besides the budget ValueError:
# a CRC mismatch (BadZipFile), a corrupt deflate stream (zlib.error), an encrypted member
# (RuntimeError from zipfile). Each is a validation issue, never an exception through MCP.
ZIP_MEMBER_ERRORS = (ValueError, zipfile.BadZipFile, zlib.error, RuntimeError)


def _zip_member_sha256(archive: zipfile.ZipFile, name: str, max_bytes: int) -> str:
    """sha256 of a member, refusing (ValueError) one that declares or decompresses past max_bytes.

    The declared size is checked first and the stream is counted as it is
    read: a member whose header lies about its size cannot be used to
    decompress without bound.
    """
    info = archive.getinfo(name)
    if info.file_size > max_bytes:
        raise ValueError(f"{name}: {info.file_size} bytes exceeds the {max_bytes}-byte limit")
    h = hashlib.sha256()
    total = 0
    with archive.open(name) as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"{name}: decompresses past the {max_bytes}-byte limit")
            h.update(chunk)
    return h.hexdigest()


def _identity_matches(record: dict[str, Any], identity: dict[str, str | None]) -> bool:
    """All three identity keys are present in `record` (manifest or run record) and equal `identity`.

    A record without the keys (written before resources were part of the
    identity, or by a run that was not a plain seed simulation) never matches.
    """
    return all(key in record for key in IDENTITY_KEYS) and all(record[key] == identity[key] for key in IDENTITY_KEYS)


def _read_run_record(run_dir: Path, root: Path) -> dict[str, Any] | None:
    """run_record.json of a run under the caller's root, read without following links, else None."""
    meta = run_dir / "run_record.json"
    if not is_regular_file_inside(meta, root):
        return None
    try:
        data = json.loads(read_file_bounded(meta, MAX_RUN_RECORD_BYTES).decode("utf-8", errors="replace"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _find_completed_seed_run(identity: dict[str, str | None]) -> dict[str, Any] | None:
    """The newest successful run whose recorded identity equals `identity`, else None.

    Only the triple run_simulation wrote at launch is compared: nothing in the
    run dir (written by the tenant's sandboxed process) is rehashed, the run
    is the directory the record was found in (never the record's own run_dir
    field), and eplusout.sql must be a regular file inside it.
    """
    from mcp_server.config import user_run_root

    root = user_run_root()
    if not root.exists():
        return None

    matches: list[dict[str, Any]] = []
    for run_dir in sorted(root.glob("run_*")):
        if run_dir.is_symlink() or not run_dir.is_dir():
            continue
        data = _read_run_record(run_dir, root)
        if not data or data.get("status") != "success" or not _identity_matches(data, identity):
            continue
        if not any(is_regular_file_inside(run_dir / rel, run_dir) for rel in ("run/eplusout.sql", "eplusout.sql")):
            continue
        matches.append(
            {
                "run_id": run_dir.name,
                "run_dir": str(run_dir),
                "created_at": data.get("created_at") or 0,
                "ended_at": data.get("ended_at") or 0,
            },
        )
    if not matches:
        return None
    matches.sort(key=lambda item: float(item.get("ended_at") or item.get("created_at") or 0), reverse=True)
    return matches[0]


def _basic_seed_qaqc(run_id: str) -> dict[str, Any]:
    """Basic post-simulation QA/QC suitable for gating OSAF packaging."""
    from mcp_server.skills.results.operations import extract_simulation_errors_op, extract_summary_metrics
    from mcp_server.skills.simulation.operations import get_run_status

    issues: list[str] = []
    status = get_run_status(run_id)
    run = status.get("run") if isinstance(status.get("run"), dict) else {}
    if not status.get("ok") or run.get("status") != "success":
        issues.append(f"Simulation run is not successful: {run.get('status') or status.get('error')}")

    errors = extract_simulation_errors_op(run_id)
    fatal_count = len(errors.get("fatal") or []) if errors.get("ok") else None
    severe_count = len(errors.get("severe") or []) if errors.get("ok") else None
    warning_count = errors.get("warning_count") if errors.get("ok") else None
    if not errors.get("ok"):
        issues.append(f"Could not parse EnergyPlus errors: {errors.get('message') or errors.get('error')}")
    else:
        if fatal_count:
            issues.append(f"EnergyPlus reported {fatal_count} fatal error(s)")
        if severe_count:
            issues.append(f"EnergyPlus reported {severe_count} severe error(s)")

    metrics = extract_summary_metrics(run_id)
    if not metrics.get("ok"):
        issues.append(f"Could not extract summary metrics: {metrics.get('message') or metrics.get('error')}")
    else:
        warnings = list(metrics.get("warnings") or [])
        issues.extend(warnings)
        metric_data = metrics.get("metrics") if isinstance(metrics.get("metrics"), dict) else {}
        total_site = metric_data.get("total_site_energy") if isinstance(metric_data.get("total_site_energy"), dict) else {}
        if total_site.get("value") is None:
            issues.append("Summary metrics did not include total site energy")

    return {
        "ok": not issues,
        "passed": not issues,
        "issues": issues,
        "run_status": status,
        "error_summary": {
            "fatal_count": fatal_count,
            "severe_count": severe_count,
            "warning_count": warning_count,
        },
        "summary_metrics": metrics,
    }


def _manifest_predates_resource_identity(manifest: dict[str, Any]) -> bool:
    """A manifest written before the resource set was part of the seed identity."""
    return any(key not in manifest for key in IDENTITY_KEYS)


def _manifest_is_valid(manifest: dict[str, Any]) -> bool:
    if manifest.get("ok") is not True:
        return False
    if not manifest.get("seed_sha256") or _manifest_predates_resource_identity(manifest):
        return False
    qaqc = manifest.get("basic_qaqc")
    if not isinstance(qaqc, dict) or qaqc.get("passed") is not True:
        return False
    return bool(manifest.get("run_id"))


def _read_manifest(path: Path) -> dict[str, Any] | None:
    """The manifest as a dict, read without following a link at its name, else None."""
    try:
        data = json.loads(read_file_bounded(path, MAX_MANIFEST_BYTES).decode("utf-8", errors="replace"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _osa_schema_path(schema_path: str | Path | None = None) -> Path:
    if schema_path is not None:
        return Path(schema_path).expanduser().resolve()
    for env_var in OSA_SCHEMA_ENV_VARS:
        value = os.environ.get(env_var)
        if value:
            return Path(value).expanduser().resolve()
    return DEFAULT_OSA_SCHEMA_PATH


def _read_osa_schema(schema_path: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    path = _osa_schema_path(schema_path)
    # The bundled/env schema is operator-owned; a caller-supplied path is tenant input.
    if schema_path is not None and not _is_analysis_path_allowed(path):
        raise ValueError(f"Schema path is not allowed: {path}")
    try:
        if schema_path is not None:  # tenant input: opened by descriptor from its root (#190)
            schema = json.loads(read_file_bounded(path, MAX_JSON_BYTES).decode("utf-8"))
        else:
            schema = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"OSA JSON schema not found: {path}") from None
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid OSA JSON schema in {path}: {e}") from None
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"OSA JSON schema not readable: {path} ({e})") from None
    if not isinstance(schema, dict):
        raise ValueError(f"Expected OSA JSON schema object in {path}")
    try:
        Draft4Validator.check_schema(schema)
    except SchemaError as e:
        raise ValueError(f"Invalid Draft 4 OSA JSON schema in {path}: {e.message}") from None
    return path, schema


def _json_path(parts: Iterable[str | int]) -> str:
    rendered = "$"
    for part in parts:
        if isinstance(part, int):
            rendered += f"[{part}]"
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part):
            rendered += f".{part}"
        else:
            rendered += f"[{part!r}]"
    return rendered


def _refuse_remote_ref(uri: str):
    raise NoSuchResource(ref=uri)


def _schema_issues(data: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    # A tenant-supplied schema may carry a remote $ref; jsonschema would fetch it with its
    # own urllib (http, file, redirects), bypassing every gate in this module. The registry
    # below refuses all retrieval; '#/...' refs still resolve from the root resource.
    validator = Draft4Validator(schema, registry=Registry(retrieve=_refuse_remote_ref))
    try:
        errors = sorted(validator.iter_errors(data), key=lambda e: (list(e.absolute_path), e.message))
    except Unresolvable as e:
        raise ValueError(f"OSA JSON schema contains a remote or unresolvable $ref: {e}") from None
    return [f"{_json_path(error.absolute_path)}: {error.message}" for error in errors]


def _normalize_seed_file(seed: dict[str, Any] | str | None) -> dict[str, Any] | None:
    if seed is None:
        return None
    if isinstance(seed, dict):
        return seed
    suffix = Path(seed).suffix.lower()
    return {"file_type": "OSW" if suffix == ".osw" else "OSM", "path": seed}


def _normalize_weather_file(weather_file: dict[str, Any] | str | None) -> dict[str, Any] | None:
    if weather_file is None:
        return None
    if isinstance(weather_file, dict):
        return weather_file
    suffix = Path(weather_file).suffix.lower().lstrip(".")
    return {"file_type": suffix.upper() or "EPW", "path": weather_file}


def _normalize_output_variable(output_variable: dict[str, Any]) -> dict[str, Any]:
    variable = dict(output_variable)
    name = str(variable.get("name") or "")
    if not name and variable.get("report") and variable.get("report_file") and variable.get("var_name"):
        parts = [variable["report"], variable["report_file"], variable["var_name"]]
        if variable.get("end_use"):
            parts.append(variable["end_use"])
        if variable.get("end_use_category"):
            parts.append(variable["end_use_category"])
        name = ".".join(str(part) for part in parts)
        variable["name"] = name
    display_name = variable.get("display_name") or name
    variable.setdefault("display_name", display_name)
    variable.setdefault("display_name_short", display_name)
    variable.setdefault("objective_function", False)
    variable.setdefault("objective_function_index", None)
    variable.setdefault("objective_function_target", None)
    variable.setdefault("scaling_factor", None)
    variable.setdefault("objective_function_group", None)
    variable.setdefault("metadata_id", None)
    variable.setdefault("visualize", True)
    variable.setdefault("export", True)
    variable.setdefault("variable_type", "double")
    return variable


def _normalize_workflow(workflow: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, step in enumerate(workflow or []):
        item = dict(step)
        item["workflow_index"] = index
        variables = item.get("variables")
        if isinstance(variables, list):
            for variable in variables:
                if isinstance(variable, dict):
                    variable["workflow_index"] = index
        normalized.append(item)
    return normalized


def _default_output_variables() -> list[dict[str, Any]]:
    return [dict(variable) for variable in DEFAULT_OUTPUT_VARIABLES]


def get_default_output_variables() -> dict[str, Any]:
    """Return the foundational OSAF output variables used by default analysis JSON creation."""
    return {
        "ok": True,
        "output_variables": _default_output_variables(),
        "count": len(DEFAULT_OUTPUT_VARIABLES),
        "names": [str(variable["name"]) for variable in DEFAULT_OUTPUT_VARIABLES],
    }


def get_osaf_algorithms(category: str | None = None) -> dict[str, Any]:
    """Return supported OSAF analysis algorithms and when to use them."""
    algorithms = [dict(algorithm) for algorithm in OSAF_ALGORITHMS]
    categories = sorted({str(algorithm["category"]) for algorithm in algorithms})
    if category:
        normalized = category.strip().lower()
        algorithms = [
            algorithm
            for algorithm in algorithms
            if str(algorithm["category"]).lower() == normalized
            or str(algorithm["analysis_type"]).lower() == normalized
        ]
    return {
        "ok": True,
        "algorithms": algorithms,
        "count": len(algorithms),
        "categories": categories,
        "analysis_types": [str(algorithm["analysis_type"]) for algorithm in algorithms],
        "notes": [
            "For sampled/algorithm-generated analyses, start the algorithm action first, then batch_run.",
            "For single_run smoke tests, start single_run first, then batch_run.",
            "Do not use DOE with only one real measure variable; use lhs or single_run instead.",
        ],
    }


def _common_measures_dir() -> Path:
    return Path(os.environ.get("COMMON_MEASURES_DIR", "/opt/common-measures")).expanduser().resolve()


def _foundational_measure_path(measure_name: str) -> Path:
    return _common_measures_dir() / measure_name


def get_foundational_analysis_measures() -> dict[str, Any]:
    measures: list[dict[str, Any]] = []
    missing: list[str] = []
    for spec in FOUNDATIONAL_ANALYSIS_MEASURES:
        measure_name = str(spec["measure_name"])
        path = _foundational_measure_path(measure_name)
        entry = {**spec, "measure_dir": str(path), "available": path.is_dir()}
        measures.append(entry)
        if not path.is_dir():
            missing.append(measure_name)
    return {
        "ok": not missing,
        "common_measures_dir": str(_common_measures_dir()),
        "measure_names": [str(spec["measure_name"]) for spec in FOUNDATIONAL_ANALYSIS_MEASURES],
        "measures": measures,
        "missing": missing,
        "error": None if not missing else f"Missing foundational analysis measures: {', '.join(missing)}",
    }


def _workflow_measure_names(workflow: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for step in workflow:
        if not isinstance(step, dict):
            continue
        for key in ("measure_definition_name", "measure_definition_name_xml", "name"):
            value = step.get(key)
            if value:
                names.add(str(value))
    return names


def _foundational_measure_names() -> list[str]:
    return [str(spec["measure_name"]) for spec in FOUNDATIONAL_ANALYSIS_MEASURES]


def _missing_foundational_workflow_measures(problem: dict[str, Any]) -> list[str]:
    workflow = problem.get("workflow")
    if not isinstance(workflow, list):
        return _foundational_measure_names()
    workflow_names = _workflow_measure_names(workflow)
    return [name for name in _foundational_measure_names() if name not in workflow_names]


def _foundational_analysis_workflow_steps(existing_workflow: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_names = _workflow_measure_names(existing_workflow)
    steps: list[dict[str, Any]] = []
    for spec in FOUNDATIONAL_ANALYSIS_MEASURES:
        measure_name = str(spec["measure_name"])
        if measure_name in existing_names:
            continue
        measure_dir = _foundational_measure_path(measure_name)
        if not measure_dir.is_dir():
            raise ValueError(
                f"Foundational analysis measure '{measure_name}' not found at {measure_dir}. "
                "Set COMMON_MEASURES_DIR so analysis JSON creation can include foundational measures.",
            )
        steps.append(
            build_measure_workflow_step(
                str(measure_dir),
                arguments=dict(spec.get("arguments") or {}),
                instance_name=str(spec.get("instance_name") or measure_name),
                display_name=str(spec.get("display_name") or measure_name),
            )
        )
    return steps


def _normalize_analysis_workflow(workflow: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized = _normalize_workflow(workflow)
    normalized.extend(_foundational_analysis_workflow_steps(normalized))
    for index, step in enumerate(normalized):
        step["workflow_index"] = index
    return normalized


def _zip_member_parts(name: str) -> list[str]:
    normalized = name.replace("\\", "/")
    return [part for part in normalized.split("/") if part]


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _measure_dirs(entries: list[str]) -> dict[str, set[str]]:
    measures: dict[str, set[str]] = {}
    for name in entries:
        parts = _zip_member_parts(name)
        if len(parts) < 3 or parts[0] != "measures":
            continue
        measure_name = parts[1]
        measures.setdefault(measure_name, set()).add(parts[-1])
    return measures


def _text(parent: ET.Element, path: str, default: str | None = None) -> str | None:
    child = parent.find(path)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower() or "measure"


def _measure_type(root: ET.Element) -> str:
    for attr in root.findall("./attributes/attribute"):
        if _text(attr, "name") == "Measure Type":
            return _text(attr, "value", "ModelMeasure") or "ModelMeasure"
    return "ModelMeasure"


def _coerce_value(value_type: str, value: Any) -> Any:
    if value is None:
        return None
    kind = value_type.lower()
    if kind == "double":
        return float(value)
    if kind == "integer":
        return int(value)
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes", "y"}
    return str(value)


def _read_measure_metadata(measure_dir: str | Path) -> dict[str, Any]:
    measure_path = Path(measure_dir).expanduser().resolve()
    if not _is_analysis_path_allowed(measure_path):
        raise ValueError(f"Measure directory is not allowed: {measure_path}")
    if not measure_path.is_dir():
        raise ValueError(f"Measure directory not found: {measure_path}")
    xml_path = measure_path / "measure.xml"
    if xml_path.is_symlink() or not _is_analysis_path_allowed(xml_path.resolve()):
        raise ValueError(f"measure.xml is not allowed: {xml_path}")
    if not xml_path.is_file():
        raise ValueError(f"measure.xml not found in measure directory: {measure_path}")

    root = ET.parse(xml_path).getroot()
    arguments: list[dict[str, Any]] = []
    for arg in root.findall("./arguments/argument"):
        raw_type = (_text(arg, "type", "String") or "String").lower()
        value_type = "string" if raw_type == "choice" else raw_type
        default_value = _coerce_value(value_type, _text(arg, "default_value"))
        display_name = _text(arg, "display_name") or _text(arg, "name", "Argument") or "Argument"
        arguments.append(
            {
                "display_name": display_name,
                "display_name_short": display_name,
                "name": _text(arg, "name", "") or "",
                "value_type": value_type,
                "default_value": default_value,
                "value": default_value,
            }
        )

    display_name = _text(root, "display_name") or _text(root, "name", measure_path.name) or measure_path.name
    return {
        "measure_path": measure_path,
        "name": _text(root, "name", measure_path.name) or measure_path.name,
        "display_name": display_name,
        "class_name": _text(root, "class_name"),
        "uid": _text(root, "uid") or str(uuid.uuid4()),
        "version_id": _text(root, "version_id") or str(uuid.uuid4()),
        "description": _text(root, "description"),
        "measure_type": _measure_type(root),
        "arguments": arguments,
    }


def _validate_distribution(distribution: dict[str, Any]) -> dict[str, Any]:
    dist = dict(distribution)
    if "mean" in dist and "mode" not in dist:
        dist["mode"] = dist["mean"]
    dist_type = str(dist.get("type", "")).lower()
    if dist_type not in SUPPORTED_DISTRIBUTIONS:
        raise ValueError(
            f"Unsupported distribution type '{dist.get('type')}'. "
            f"Use one of: {', '.join(sorted(SUPPORTED_DISTRIBUTIONS))}."
        )
    for key in ("minimum", "maximum", "mode"):
        if key not in dist:
            raise ValueError(f"Distribution '{dist_type}' is missing required key '{key}'.")
    if dist_type in {"normal", "lognormal"} and "standard_deviation" not in dist:
        raise ValueError(f"Distribution '{dist_type}' requires standard_deviation.")
    if dist_type == "discrete":
        values = dist.get("values")
        if not isinstance(values, list) or not values:
            raise ValueError("Discrete distribution requires a non-empty values list.")
        weights = dist.get("weights")
        if weights is None:
            dist["weights"] = [1 / len(values)] * len(values)
        elif not isinstance(weights, list) or len(weights) != len(values):
            raise ValueError("Discrete distribution weights must match values length.")
    return dist


def _variable_from_spec(argument: dict[str, Any], spec: dict[str, Any], workflow_index: int) -> dict[str, Any]:
    distribution = _validate_distribution(spec.get("distribution") or spec)
    static_value = spec.get("static_value", argument.get("default_value"))
    variable_type = spec.get("variable_type", "variable")
    variable: dict[str, Any] = {
        "argument": {**argument, "value": static_value},
        "display_name": spec.get("display_name") or argument["display_name"],
        "display_name_short": (
            spec.get("display_name_short") or spec.get("display_name") or argument["display_name_short"]
        ),
        "variable_type": variable_type,
        "static_value": static_value,
        "minimum": distribution["minimum"],
        "maximum": distribution["maximum"],
        "relation_to_output": distribution.get("relation_to_output"),
        "workflow_index": workflow_index,
        "uuid": str(uuid.uuid4()),
        "version_uuid": str(uuid.uuid4()),
        "uncertainty_description": {
            "type": distribution["type"],
            "attributes": [
                {"name": "lower_bounds", "value": distribution["minimum"]},
                {"name": "upper_bounds", "value": distribution["maximum"]},
                {"name": "modes", "value": distribution["mode"]},
                {"name": "delta_x", "value": distribution.get("step_size")},
                {"name": "stddev", "value": distribution.get("standard_deviation")},
            ],
        },
    }
    variable["pivot" if variable_type == "pivot" else "variable"] = True
    if distribution["type"] == "discrete":
        variable["uncertainty_description"]["attributes"].insert(
            0,
            {
                "name": "discrete",
                "values_and_weights": [
                    {"value": value, "weight": weight}
                    for value, weight in zip(distribution["values"], distribution["weights"])
                ],
            },
        )
    return variable


def build_measure_workflow_step(
    measure_dir: str,
    *,
    arguments: dict[str, Any] | None = None,
    variables: list[dict[str, Any]] | None = None,
    instance_name: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    metadata = _read_measure_metadata(measure_dir)
    measure_path = metadata["measure_path"]
    arg_by_name = {arg["name"]: dict(arg) for arg in metadata["arguments"]}
    for name, value in (arguments or {}).items():
        if name not in arg_by_name:
            raise ValueError(f"Measure '{metadata['name']}' has no argument named '{name}'.")
        arg_by_name[name]["value"] = _coerce_value(arg_by_name[name]["value_type"], value)

    variable_names = set()
    workflow_variables = []
    for index, spec in enumerate(variables or []):
        arg_name = spec.get("argument_name") or spec.get("name")
        if not arg_name:
            raise ValueError("Each variable spec must include argument_name.")
        if arg_name not in arg_by_name:
            raise ValueError(f"Measure '{metadata['name']}' has no argument named '{arg_name}'.")
        variable_names.add(arg_name)
        workflow_variables.append(_variable_from_spec(arg_by_name[arg_name], spec, index))

    static_arguments = [arg for name, arg in arg_by_name.items() if name not in variable_names]
    return {
        "measure_type": metadata["measure_type"],
        "name": instance_name or _slug(metadata["name"]),
        "display_name": display_name or metadata["display_name"],
        "measure_definition_class_name": metadata["class_name"],
        "measure_definition_directory": f"./measures/{measure_path.name}",
        "measure_definition_directory_local": str(measure_path),
        "measure_definition_display_name": metadata["display_name"],
        "measure_definition_name": metadata["name"],
        "measure_definition_name_xml": metadata["name"],
        "measure_definition_uuid": metadata["uid"],
        "measure_definition_version_uuid": metadata["version_id"],
        "uuid": metadata["uid"],
        "version_uuid": metadata["version_id"],
        "description": metadata["description"],
        "arguments": static_arguments,
        "variables": workflow_variables,
    }


def _request_json(
    method: str,
    server_url: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    headers = {"Accept": "application/json", **_auth_headers(server_url)}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(_url(server_url, path), data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"response": parsed}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenStudio Server HTTP {e.code} for {path}: {detail}") from None
    except URLError as e:
        raise RuntimeError(f"Could not reach OpenStudio Server at {server_url}: {e.reason}") from None
    except HTTPException as e:
        raise RuntimeError(f"Invalid request to OpenStudio Server at {server_url}: {e}") from None


def _request_form(
    method: str,
    server_url: str,
    path: str,
    *,
    form: dict[str, Any],
    timeout: int = 600,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        **_auth_headers(server_url),
    }
    data = urlencode({key: str(value) for key, value in form.items() if value is not None}).encode("utf-8")
    req = Request(_url(server_url, path), data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw.strip() else {}
            return {"ok": True, "status": resp.status, "response": parsed}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"OpenStudio Server HTTP {e.code} for {path}: {detail}"}
    except URLError as e:
        return {"ok": False, "error": f"Could not reach OpenStudio Server at {server_url}: {e.reason}"}
    except HTTPException as e:
        return {"ok": False, "error": f"Invalid request to OpenStudio Server at {server_url}: {e}"}


def _download(
    server_url: str,
    path: str,
    output_dir: str | Path,
    fallback_name: str,
    *,
    timeout: int = 3600,
) -> dict[str, Any]:
    out_dir = Path(output_dir).expanduser().resolve()
    if not _is_analysis_path_allowed(out_dir, write=True):  # before any request: no fetch for a refused dir
        return {"ok": False, "error": f"Output directory is not writable/allowed: {out_dir}"}
    req = Request(_url(server_url, path), headers={"Accept": "*/*", **_auth_headers(server_url)}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            disposition = resp.headers.get("content-disposition", "")
            match = re.search(r'filename="?([^";]+)"?', disposition, flags=re.IGNORECASE)
            filename = match.group(1) if match else fallback_name
            safe_name = "".join(c if c.isalnum() or c in ("-", "_", ".", " ") else "_" for c in filename).strip()
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / (safe_name or fallback_name)
            # The dir is the caller's, but a symlink planted inside it would redirect
            # write_bytes anywhere (another tenant's file); refuse rather than follow.
            if out_path.is_symlink() or (out_path.exists() and not out_path.is_file()):
                return {"ok": False, "error": f"Refusing to write through a symlink or non-file: {out_path}"}
            out_path.write_bytes(body)
            return {
                "ok": True,
                "output_path": str(out_path),
                "bytes": len(body),
                "content_type": resp.headers.get("content-type"),
            }
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"OpenStudio Server HTTP {e.code} for {path}: {detail}"}
    except URLError as e:
        return {"ok": False, "error": f"Could not reach OpenStudio Server at {server_url}: {e.reason}"}
    except HTTPException as e:
        return {"ok": False, "error": f"Invalid request to OpenStudio Server at {server_url}: {e}"}


def _multipart_upload(server_url: str, path: str, file_path: str | Path, *, timeout: int = 1800) -> dict[str, Any]:
    p = Path(file_path).expanduser().resolve()
    if not _is_analysis_path_allowed(p):
        return {"ok": False, "error": f"Upload file path is not allowed: {p}"}
    if not p.exists():
        return {"ok": False, "error": f"Upload file not found: {p}"}
    try:
        payload = read_file_bounded(p, MAX_UPLOAD_BYTES)  # by descriptor from the tenant root (#190)
    except ValueError as e:
        return {"ok": False, "error": f"Upload file could not be read: {e}"}
    boundary = f"----openstudio-mcp-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(str(p))[0] or "application/zip"
    parts = [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{p.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode(),
        payload,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
        "Accept": "application/json",
        **_auth_headers(server_url),
    }
    req = Request(_url(server_url, path), data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            return {"ok": True, "status": resp.status, "response": parsed}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"OpenStudio Server HTTP {e.code} for upload: {detail}"}
    except URLError as e:
        return {"ok": False, "error": f"Could not reach OpenStudio Server at {server_url}: {e.reason}"}


def create_osa_json(
    output_path: str,
    analysis_name: str,
    analysis_type: str = "single_run",
    workflow: list[dict[str, Any]] | None = None,
    output_variables: list[dict[str, Any]] | None = None,
    algorithm: dict[str, Any] | None = None,
    extra_analysis_fields: dict[str, Any] | None = None,
    seed: dict[str, Any] | str | None = None,
    weather_file: dict[str, Any] | str | None = None,
    file_format_version: int = 1,
    schema_path: str | None = None,
    validate_after_create: bool = True,
) -> dict[str, Any]:
    analysis_uuid = str(uuid.uuid4())
    machine_name = re.sub(r"[^a-zA-Z0-9_]+", "_", analysis_name).strip("_").lower() or "analysis"
    normalized_output_variables = output_variables if output_variables is not None else _default_output_variables()
    try:
        analysis = {
            "display_name": analysis_name,
            "name": machine_name,
            "uuid": analysis_uuid,
            "output_variables": [_normalize_output_variable(v) for v in normalized_output_variables],
            "file_format_version": file_format_version,
            "problem": {
                "analysis_type": analysis_type,
                "algorithm": algorithm or {},
                "workflow": _normalize_analysis_workflow(workflow),
            },
        }
        normalized_seed = _normalize_seed_file(seed)
        if normalized_seed is not None:
            analysis["seed"] = normalized_seed
        normalized_weather = _normalize_weather_file(weather_file)
        if normalized_weather is not None:
            analysis["weather_file"] = normalized_weather
        analysis_fields = dict(SAFE_ANALYSIS_FIELD_DEFAULTS)
        if extra_analysis_fields:
            analysis_fields.update(extra_analysis_fields)
        analysis.update(analysis_fields)

        path = _write_json(output_path, {"analysis": analysis})
        result = {"ok": True, "osa_json_path": path, "analysis_id": analysis_uuid, "analysis": analysis}
        if validate_after_create:
            result["validation"] = validate_osa_json(
                path,
                schema_path=schema_path,
                require_foundational_measures=True,
            )
        return result
    except ValueError as e:
        return {"ok": False, "error": str(e)}


def create_osa_json_from_measures(
    output_path: str,
    analysis_name: str,
    measure_specs: list[dict[str, Any]],
    analysis_type: str = "single_run",
    algorithm: dict[str, Any] | None = None,
    output_variables: list[dict[str, Any]] | None = None,
    extra_analysis_fields: dict[str, Any] | None = None,
    seed: dict[str, Any] | str | None = None,
    weather_file: dict[str, Any] | str | None = None,
    file_format_version: int = 1,
    schema_path: str | None = None,
    validate_after_create: bool = True,
) -> dict[str, Any]:
    """Create an OSA JSON file from measure directories and variable specs."""
    try:
        workflow = [
            build_measure_workflow_step(
                spec["measure_dir"],
                arguments=spec.get("arguments"),
                variables=spec.get("variables"),
                instance_name=spec.get("instance_name"),
                display_name=spec.get("display_name"),
            )
            for spec in measure_specs
        ]
        return create_osa_json(
            output_path=output_path,
            analysis_name=analysis_name,
            analysis_type=analysis_type,
            workflow=workflow,
            output_variables=output_variables,
            algorithm=algorithm,
            extra_analysis_fields=extra_analysis_fields,
            seed=seed,
            weather_file=weather_file,
            file_format_version=file_format_version,
            schema_path=schema_path,
            validate_after_create=validate_after_create,
        )
    except (KeyError, ValueError) as e:
        return {"ok": False, "error": str(e)}


def add_measure_to_osa_json(
    osa_json_path: str,
    measure_dir: str,
    arguments: dict[str, Any] | None = None,
    variables: list[dict[str, Any]] | None = None,
    instance_name: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Append a measure workflow step to an existing OSA JSON file."""
    try:
        data = _read_json(osa_json_path)
        analysis = data.setdefault("analysis", {})
        problem = analysis.setdefault("problem", {})
        workflow = problem.setdefault("workflow", [])
        if not isinstance(workflow, list):
            return {"ok": False, "error": "analysis.problem.workflow must be an array."}
        step = build_measure_workflow_step(
            measure_dir,
            arguments=arguments,
            variables=variables,
            instance_name=instance_name,
            display_name=display_name,
        )
        workflow.append(step)
        for index, workflow_step in enumerate(workflow):
            if isinstance(workflow_step, dict):
                workflow_step.setdefault("workflow_index", index)
        path = _write_json(osa_json_path, data)
        return {
            "ok": True,
            "osa_json_path": path,
            "workflow_count": len(workflow),
            "measure_step": step,
            "validation": validate_osa_json(path),
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}


def _effective_weather(seed: Path) -> Path | None:
    """The EPW run_simulation would stage for `seed` with no override: the model's own, same gate."""
    from mcp_server.skills.weather.operations import resolve_model_weather_epw

    epw = resolve_model_weather_epw(seed)["epw"]
    return Path(epw) if epw is not None else None


def preflight_seed_for_analysis_package(
    seed_path: str,
    weather_file: str | None = None,
    manifest_path: str | None = None,
    *,
    template: str = "90.1-2019",
    force_rerun: bool = False,
    wait_timeout_seconds: int = 0,
    poll_interval_seconds: int = 30,
) -> dict[str, Any]:
    """Ensure an OSAF seed has simulated and passed basic QA/QC.

    The seed's identity is the OSM, the effective weather file (the one
    passed, else the model's own, as run_simulation resolves it) and its
    resource set (companion folder, see model_bundle.resources_digest). An
    existing manifest or a completed run_simulation run is reused only when
    its recorded identity equals all three. If no completed run exists,
    starts one with run_simulation. The manifest is written only when the
    simulation is successful and QA/QC passes.
    """
    from mcp_server.config import is_path_allowed, user_run_root
    from mcp_server.skills.simulation.operations import get_run_status, run_simulation

    seed = Path(seed_path).expanduser()
    if seed.is_symlink():
        return {"ok": False, "ready": False, "error": f"Seed path is a symlink (not allowed): {seed}"}
    seed = seed.resolve()
    if not seed.exists():
        return {"ok": False, "ready": False, "error": f"Seed model not found: {seed}"}
    if seed.suffix.lower() != ".osm":
        return {"ok": False, "ready": False, "error": "Seed preflight currently requires an .osm seed model."}
    if not is_path_allowed(seed):
        return {"ok": False, "ready": False, "error": f"Seed path is not allowed: {seed}"}
    manifest: Path | None = None
    if manifest_path:
        # The link check is on the path as given: resolve() would hand back the
        # link's target, which is never itself a link.
        manifest = Path(manifest_path).expanduser()
        if manifest.is_symlink():
            return {"ok": False, "ready": False, "error": f"Manifest path is a symlink (not allowed): {manifest}"}
        manifest = manifest.resolve()
        if not _is_analysis_path_allowed(manifest, write=True):
            return {"ok": False, "ready": False, "error": f"Manifest path is not writable/allowed: {manifest}"}

    epw: Path | None = None
    if weather_file:
        epw = Path(weather_file).expanduser().resolve()
        if not epw.exists():
            return {"ok": False, "ready": False, "error": f"Weather file not found: {epw}"}
        if epw.suffix.lower() != ".epw":
            return {"ok": False, "ready": False, "error": "Seed preflight weather_file must be an .epw file."}
        if not is_path_allowed(epw):
            return {"ok": False, "ready": False, "error": f"Weather path is not allowed: {epw}"}
    else:
        epw = _effective_weather(seed)

    try:
        seed_hash = _sha256_file(seed)
        epw_hash = _sha256_file(epw) if epw else None
    except (OSError, ValueError) as e:
        return {"ok": False, "ready": False, "error": f"Seed or weather file could not be hashed: {e}"}
    try:
        resources = resources_digest(seed)
    except ValueError as e:
        return {"ok": False, "ready": False, "error": f"Seed resources could not be hashed: {e}"}
    identity: dict[str, str | None] = {
        "seed_sha256": seed_hash, "weather_sha256": epw_hash, "resources_sha256": resources["sha256"],
    }
    if manifest and manifest.exists() and not force_rerun:
        existing_manifest = _read_manifest(manifest)
        if (
            existing_manifest
            and _manifest_is_valid(existing_manifest)
            and _identity_matches(existing_manifest, identity)
        ):
            return {
                "ok": True,
                "ready": True,
                "reused": True,
                "source": "manifest",
                "manifest_path": str(manifest),
                "manifest": existing_manifest,
            }

    cached_run = None if force_rerun else _find_completed_seed_run(identity)
    run_id: str | None = None
    reused = False
    if cached_run:
        run_id = str(cached_run["run_id"])
        reused = True
    else:
        started = run_simulation(
            osm_path=str(seed),
            epw_path=str(epw) if epw else None,
            name=f"analysis_seed_preflight_{seed.stem}",
        )
        if not started.get("ok"):
            return {"ok": False, "ready": False, "error": "Could not start seed simulation.", "simulation": started}
        run_id = str(started["run_id"])

        deadline = time.time() + max(0, int(wait_timeout_seconds))
        while wait_timeout_seconds > 0:
            status = get_run_status(run_id)
            run = status.get("run") if isinstance(status.get("run"), dict) else {}
            if run.get("status") in DONE_STATUSES or run.get("status") in FAILED_STATUSES:
                break
            if time.time() >= deadline:
                break
            time.sleep(max(1, int(poll_interval_seconds)))

        status = get_run_status(run_id)
        run = status.get("run") if isinstance(status.get("run"), dict) else {}
        if run.get("status") not in DONE_STATUSES:
            return {
                "ok": True,
                "ready": False,
                "reused": False,
                "status": run.get("status"),
                "run_id": run_id,
                "simulation": started,
                "message": "Seed simulation has started but is not complete; rerun this preflight after it finishes.",
            }
        # The run hashed its own staged snapshot; the identity above was taken
        # from the source files before the copy. Different means the seed, its
        # weather file or a resource changed in between: that run is not
        # evidence for the seed as it is now.
        root = user_run_root()
        try:
            record = _read_run_record(resolve_run_dir(root, run_id), root)
        except FileNotFoundError:
            record = None
        if record is None or not _identity_matches(record, identity):
            return {
                "ok": False, "ready": False, "run_id": run_id,
                "error": "The seed model, its weather file or its resources changed while the preflight "
                         "simulation ran; run the preflight again.",
            }

    qaqc = _basic_seed_qaqc(run_id)
    ready = bool(qaqc.get("passed"))
    result_manifest = {
        "ok": ready,
        "schema": "openstudio-mcp.analysis.seed_qaqc.v1",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed_file": str(seed),
        "seed_sha256": seed_hash,
        "weather_file": str(epw) if epw else None,
        "weather_sha256": epw_hash,
        "resources_sha256": resources["sha256"],
        "resource_files": sorted(resources["files"]),
        "template": template,
        "run_id": run_id,
        "simulation_reused": reused,
        "basic_qaqc": qaqc,
    }
    if manifest:
        try:
            manifest.parent.mkdir(parents=True, exist_ok=True)
            write_text_in_dir_nofollow(manifest.parent, manifest.name, json.dumps(result_manifest, indent=2) + "\n")
        except (OSError, ValueError) as e:
            return {"ok": False, "ready": False, "run_id": run_id, "error": f"Could not write the manifest: {e}"}

    return {
        "ok": ready,
        "ready": ready,
        "reused": reused,
        "run_id": run_id,
        "manifest_path": str(manifest) if manifest else None,
        "manifest": result_manifest,
        "basic_qaqc": qaqc,
        "error": None if ready else "Seed simulation QA/QC failed.",
    }


def _seed_entries(seeds_dir: Path) -> tuple[list[Path], list[Path]]:
    """(seed models, every other file or link) under seeds/, recursively."""
    seeds: list[Path] = []
    others: list[Path] = []
    if not seeds_dir.is_dir():
        return seeds, others
    for entry in sorted(seeds_dir.rglob("*")):
        if entry.is_dir() and not entry.is_symlink():
            continue
        if not entry.is_symlink() and entry.suffix.lower() in SEED_SUFFIXES:
            seeds.append(entry)
        else:
            others.append(entry)
    return seeds, others


def _stage_package_seed(pkg: Path, seed_path: str | None) -> dict[str, Any]:
    """Put the seed under pkg/seeds/; {"seed": model to preflight, "seed_member": str} or {"error"}.

    An external seed_path is copied no-follow into seeds/<name> (a copy
    already there must hold the same bytes). The preflight then runs on the
    external model, whose companion folder holds its resources; the packaged
    copy is byte-identical, so the manifest's seed_sha256 is its hash too.
    seeds/ must end up holding exactly one seed and nothing else: submission
    takes the first member, the manifest vouches for one, and a companion
    folder under seeds/ would be invisible to datapoints anyway (resources
    are packaged flat into lib/, which every datapoint searches).
    """
    seeds_dir = pkg / "seeds"
    seeds, others = _seed_entries(seeds_dir)
    if others:
        listed = ", ".join(p.relative_to(pkg).as_posix() for p in others)
        return {"error": f"seeds/ may hold only the seed model (resources are packaged into lib/); remove: {listed}"}
    if seed_path:
        src = Path(seed_path).expanduser()
        if src.is_symlink():
            return {"error": f"Seed path is a symlink (not allowed): {src}"}
        src = src.resolve()
        if not src.is_file():
            return {"error": f"Seed model not found: {src}"}
        if src.suffix.lower() != ".osm":
            return {"error": "Seed preflight currently requires an .osm seed model."}
        if not _is_analysis_path_allowed(src):
            return {"error": f"Seed path is not allowed: {src}"}
        dest = seeds_dir / src.name
        extra = [p for p in seeds if p != dest]
        if extra:
            listed = ", ".join(p.relative_to(pkg).as_posix() for p in extra)
            return {"error": f"seeds/ must hold exactly one seed model; {listed} would be packaged beside "
                             f"seeds/{src.name}. Remove it or use another package_dir."}
        if src.parent != seeds_dir:
            if dest.is_symlink() or (dest.exists() and not dest.is_file()):
                return {"error": f"seeds/{src.name} is a link or not a regular file (not allowed)"}
            try:
                if dest.is_file():
                    if sha256_regular_file_nofollow(dest, MAX_BUNDLE_OSM_BYTES) != _sha256_file(src):
                        return {"error": f"seeds/{src.name} already exists with different content than {src}; "
                                         "remove it or rename the seed"}
                else:
                    seeds_dir.mkdir(parents=True, exist_ok=True)
                    copy_regular_file_nofollow(src, dest, MAX_BUNDLE_OSM_BYTES)
            except (OSError, ValueError) as e:
                return {"error": f"Seed model could not be copied into seeds/: {e}"}
        return {"seed": src, "seed_member": f"seeds/{src.name}"}
    if not seeds:
        return {"error": "No .osm seed model found in package_dir/seeds; pass seed_path explicitly."}
    if len(seeds) > 1:
        listed = ", ".join(p.relative_to(pkg).as_posix() for p in seeds)
        return {"error": f"seeds/ must hold exactly one seed model; found: {listed}. Remove the extra seeds."}
    seed = seeds[0]
    if seed.suffix.lower() != ".osm":
        return {"error": "Seed preflight currently requires an .osm seed model."}
    return {"seed": seed, "seed_member": seed.relative_to(pkg).as_posix()}


def _package_seed_resources(seed: Path, lib_dir: Path) -> dict[str, Any]:
    """Copy the seed's effective resources into lib/ and verify each by hash.

    The datapoint OSW searches ../lib (the analysis gem adds it to every
    workflow's file_paths), so the resources land there with their relative
    subpaths. lib/ is shared by every packaging of this package_dir: a
    same-named file already there is kept by the copy, so every packaged
    resource is hashed afterwards and must be the seed's; anything else in
    lib/ is reported, never deleted. Returns {"resource_files", "lib_files_not_from_seed"}
    or {"error"}.
    """
    manifest_rel = Path(SEED_QAQC_MANIFEST).relative_to("lib").as_posix()
    try:
        digest = resources_digest(seed, allowed=_is_analysis_path_allowed)
        sources = resource_sources(seed, allowed=_is_analysis_path_allowed)
    except ValueError as e:
        return {"error": f"Seed resources could not be packaged: {e}"}
    if manifest_rel in digest["files"]:
        return {"error": f"a seed resource is named {manifest_rel}, the package manifest's name; rename it"}
    if digest["files"]:
        try:
            outcome = copy_resources(sources, lib_dir, overwrite=False)
        except ValueError as e:
            return {"error": f"Seed resources could not be packaged into lib/: {e}"}
        failed = [f"lib/{rel} ({why})" for rel, why in outcome["skipped"] if why != "not a regular file"]
        if failed:
            return {"error": "Seed resources could not be packaged into lib/: " + "; ".join(failed)}
        for rel, expected in sorted(digest["files"].items()):
            try:
                actual = sha256_regular_file_nofollow(lib_dir / rel, MAX_RESOURCE_FILE_BYTES)
            except (OSError, ValueError) as e:
                return {"error": f"lib/{rel} could not be verified after packaging: {e}"}
            if actual != expected:
                return {"error": f"lib/{rel} already exists with different content than the seed's resource; "
                                 "remove it from lib/ or rename the resource"}
    extra: list[str] = []
    if lib_dir.is_dir():
        for entry in sorted(lib_dir.rglob("*")):
            rel = entry.relative_to(lib_dir).as_posix()
            if entry.is_file() and not entry.is_symlink() and rel not in digest["files"] and rel != manifest_rel:
                extra.append(rel)
    return {"resource_files": sorted(digest["files"]), "lib_files_not_from_seed": extra}


def _resolve_package_weather(package_dir: Path, weather_file: str | None) -> Path | None:
    if weather_file:
        return Path(weather_file).expanduser().resolve()
    candidates = sorted((package_dir / "weather").glob("*.epw"))
    return candidates[0].resolve() if candidates else None


def _inside(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    return resolved == root or str(resolved).startswith(str(root) + os.sep)


@contextlib.contextmanager
def _zip_for_read(path: Path):
    """A tenant-chosen zip opened for reading by descriptor from its root (#190).

    Raises what ``zipfile.ZipFile(path)`` would (FileNotFoundError, OSError,
    BadZipFile) plus ValueError for an entry that is not a regular file; a
    component swapped for a link after the caller's check fails the open.
    """
    fd = open_confined(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as fh, zipfile.ZipFile(fh) as archive:
        yield archive


def _write_support_zip(package_dir: Path, output_zip_path: Path) -> str | None:
    """Zip the package roots. Returns an error string instead of following a symlink.

    The package dir is tenant-writable, so both ends are anchored by descriptor (#190): the
    output zip's directory is created and the zip opened through the walk from the tenant
    root, and every member is enumerated and opened relative to its directory's descriptor
    (``archive.write(path)`` would open by pathname and follow a link planted after the
    check). A link anywhere under a package root, a non-regular file, or a member over the
    budgets is an error naming it.
    """
    # The archive is written to a private temp name beside the output (created exclusively
    # through the parent's descriptor) and published by rename on success, so the previous
    # archive survives a failed attempt and a link planted at the output name is replaced,
    # never written through. On failure only that temp file, identified by inode, is removed.
    try:
        parent = DirHandle.open(output_zip_path.parent, create=True)
    except (OSError, ValueError) as e:
        return f"output zip path is not writable (not allowed): {output_zip_path} ({e})"
    with parent:
        tmp_name = f".{output_zip_path.name}.{uuid.uuid4().hex[:8]}.part"
        try:
            out_fd, _existed = parent.create_file(tmp_name, overwrite=False)
            ident = (os.fstat(out_fd).st_dev, os.fstat(out_fd).st_ino)
        except (OSError, ValueError) as e:
            return f"output zip path is not writable (not allowed): {output_zip_path} ({e})"
        try:
            with os.fdopen(out_fd, "wb") as out_f, \
                    zipfile.ZipFile(out_f, "w", compression=zipfile.ZIP_DEFLATED) as archive, \
                    DirHandle.open(package_dir) as pkg:
                err = _zip_package_roots(archive, pkg)
        except (OSError, ValueError) as e:
            err = f"could not write the package zip: {e}"
        if not err:
            try:
                existing = parent.lstat(output_zip_path.name)
                if existing is not None and stat.S_ISDIR(existing.st_mode):
                    err = f"output zip path is a directory (not allowed): {output_zip_path}"
                elif parent.fd is None:
                    os.replace(parent.path / tmp_name, parent.path / output_zip_path.name)
                else:
                    os.rename(tmp_name, output_zip_path.name, src_dir_fd=parent.fd, dst_dir_fd=parent.fd)
            except (OSError, ValueError) as e:
                err = f"could not publish the package zip at {output_zip_path}: {e}"
        if err:
            with contextlib.suppress(OSError, ValueError):
                st = parent.lstat(tmp_name)
                if st is not None and (st.st_dev, st.st_ino) == ident:
                    parent.unlink(tmp_name)
    return err


def _zip_package_roots(archive: zipfile.ZipFile, pkg: DirHandle) -> str | None:
    totals = {"bytes": 0}
    for root in sorted(REQUIRED_ANALYSIS_PACKAGE_ROOTS):
        st = pkg.lstat(root)
        if st is None:
            continue
        if stat.S_ISLNK(st.st_mode):
            return f"package member is a symlink (not allowed): {root}"
        if not stat.S_ISDIR(st.st_mode):
            return f"package member is not a directory: {root}"
        with pkg.subdir(root) as handle:
            err = _zip_tree(archive, handle, PurePosixPath(root), totals)
        if err:
            return err
    return None


def _zip_tree(archive: zipfile.ZipFile, handle: DirHandle, rel: PurePosixPath, totals: dict[str, int]) -> str | None:
    """Archive every regular file under ``handle`` (opened relative to it); an error string on anything else."""
    with handle.scandir() as it:
        entries = sorted(it, key=lambda e: e.name)
    for entry in entries:
        arcname = (rel / entry.name).as_posix()
        if entry.is_symlink():
            return f"package member is a symlink (not allowed): {arcname}"
        if entry.is_dir(follow_symlinks=False):
            with handle.subdir(entry.name) as child:
                err = _zip_tree(archive, child, rel / entry.name, totals)
            if err:
                return err
            continue
        if not entry.is_file(follow_symlinks=False):
            return f"package member is not a regular file (not allowed): {arcname}"
        fd = handle.open_file(entry.name, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            if st.st_size > MAX_PACKAGE_FILE_BYTES:
                return f"package member {arcname}: {st.st_size} bytes exceeds the {MAX_PACKAGE_FILE_BYTES}-byte limit"
            totals["bytes"] += st.st_size
            if totals["bytes"] > MAX_PACKAGE_TOTAL_BYTES:
                return f"package exceeds {MAX_PACKAGE_TOTAL_BYTES} bytes in total"
            info = zipfile.ZipInfo(arcname, date_time=max(time.localtime(st.st_mtime)[:6], (1980, 1, 1, 0, 0, 0)))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | stat.S_IMODE(st.st_mode)) << 16
            written = 0
            with archive.open(info, "w") as member:
                while chunk := os.read(fd, 1 << 20):
                    written += len(chunk)
                    if written > st.st_size or written > MAX_PACKAGE_FILE_BYTES:
                        return f"package member {arcname} grew while being archived"
                    member.write(chunk)
        finally:
            os.close(fd)
    return None


def _ensure_foundational_measures_in_package(package_dir: Path) -> dict[str, Any]:
    copied: list[str] = []
    present: list[str] = []
    missing: list[str] = []
    package_root = package_dir.resolve()
    target_root = package_dir / "measures"

    def _refused(what: Path) -> dict[str, Any]:
        # rmtree/copytree below would follow the link and delete/write another tenant's tree.
        return {
            "ok": False, "copied": copied, "present": present, "missing": missing,
            "common_measures_dir": str(_common_measures_dir()),
            "error": f"package measures path is a symlink or resolves outside the package (not allowed): {what}",
        }

    if target_root.is_symlink():
        return _refused(target_root)
    # Created from the confinement root by descriptor (#190): the package dir swapped for a link
    # after the check above must not have measures/ created through it.
    try:
        DirHandle.open(target_root, create=True).close()
    except (OSError, ValueError) as e:
        return _refused(f"{target_root} ({e})")

    for spec in FOUNDATIONAL_ANALYSIS_MEASURES:
        measure_name = str(spec["measure_name"])
        target = target_root / measure_name
        if target.is_symlink() or not _inside(target, package_root):
            return _refused(target)
        if target.is_dir() and (target / "measure.rb").is_file() and (target / "measure.xml").is_file():
            present.append(measure_name)
            continue
        source = _foundational_measure_path(measure_name)
        if not source.is_dir():
            missing.append(measure_name)
            continue
        # The package dir is tenant-writable: both trees are walked by descriptor (#190) and a
        # stale target is removed through its parent's descriptor, so a measures/ component
        # swapped for a link after the check above fails here instead of clearing or writing
        # another tree.
        try:
            copy_tree_confined(source, target, replace=True,
                               ignore=lambda name: name in (".git", ".bundle", "__pycache__") or name.endswith(".pyc"))
        except (OSError, ValueError) as e:
            return _refused(f"{target} ({e})")
        copied.append(measure_name)

    return {
        "ok": not missing,
        "copied": copied,
        "present": present,
        "missing": missing,
        "common_measures_dir": str(_common_measures_dir()),
        "error": None if not missing else f"Missing foundational analysis measures: {', '.join(missing)}",
    }


def prepare_analysis_package(
    package_dir: str,
    output_zip_path: str,
    seed_path: str | None = None,
    weather_file: str | None = None,
    *,
    template: str = "90.1-2019",
    force_rerun: bool = False,
    wait_timeout_seconds: int = 0,
    poll_interval_seconds: int = 30,
) -> dict[str, Any]:
    """Stage the seed and its resources, run/reuse the preflight, write the manifest, zip the package."""
    pkg = Path(package_dir).expanduser().resolve()
    if not pkg.exists() or not pkg.is_dir():
        return {"ok": False, "error": f"Package directory not found: {pkg}"}
    if not _is_analysis_path_allowed(pkg, write=True):
        return {"ok": False, "error": f"Package directory is not writable/allowed: {pkg}"}
    out = Path(output_zip_path).expanduser().resolve()
    if not _is_analysis_path_allowed(out, write=True):
        return {"ok": False, "error": f"Output ZIP path is not writable/allowed: {out}"}

    # Both dirs receive copies below: neither may be a link, sit under one, or
    # resolve outside the package (same check as a model's resource dir).
    seeds_dir, lib_dir = pkg / "seeds", pkg / "lib"
    for member in (seeds_dir, lib_dir):
        issue = resource_dir_issue(member, write=True, allowed=_is_analysis_path_allowed)
        if issue:
            return {"ok": False, "error": f"package {member.name}/ is not usable: {issue}"}
    staged = _stage_package_seed(pkg, seed_path)
    if staged.get("error"):
        return {"ok": False, "error": staged["error"]}
    seed: Path = staged["seed"]
    seed_member: str = staged["seed_member"]
    packaged = _package_seed_resources(seed, lib_dir)
    if packaged.get("error"):
        return {"ok": False, "error": packaged["error"], "seed_member": seed_member}

    epw = _resolve_package_weather(pkg, weather_file)
    manifest_path = pkg / SEED_QAQC_MANIFEST
    preflight = preflight_seed_for_analysis_package(
        seed_path=str(seed),
        weather_file=str(epw) if epw else None,
        manifest_path=str(manifest_path),
        template=template,
        force_rerun=force_rerun,
        wait_timeout_seconds=wait_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    if not preflight.get("ready"):
        return {
            "ok": False,
            "error": "Seed model must complete simulation and pass basic QA/QC before packaging.",
            "preflight": preflight,
            "seed_member": seed_member,
        }
    # The manifest names the packaged member so validation and submission use
    # the seed the preflight vouched for, whatever else sorts first in seeds/.
    # Read and written through a descriptor of lib/ itself: the check at the top
    # does not cover a lib/ swapped for a link while the preflight ran.
    try:
        manifest_data = json.loads(read_file_in_dir_nofollow(lib_dir, manifest_path.name, MAX_MANIFEST_BYTES))
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"Could not read {SEED_QAQC_MANIFEST} back: {e}", "preflight": preflight}
    if not isinstance(manifest_data, dict):
        return {"ok": False, "error": f"{SEED_QAQC_MANIFEST} is not a JSON object.", "preflight": preflight}
    if manifest_data.get("seed_member") != seed_member:
        manifest_data["seed_member"] = seed_member
        try:
            write_text_in_dir_nofollow(lib_dir, manifest_path.name, json.dumps(manifest_data, indent=2) + "\n")
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"Could not write {SEED_QAQC_MANIFEST}: {e}", "preflight": preflight}

    foundational_measures = _ensure_foundational_measures_in_package(pkg)
    if not foundational_measures.get("ok"):
        return {
            "ok": False,
            "error": "Foundational analysis measures must be available before packaging.",
            "preflight": preflight,
            "foundational_measures": foundational_measures,
        }

    zip_error = _write_support_zip(pkg, out)
    if zip_error:  # the writer has discarded any archive it created
        return {
            "ok": False,
            "error": zip_error,
            "preflight": preflight,
            "foundational_measures": foundational_measures,
        }
    validation = validate_analysis_package(str(out), require_seed_qaqc=True, require_foundational_measures=True)
    result = {
        "ok": validation.get("ok", False),
        "zip_path": str(out),
        "seed_member": seed_member,
        "resource_files": packaged["resource_files"],
        "lib_files_not_from_seed": packaged["lib_files_not_from_seed"],
        "preflight": preflight,
        "foundational_measures": foundational_measures,
        "validation": validation,
        "error": None if validation.get("ok") else "Created ZIP failed package validation.",
    }
    if not seed_path and packaged["lib_files_not_from_seed"]:
        # A seed taken from seeds/ has no companion folder there (nothing else may
        # sit under seeds/), so the preflight simulated it without resources and
        # the manifest records none, whatever an earlier packaging left in lib/.
        result["warnings"] = [
            "The seed was taken from seeds/ and has no resources there; the preflight ran it without "
            f"the files in lib/ ({', '.join(packaged['lib_files_not_from_seed'])}). Pass seed_path as the "
            "model where it was saved to package and simulate its companion resources.",
        ]
    return result


def _analysis_variable_count(problem: dict[str, Any]) -> int:
    workflow = problem.get("workflow")
    if not isinstance(workflow, list):
        return 0

    count = 0
    for step in workflow:
        if not isinstance(step, dict):
            continue
        variables = step.get("variables")
        if not isinstance(variables, list):
            continue
        for variable in variables:
            if isinstance(variable, dict) and variable.get("variable") is not False and not variable.get("pivot"):
                count += 1
    return count


def validate_osa_json(
    osa_json_path: str,
    schema_path: str | None = None,
    require_foundational_measures: bool = False,
) -> dict[str, Any]:
    issues: list[str] = []
    try:
        data = _read_json(osa_json_path)
    except ValueError as e:
        return {"ok": False, "error": str(e), "issues": [str(e)]}

    analysis = data.get("analysis")
    if not isinstance(analysis, dict):
        issues.append("Root object must contain an analysis object.")
        analysis = {}

    if not analysis.get("name"):
        issues.append("analysis.name is missing.")

    problem = analysis.get("problem")
    if not isinstance(problem, dict):
        issues.append("analysis.problem must be an object.")
        problem = {}

    if not problem.get("analysis_type"):
        issues.append("analysis.problem.analysis_type is missing.")
    if "workflow" in problem and not isinstance(problem["workflow"], list):
        issues.append("analysis.problem.workflow must be an array when present.")
    if "output_variables" in analysis and not isinstance(analysis["output_variables"], list):
        issues.append("analysis.output_variables must be an array when present.")

    variable_count = _analysis_variable_count(problem)
    analysis_type = problem.get("analysis_type")
    if isinstance(analysis_type, str) and analysis_type.lower() == "doe" and variable_count < 2:
        issues.append(
            "DOE analyses require at least two measure variables in analysis.problem.workflow. "
            "Use single_run for a single datapoint, use a schema-supported sampling analysis type such as lhs, "
            "or add another real variable before selecting DOE.",
        )
    missing_foundational: list[str] = []
    if require_foundational_measures:
        missing_foundational = _missing_foundational_workflow_measures(problem)
        if missing_foundational:
            issues.append(
                "analysis.problem.workflow is missing foundational analysis measure(s): "
                f"{', '.join(missing_foundational)}. Include view_model, openstudio_results, and generic_qaqc "
                "in the OSA JSON workflow before submitting to OSAF.",
            )

    schema_file = _osa_schema_path(schema_path)
    try:
        schema_file, schema = _read_osa_schema(schema_path)
        schema_issues = _schema_issues(data, schema)
    except ValueError as e:
        return {
            "ok": False,
            "error": str(e),
            "issues": issues + [str(e)],
            "structural_issues": issues,
            "schema_issues": [str(e)],
            "schema_path": str(schema_file),
            "osa_json_path": str(Path(osa_json_path).expanduser().resolve()),
            "analysis_id": analysis.get("uuid"),
            "analysis_type": analysis_type,
            "analysis_variable_count": variable_count,
            "require_foundational_measures": require_foundational_measures,
            "foundational_measure_names": _foundational_measure_names(),
            "missing_foundational_measures": missing_foundational,
        }
    issues.extend(schema_issues)

    return {
        "ok": not issues,
        "issues": issues,
        "structural_issues": issues[: len(issues) - len(schema_issues)],
        "schema_issues": schema_issues,
        "schema_path": str(schema_file),
        "osa_json_path": str(Path(osa_json_path).expanduser().resolve()),
        "analysis_id": analysis.get("uuid"),
        "analysis_type": analysis_type,
        "analysis_variable_count": variable_count,
        "require_foundational_measures": require_foundational_measures,
        "foundational_measure_names": _foundational_measure_names(),
        "missing_foundational_measures": missing_foundational,
    }


def _lib_resource_issues(zip_path: Path, manifest: dict[str, Any], lib_files: list[str]) -> list[str]:
    """The zip's lib/ members listed in the manifest must hash to its resources_sha256."""
    expected = manifest.get("resources_sha256")
    if expected is None:
        return []
    listed = manifest.get("resource_files")
    if not isinstance(listed, list) or not all(isinstance(rel, str) and rel for rel in listed):
        return [f"{SEED_QAQC_MANIFEST} resource_files must list the packaged resources."]
    if len(set(listed)) != len(listed):
        return [f"{SEED_QAQC_MANIFEST} resource_files lists a resource more than once."]
    if len(listed) > MAX_RESOURCE_FILES:
        return [f"{SEED_QAQC_MANIFEST} lists more than {MAX_RESOURCE_FILES} resources."]
    present = set(lib_files)
    hashes: dict[str, str] = {}
    missing: list[str] = []
    total = 0
    # The same budgets staging applies: the zip is tenant-built, so each member's
    # declared and actual size is bounded before it is decompressed and hashed.
    with _zip_for_read(zip_path) as archive:
        for rel in listed:
            name = f"lib/{rel}"
            if name not in present:
                missing.append(name)
                continue
            total += archive.getinfo(name).file_size
            if total > MAX_RESOURCE_TOTAL_BYTES:
                return [
                    f"lib/ resources listed in {SEED_QAQC_MANIFEST} exceed {MAX_RESOURCE_TOTAL_BYTES} bytes in total.",
                ]
            try:
                hashes[rel] = _zip_member_sha256(archive, name, MAX_RESOURCE_FILE_BYTES)
            except ZIP_MEMBER_ERRORS as e:
                return [f"lib/ resource could not be verified: {e}"]
    if missing:
        return [f"lib/ is missing seed resources listed in {SEED_QAQC_MANIFEST}: {', '.join(missing)}"]
    if combine_resource_hashes(hashes) != expected:
        return [
            f"lib/ resources do not match {SEED_QAQC_MANIFEST} resources_sha256. "
            "Run openstudio_analysis_prepare_package again.",
        ]
    return []


def validate_analysis_package(
    zip_path: str,
    require_seed_qaqc: bool = True,
    require_foundational_measures: bool = True,
) -> dict[str, Any]:
    """Validate the OSAF support ZIP layout before upload.

    Expected root layout matches OpenStudio-analysis-gem's osw_project fixture:
    measures/, weather/, seeds/, scripts/, and lib/ at the archive root.
    When require_seed_qaqc=True, the ZIP must also contain
    lib/seed_simulation_qaqc.json proving the packaged seed already simulated
    successfully and passed basic QA/QC.
    """
    path = Path(zip_path).expanduser().resolve()
    if not _is_analysis_path_allowed(path):
        return {"ok": False, "error": f"Analysis package path is not allowed: {path}", "issues": ["Path not allowed."]}
    issues: list[str] = []
    seed_qaqc_manifest: dict[str, Any] | None = None
    try:
        with _zip_for_read(path) as archive:
            infos = archive.infolist()
            if SEED_QAQC_MANIFEST in archive.namelist():
                try:
                    parsed = json.loads(archive.read(SEED_QAQC_MANIFEST).decode("utf-8"))
                    if isinstance(parsed, dict):
                        seed_qaqc_manifest = parsed
                    else:
                        issues.append(f"{SEED_QAQC_MANIFEST} must contain a JSON object.")
                except Exception as e:
                    issues.append(f"Could not parse {SEED_QAQC_MANIFEST}: {e}")
    except FileNotFoundError:
        return {"ok": False, "error": f"Analysis package ZIP not found: {path}", "issues": [f"File not found: {path}"]}
    except zipfile.BadZipFile:
        return {"ok": False, "error": f"Invalid analysis package ZIP: {path}", "issues": ["Not a valid ZIP archive."]}
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"Could not read analysis package ZIP {path}: {e}", "issues": [str(e)]}

    if not infos:
        issues.append("Analysis package ZIP is empty.")

    names = [info.filename for info in infos]
    file_names = [name for name, info in zip(names, infos) if not info.is_dir()]
    seen_names: set[str] = set()
    duplicate_names: set[str] = set()
    roots: set[str] = set()
    uncompressed_bytes = 0
    compressed_bytes = 0

    for info in infos:
        name = info.filename
        parts = _zip_member_parts(name)
        if not parts:
            issues.append("Archive contains an empty member name.")
            continue
        if name.startswith("/") or parts[0] in (".", "..") or ".." in parts:
            issues.append(f"Archive member must not use absolute or parent paths: {name}")
        if len(parts) == 1 and not info.is_dir():
            issues.append(f"Archive member must be inside a required root folder: {name}")
        roots.add(parts[0])
        if name in seen_names:
            duplicate_names.add(name)
        seen_names.add(name)
        if _zip_member_is_symlink(info):
            issues.append(f"Archive member must not be a symlink: {name}")
        uncompressed_bytes += info.file_size
        compressed_bytes += info.compress_size

    missing_roots = sorted(REQUIRED_ANALYSIS_PACKAGE_ROOTS - roots)
    extra_roots = sorted(roots - REQUIRED_ANALYSIS_PACKAGE_ROOTS)
    if missing_roots:
        issues.append(f"Missing required root folders: {', '.join(missing_roots)}")
    if extra_roots:
        issues.append(f"Unexpected root folders/files: {', '.join(extra_roots)}")
    if duplicate_names:
        issues.append(f"Duplicate archive members: {', '.join(sorted(duplicate_names))}")

    grouped_files: dict[str, list[str]] = {root: [] for root in REQUIRED_ANALYSIS_PACKAGE_ROOTS}
    for name in file_names:
        parts = _zip_member_parts(name)
        if parts and parts[0] in grouped_files:
            grouped_files[parts[0]].append(name)

    seed_files = grouped_files["seeds"]
    weather_files = grouped_files["weather"]
    script_files = grouped_files["scripts"]
    lib_files = grouped_files["lib"]
    measure_files = grouped_files["measures"]

    seed_models = sorted(name for name in seed_files if Path(name).suffix.lower() in SEED_SUFFIXES)
    non_seed = sorted(set(seed_files) - set(seed_models))
    if not seed_models:
        issues.append("seeds/ must contain at least one .osm or .osw seed file.")
    if non_seed:
        issues.append(f"seeds/ must contain only .osm or .osw seed files (resources go to lib/): {', '.join(non_seed)}")
    if not any(Path(name).suffix.lower() == ".epw" for name in weather_files):
        issues.append("weather/ must contain at least one .epw weather file.")
    unexpected_weather = sorted(
        name
        for name in weather_files
        if Path(name).suffix.lower() and Path(name).suffix.lower() not in WEATHER_SUFFIXES
    )
    if unexpected_weather:
        issues.append(f"weather/ contains unexpected file types: {', '.join(unexpected_weather)}")
    if not script_files:
        issues.append("scripts/ must contain analysis or data_point scripts.")
    if not lib_files:
        issues.append("lib/ must contain supporting files.")
    if not measure_files:
        issues.append("measures/ must contain at least one measure directory.")

    if require_foundational_measures:
        measures = _measure_dirs(measure_files)
        missing_foundational = [
            str(spec["measure_name"])
            for spec in FOUNDATIONAL_ANALYSIS_MEASURES
            if str(spec["measure_name"]) not in measures
        ]
        if missing_foundational:
            issues.append(
                "Missing foundational analysis measure(s): "
                f"{', '.join(missing_foundational)}. Run openstudio_analysis_prepare_package first.",
            )

    if require_seed_qaqc:
        if seed_qaqc_manifest is None:
            issues.append(
                f"Missing required seed simulation QA/QC manifest: {SEED_QAQC_MANIFEST}. "
                "Run openstudio_analysis_prepare_package first.",
            )
        else:
            if _manifest_predates_resource_identity(seed_qaqc_manifest):
                issues.append(
                    f"{SEED_QAQC_MANIFEST} predates the resource identity (no resources_sha256). "
                    "Run openstudio_analysis_prepare_package again.",
                )
            elif not _manifest_is_valid(seed_qaqc_manifest):
                issues.append(f"{SEED_QAQC_MANIFEST} does not show a passing seed simulation QA/QC result.")
            # The manifest vouches for one seed, and submission takes one: the
            # archive must hold exactly that one, hashing to seed_sha256.
            if len(seed_models) > 1:
                issues.append(
                    "seeds/ must contain exactly one seed model when the QA/QC manifest is required; "
                    f"found: {', '.join(seed_models)}",
                )
            member = seed_qaqc_manifest.get("seed_member")
            if member is not None and member not in seed_models:
                issues.append(f"{SEED_QAQC_MANIFEST} seed_member {member} is not a seed in seeds/.")
                member = None
            if member is None and len(seed_models) == 1:
                member = seed_models[0]
            manifest_seed_hash = seed_qaqc_manifest.get("seed_sha256")
            if manifest_seed_hash and member:
                member_hash = None
                try:
                    with _zip_for_read(path) as archive:
                        member_hash = _zip_member_sha256(archive, member, MAX_BUNDLE_OSM_BYTES)
                except (*ZIP_MEMBER_ERRORS, OSError) as e:
                    issues.append(f"{member} could not be hashed: {e}")
                if member_hash is not None and member_hash != manifest_seed_hash:
                    issues.append(f"{SEED_QAQC_MANIFEST} seed_sha256 does not match {member}.")
            try:
                issues.extend(_lib_resource_issues(path, seed_qaqc_manifest, lib_files))
            except (*ZIP_MEMBER_ERRORS, OSError) as e:
                issues.append(f"lib/ resources could not be read from the package: {e}")

    measures = _measure_dirs(measure_files)
    complete_measure_dirs = sorted(
        measure_name
        for measure_name, filenames in measures.items()
        if {"measure.rb", "measure.xml"}.issubset(filenames)
    )
    if not complete_measure_dirs:
        issues.append("measures/ must contain at least one measure directory with measure.rb and measure.xml.")
    for measure_name, filenames in sorted(measures.items()):
        missing = {"measure.rb", "measure.xml"} - filenames
        if missing:
            issues.append(f"Measure '{measure_name}' is missing: {', '.join(sorted(missing))}")

    return {
        "ok": not issues,
        "issues": issues,
        "zip_path": str(path),
        "required_roots": sorted(REQUIRED_ANALYSIS_PACKAGE_ROOTS),
        "root_folders": sorted(roots),
        "file_count": len(file_names),
        "measure_count": len(measures),
        "complete_measure_count": len(complete_measure_dirs),
        "seed_files": sorted(seed_files),
        "weather_files": sorted(weather_files),
        "script_files": sorted(script_files),
        "lib_files": sorted(lib_files),
        "measure_files": sorted(measure_files),
        "require_seed_qaqc": require_seed_qaqc,
        "require_foundational_measures": require_foundational_measures,
        "foundational_measure_names": [str(spec["measure_name"]) for spec in FOUNDATIONAL_ANALYSIS_MEASURES],
        "seed_qaqc_manifest": seed_qaqc_manifest,
        "uncompressed_bytes": uncompressed_bytes,
        "compressed_bytes": compressed_bytes,
    }


def create_project(project_name: str, server_url: str | None = None) -> dict[str, Any]:
    try:
        base = _server_url(server_url)
        response = _request_json("POST", base, "/projects.json", body={"project": {"name": project_name}}, timeout=600)
    except (ValueError, RuntimeError) as e:
        return {"ok": False, "error": str(e)}

    project_id = response.get("_id") or response.get("id") or response.get("uuid")
    if not project_id:
        return {"ok": False, "error": "Project response did not include _id/id/uuid.", "response": response}
    return {"ok": True, "project_id": str(project_id), "response": response}


def check_server_health(server_url: str | None = None) -> dict[str, Any]:
    try:
        base = _server_url(server_url)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        response = _request_json("GET", base, "/status.json", timeout=60)
    except RuntimeError as e:
        return {"ok": False, "server_url": base, "error": str(e)}
    return {"ok": True, "server_url": base, "response": response}


def submit_analysis(
    project_id: str,
    osa_json_path: str,
    server_url: str | None = None,
    analysis_name: str | None = None,
    upload_zip_path: str | None = None,
    schema_path: str | None = None,
    require_foundational_measures: bool = True,
) -> dict[str, Any]:
    validation = validate_osa_json(
        osa_json_path,
        schema_path=schema_path,
        require_foundational_measures=require_foundational_measures,
    )
    if not validation["ok"]:
        return {"ok": False, "error": "OSA JSON validation failed.", "validation": validation}
    package_validation = None
    if upload_zip_path:
        package_validation = validate_analysis_package(upload_zip_path)
        if not package_validation["ok"]:
            return {
                "ok": False,
                "error": "Analysis package ZIP validation failed.",
                "validation": validation,
                "package_validation": package_validation,
            }

    try:
        base = _server_url(server_url)
        _seg(project_id)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    formulation = _read_json(osa_json_path)
    if analysis_name:
        formulation["analysis"]["display_name"] = analysis_name
        formulation["analysis"]["name"] = re.sub(r"[^a-zA-Z0-9_]+", "_", analysis_name).strip("_").lower() or "analysis"

    try:
        response = _request_json(
            "POST",
            base,
            f"/projects/{_seg(project_id)}/analyses.json",
            body=formulation,
            timeout=600,
        )
    except RuntimeError as e:
        return {
            "ok": False,
            "error": str(e),
            "validation": validation,
            "package_validation": package_validation,
        }
    analysis_id = response.get("_id") or response.get("id") or response.get("uuid") or validation.get("analysis_id")
    if not analysis_id:
        return {"ok": False, "error": "Analysis response did not include _id/id/uuid.", "response": response}

    upload = None
    if upload_zip_path:
        try:
            upload_path = f"/analyses/{_seg(analysis_id)}/upload.json"
        except ValueError as e:  # the server handed back an id that cannot form a path segment
            return {
                "ok": False,
                "error": f"Analysis created but its id is unusable for upload: {e}",
                "analysis_id": analysis_id,
                "response": response,
            }
        upload = _multipart_upload(base, upload_path, upload_zip_path)
        if not upload.get("ok"):
            return {
                "ok": False,
                "error": "Analysis created but ZIP upload failed.",
                "analysis_id": analysis_id,
                "upload": upload,
            }

    return {
        "ok": True,
        "analysis_id": str(analysis_id),
        "response": response,
        "upload": upload,
        "package_validation": package_validation,
    }


def start_analysis(
    analysis_id: str,
    server_url: str | None = None,
    analysis_type: str = "single_run",
    without_delay: bool = False,
) -> dict[str, Any]:
    try:
        base = _server_url(server_url)
        path = f"/analyses/{_seg(analysis_id)}/action.json"
    except ValueError as e:
        return {"ok": False, "analysis_id": analysis_id, "analysis_type": analysis_type, "error": str(e)}
    result = _request_form(
        "POST",
        base,
        path,
        form={
            "analysis_action": "start",
            "analysis_type": analysis_type,
            "without_delay": "true" if without_delay else None,
        },
        timeout=600,
    )
    if not result.get("ok"):
        return {"ok": False, "analysis_id": analysis_id, "analysis_type": analysis_type, **result}
    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    code = response.get("code")
    if code not in (None, 200):
        return {
            "ok": False,
            "analysis_id": analysis_id,
            "analysis_type": analysis_type,
            "error": response.get("error") or f"OpenStudio Server returned action code {code}.",
            "response": response,
            "status": result.get("status"),
        }
    return {
        "ok": True,
        "analysis_id": analysis_id,
        "analysis_type": analysis_type,
        "status": result.get("status"),
        "response": response,
    }


def start_sampled_analysis_run(
    analysis_id: str,
    server_url: str | None = None,
    sampler_analysis_type: str = "lhs",
    without_delay: bool = False,
) -> dict[str, Any]:
    """Generate sampled datapoints, then queue them with batch_run."""
    if sampler_analysis_type == "batch_run":
        return {
            "ok": False,
            "analysis_id": analysis_id,
            "sampler_analysis_type": sampler_analysis_type,
            "error": "sampler_analysis_type must be a sampling analysis type such as lhs, not batch_run.",
        }

    sampler_start = start_analysis(
        analysis_id=analysis_id,
        server_url=server_url,
        analysis_type=sampler_analysis_type,
        without_delay=without_delay,
    )
    if not sampler_start.get("ok"):
        return {
            "ok": False,
            "stage": f"start_{sampler_analysis_type}",
            "analysis_id": analysis_id,
            "sampler_analysis_type": sampler_analysis_type,
            "sampler_start": sampler_start,
        }

    batch_run_start = start_analysis(
        analysis_id=analysis_id,
        server_url=server_url,
        analysis_type="batch_run",
        without_delay=without_delay,
    )
    if not batch_run_start.get("ok"):
        return {
            "ok": False,
            "stage": "start_batch_run",
            "analysis_id": analysis_id,
            "sampler_analysis_type": sampler_analysis_type,
            "sampler_start": sampler_start,
            "batch_run_start": batch_run_start,
        }

    return {
        "ok": True,
        "stage": "started",
        "analysis_id": analysis_id,
        "sampler_analysis_type": sampler_analysis_type,
        "sampler_start": sampler_start,
        "batch_run_start": batch_run_start,
    }


def get_analysis_status(
    analysis_id: str,
    server_url: str | None = None,
    analysis_type: str | None = None,
) -> dict[str, Any]:
    try:
        base = _server_url(server_url)
        path = f"/analyses/{_seg(analysis_id)}/status.json"
    except ValueError as e:
        return {"ok": False, "analysis_id": analysis_id, "error": str(e)}
    try:
        response = _request_json("GET", base, path, timeout=300)
    except RuntimeError as e:
        return {"ok": False, "analysis_id": analysis_id, "error": str(e), "server_url": base}
    analysis = response.get("analysis") if isinstance(response.get("analysis"), dict) else {}
    status = str(analysis.get("status") or response.get("status") or "unknown").lower()
    response_analysis_type = analysis.get("analysis_type")
    type_matches = analysis_type is None or response_analysis_type in (analysis_type, "batch_run")
    return {
        "ok": True,
        "analysis_id": analysis_id,
        "status": status,
        "analysis_type": response_analysis_type,
        "type_matches": type_matches,
        "done": status in DONE_STATUSES,
        "failed": status in FAILED_STATUSES,
        "response": response,
    }


def _status_datapoint_count(status: dict[str, Any]) -> int:
    response = status.get("response") if isinstance(status.get("response"), dict) else {}
    analysis = response.get("analysis") if isinstance(response.get("analysis"), dict) else {}
    value = analysis.get("total_datapoints")
    return value if isinstance(value, int) else 0


def _status_datapoints(status: dict[str, Any]) -> list[dict[str, Any]]:
    response = status.get("response") if isinstance(status.get("response"), dict) else {}
    analysis = response.get("analysis") if isinstance(response.get("analysis"), dict) else {}
    data_points = analysis.get("data_points")
    return data_points if isinstance(data_points, list) else []


def _wait_for_datapoints(
    analysis_id: str,
    server_url: str,
    *,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> dict[str, Any]:
    started = time.monotonic()
    last_status: dict[str, Any] | None = None
    while time.monotonic() - started <= timeout_seconds:
        last_status = get_analysis_status(analysis_id, server_url=server_url)
        if _status_datapoint_count(last_status) > 0:
            return {"ok": True, "status": last_status}
        time.sleep(max(1, int(poll_interval_seconds)))
    return {
        "ok": False,
        "error": f"Timed out after {timeout_seconds}s waiting for single_run to create a datapoint.",
        "last_status": last_status,
    }


def _wait_for_datapoint_completion(
    analysis_id: str,
    server_url: str,
    *,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> dict[str, Any]:
    started = time.monotonic()
    last_status: dict[str, Any] | None = None
    while time.monotonic() - started <= timeout_seconds:
        last_status = get_analysis_status(analysis_id, server_url=server_url)
        data_points = _status_datapoints(last_status)
        if data_points:
            statuses = {str(dp.get("status") or "unknown").lower() for dp in data_points}
            status_messages = [str(dp.get("status_message") or "").lower() for dp in data_points]
            failure_messages = [message for message in status_messages if "failure" in message or "error" in message]
            if failure_messages:
                return {
                    "ok": False,
                    "error": f"At least one datapoint reported failure: {', '.join(sorted(set(failure_messages)))}",
                    "status": last_status,
                    "data_point_statuses": sorted(statuses),
                }
            if statuses and statuses.issubset(DONE_STATUSES):
                return {"ok": True, "status": last_status, "data_point_statuses": sorted(statuses)}
            if any(status in FAILED_STATUSES for status in statuses):
                return {
                    "ok": False,
                    "error": f"At least one datapoint failed: {', '.join(sorted(statuses))}",
                    "status": last_status,
                    "data_point_statuses": sorted(statuses),
                }
        time.sleep(max(1, int(poll_interval_seconds)))
    return {
        "ok": False,
        "error": f"Timed out after {timeout_seconds}s waiting for datapoint simulation completion.",
        "last_status": last_status,
    }


def _package_seed_weather_refs(package_validation: dict[str, Any]) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    seed_files = package_validation.get("seed_files") if isinstance(package_validation.get("seed_files"), list) else []
    weather_files = package_validation.get("weather_files") if isinstance(package_validation.get("weather_files"), list) else []
    manifest = package_validation.get("seed_qaqc_manifest")
    member = manifest.get("seed_member") if isinstance(manifest, dict) else None
    if not (isinstance(member, str) and member in seed_files):
        seed_models = [name for name in seed_files if Path(name).suffix.lower() in SEED_SUFFIXES]
        member = seed_models[0] if seed_models else (seed_files[0] if seed_files else None)
    seed = {"file_type": "OSM", "path": f"./{member}"} if member else None
    epw_files = [path for path in weather_files if str(path).lower().endswith(".epw")]
    weather_path = epw_files[0] if epw_files else (weather_files[0] if weather_files else None)
    weather = {"file_type": "EPW", "path": f"./{weather_path}"} if weather_path else None
    return seed, weather


def _ordered_package_measure_names(package_validation: dict[str, Any]) -> list[str]:
    measure_files = package_validation.get("measure_files") if isinstance(package_validation.get("measure_files"), list) else []
    measure_names = sorted(_measure_dirs(measure_files))
    foundational = _foundational_measure_names()
    foundational_set = set(foundational)
    ordered = [name for name in measure_names if name not in foundational_set]
    ordered.extend(name for name in foundational if name in measure_names)
    return ordered


def _build_static_workflow_from_package(zip_path: str, package_validation: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a single-run workflow from all packaged measures using default argument values."""
    measure_names = _ordered_package_measure_names(package_validation)
    if not measure_names:
        raise ValueError("Package contains no measure directories to submit in the smoke-test OSA JSON.")

    # Extract under the caller's own run root on the shared server: the global tempdir is
    # outside every tenant root there, so _read_measure_metadata would refuse the measures.
    base_dir = None
    if _is_http_mode():
        from mcp_server.config import user_run_root

        base_dir = user_run_root()
    tmpdir = tempfile.mkdtemp(prefix="openstudio_smoke_measures_", dir=base_dir)
    try:
        tmp = Path(tmpdir)
        # The path validation authorized, not a fresh resolve of the caller's string: a resolve
        # here would follow a link swapped in since and hand the walk another tree's real path.
        authorized = Path(package_validation.get("zip_path") or zip_path)
        with _zip_for_read(authorized) as archive:
            for info in archive.infolist():
                parts = _zip_member_parts(info.filename)
                if len(parts) >= 2 and parts[0] == "measures":
                    archive.extract(info, tmp)

        workflow = [
            build_measure_workflow_step(str(tmp / "measures" / measure_name))
            for measure_name in measure_names
        ]
    finally:
        remove_tree_confined(tmpdir, ignore_errors=True)

    for index, step in enumerate(workflow):
        step["workflow_index"] = index
    return workflow


def test_server_config_single_run(
    upload_zip_path: str,
    server_url: str | None = None,
    output_dir: str | None = None,
    project_name: str = "OpenStudio Server Config Smoke Test",
    wait_timeout_seconds: int = 600,
    poll_interval_seconds: int = 10,
    schema_path: str | None = None,
) -> dict[str, Any]:
    """Smoke-test OpenStudio Server by submitting and starting a single_run analysis."""
    try:
        base = _server_url(server_url)
    except ValueError as e:
        return {"ok": False, "stage": "server_url", "error": str(e)}
    health = check_server_health(base)
    if not health.get("ok"):
        return {"ok": False, "stage": "health", "server_url": base, "health": health}

    package_validation = validate_analysis_package(upload_zip_path)
    if not package_validation.get("ok"):
        return {
            "ok": False,
            "stage": "package_validation",
            "server_url": base,
            "health": health,
            "package_validation": package_validation,
        }

    seed, weather = _package_seed_weather_refs(package_validation)
    if seed is None:
        return {"ok": False, "stage": "package_validation", "error": "Package validation found no seed model."}
    try:
        workflow = _build_static_workflow_from_package(upload_zip_path, package_validation)
    except (*ZIP_MEMBER_ERRORS, OSError) as e:  # a package swapped, removed or truncated since validation
        return {
            "ok": False,
            "stage": "build_static_workflow",
            "server_url": base,
            "health": health,
            "package_validation": package_validation,
            "error": str(e),
        }

    if output_dir:
        out_dir = Path(output_dir).expanduser().resolve()
        if not _is_analysis_path_allowed(out_dir, write=True):
            return {"ok": False, "error": f"Output directory is not writable/allowed: {out_dir}"}
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        from mcp_server.config import user_run_root

        base_dir = user_run_root() if _is_http_mode() else Path(tempfile.gettempdir())
        out_dir = Path(tempfile.mkdtemp(prefix="openstudio_server_config_", dir=base_dir)).resolve()

    osa_path = out_dir / "single_run_server_config_test.json"
    created = create_osa_json(
        output_path=str(osa_path),
        analysis_name=project_name,
        analysis_type="single_run",
        workflow=workflow,
        algorithm={"number_of_samples": 1},
        extra_analysis_fields={
            "cli_debug": "",
            "cli_verbose": "",
            "download_reports": False,
            "download_osw": False,
            "download_osm": False,
            "download_zip": False,
        },
        seed=seed,
        weather_file=weather,
        schema_path=schema_path,
        validate_after_create=True,
    )
    if not created.get("ok") or not created.get("validation", {}).get("ok"):
        return {
            "ok": False,
            "stage": "create_osa_json",
            "server_url": base,
            "health": health,
            "created": created,
            "package_validation": package_validation,
        }

    project = create_project(project_name=project_name, server_url=base)
    if not project.get("ok"):
        return {"ok": False, "stage": "create_project", "server_url": base, "health": health, "project": project}

    submission = submit_analysis(
        project_id=project["project_id"],
        osa_json_path=str(osa_path),
        server_url=base,
        upload_zip_path=upload_zip_path,
        schema_path=schema_path,
        require_foundational_measures=True,
    )
    if not submission.get("ok"):
        return {
            "ok": False,
            "stage": "submit",
            "server_url": base,
            "health": health,
            "project": project,
            "submission": submission,
        }

    analysis_id = submission["analysis_id"]
    single_run_start = start_analysis(analysis_id, server_url=base, analysis_type="single_run")
    if not single_run_start.get("ok"):
        return {
            "ok": False,
            "stage": "start_single_run",
            "server_url": base,
            "health": health,
            "project": project,
            "submission": submission,
            "single_run_start": single_run_start,
        }

    datapoints = _wait_for_datapoints(
        analysis_id,
        base,
        timeout_seconds=max(0, int(wait_timeout_seconds)),
        poll_interval_seconds=poll_interval_seconds,
    )
    if not datapoints.get("ok"):
        return {
            "ok": False,
            "stage": "wait_for_single_run_datapoint",
            "server_url": base,
            "health": health,
            "project": project,
            "submission": submission,
            "single_run_start": single_run_start,
            "datapoints": datapoints,
        }

    batch_run_start = start_analysis(analysis_id, server_url=base, analysis_type="batch_run")
    if not batch_run_start.get("ok"):
        return {
            "ok": False,
            "stage": "start_batch_run",
            "server_url": base,
            "health": health,
            "project": project,
            "submission": submission,
            "single_run_start": single_run_start,
            "datapoints": datapoints,
            "batch_run_start": batch_run_start,
        }

    final_status = _wait_for_datapoint_completion(
        analysis_id,
        base,
        poll_interval_seconds=max(1, int(poll_interval_seconds)),
        timeout_seconds=max(0, int(wait_timeout_seconds)),
    )
    return {
        "ok": bool(final_status.get("ok")),
        "stage": "complete" if final_status.get("ok") else "wait_for_batch_run",
        "server_url": base,
        "health": health,
        "project_id": project["project_id"],
        "analysis_id": analysis_id,
        "osa_json_path": str(osa_path),
        "package_validation": package_validation,
        "submission": submission,
        "single_run_start": single_run_start,
        "datapoints": datapoints,
        "batch_run_start": batch_run_start,
        "final_status": final_status,
        "error": None if final_status.get("ok") else final_status.get("error"),
    }


def wait_for_analysis(
    analysis_id: str,
    server_url: str | None = None,
    analysis_type: str | None = None,
    poll_interval_seconds: int = 60,
    timeout_seconds: int = 86400,
) -> dict[str, Any]:
    if poll_interval_seconds <= 0:
        return {"ok": False, "error": "poll_interval_seconds must be > 0."}
    if timeout_seconds <= 0:
        return {"ok": False, "error": "timeout_seconds must be > 0."}

    started = time.monotonic()
    last_status: dict[str, Any] | None = None
    while time.monotonic() - started <= timeout_seconds:
        last_status = get_analysis_status(analysis_id, server_url=server_url, analysis_type=analysis_type)
        if not last_status.get("ok"):
            return {"ok": False, **last_status}
        if last_status["done"]:
            return {"ok": True, **last_status}
        if last_status["failed"]:
            return {"ok": False, "error": f"Analysis failed with status {last_status['status']}.", **last_status}
        time.sleep(poll_interval_seconds)

    return {
        "ok": False,
        "error": f"Timed out after {timeout_seconds}s waiting for analysis {analysis_id}.",
        "last_status": last_status,
    }


def download_analysis_data(
    analysis_id: str,
    output_dir: str,
    server_url: str | None = None,
    file_format: str = "csv",
) -> dict[str, Any]:
    # file_format becomes a path suffix: allowlist it rather than quote it, so it can
    # neither traverse nor request a format the server does not serve.
    if file_format not in DOWNLOAD_FORMATS:
        return {"ok": False, "error": f"file_format must be one of {', '.join(DOWNLOAD_FORMATS)}; got {file_format!r}"}
    try:
        base = _server_url(server_url)
        segment = _seg(analysis_id)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    query = urlencode({"export": "true"})
    return _download(
        base,
        f"/analyses/{segment}/download_data.{file_format}?{query}",
        output_dir,
        f"analysis_{segment}_data.{file_format}",
    )


def get_analysis_results_json(analysis_id: str, server_url: str | None = None) -> dict[str, Any]:
    try:
        base = _server_url(server_url)
        response = _request_json("GET", base, f"/analyses/{_seg(analysis_id)}/analysis_data.json", timeout=600)
    except (ValueError, RuntimeError) as e:
        return {"ok": False, "error": str(e), "analysis_id": analysis_id}
    return {"ok": True, "analysis_id": analysis_id, "response": response}

def submit_wait_download(
    project_id: str,
    osa_json_path: str,
    output_dir: str,
    server_url: str | None = None,
    analysis_name: str | None = None,
    upload_zip_path: str | None = None,
    schema_path: str | None = None,
    analysis_type: str | None = None,
    poll_interval_seconds: int = 60,
    timeout_seconds: int = 86400,
    download_format: str = "csv",
    require_foundational_measures: bool = True,
) -> dict[str, Any]:
    submission = submit_analysis(
        project_id=project_id,
        osa_json_path=osa_json_path,
        server_url=server_url,
        analysis_name=analysis_name,
        upload_zip_path=upload_zip_path,
        schema_path=schema_path,
        require_foundational_measures=require_foundational_measures,
    )
    if not submission.get("ok"):
        return {"ok": False, "stage": "submit", "submission": submission}

    analysis_id = submission["analysis_id"]
    status = wait_for_analysis(
        analysis_id,
        server_url=server_url,
        analysis_type=analysis_type,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )
    if not status.get("ok"):
        return {"ok": False, "stage": "wait", "submission": submission, "status": status}

    download = download_analysis_data(analysis_id, output_dir, server_url=server_url, file_format=download_format)
    return {
        "ok": bool(download.get("ok")),
        "stage": "complete" if download.get("ok") else "download",
        "submission": submission,
        "status": status,
        "download": download,
    }
