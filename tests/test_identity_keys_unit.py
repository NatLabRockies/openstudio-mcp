"""Principal keys must stay stable and never alias local storage (#170)."""
import sys
from types import SimpleNamespace

import pytest

from mcp_server import config, identity

pytestmark = pytest.mark.unit

RESERVED = {
    "local", "python_packages", "uploads", "lost+found", "examples", "models",
    "exports", "bar_building", "floorspacejs", "custom_measures",
}


@pytest.mark.parametrize("raw", [*sorted(RESERVED), "LOCAL", "..", ".", "___", "", "a/../b"])
def test_reserved_or_degenerate_never_local(raw):
    # Regression: a principal named like a shared directory could access local user data.
    key = identity._sanitize(raw)
    assert key != identity.LOCAL
    assert "/" not in key and key not in ("", ".", "..")
    assert key.lower() not in RESERVED


def test_distinct_principals_get_distinct_keys():
    # Regression: replacing punctuation with underscores merged unrelated principals.
    raws = ["a@x.com", "a_x.com", "a/x.com", "a x.com", "a@x.com ", "alice", "alice~", "Alice.", "Alice", "ALICE"]
    keys = [identity._sanitize(r) for r in raws]
    assert len(set(keys)) == len(raws)


def test_keys_distinct_on_case_insensitive_fs():
    # Validates: case folding and local run names cannot merge tenant directories.
    raws = ["Alice", "alice", "ALICE", "run_0123456789ab"]
    keys = [identity._sanitize(r).casefold() for r in raws]
    assert len(set(keys)) == len(raws)
    assert identity._sanitize("run_0123456789ab") != "run_0123456789ab"


@pytest.mark.parametrize(("raw", "expected"), [
    ("alice-01", "alice-01"),
    ("local", "local~25bf8e1a2393f1108d37029b3df5593236c755742ec93465bbafa9b290bddcf6"),
    ("Alice", "Alice~3bc51062973c458d5a6f2d8d64a023246354ad7e064b1e4e009ec8a0699a3043"),
    ("a@x.com", "a_x.com~478abec7430569163161dfea8513b8ce89d05f559456a26e945c66e1fe55a29d"),
])
def test_plain_names_unchanged_and_deterministic(raw, expected):
    # Validates: persisted identity keys must not change silently and orphan user data.
    assert identity._sanitize(raw) == expected


@pytest.mark.parametrize("bad", ["..", "a/b", "", "a/../bob", "a/..", "a\\b"])
def test_run_root_for_rejects_escaping_keys(tmp_path, monkeypatch, bad):
    # Validates: explicit route keys cannot resolve outside a single tenant directory.
    monkeypatch.setattr(config, "RUN_ROOT", tmp_path.resolve())
    with pytest.raises(ValueError, match="invalid user key"):
        config.run_root_for(bad)


def test_run_root_for_plain_key(tmp_path, monkeypatch):
    # Validates: plain tenant and local paths retain their existing layouts.
    monkeypatch.setattr(config, "RUN_ROOT", tmp_path.resolve())
    assert config.run_root_for("alice") == tmp_path.resolve() / "alice"
    assert config.run_root_for("local") == tmp_path.resolve()


def test_authenticated_local_never_owns_run_root(tmp_path, monkeypatch):
    # Regression: a verified principal named local must not gain the whole run root.
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setattr(config, "RUN_ROOT", tmp_path.resolve())
    monkeypatch.setattr(identity, "_access_token", lambda: SimpleNamespace(client_id="local"))
    expected = "local~25bf8e1a2393f1108d37029b3df5593236c755742ec93465bbafa9b290bddcf6"
    assert identity.user_key() == expected
    assert config.user_run_root() == tmp_path.resolve() / expected


@pytest.mark.parametrize("principal", ["unknown", "", None])
def test_authenticated_token_requires_principal(monkeypatch, principal):
    # Regression: JWTs without identity claims shared FastMCP's unknown principal.
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setattr(identity, "_access_token", lambda: SimpleNamespace(client_id=principal))
    with pytest.raises(ValueError, match="Authenticated token has no usable principal"):
        identity.user_key()


def test_fixed_local_directories_are_reserved():
    # Validates: the shared configuration inventory is kept in sync with identity scoping.
    assert config.LOCAL_RUN_DIR_NAMES == RESERVED - {"local"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink test")
@pytest.mark.parametrize("target", ["outside", "peer"])
def test_user_run_root_rejects_symlink_escape(tmp_path, monkeypatch, target):
    # Regression: user_run_root followed tenant-root symlinks outside RUN_ROOT.
    root = tmp_path / "runs"
    root.mkdir()
    outside = tmp_path / "outside" if target == "outside" else root / "bob"
    outside.mkdir()
    (root / "alice").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(config, "RUN_ROOT", root.resolve())
    monkeypatch.setattr(identity, "user_key", lambda: "alice")
    with pytest.raises(ValueError, match="invalid user key"):
        config.user_run_root()
