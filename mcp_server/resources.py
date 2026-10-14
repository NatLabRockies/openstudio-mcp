"""A model's companion resources, laid out the way the OpenStudio Application does it.

`/path/to/model.osm` keeps its resources (ExternalFile targets: Python EMS plugin
scripts, Schedule:File CSVs, custom EPWs) in its companion folder
`/path/to/model/files/` (SDK `getCompanionFolder`, used as is). Every OSM owns
its own folder, so two models in one directory never share or overwrite each
other's resources. Only `files/` is created here; the Application's
`workflow.osw`, `run/` and `measures/` entries are not (it creates them itself
when it opens a model).

Models this server saved before the companion folder existed keep their
resources in a sibling `<dir>/files/`. Reads honour both, companion first;
writes go to the companion folder; a save copies the legacy resources forward.

Both dirs are tenant-writable, so nothing here follows a symlink: not at the
companion folder, not at `files/`, not at an entry.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.config import is_path_allowed
from mcp_server.util import copy_regular_file_nofollow

# Matches the measure-output budget in measures/operations.py.
MAX_RESOURCE_FILE_BYTES = 64 * 1024 * 1024


def companion_folder(osm_path: Path | str) -> Path:
    """`<dir>/<stem>/` for an OSM, via the SDK (the Application's rule)."""
    return Path(openstudio.getCompanionFolder(openstudio.path(str(Path(osm_path)))))


def companion_files_dir(osm_path: Path | str) -> Path:
    """Where a model's resources live: `<dir>/<stem>/files/`."""
    return companion_folder(osm_path) / "files"


def legacy_files_dir(osm_path: Path | str) -> Path:
    """The sibling `<dir>/files/` this server used before the companion folder."""
    return Path(osm_path).parent / "files"


def resource_dir_issue(files_dir: Path, *, write: bool) -> str | None:
    """Why `files_dir` must not be used as a resource dir, or None when it may be.

    The dir need not exist yet. It must not be a symlink, nor sit under a
    symlinked parent (a link planted at the companion folder would make
    `<stem>/files` look like an ordinary directory), must not exist as a
    non-directory, and its resolved location must be inside the caller's
    allowed roots (writable ones when `write`).
    """
    parent = files_dir.parent
    if parent.is_symlink():
        return f"{parent} is a symlink"
    if parent.exists() and not parent.is_dir():
        return f"{parent} exists and is not a directory"
    if files_dir.is_symlink():
        return f"{files_dir} is a symlink"
    if files_dir.exists() and not files_dir.is_dir():
        return f"{files_dir} exists and is not a directory"
    if not is_path_allowed(files_dir, write=write):
        kind = "writable for this session" if write else "inside the allowed roots"
        return f"{files_dir} is not {kind}"
    return None


def resource_sources(osm_path: Path | str) -> list[Path]:
    """Existing resource dirs of a model, highest precedence first.

    Companion folder, then the legacy sibling. Dirs that do not exist are
    left out; a dir that fails resource_dir_issue(read) raises ValueError so
    a planted link is never silently read around.
    """
    out: list[Path] = []
    for candidate in (companion_files_dir(osm_path), legacy_files_dir(osm_path)):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        issue = resource_dir_issue(candidate, write=False)
        if issue:
            raise ValueError(f"resource dir not usable: {issue}")
        out.append(candidate)
    return out


def find_resource(osm_path: Path | str | None, name: str, *, first: list[Path] = ()) -> Path | None:
    """The regular, non-link file `name` from the first source that has it.

    `first` are dirs searched before the model's own (the session's pending
    workspace); `osm_path` None means a model with no file yet.
    """
    safe = Path(name).name
    if not safe:
        return None
    sources = list(first)
    if osm_path is not None:
        sources += resource_sources(osm_path)
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


def copy_resources(
    sources: list[Path], dst: Path, *, overwrite: bool = False,
) -> dict[str, Any]:
    """Copy resource files from `sources` into `dst`, first source wins per name.

    Walks each source without following links, copies regular files through
    no-follow opens with the size budget, keeps relative subpaths. An entry
    already present in `dst` is left alone unless `overwrite` (an existing
    link or directory at a destination name is never written through and is
    reported as skipped). A source that IS `dst` is ignored; a source that
    nests with `dst` (a `files.osm` whose companion sits inside the legacy
    `files/`) raises ValueError. Creates `dst` only when there is something
    to copy. Returns {"copied": [(rel, source_index)], "skipped": [(rel, why)]}.
    """
    copied: list[tuple[str, int]] = []
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, src in enumerate(sources):
        if not src.is_dir() or src.is_symlink():
            continue
        relation = _related(src, dst)
        if relation == "same":
            continue
        if relation == "inside":
            raise ValueError(f"{src} and {dst} nest inside each other; refusing to copy resources")
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
            here = Path(dirpath)
            dirnames[:] = [d for d in dirnames if not (here / d).is_symlink()]
            for fname in sorted(filenames):
                entry = here / fname
                rel = str((here / fname).relative_to(src))
                if rel in seen:
                    continue
                seen.add(rel)
                if entry.is_symlink() or not entry.is_file():
                    skipped.append((rel, "not a regular file"))
                    continue
                target = dst / rel
                if target.is_symlink() or target.is_dir():
                    skipped.append((rel, "destination is a link or directory"))
                    continue
                if target.exists() and not overwrite:
                    continue
                if target.parent.is_symlink():
                    skipped.append((rel, "destination parent is a link"))
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    copy_regular_file_nofollow(entry, target, MAX_RESOURCE_FILE_BYTES)
                except (OSError, ValueError) as e:
                    skipped.append((rel, str(e)))
                    continue
                copied.append((rel, index))
    return {"copied": copied, "skipped": skipped}


def stage_model_resources(
    osm_path: Path | str | None, dst: Path, *, first: list[Path] = (),
) -> str | None:
    """Copy a model's resources (and `first` dirs, which win) into a run's `files/`.

    For run_simulation and apply_measure: the CLI searches `<run_dir>/files`
    for ExternalFile names, so the resources travel with the seed without any
    path in the model or OSW being rewritten; the copy, rather than a search
    path pointing at the model dir, is what the sandbox tier needs (the
    confined subprocess reads only its run dir). Returns an error string when
    a source dir is not usable (a planted link), else None.
    """
    sources = list(first)
    if osm_path is not None:
        try:
            sources += resource_sources(osm_path)
        except ValueError as e:
            return f"Model resources were not staged: {e}"
    if not sources:
        return None
    try:
        copy_resources(sources, dst)
    except ValueError as e:
        return f"Model resources were not staged: {e}"
    return None
