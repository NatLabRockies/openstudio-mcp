"""Multi-tenant isolation for the measures tree (/measures).

No Docker/OpenStudio — these test the pure path-scoping primitives in
mcp_server.config that decide whether one HTTP tenant can reach another's
authored/downloaded measures. The end-to-end create/list path across two HTTP
sessions is covered by tests/test_measure_discovery.py.
"""
from __future__ import annotations

import pytest

from mcp_server import config

pytestmark = pytest.mark.unit


def test_measures_tree_is_not_a_shared_read_root():
    # Regression: PR #65 added /measures (+ custom/bcl) to _SHARED_READ_ROOTS, so
    # is_path_allowed granted every tenant read access to the whole measures tree —
    # i.e. one tenant could read another's authored measures. The measures tree must
    # be governed by per-user scoping, never a global shared read root.
    probe = (config.MEASURES_DIR / "someone_else" / "custom" / "m").resolve()
    assert not any(config._under(probe, r) for r in config._SHARED_READ_ROOTS), (
        "MEASURES_DIR must not be reachable via _SHARED_READ_ROOTS — that exposes "
        "every tenant's measures to every other tenant"
    )


@pytest.mark.parametrize(
    "helper",
    ["user_run_root", "user_measures_root", "user_custom_measures_dir", "user_bcl_measures_dir"],
)
def test_per_user_path_helpers_are_tenant_disjoint(monkeypatch, tmp_path, helper):
    # Regression: PR #65 made custom_measures_dir() a process-global constant, so two
    # tenants resolved to the SAME directory. Every per-user storage helper must yield
    # distinct, non-nested paths for distinct user keys. This is the invariant that
    # would have failed the moment a helper stopped keying on identity.
    monkeypatch.setattr(config, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(config, "MEASURES_DIR", tmp_path / "measures")
    fn = getattr(config, helper)

    monkeypatch.setattr("mcp_server.identity.user_key", lambda: "alice")
    a = fn()
    monkeypatch.setattr("mcp_server.identity.user_key", lambda: "bob")
    b = fn()

    assert a != b, f"{helper}() must differ per tenant, got {a} for both"
    assert not config._under(a, b) and not config._under(b, a), (
        f"{helper}() tenants must be non-nested: {a} vs {b}"
    )


def test_is_path_allowed_denies_cross_tenant_measures(monkeypatch, tmp_path):
    # Regression: with the measures tree shipped as a shared read root (PR #65),
    # is_path_allowed returned True for another tenant's measures dir. A caller must
    # NOT be able to read or write any /measures path outside their own key.
    monkeypatch.setattr(config, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(config, "MEASURES_DIR", tmp_path / "measures")
    monkeypatch.setattr(config, "USER_MEASURES_DIR", tmp_path / "measures")
    # Reproduce the PR's shipped config: measures tree present as a shared read root.
    monkeypatch.setattr(config, "_SHARED_READ_ROOTS", [
        tmp_path / "measures",
        tmp_path / "measures" / "custom",
        tmp_path / "measures" / "bcl",
    ])
    monkeypatch.setattr("mcp_server.identity.user_key", lambda: "alice")

    bob_measure = tmp_path / "measures" / "bob" / "custom" / "m"
    assert config.is_path_allowed(bob_measure) is False, "must not read another tenant's measures"
    assert config.is_path_allowed(bob_measure, write=True) is False, "must not write another tenant's measures"


def test_is_path_allowed_grants_own_measures_read_write(monkeypatch, tmp_path):
    # Validates: a caller has full read+write within their OWN measures area, so
    # create_measure/edit_measure/test_measure work in place (per-user, persists).
    monkeypatch.setattr(config, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(config, "MEASURES_DIR", tmp_path / "measures")
    monkeypatch.setattr(config, "USER_MEASURES_DIR", tmp_path / "measures")
    monkeypatch.setattr("mcp_server.identity.user_key", lambda: "alice")

    own = config.user_custom_measures_dir() / "my_measure"
    assert config.is_path_allowed(own) is True
    assert config.is_path_allowed(own, write=True) is True


def test_local_user_is_keyed_not_root_owner(monkeypatch, tmp_path):
    # Validates: the local/stdio user is a normal keyed principal (/measures/local/…)
    # — nobody owns the bare /measures root, so no identity can reach the whole tree.
    from mcp_server.identity import LOCAL
    monkeypatch.setattr(config, "MEASURES_DIR", tmp_path / "measures")
    monkeypatch.setattr("mcp_server.identity.user_key", lambda: LOCAL)

    root = config.user_measures_root()
    assert root == (tmp_path / "measures" / LOCAL).resolve(), (
        "local must be keyed under /measures/<LOCAL>, not own the bare /measures root"
    )
