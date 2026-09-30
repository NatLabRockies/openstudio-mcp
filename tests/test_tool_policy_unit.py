import pytest

from mcp_server import sandbox, tool_policy

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for v in ("OSMCP_TOOLS_ALLOW", "OSMCP_TOOLS_DENY", "OSMCP_ENABLE_CODE_TOOLS", "OSMCP_ALLOW_UNSANDBOXED"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")


def test_stdio_exposes_everything():
    assert all(tool_policy.tool_enabled(t) for t in tool_policy.CODE_AUTHORING_TOOLS)


def test_http_hides_code_tools_by_default(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    assert not tool_policy.tool_enabled("create_measure")
    assert tool_policy.tool_enabled("apply_measure")
    monkeypatch.setenv("OSMCP_ENABLE_CODE_TOOLS", "true")
    assert tool_policy.tool_enabled("create_measure")


def test_allow_and_deny_lists(monkeypatch):
    monkeypatch.setenv("OSMCP_TOOLS_DENY", "run_osw, view_model")
    assert not tool_policy.tool_enabled("run_osw")
    assert tool_policy.tool_enabled("get_model_summary")
    monkeypatch.setenv("OSMCP_TOOLS_ALLOW", "get_model_summary")
    assert not tool_policy.tool_enabled("apply_measure")
    assert tool_policy.tool_enabled("get_model_summary")


def test_http_fails_closed_without_full_sandbox(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setattr(sandbox, "active_tier", lambda: "clean-env")
    with pytest.raises(RuntimeError, match="full sandbox"):
        tool_policy.enforce_http_sandbox()
    monkeypatch.setenv("OSMCP_ALLOW_UNSANDBOXED", "true")
    tool_policy.enforce_http_sandbox()
    monkeypatch.delenv("OSMCP_ALLOW_UNSANDBOXED")
    monkeypatch.setattr(sandbox, "active_tier", lambda: "landlock")
    tool_policy.enforce_http_sandbox()


def test_stdio_never_blocked(monkeypatch):
    monkeypatch.setattr(sandbox, "active_tier", lambda: "off")
    tool_policy.enforce_http_sandbox()
