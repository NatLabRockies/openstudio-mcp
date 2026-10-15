"""A model's companion resources, laid out the way the OpenStudio Application does it.

`/path/to/model.osm` keeps its resources (ExternalFile targets: Python EMS plugin
scripts, Schedule:File CSVs, custom EPWs) in its companion folder
`/path/to/model/files/`. The folder is the SDK's `getCompanionFolder` rule
(`<dir>/<name up to its last dot>`), computed here without the SDK so this
module stays importable in the unit tier; an integration test pins parity
with the SDK. Every OSM owns its own folder, so two models in one directory
never share or overwrite each other's resources. Only `files/` is created here; the Application's
`workflow.osw`, `run/` and `measures/` entries are not (it creates them itself
when it opens a model).

Models this server saved before the companion folder existed keep their
resources in a sibling `<dir>/files/`. Reads honour both, companion first;
writes go to the companion folder; a save copies the legacy resources forward.

Both dirs are tenant-writable, so nothing here follows a symlink: not at the
companion folder, not at `files/`, not at an entry.

Path authorization defaults to the request's identity (`is_path_allowed`).
The signed download route runs outside any request, so every reader here
takes an `allowed` callable (`is_path_allowed_for` bound to the token's key)
and passes it down; `copy_resources` itself never authorizes, its callers do.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path, PurePath
from typing import Any, Protocol

from mcp_server.config import is_path_allowed
from mcp_server.confined_fs import DirHandle
from mcp_server.util import copy_fd_bounded, open_nofollow_for_write

# Per-file budget matches the measure-output budget in measures/operations.py;
# the aggregate caps bound one copy (a save, a run staging) as a whole.
MAX_RESOURCE_FILE_BYTES = 64 * 1024 * 1024
MAX_RESOURCE_FILES = 500
MAX_RESOURCE_TOTAL_BYTES = 1024 * 1024 * 1024
# Written into the companion folder (not files/) once a save has copied the
# legacy sibling files/ forward; from then on the sibling dir is not consulted.
MIGRATED_MARKER = ".resources-migrated"


class PathAllowed(Protocol):
    """`is_path_allowed` or `functools.partial(is_path_allowed_for, key)`."""

    def __call__(self, p: Path, *, write: bool = False) -> bool: ...


def companion_folder(osm_path: Path | str) -> Path:
    """`<dir>/<stem>/` for an OSM: the SDK's getCompanionFolder rule, computed locally.

    The SDK (boost `stem()`) takes the name up to its LAST dot, so
    `model.v2.osm` -> `model.v2`, `.osm` -> the parent dir, `model.` ->
    `model`. pathlib's `stem` differs on the last two; this matches the SDK
    (pinned by tests/test_model_bundle.py::test_companion_folder_rule_matches_the_sdk).
    """
    p = Path(osm_path)
    stem = p.name.rpartition(".")[0] if "." in p.name else p.name
    return p.parent / stem


def companion_files_dir(osm_path: Path | str) -> Path:
    """Where a model's resources live: `<dir>/<stem>/files/`."""
    return companion_folder(osm_path) / "files"


def legacy_files_dir(osm_path: Path | str) -> Path:
    """The sibling `<dir>/files/` this server used before the companion folder."""
    return Path(osm_path).parent / "files"


def resource_dir_issue(
    files_dir: Path, *, write: bool, allowed: PathAllowed | None = None,
) -> str | None:
    """Why `files_dir` must not be used as a resource dir, or None when it may be.

    The dir need not exist yet. It must not be a symlink, nor sit under a
    symlinked parent (a link planted at the companion folder would make
    `<stem>/files` look like an ordinary directory), must not exist as a
    non-directory, and its resolved location must be inside the caller's
    allowed roots (writable ones when `write`), per `allowed` (default: the
    request identity's `is_path_allowed`).
    """
    check = allowed if allowed is not None else is_path_allowed
    parent = files_dir.parent
    if parent.is_symlink():
        return f"{parent} is a symlink"
    if parent.exists() and not parent.is_dir():
        return f"{parent} exists and is not a directory"
    if files_dir.is_symlink():
        return f"{files_dir} is a symlink"
    if files_dir.exists() and not files_dir.is_dir():
        return f"{files_dir} exists and is not a directory"
    if not check(files_dir, write=write):
        kind = "writable for this session" if write else "inside the allowed roots"
        return f"{files_dir} is not {kind}"
    return None


