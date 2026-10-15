"""A model bundle: the OSM plus its companion folder, the unit the OpenStudio Application moves.

The Application opens a model by copying its whole companion folder into a
temp dir and saves it back wholesale; a model is never one file. This module
is that unit for the server's own moves (`request_download(bundle=True)`,
and the zip layout a later upload can restore):

    <stem>.osm
    <stem>/files/<resource>...        the effective resources, #199 precedence
    <stem>/.resources-migrated        so an unzip beside a stray files/ never
                                      reads it as the model's legacy resources

Everything comes through `resources.copy_resources`: regular files only,
no-follow opens, links skipped, the per-file and aggregate budgets, and a
`ValueError` on a source that is a planted link. A regular resource that
could not be copied fails the bundle; a model with a resource silently
missing is worse than no bundle.

`resources_digest` is the same unit as an identity: the OSAF seed preflight
and `run_simulation` both hash the effective resource set with it, so a
cached seed run is reused only when the resources it simulated are the
ones the package carries.

SDK-free on purpose (see resources.py): the signed download route and the
unit tier both import it.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from mcp_server.config import run_root_for, user_run_root
from mcp_server.resources import (
    MAX_RESOURCE_FILE_BYTES,
    MAX_RESOURCE_FILES,
    MAX_RESOURCE_TOTAL_BYTES,
    MIGRATED_MARKER,
    PathAllowed,
    companion_folder,
    copy_resources,
    resource_dir_issue,
    resource_sources,
)
from mcp_server.util import (
    copy_regular_file_nofollow,
    open_nofollow_for_write,
    sha256_regular_file_nofollow,
)

# An OSM is one regular file; this bounds the no-follow copy into the staging dir.
MAX_BUNDLE_OSM_BYTES = 1024 * 1024 * 1024
STAGING_PREFIX = "_bundle_"
MARKER_TEXT = "resources complete in files/ (model bundle)\n"


def _resource_dirs(osm: Path, first: list[Path], allowed: PathAllowed | None) -> list[Path]:
    sources: list[Path] = []
    for extra in first:
        issue = resource_dir_issue(extra, write=False, allowed=allowed)
        if issue:
            raise ValueError(f"resource dir not usable: {issue}")
        sources.append(extra)
    sources += resource_sources(osm, allowed=allowed)
    return sources


def lexical_link_issue(path: Path) -> str | None:
    """Why `path` cannot be used as the lexical location of a bundle, else None.

    `is_path_allowed_for` resolves before it checks, so a link inside the
    caller's own root passes it; the bundle must still never read through
    one (the companion folder next to a linked OSM is not the model's). So
    every component from the filesystem anchor down is checked for a link,
    and a path with `.` or `..` parts is refused outright: `/x/../y/m.osm`
    means different things depending on whether `x` is a link.
    """
    if not path.is_absolute():
        return f"{path} is not an absolute path"
    if any(part in (".", "..") for part in path.parts):
        return f"{path} contains '.' or '..' components"
    here = Path(path.anchor)
    for part in path.parts[1:]:
        here = here / part
        if here.is_symlink():
            return f"{here} is a symlink"
    return None


def list_bundle_members(
    osm_path: Path | str, *, first: list[Path] = (), allowed: PathAllowed | None = None,
) -> list[str]:
    """The arcnames `stage_bundle` would produce, without copying anything.

    Same walk rules as `copy_resources` (first source wins per relative
    path, links and non-regular entries skipped, the marker never listed
    from a source). Raises ValueError like `stage_bundle` on a planted link
    at the OSM, the companion folder or `files/`.
    """
    osm = Path(osm_path)
    if osm.is_symlink() or not osm.is_file():
        raise ValueError(f"{osm} is a symlink or not a regular file")
    stem = companion_folder(osm).name
    members = [osm.name]
    seen: set[str] = set()
    for src in _resource_dirs(osm, list(first), allowed):
        if not src.is_dir() or src.is_symlink():
            continue
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
            here = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames if not (here / d).is_symlink())
            rel_dir = here.relative_to(src)
            for fname in sorted(filenames):
                rel = str(rel_dir / fname) if rel_dir.parts else fname
                if rel in seen or fname == MIGRATED_MARKER:
                    continue
                seen.add(rel)  # before the regular-file test, exactly as copy_resources does
                entry = here / fname
                if entry.is_symlink() or not entry.is_file():
                    continue
                members.append(f"{stem}/files/{Path(rel).as_posix()}")
    members.append(f"{stem}/{MIGRATED_MARKER}")
    return members


def combine_resource_hashes(files: dict[str, str]) -> str | None:
    """One sha256 over `{rel: sha256}`, independent of walk order; None for no files.

    The manifest and the run record store this value; `validate_analysis_package`
    recomputes it from the zip's lib/ members with the same function.
    """
    if not files:
        return None
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(f"{rel}\0{files[rel]}\n".encode())
    return digest.hexdigest()


def digest_resource_dirs(sources: list[Path]) -> dict[str, Any]:
    """{"files": {rel: sha256}, "sha256": str | None} of the effective resource set in `sources`.

    The walk is `copy_resources`' walk: first dir wins per relative path,
    links and non-regular entries are left out, the migration marker is
    never a resource, the per-file and aggregate budgets apply, and a dir
    that does not exist contributes nothing. Hashing a regular file that
    cannot be read (over the budget, unreadable) raises ValueError: a
    resource that could not be staged must not be part of an identity.
    Relative paths are POSIX, so the same set hashes the same in a run's
    files/, a companion folder and a package's lib/.
    """
    files: dict[str, str] = {}
    seen: set[str] = set()
    total = 0
    for src in sources:
        if not src.is_dir() or src.is_symlink():
            continue
        walk_errors: list[OSError] = []
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False, onerror=walk_errors.append):
            here = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames if not (here / d).is_symlink())
            rel_dir = here.relative_to(src)
            for fname in sorted(filenames):
                rel = (rel_dir / fname).as_posix() if rel_dir.parts else fname
                if rel in seen or fname == MIGRATED_MARKER:
                    continue
                seen.add(rel)
                entry = here / fname
                if entry.is_symlink() or not entry.is_file():
                    continue
                if len(files) + 1 > MAX_RESOURCE_FILES:
                    raise ValueError(f"more than {MAX_RESOURCE_FILES} resource files; refusing to hash")
                total += entry.stat().st_size
                if total > MAX_RESOURCE_TOTAL_BYTES:
                    raise ValueError(f"resources exceed {MAX_RESOURCE_TOTAL_BYTES} bytes in total; refusing to hash")
                try:
                    files[rel] = sha256_regular_file_nofollow(entry, MAX_RESOURCE_FILE_BYTES)
                except (OSError, ValueError) as e:
                    raise ValueError(f"resource {rel} could not be hashed: {e}") from e
        if walk_errors:
            err = walk_errors[0]
            raise ValueError(f"resources under {src} are unreadable: {err.strerror or err}")
    return {"files": files, "sha256": combine_resource_hashes(files)}


def resources_digest(
    osm_path: Path | str, *, first: list[Path] = (), allowed: PathAllowed | None = None,
) -> dict[str, Any]:
    """`digest_resource_dirs` over a model's effective resource dirs (`first`, companion, legacy).

    Raises ValueError like `stage_bundle` when a resource dir is a planted
    link. A model with no resources digests to {"files": {}, "sha256": None}.
    """
    return digest_resource_dirs(_resource_dirs(Path(osm_path), list(first), allowed))


def stage_bundle(
    osm_path: Path | str, staging: Path, *,
    first: list[Path] = (), allowed: PathAllowed | None = None,
) -> dict[str, Any]:
    """Lay the bundle out under `staging` (a server-created, empty dir).

    Returns {"members": [arcname...], "skipped": [(rel, why)...]} where
    skipped holds only links and non-regular entries; a regular resource
    that failed to copy raises ValueError instead.
    """
    osm = Path(osm_path)
    if osm.is_symlink() or not osm.is_file():
        raise ValueError(f"{osm} is a symlink or not a regular file")
    sources = _resource_dirs(osm, list(first), allowed)
    stem = companion_folder(osm).name
    staging.mkdir(parents=True, exist_ok=True)
    copy_regular_file_nofollow(osm, staging / osm.name, MAX_BUNDLE_OSM_BYTES)
    members = [osm.name]
    skipped: list[tuple[str, str]] = []
    if sources:
        outcome = copy_resources(sources, staging / stem / "files")
        failed = [f"{rel} ({why})" for rel, why in outcome["skipped"] if why != "not a regular file"]
        if failed:
            raise ValueError("resources could not be copied: " + "; ".join(failed))
        members += [f"{stem}/files/{Path(rel).as_posix()}" for rel, _ in outcome["copied"]]
        skipped = list(outcome["skipped"])
    (staging / stem).mkdir(exist_ok=True)
    with open_nofollow_for_write(staging / stem / MIGRATED_MARKER) as fh:
        fh.write(MARKER_TEXT)
    members.append(f"{stem}/{MIGRATED_MARKER}")
    return {"members": members, "skipped": skipped}


def write_bundle_zip(
    osm_path: Path | str, zip_path: Path, *,
    first: list[Path] = (), key: str | None = None, allowed: PathAllowed | None = None,
) -> dict[str, Any]:
    """Stage the bundle under the tenant's run root and zip it to `zip_path`.

    `key` names the tenant when called off-request (the signed route);
    otherwise the request identity's run root is used. The staging dir is
    removed before returning. Only the staged regular files are written, so
    `ZipFile.write` never follows a link.
    """
    root = run_root_for(key) if key is not None else user_run_root()
    staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=root))
    try:
        result = stage_bundle(osm_path, staging, first=first, allowed=allowed)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for member in result["members"]:
                src = staging / member
                if src.is_file() and not src.is_symlink():
                    zf.write(src, member)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return result
