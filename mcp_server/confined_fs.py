"""Descriptor-anchored file access under tenant-writable trees (issue #190).

The server reads, writes and copies files in directories that a tenant's
sandboxed processes also write (run dirs, the session workspace, a model's
companion folder, an OSAF package dir, measure dirs, the temp staging of
``openstudio measure -u``). A no-follow open protects the final path
component only; every directory above it is resolved by pathname at open
time, after whatever the caller checked. Here a path is anchored instead:
its confinement root (``config.confinement_roots()``: RUN_ROOT, MEASURES_DIR
and the canonical temp dir, all server-owned, with no tenant-writable
ancestor) is opened by pathname, and every component below it is opened
relative to the previous directory's descriptor with ``O_NOFOLLOW |
O_DIRECTORY``. A link planted at any component, at any time, fails that
component's open instead of redirecting the access.

Paths under no confinement root (the shared read-only roots) and platforms
without ``dir_fd`` (Windows) keep the final-component no-follow behaviour
through the same API, so callers need not know which case they are in.

Writes never truncate anything that is not a regular file: a file is created
with ``O_EXCL``, and an existing entry is opened without ``O_TRUNC``,
checked with ``fstat`` and truncated through that same descriptor.
"""
from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path, PurePath

O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_BINARY = getattr(os, "O_BINARY", 0)
_DIR_FLAGS = os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC


def supported() -> bool:
    """Whether this platform can walk a tree by descriptor (openat family; Linux, macOS)."""
    return os.open in os.supports_dir_fd and os.mkdir in os.supports_dir_fd and O_DIRECTORY != 0


def lexical_abspath(path: str | os.PathLike[str]) -> Path:
    """Absolute path WITHOUT resolving links: the walk decides what each component is.

    A ``..`` component is refused (ValueError): collapsing it lexically would
    not match what a resolve-based authorization saw when a link sits before
    it (``alice/link/../../bob`` resolves inside alice but collapses to bob),
    and the descriptor walk cannot step out of the directory it holds.
    """
    raw = os.fspath(path)
    if ".." in Path(raw).parts:
        raise ValueError(f"path contains a '..' component: {raw!r}")
    return Path(os.path.abspath(raw))  # noqa: PTH100 - resolve() would follow links


def confinement_root_for(path: str | os.PathLike[str]) -> Path | None:
    """The longest registered root the lexical path lies under, or None."""
    from mcp_server.config import confinement_roots

    p = str(lexical_abspath(path))
    best: Path | None = None
    for root in confinement_roots():
        r = str(root)
        if (p == r or p.startswith(r + os.sep)) and (best is None or len(r) > len(str(best))):
            best = root
    return best


def check_name(name: str) -> str:
    """A single path component; anything else would make ``dir_fd`` meaningless."""
    if (not name or name in (".", "..") or "/" in name or os.sep in name
            or (os.altsep is not None and os.altsep in name)):
        raise ValueError(f"not a plain file name: {name!r}")
    return name