def legacy_migrated(osm_path: Path | str) -> bool:
    """True once a save has copied the model's legacy sibling files/ into its companion folder.

    Only a regular file counts: the companion folder is tenant-writable, and
    a link planted at the marker's name must neither count nor be written.
    """
    marker = companion_folder(osm_path) / MIGRATED_MARKER
    return marker.is_file() and not marker.is_symlink()


def mark_legacy_migrated(osm_path: Path | str) -> None:
    """Write the marker; refuses (ValueError) a link or non-regular entry at its name."""
    folder = companion_folder(osm_path)
    if folder.is_symlink():
        raise ValueError(f"{folder} is a symlink")
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / MIGRATED_MARKER
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise ValueError(f"{marker} is not a regular file; refusing to write the migration marker")
    with open_nofollow_for_write(marker) as fh:
        fh.write("legacy sibling files/ copied into files/ by save_osm_model\n")


def resource_sources(osm_path: Path | str, *, allowed: PathAllowed | None = None) -> list[Path]:
    """Existing resource dirs of a model, highest precedence first.

    Companion folder, then the legacy sibling until a save has migrated it
    (see MIGRATED_MARKER): after that the companion folder is the whole truth,
    so a resource deleted from it does not come back and a file added to a
    shared legacy dir does not creep in. Dirs that do not exist are left out;
    a dir that fails resource_dir_issue(read) raises ValueError so a planted
    link is never silently read around.
    """
    candidates = [companion_files_dir(osm_path)]
    if not legacy_migrated(osm_path):
        candidates.append(legacy_files_dir(osm_path))
    out: list[Path] = []
    for candidate in candidates:
        if not candidate.exists() and not candidate.is_symlink():
            continue
        issue = resource_dir_issue(candidate, write=False, allowed=allowed)
        if issue:
            raise ValueError(f"resource dir not usable: {issue}")
        out.append(candidate)
    return out


def find_resource(
    osm_path: Path | str | None, name: str, *,
    first: list[Path] = (), allowed: PathAllowed | None = None,
) -> Path | None:
    """The regular, non-link file `name` from the first source that has it.

    `first` are dirs searched before the model's own (the session's pending
    workspace); `osm_path` None means a model with no file yet.
    """
    safe = Path(name).name
    if not safe:
        return None
    sources: list[Path] = []
    for extra in first:
        issue = resource_dir_issue(extra, write=False, allowed=allowed)
        if issue:
            raise ValueError(f"resource dir not usable: {issue}")
        sources.append(extra)
    if osm_path is not None:
        sources += resource_sources(osm_path, allowed=allowed)
    for src in sources:
        candidate = src / safe
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def _related(a: Path, b: Path) -> str | None:
    """'same' / 'inside' when the resolved dirs coincide or nest, else None."""
    ra, rb = a.resolve(), b.resolve()
    if ra == rb:
        return "same"
    if str(ra).startswith(str(rb) + os.sep) or str(rb).startswith(str(ra) + os.sep):
        return "inside"
    return None


def _note_identity(handle: DirHandle, own: set[tuple[int, int]], other: set[tuple[int, int]],
                   src: Path, dst: Path) -> None:
    """Record a directory's (dev, inode); a directory seen on the other side means src and dst nest."""
    ident = handle.identity()
    if ident in other:
        raise ValueError(f"{src} and {dst} nest inside each other; refusing to copy resources")
    own.add(ident)


