"""Principal -> directory key must be injective and never alias LOCAL (#170)."""
import pytest

from mcp_server import config, identity

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("raw", ["local", "LOCAL", "..", ".", "___", "", "python_packages", "uploads", "a/../b"])
def test_reserved_or_degenerate_never_local(raw):
    key = identity._sanitize(raw)
    assert key != identity.LOCAL
    assert "/" not in key and key not in ("", ".", "..")
    assert key.lower() not in identity._RESERVED_KEYS


def test_distinct_principals_get_distinct_keys():
    raws = ["a@x.com", "a_x.com", "a/x.com", "a x.com", "a@x.com ", "alice", "alice~", "Alice.", "Alice", "ALICE"]
    keys = [identity._sanitize(r) for r in raws]
    assert len(set(keys)) == len(raws)


def test_keys_distinct_on_case_insensitive_fs():
    raws = ["Alice", "alice", "ALICE", "run_0123456789ab"]
    keys = [identity._sanitize(r).casefold() for r in raws]
    assert len(set(keys)) == len(raws)
    assert identity._sanitize("run_0123456789ab") != "run_0123456789ab"


def test_plain_names_unchanged_and_deterministic():
    assert identity._sanitize("alice-01") == "alice-01"
    assert identity._sanitize("a@x.com") == identity._sanitize("a@x.com")


def test_run_root_for_rejects_escaping_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUN_ROOT", tmp_path.resolve())
    for bad in ("..", "a/b", ""):
        with pytest.raises(ValueError, match="invalid user key"):
            config.run_root_for(bad)
    assert config.run_root_for("alice").parent == tmp_path.resolve()