class DirHandle:
    """A directory held open by descriptor; entries are opened relative to it.

    ``fd`` is None in path mode (a directory under no confinement root, or a
    platform without ``dir_fd``): entries are then opened by joined pathname
    with a no-follow open of the entry and an ``is_symlink`` check of each
    subdirectory, the pre-#190 behaviour.
    """

    def __init__(self, path: Path, fd: int | None):
        self.path = path
        self.fd = fd

    @classmethod
    def open(cls, directory: str | os.PathLike[str], *, create: bool = False,
             immediate: bool = False) -> DirHandle:
        """Handle on ``directory``, walked from its confinement root when it has one.

        ``create`` makes missing components on the way (each then opened
        no-follow, so a link planted at a created name is refused). Without a
        root: ``immediate=True`` opens the directory itself by pathname with
        ``O_NOFOLLOW`` (what ``write_text_in_dir_nofollow`` did before #190, a
        link AT the directory refused); otherwise path mode.
        """
        p = lexical_abspath(directory)
        root = confinement_root_for(p) if supported() else None
        if root is None:
            if create and not p.exists():
                parent = cls.open(p.parent, create=True)
                try:
                    return parent.subdir(p.name, create=True)
                finally:
                    parent.close()
            if immediate and supported():
                return cls(p, os.open(p, _DIR_FLAGS))
            return cls(p, None)
        root_handle = cls(root, os.open(root, _DIR_FLAGS))
        rel = p.relative_to(root)
        if not rel.parts:
            return root_handle
        try:
            return root_handle.walk(rel, create=create)
        finally:
            root_handle.close()

    def walk(self, rel: PurePath | str, *, create: bool = False) -> DirHandle:
        """Handle on ``rel`` below this directory, one no-follow component at a time.

        Returns this handle itself for an empty ``rel``; intermediates are closed.
        """
        parts = PurePath(rel).parts
        if not parts:
            return self
        cur = self
        try:
            for part in parts:
                nxt = cur.subdir(part, create=create)
                if cur is not self:
                    cur.close()
                cur = nxt
        except BaseException:
            if cur is not self:
                cur.close()
            raise
        return cur

    def subdir(self, name: str, *, create: bool = False) -> DirHandle:
        """Open (or create then open) the subdirectory ``name``; a link or non-directory at it fails."""
        check_name(name)
        child = self.path / name
        if self.fd is None:
            if child.is_symlink():
                raise OSError(getattr(os, "ELOOP", 40), "is a symbolic link", str(child))
            if not child.exists():
                if not create:
                    raise FileNotFoundError(str(child))
                child.mkdir()
            if not child.is_dir():
                raise NotADirectoryError(str(child))
            return DirHandle(child, None)
        try:
            fd = os.open(name, _DIR_FLAGS, dir_fd=self.fd)
        except FileNotFoundError:
            if not create:
                raise
            with contextlib.suppress(FileExistsError):  # created meanwhile: the open below decides what it is
                os.mkdir(name, 0o755, dir_fd=self.fd)
            fd = os.open(name, _DIR_FLAGS, dir_fd=self.fd)
        return DirHandle(child, fd)

    def _open(self, name: str, flags: int, mode: int) -> int:
        if self.fd is None:
            return os.open(self.path / name, flags, mode)
        return os.open(name, flags, mode, dir_fd=self.fd)

    def open_file(self, name: str, flags: int, mode: int = 0o644, *,
                  not_same_as: tuple[int, int] | None = None) -> int:
        """Open ``name`` here as a regular file (ValueError otherwise), never following a link.

        ``O_NOFOLLOW | O_NONBLOCK`` are always added (a FIFO cannot block the
        open before ``fstat`` rejects it). ``O_CREAT | O_TRUNC`` is carried
        out as create-exclusive, else open-existing, ``fstat``, ``ftruncate``;
        ``not_same_as`` (a source's ``(st_dev, st_ino)``) refuses that
        truncation when the existing entry is the source itself.
        """
        if flags & os.O_CREAT and flags & os.O_TRUNC:
            fd, _existed = self.create_file(name, mode, overwrite=True, flags=flags, not_same_as=not_same_as)
            return fd
        check_name(name)
        fd = self._open(name, flags | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC | O_BINARY, mode)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError(f"{name}: not a regular file")
        except BaseException:
            os.close(fd)
            raise
        return fd

    def create_file(self, name: str, mode: int = 0o644, *, overwrite: bool,
                    flags: int = os.O_WRONLY, not_same_as: tuple[int, int] | None = None) -> tuple[int, bool]:
        """Create ``name`` for writing; returns (fd, existed).

        Created exclusively when absent. When present: ``FileExistsError``
        unless ``overwrite``; then it is opened without truncation, must be
        a regular file (ValueError, nothing touched) and must not be the
        file ``not_same_as`` identifies (a copy's source: same path or a hard
        link; ValueError, nothing touched), and is then truncated through the
        descriptor. ``flags`` may add O_RDWR / O_APPEND; CREAT, EXCL and
        TRUNC are managed here.
        """
        check_name(name)
        base = (flags & ~(os.O_CREAT | os.O_EXCL | os.O_TRUNC)) | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC | O_BINARY
        try:
            fd = self._open(name, base | os.O_CREAT | os.O_EXCL, mode)
            existed = False
        except FileExistsError:
            if not overwrite:
                raise
            fd = self._open(name, base, mode)
            existed = True
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise ValueError(f"{name}: not a regular file")
            if existed and not_same_as is not None and (st.st_dev, st.st_ino) == not_same_as:
                raise ValueError(f"{name}: destination is the source file")
            if existed:
                os.ftruncate(fd, 0)
        except BaseException:
            os.close(fd)
            raise
        return fd, existed

    def scandir(self):
        """``os.scandir`` of this directory; check entries with ``follow_symlinks=False``."""
        return os.scandir(self.fd if self.fd is not None else self.path)

    def lstat(self, name: str) -> os.stat_result | None:
        """``lstat`` of the entry ``name`` here, None when absent; never follows a link."""
        check_name(name)
        try:
            if self.fd is None:
                return os.lstat(self.path / name)
            return os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None

    def unlink(self, name: str) -> None:
        check_name(name)
        if self.fd is None:
            (self.path / name).unlink()
        else:
            os.unlink(name, dir_fd=self.fd)

    def identity(self) -> tuple[int, int]:
        """(st_dev, st_ino) of the directory itself, for same-directory checks across handles."""
        st = os.fstat(self.fd) if self.fd is not None else os.lstat(self.path)
        return st.st_dev, st.st_ino

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self) -> DirHandle:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def open_confined(path: str | os.PathLike[str], flags: int, mode: int = 0o644, *,
                  not_same_as: tuple[int, int] | None = None) -> int:
    """``os.open`` for a file under a tenant-writable tree, walked from its confinement root.

    Links at any component fail (OSError), a non-regular file fails
    (ValueError), ``O_CREAT | O_TRUNC`` follows the create-exclusive /
    ftruncate policy. Outside every root the final component is opened
    no-follow by pathname with the same checks.
    """
    p = lexical_abspath(path)
    handle = DirHandle.open(p.parent)
    try:
        return handle.open_file(p.name, flags, mode, not_same_as=not_same_as)
    finally:
        handle.close()