def copy_resources(
    sources: list[Path], dst: Path, *, overwrite: bool = False,
) -> dict[str, Any]:
    """Copy resource files from `sources` into `dst`, first source wins per relative path.

    Regular files only, with the size budgets, keeping relative subpaths (a
    plugin may import a sibling package). Both trees are walked by directory
    descriptor (confined_fs, issue #190): every component of a source and of
    the destination under a confinement root is opened no-follow relative to
    its parent, so a link planted at any level, before or during the copy,
    is refused rather than followed; outside the roots the same walk runs by
    pathname with no-follow opens of each entry. The walk does not descend
    into linked dirs, a linked entry is skipped, and a link or directory at
    a destination file name is never written through (reported as skipped).
    An entry already present in `dst` is left alone unless `overwrite` (then
    reported in "replaced"); an existing destination is truncated only after
    it is confirmed to be a regular file. A source that IS `dst` is ignored;
    a source that nests with `dst` (a `files.osm` whose companion sits inside
    the legacy `files/`, or a destination that appears inside a source while
    walking) raises ValueError, as does exceeding the aggregate budget.
    Creates `dst` only when there is something to copy. Returns {"copied":
    [(rel, source_index)], "replaced": [rel], "skipped": [(rel, why)]}.
    """
    if dst.is_symlink() or dst.parent.is_symlink():
        raise ValueError(f"{dst} or its parent is a symlink; refusing to write resources there")
    copied: list[tuple[str, int]] = []
    replaced: list[str] = []
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()
    total = 0
    dst_handle: DirHandle | None = None
    src_ids: set[tuple[int, int]] = set()
    dst_ids: set[tuple[int, int]] = set()

    def destination(rel_dir: PurePath, src: Path) -> DirHandle:
        """Handle on dst/rel_dir, created on first use; a failure at dst itself is an error."""
        nonlocal dst_handle
        if dst_handle is None:
            try:
                dst_handle = DirHandle.open(dst, create=True)
            except OSError as e:
                raise ValueError(f"{dst} is not usable as a resource dir: {e}") from e
            _note_identity(dst_handle, dst_ids, src_ids, src, dst)
        if not rel_dir.parts:
            return dst_handle
        sub = dst_handle.walk(rel_dir, create=True)
        try:
            _note_identity(sub, dst_ids, src_ids, src, dst)
        except BaseException:
            sub.close()
            raise
        return sub

    def copy_tree(handle: DirHandle, rel_dir: PurePath, index: int, src: Path) -> None:
        nonlocal total
        _note_identity(handle, src_ids, dst_ids, src, dst)
        here = str(rel_dir) if rel_dir.parts else "."
        try:
            with handle.scandir() as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError as e:
            # A subtree the walk could not read must not vanish silently: it is
            # reported as a failed (non-link) entry, so staging errors and a
            # migration is not declared complete.
            skipped.append((here, f"unreadable: {e.strerror or e}"))
            return
        for entry in entries:
            rel = str(rel_dir / entry.name) if rel_dir.parts else entry.name
            if entry.is_dir(follow_symlinks=False):
                try:
                    child = handle.subdir(entry.name)
                except OSError as e:
                    skipped.append((rel, f"unreadable: {e.strerror or e}"))
                    continue
                try:
                    copy_tree(child, rel_dir / entry.name, index, src)
                finally:
                    child.close()
                continue
            if entry.is_symlink() and entry.is_dir():
                skipped.append((rel, "not a regular file"))  # a linked dir is not descended
                continue
            if rel in seen or entry.name == MIGRATED_MARKER:
                continue
            seen.add(rel)
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                skipped.append((rel, "not a regular file"))
                continue
            try:
                target_dir = destination(rel_dir, src)
            except OSError as e:
                skipped.append((rel, f"destination parent is a link ({e.strerror or e})"))
                continue
            try:
                existing = target_dir.lstat(entry.name)
                if existing is not None:
                    if stat.S_ISLNK(existing.st_mode) or stat.S_ISDIR(existing.st_mode):
                        skipped.append((rel, "destination is a link or directory"))
                        continue
                    if not stat.S_ISREG(existing.st_mode):
                        skipped.append((rel, "destination is not a regular file"))
                        continue
                    if not overwrite:
                        continue
                if len(copied) + 1 > MAX_RESOURCE_FILES:
                    raise ValueError(f"more than {MAX_RESOURCE_FILES} resource files; refusing to copy")
                try:
                    src_fd = handle.open_file(entry.name, os.O_RDONLY)
                except (OSError, ValueError) as e:
                    skipped.append((rel, str(e)))
                    continue
                try:
                    size = os.fstat(src_fd).st_size
                    total += size
                    if total > MAX_RESOURCE_TOTAL_BYTES:
                        raise ValueError(
                            f"resources exceed {MAX_RESOURCE_TOTAL_BYTES} bytes in total; refusing to copy")
                    if size > MAX_RESOURCE_FILE_BYTES:
                        skipped.append(
                            (rel, f"{entry.name}: {size} bytes exceeds the {MAX_RESOURCE_FILE_BYTES}-byte limit"))
                        continue
                    try:
                        dst_fd, existed = target_dir.create_file(entry.name, overwrite=overwrite)
                    except FileExistsError:
                        continue  # appeared since the lstat; not overwriting
                    except (OSError, ValueError):
                        skipped.append((rel, "destination is a link or directory"))
                        continue
                    try:
                        copy_fd_bounded(src_fd, dst_fd, MAX_RESOURCE_FILE_BYTES, entry.name)
                    except (OSError, ValueError) as e:
                        skipped.append((rel, str(e)))
                        continue
                finally:
                    os.close(src_fd)
                copied.append((rel, index))
                if existed:
                    replaced.append(rel)
            finally:
                if target_dir is not dst_handle:
                    target_dir.close()

    try:
        for index, src in enumerate(sources):
            if not src.is_dir() or src.is_symlink():
                continue
            relation = _related(src, dst)
            if relation == "same":
                continue
            if relation == "inside":
                raise ValueError(f"{src} and {dst} nest inside each other; refusing to copy resources")
            try:
                handle = DirHandle.open(src)
            except OSError as e:
                skipped.append((".", f"unreadable: {e.strerror or e}"))
                continue
            try:
                copy_tree(handle, PurePath(), index, src)
            finally:
                handle.close()
    finally:
        if dst_handle is not None:
            dst_handle.close()
    return {"copied": copied, "replaced": replaced, "skipped": skipped}


