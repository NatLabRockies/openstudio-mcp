"""Directory-tree copy and removal under tenant-writable trees (issue #190, part 2).

``shutil.copytree`` and ``shutil.rmtree(path)`` resolve every component of
both trees by pathname at the moment each entry is opened, after whatever the
caller checked. The server stages measure dirs into run dirs, copies run dirs
to a tenant's exports, fills an OSAF package's ``measures/`` and stages an OSW's
directory, all in trees a tenant's sandboxed process also writes. Here both
trees are walked by directory descriptor (``confined_fs.DirHandle``): the
source and the destination are opened from their confinement roots, each
sub-directory relative to its parent with ``O_NOFOLLOW | O_DIRECTORY``, each
file opened no-follow and ``fstat``-checked, each destination file created
through ``DirHandle.create_file`` (never through a link or directory at that
name). A link planted at any component, before or during the copy, fails the
copy instead of redirecting it.

Policy, chosen for trees the sandbox will execute (a silently partial measure
is worse than a failed call): anything that cannot be copied faithfully raises
(``OSError`` for a link or missing component, ``ValueError`` for a non-regular
entry, a budget breach, a nesting of the two trees or a link that leaves the
tree). A symbolic link
is recreated as a link only when it is relative and has no ``..`` component:
such a link can only resolve to a descendant of its own directory, however
links chain (a per-link lexical check is not enough: ``a/up -> ..`` and
``link -> a/up/../x`` each look contained and together escape). Any other link
raises, since the pathname pre-filter (``util.reject_escaping_symlinks``)
already passed and an escaping link at copy time is a swap. Directory and
regular-file permission bits are kept (the sandbox relies on them);
modification times are not. Entries that are neither regular
files, directories nor links (FIFOs, sockets, devices) raise.
"""
from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable, Iterable
from pathlib import Path, PurePath, PurePosixPath

from mcp_server.confined_fs import DirHandle, lexical_abspath
from mcp_server.util import copy_fd_bounded

MAX_TREE_FILES = 20_000
MAX_TREE_FILE_BYTES = 1024 * 1024 * 1024
MAX_TREE_TOTAL_BYTES = 8 * 1024 * 1024 * 1024


def remove_tree_confined(path: str | os.PathLike[str]) -> bool:
    """Remove the entry at ``path`` (a directory tree, a file or a link) through its parent's descriptor.

    Returns whether anything was there. A link at ``path`` is unlinked, never
    followed; a directory is removed with ``shutil.rmtree`` anchored on the
    parent descriptor (``dir_fd``), so nothing above it is resolved again by
    pathname. Links at the parent's components fail the open (OSError).
    """
    p = lexical_abspath(path)
    try:
        parent = DirHandle.open(p.parent)
    except FileNotFoundError:
        return False  # no parent, so nothing at the path; a link on the way is a different error
    with parent:
        st = parent.lstat(p.name)
        if st is None:
            return False
        if stat.S_ISDIR(st.st_mode):
            if parent.fd is None:
                shutil.rmtree(p)
            else:
                shutil.rmtree(p.name, dir_fd=parent.fd)
        else:
            parent.unlink(p.name)
    return True


def _link_is_descending(target: str) -> bool:
    """Whether a link target is relative with no ``..``: it can then only name a descendant of the link's dir."""
    if not target or PurePath(target).is_absolute() or target.startswith(("/", "\\")):
        return False
    return ".." not in PurePosixPath(target.replace(os.sep, "/")).parts


