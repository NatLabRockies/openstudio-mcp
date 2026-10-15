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
from pathlib import Path
from typing import Any, Protocol

from mcp_server.config import is_path_allowed
from mcp_server.util import copy_regular_file_nofollow, open_nofollow_for_write

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


def _components_are_real_dirs(base: Path, rel_dir: Path) -> bool:
    """True when every directory from `base` down to `base/rel_dir` exists as a real dir or not yet.

    A link at any intermediate component would redirect a write below it, so
    each component is checked, not only the immediate parent.
    """
    here = base
    for part in rel_dir.parts:
        here = here / part
        if here.is_symlink():
            return False
        if here.exists() and not here.is_dir():
            return False
    return True


def copy_resources(
    sources: list[Path], dst: Path, *, overwrite: bool = False,
) -> dict[str, Any]:
    """Copy resource files from `sources` into `dst`, first source wins per relative path.

    Regular files only, through no-follow opens with the size budget, keeping
    relative subpaths (a plugin may import a sibling package). Links are
    never followed: the walk does not descend into linked dirs, a linked
    entry is skipped, and on the destination every directory component down
    to the target is checked (`dst` and its parent, the companion folder,
    included). An entry already present in `dst` is left alone unless
    `overwrite` (then reported in "replaced"); a link or directory at a
    destination file name is never written through and is reported as
    skipped. A source that IS `dst` is ignored; a source that nests with
    `dst` (a `files.osm` whose companion sits inside the legacy `files/`)
    raises ValueError, as does exceeding the aggregate budget. Creates `dst`
    only when there is something to copy. Returns {"copied": [(rel,
    source_index)], "replaced": [rel], "skipped": [(rel, why)]}.
    """
    if dst.is_symlink() or dst.parent.is_symlink():
        raise ValueError(f"{dst} or its parent is a symlink; refusing to write resources there")
    copied: list[tuple[str, int]] = []
    replaced: list[str] = []
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()
    total = 0
    for index, src in enumerate(sources):
        if not src.is_dir() or src.is_symlink():
            continue
        relation = _related(src, dst)
        if relation == "same":
            continue
        if relation == "inside":
            raise ValueError(f"{src} and {dst} nest inside each other; refusing to copy resources")
        walk_errors: list[OSError] = []
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False, onerror=walk_errors.append):
            here = Path(dirpath)
            linked_dirs = [d for d in dirnames if (here / d).is_symlink()]
            for d in linked_dirs:
                skipped.append((str((here / d).relative_to(src)), "not a regular file"))
            dirnames[:] = sorted(d for d in dirnames if d not in linked_dirs)
            rel_dir = here.relative_to(src)
            for fname in sorted(filenames):
                rel = str(rel_dir / fname) if rel_dir.parts else fname
                if rel in seen or fname == MIGRATED_MARKER:
                    continue
                seen.add(rel)
                entry = here / fname
                if entry.is_symlink() or not entry.is_file():
                    skipped.append((rel, "not a regular file"))
                    continue
                target = dst / rel
                if not _components_are_real_dirs(dst, rel_dir):
                    skipped.append((rel, "destination parent is a link"))
                    continue
                if target.is_symlink() or target.is_dir():
                    skipped.append((rel, "destination is a link or directory"))
                    continue
                existed = target.exists()
                if existed and not overwrite:
                    continue
                if len(copied) + 1 > MAX_RESOURCE_FILES:
                    raise ValueError(f"more than {MAX_RESOURCE_FILES} resource files; refusing to copy")
                total += entry.stat().st_size
                if total > MAX_RESOURCE_TOTAL_BYTES:
                    raise ValueError(f"resources exceed {MAX_RESOURCE_TOTAL_BYTES} bytes in total; refusing to copy")
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    copy_regular_file_nofollow(entry, target, MAX_RESOURCE_FILE_BYTES)
                except (OSError, ValueError) as e:
                    skipped.append((rel, str(e)))
                    continue
                copied.append((rel, index))
                if existed:
                    replaced.append(rel)
        # A subtree the walk could not read must not vanish silently: it is
        # reported as a failed (non-link) entry, so staging errors and a
        # migration is not declared complete.
        for err in walk_errors:
            where = Path(err.filename) if err.filename else src
            try:
                rel = str(where.relative_to(src)) or "."
            except ValueError:
                rel = str(where)
            skipped.append((rel, f"unreadable: {err.strerror or err}"))
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