def stage_model_resources(
    osm_path: Path | str | None, dst: Path, *,
    first: list[Path] = (), allowed: PathAllowed | None = None, overwrite: bool = False,
) -> str | None:
    """Copy a model's resources (and `first` dirs, which win) into a run's `files/`.

    For run_simulation and apply_measure: the CLI searches `<run_dir>/files`
    for ExternalFile names, so the resources travel with the seed without any
    path in the model or OSW being rewritten; the copy, rather than a search
    path pointing at the model dir, is what the sandbox tier needs (the
    confined subprocess reads only its run dir). A file already in `dst` is
    kept unless `overwrite`. Returns an error string when a source dir is
    not usable (a planted link), else None.
    """
    sources = list(first)
    if osm_path is not None:
        try:
            sources += resource_sources(osm_path, allowed=allowed)
        except ValueError as e:
            return f"Model resources were not staged: {e}"
    if not sources:
        return None
    try:
        outcome = copy_resources(sources, dst, overwrite=overwrite)
    except ValueError as e:
        return f"Model resources were not staged: {e}"
    # A link is skipped on purpose; a regular resource that could not be
    # copied (over the budget, unreadable) would silently vanish from the run.
    failed = [f"{name} ({why})" for name, why in outcome["skipped"] if why != "not a regular file"]
    if failed:
        return "Model resources were not staged: " + "; ".join(failed)
    return None