class _TreeCopy:
    def __init__(self, src: Path, dst: Path, *, exclude_names: Iterable[str], ignore: Callable[[str], bool] | None,
                 max_files: int, max_file_bytes: int, max_total_bytes: int, root_mode: bool):
        self.src = src
        self.dst = dst
        self.root_mode = root_mode
        self.exclude = set(exclude_names)
        self.ignore = ignore
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.counts = {"dirs": 0, "files": 0, "bytes": 0, "links": 0}
        self.src_ids: set[tuple[int, int]] = set()
        self.dst_ids: set[tuple[int, int]] = set()

    def _note(self, handle: DirHandle, own: set[tuple[int, int]], other: set[tuple[int, int]]) -> None:
        ident = handle.identity()
        if ident in other:
            raise ValueError(f"{self.src} and {self.dst} nest inside each other; refusing to copy")
        own.add(ident)

    def copy_dir(self, src: DirHandle, dst: DirHandle, rel_dir: PurePath) -> None:
        self._note(src, self.src_ids, self.dst_ids)
        self._note(dst, self.dst_ids, self.src_ids)
        with src.scandir() as it:
            entries = sorted(it, key=lambda e: e.name)
        top = not rel_dir.parts
        for entry in entries:
            name = entry.name
            if (top and name in self.exclude) or (self.ignore is not None and self.ignore(name)):
                continue
            rel = rel_dir / name
            if entry.is_symlink():
                self.copy_link(src, dst, name, rel_dir)
            elif entry.is_dir(follow_symlinks=False):
                child_src = src.subdir(name)
                try:
                    child_dst = dst.subdir(name, create=True)
                    try:
                        self.counts["dirs"] += 1
                        self.copy_dir(child_src, child_dst, rel)
                    finally:
                        child_dst.close()
                finally:
                    child_src.close()
            elif entry.is_file(follow_symlinks=False):
                self.copy_file(src, dst, name, rel)
            else:
                raise ValueError(f"{rel}: not a regular file")
        # The directory's own permission bits, after its children (a read-only dir must still
        # receive them); copytree did the same through copystat. The destination root keeps its
        # own mode when the caller merges into a directory it goes on writing (root_mode=False).
        if top and not self.root_mode:
            return
        mode = stat.S_IMODE((os.fstat(src.fd) if src.fd is not None else os.lstat(src.path)).st_mode)
        if dst.fd is not None and hasattr(os, "fchmod"):
            os.fchmod(dst.fd, mode)
        else:
            dst.path.chmod(mode)

    def copy_link(self, src: DirHandle, dst: DirHandle, name: str, rel_dir: PurePath) -> None:
        # os.readlink, not Path.readlink: relative to the directory descriptor; one API for both modes
        target = os.readlink(name, dir_fd=src.fd) if src.fd is not None else os.readlink(src.path / name)  # noqa: PTH115
        if not _link_is_descending(target):
            raise ValueError(f"{rel_dir / name}: link may leave the copied tree ({target!r}); refusing to copy")
        existing = dst.lstat(name)
        if existing is not None:
            if stat.S_ISDIR(existing.st_mode):
                raise IsADirectoryError(f"{rel_dir / name}: destination is a directory, source is a link")
            dst.unlink(name)
        if dst.fd is not None:
            os.symlink(target, name, dir_fd=dst.fd)
        else:
            os.symlink(target, dst.path / name)  # noqa: PTH211 - keep one API for both modes
        self.counts["links"] += 1

    def copy_file(self, src: DirHandle, dst: DirHandle, name: str, rel: PurePath) -> None:
        if self.counts["files"] + 1 > self.max_files:
            raise ValueError(f"more than {self.max_files} files under {self.src}; refusing to copy")
        src_fd = src.open_file(name, os.O_RDONLY)
        try:
            st = os.fstat(src_fd)
            if st.st_size > self.max_file_bytes:
                raise ValueError(f"{rel}: {st.st_size} bytes exceeds the {self.max_file_bytes}-byte limit")
            if self.counts["bytes"] + st.st_size > self.max_total_bytes:
                raise ValueError(f"{self.src}: tree exceeds {self.max_total_bytes} bytes in total; refusing to copy")
            dst_fd, _existed = dst.create_file(
                name, stat.S_IMODE(st.st_mode) or 0o644, overwrite=True, not_same_as=(st.st_dev, st.st_ino))
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(dst_fd, stat.S_IMODE(st.st_mode))
            except BaseException:
                os.close(dst_fd)
                raise
            copied = copy_fd_bounded(src_fd, dst_fd, self.max_file_bytes, str(rel))
        finally:
            os.close(src_fd)
        self.counts["files"] += 1
        self.counts["bytes"] += copied
        if self.counts["bytes"] > self.max_total_bytes:
            raise ValueError(f"{self.src}: tree exceeds {self.max_total_bytes} bytes in total; refusing to copy")


def copy_tree_confined(
    src: str | os.PathLike[str], dst: str | os.PathLike[str], *,
    replace: bool = False, exclude_names: Iterable[str] = (), ignore: Callable[[str], bool] | None = None,
    max_files: int = MAX_TREE_FILES, max_file_bytes: int = MAX_TREE_FILE_BYTES,
    max_total_bytes: int = MAX_TREE_TOTAL_BYTES, root_mode: bool = True,
) -> dict[str, int]:
    """Copy the directory ``src`` to ``dst`` through directory descriptors; see the module docstring.

    ``dst`` and its missing parents are created from the confinement root. With
    ``replace`` an existing entry at ``dst`` is removed first (through its
    parent's descriptor); without it the trees are merged, an existing regular
    file at a file name replaced, a link or directory there never written
    through (OSError / ValueError). ``exclude_names`` skips top-level entries
    by exact name (a ``run/`` beside the OSW, not one nested in a resource
    dir); ``ignore(name)`` skips entries it returns True for at every depth
    (caches). The budgets bound the copy (ValueError). Directory modes follow
    the source; ``root_mode=False`` leaves the destination root's own mode
    alone (a run dir the server and the sandbox keep writing into). Returns
    ``{"dirs", "files", "bytes", "links"}`` counts.
    """
    src_path = lexical_abspath(src)
    dst_path = lexical_abspath(dst)
    if src_path == dst_path:
        raise ValueError(f"{src_path} is the same directory as {dst_path}; refusing to copy")
    s, d = str(src_path), str(dst_path)
    if d.startswith(s + os.sep) or s.startswith(d + os.sep):
        raise ValueError(f"{src_path} and {dst_path} nest inside each other; refusing to copy")
    if replace:
        remove_tree_confined(dst_path)
    job = _TreeCopy(src_path, dst_path, exclude_names=exclude_names, ignore=ignore, max_files=max_files,
                    max_file_bytes=max_file_bytes, max_total_bytes=max_total_bytes, root_mode=root_mode)
    with DirHandle.open(src_path) as src_handle, DirHandle.open(dst_path, create=True) as dst_handle:
        job.copy_dir(src_handle, dst_handle, PurePath())
    return job.counts
