"""Session model-state eviction: idle TTL + LRU cap.

Exercises the eviction policy directly (manipulating the session registry with
dummy state) — deterministic, no real models or MCP server needed. It imports
model_manager (which imports openstudio), so it runs in the integration tier.
"""
import pytest
from conftest import integration_enabled

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _guard_and_clean():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")
    import mcp_server.model_manager as mm
    mm._clear_all()
    yield
    mm._clear_all()


def test_idle_sessions_evicted_by_ttl(monkeypatch):
    # Validates: a session idle longer than SESSION_TTL_SECONDS is dropped on sweep,
    # while a recently-active session is retained.
    import mcp_server.model_manager as mm

    monkeypatch.setattr(mm, "SESSION_TTL_SECONDS", 100.0)
    now = mm._now()
    mm._sessions["stale"] = mm._SessionState(model=object(), path=None, last_access=now - 1000)
    mm._sessions["fresh"] = mm._SessionState(model=object(), path=None, last_access=now)

    mm._sweep_idle()

    assert "stale" not in mm._sessions, "session idle beyond TTL must be evicted"
    assert "fresh" in mm._sessions, "recently-active session must be retained"


def test_ttl_zero_disables_eviction(monkeypatch):
    # Validates: SESSION_TTL_SECONDS=0 disables idle eviction entirely.
    import mcp_server.model_manager as mm

    monkeypatch.setattr(mm, "SESSION_TTL_SECONDS", 0.0)
    mm._sessions["ancient"] = mm._SessionState(model=object(), path=None, last_access=mm._now() - 10_000)

    mm._sweep_idle()

    assert "ancient" in mm._sessions, "TTL=0 must keep sessions regardless of idle time"


def test_lru_cap_evicts_least_recently_used(monkeypatch):
    # Validates: when at the cap, the least-recently-used session is evicted to make room.
    import mcp_server.model_manager as mm

    monkeypatch.setattr(mm, "MAX_SESSIONS", 2)
    monkeypatch.setattr(mm, "SESSION_TTL_SECONDS", 0.0)  # isolate LRU from TTL
    now = mm._now()
    mm._sessions["old"] = mm._SessionState(model=object(), path=None, last_access=now - 10)
    mm._sessions["mid"] = mm._SessionState(model=object(), path=None, last_access=now - 5)

    mm._evict_if_needed(keep="new")  # making room for a third session

    assert "old" not in mm._sessions, "LRU cap must evict the oldest session"
    assert "mid" in mm._sessions, "the more-recently-used session must survive"
