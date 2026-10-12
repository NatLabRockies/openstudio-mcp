"""Tool exposure policy and the HTTP fail-closed sandbox gate (issue #180).

Unit tier: no openstudio import. register_all_skills is exercised through a
FakeMCP so the CollectingMCP hook (the only enforcement point) is on the path.
"""
from __future__ import annotations

import asyncio

import pytest

from mcp_server import sandbox, tool_policy, tool_registry
from mcp_server.skills import register_all_skills

pytestmark = pytest.mark.unit

_POLICY_VARS = (
    "OSMCP_TOOLS_ALLOW", "OSMCP_TOOLS_DENY", "OSMCP_ENABLE_CODE_TOOLS",
    "OSMCP_ALLOW_UNSANDBOXED", "OSMCP_CODE_MODE",
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for v in _POLICY_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    yield
    # A policy-filtered roster must not outlive the test: ensure_collected() returns
    # early on a non-empty registry, so a later router/catalog test would see it.
    tool_registry.reset_descriptors()


class _FakeMCP:
    """Records registrations the way the real FastMCP would receive them."""

    def __init__(self):
        self.names: set[str] = set()

    def tool(self, name=None, **kwargs):
        def decorator(fn):
            self.names.add(name or fn.__name__)
            return fn
        return decorator

    def prompt(self, **kw):
        return lambda fn: fn

    def resource(self, *a, **kw):
        return lambda fn: fn


# ---------------------------------------------------------------- tool_enabled

@pytest.mark.parametrize("name", sorted(tool_policy.CODE_AUTHORING_TOOLS))
def test_stdio_exposes_code_tools(name):
    # Validates: the code-authoring hide applies to HTTP only; stdio (single local user)
    # keeps create_measure and friends without any opt-in flag
    assert tool_policy.tool_enabled(name) is True


@pytest.mark.parametrize("transport", ["http", "streamable-http", "HTTP"])
def test_http_exposes_code_tools_by_default(monkeypatch, transport):
    # Validates: measure authoring is on by default on every transport (maintainer
    # decision: a deployment must actively choose to forbid writing code); the five
    # code-authoring tools are exposed on HTTP with no flag set
    monkeypatch.setenv("MCP_TRANSPORT", transport)
    assert all(tool_policy.tool_enabled(t) for t in tool_policy.CODE_AUTHORING_TOOLS)


@pytest.mark.parametrize(("transport", "value"), [
    ("http", "false"), ("streamable-http", "0"), ("stdio", "no"), ("http", " OFF "),
])
def test_code_tools_opt_out_hides_on_any_transport(monkeypatch, transport, value):
    # Validates: OSMCP_ENABLE_CODE_TOOLS=false (any false spelling) hides exactly the five
    # code-authoring tools on any transport, while execution tools stay visible
    monkeypatch.setenv("MCP_TRANSPORT", transport)
    monkeypatch.setenv("OSMCP_ENABLE_CODE_TOOLS", value)
    assert all(not tool_policy.tool_enabled(t) for t in tool_policy.CODE_AUTHORING_TOOLS)
    assert tool_policy.tool_enabled("apply_measure") is True
    assert tool_policy.tool_enabled("test_measure") is True


@pytest.mark.parametrize(("deny", "hidden", "visible"), [
    ("run_osw, view_model", ("run_osw", "view_model"), ("get_model_summary",)),
    # Regression: entries were compared verbatim, so "Apply_Measure" and a leading space
    # silently matched nothing (the policy failed open)
    ("Apply_Measure,  RUN_OSW", ("apply_measure", "run_osw"), ("view_model",)),
])
def test_deny_list_is_case_insensitive(monkeypatch, deny, hidden, visible):
    # Validates: OSMCP_TOOLS_DENY hides exactly the named tools regardless of case/whitespace
    monkeypatch.setenv("OSMCP_TOOLS_DENY", deny)
    assert [tool_policy.tool_enabled(t) for t in hidden] == [False] * len(hidden)
    assert [tool_policy.tool_enabled(t) for t in visible] == [True] * len(visible)


def test_allow_list_restricts_and_deny_wins(monkeypatch):
    # Validates: with OSMCP_TOOLS_ALLOW set only listed tools register, and a tool listed in
    # both ALLOW and DENY is hidden (deny wins, as documented)
    monkeypatch.setenv("OSMCP_TOOLS_ALLOW", "Get_Model_Summary, run_osw")
    monkeypatch.setenv("OSMCP_TOOLS_DENY", "run_osw")
    assert tool_policy.tool_enabled("get_model_summary") is True
    assert tool_policy.tool_enabled("apply_measure") is False
    assert tool_policy.tool_enabled("run_osw") is False


def test_allow_listing_code_tool_does_not_override_opt_out(monkeypatch):
    # Validates: with OSMCP_ENABLE_CODE_TOOLS=false an allow-listed create_measure stays
    # hidden; the allow-list narrows, it never widens
    monkeypatch.setenv("OSMCP_ENABLE_CODE_TOOLS", "false")
    monkeypatch.setenv("OSMCP_TOOLS_ALLOW", "create_measure,apply_measure")
    assert tool_policy.tool_enabled("create_measure") is False
    assert tool_policy.tool_enabled("apply_measure") is True
    monkeypatch.setenv("OSMCP_ENABLE_CODE_TOOLS", "true")
    assert tool_policy.tool_enabled("create_measure") is True


@pytest.mark.parametrize("value", ["flase", "disabled", "maybe"])
def test_validate_policy_rejects_non_boolean_code_tools_flag(monkeypatch, value):
    # Validates: a misspelt OSMCP_ENABLE_CODE_TOOLS refuses startup instead of silently
    # keeping the default, since the operator clearly meant to set it
    monkeypatch.setenv("OSMCP_ENABLE_CODE_TOOLS", value)
    with pytest.raises(RuntimeError, match="OSMCP_ENABLE_CODE_TOOLS"):
        tool_policy.validate_policy(_KNOWN)


# ------------------------------------------------------------ validate_policy

_KNOWN = frozenset({"apply_measure", "run_osw", "get_model_summary", "create_measure"})


@pytest.mark.parametrize(("var", "value", "unknown"), [
    # Regression: OSMCP_TOOLS_DENY="run_simulaton,Apply_Measure, run_osw" hid only run_osw
    # with no log line; a typo must refuse startup instead of failing open
    ("OSMCP_TOOLS_DENY", "run_simulaton,Apply_Measure, run_osw", "run_simulaton"),
    ("OSMCP_TOOLS_ALLOW", "get_model_summary, nope", "nope"),
    ("OSMCP_TOOLS_DENY", "search", "search"),  # synthetic name only valid under OSMCP_CODE_MODE
])
def test_validate_policy_rejects_unknown_names(monkeypatch, var, value, unknown):
    # Validates: every ALLOW/DENY entry must name a tool in the roster; the error names
    # the variable and the bad entry so the operator can fix it
    monkeypatch.setenv(var, value)
    with pytest.raises(RuntimeError, match=rf"{var}.*'{unknown}'"):
        tool_policy.validate_policy(_KNOWN)


@pytest.mark.parametrize("value", ["", "   ", " , ,"])
def test_validate_policy_rejects_empty_allow_list(monkeypatch, value):
    # Regression: an empty or whitespace OSMCP_TOOLS_ALLOW allowed everything, the opposite
    # of what an operator who set the variable expects
    monkeypatch.setenv("OSMCP_TOOLS_ALLOW", value)
    with pytest.raises(RuntimeError, match="OSMCP_TOOLS_ALLOW is set but empty"):
        tool_policy.validate_policy(_KNOWN)


def test_validate_policy_accepts_roster_names_any_case(monkeypatch):
    # Validates: entries are matched case-insensitively against the roster and an unset
    # ALLOW is "allow everything", so a correct config never trips the startup check
    monkeypatch.setenv("OSMCP_TOOLS_DENY", "Apply_Measure, run_osw")
    tool_policy.validate_policy(_KNOWN)
    monkeypatch.setenv("OSMCP_TOOLS_ALLOW", "GET_MODEL_SUMMARY")
    tool_policy.validate_policy(_KNOWN)


def test_validate_policy_knows_code_mode_tools(monkeypatch):
    # Validates: with OSMCP_CODE_MODE=1 the synthetic search/get_schema/execute names are
    # part of the roster, so they can be denied without tripping the unknown-name check
    monkeypatch.setenv("OSMCP_CODE_MODE", "1")
    monkeypatch.setenv("OSMCP_TOOLS_DENY", "search")
    tool_policy.validate_policy(_KNOWN)


# ----------------------------------------------------- CollectingMCP enforcement

@pytest.mark.parametrize(("env", "hidden", "visible"), [
    ({"MCP_TRANSPORT": "http"}, set(), tool_policy.CODE_AUTHORING_TOOLS | {"apply_measure"}),
    ({"MCP_TRANSPORT": "http", "OSMCP_ENABLE_CODE_TOOLS": "false"}, tool_policy.CODE_AUTHORING_TOOLS,
     {"apply_measure", "run_osw"}),
    ({"OSMCP_ENABLE_CODE_TOOLS": "false"}, tool_policy.CODE_AUTHORING_TOOLS, {"apply_measure"}),
    ({"OSMCP_TOOLS_DENY": "Run_OSW, view_model"}, {"run_osw", "view_model"}, {"apply_measure"}),
    ({"OSMCP_TOOLS_ALLOW": "get_model_summary,list_skills"}, {"apply_measure", "run_osw"},
     {"get_model_summary", "list_skills"}),
])
def test_registration_hook_hides_from_server_and_catalog(monkeypatch, env, hidden, visible):
    # Validates: the CollectingMCP hook is the enforcement point: a hidden tool reaches
    # neither the MCP server nor the descriptor catalog (recommend_tools index), while the
    # full roster is still recorded for policy validation. Mounting develop's tool_registry
    # made the pure tool_enabled tests pass without any enforcement.
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    fake = _FakeMCP()
    register_all_skills(fake)
    catalog = set(tool_registry.descriptors())
    assert hidden.isdisjoint(fake.names), f"hidden tools registered: {hidden & fake.names}"
    assert hidden.isdisjoint(catalog), f"hidden tools in catalog: {hidden & catalog}"
    assert visible <= fake.names and visible <= catalog
    assert hidden | visible <= tool_registry.seen_names()
    assert fake.names == catalog


def test_seen_names_reset_per_registration(monkeypatch):
    # Validates: seen_names is rebuilt per register_all_skills call (tests re-register),
    # so a stale name from a previous registration cannot satisfy validate_policy
    register_all_skills(_FakeMCP())
    assert "apply_measure" in tool_registry.seen_names()
    tool_registry.reset_descriptors()
    assert tool_registry.seen_names() == set()


# ------------------------------------------------------------ CodeMode policy

def _tool_names(mcp) -> set[str]:
    return {t.name for t in asyncio.run(mcp.list_tools())}


def test_code_mode_synthetic_tools_follow_policy(monkeypatch):
    # Regression: CodeMode's search/get_schema/execute were added after the registration
    # filter, so OSMCP_TOOLS_DENY/ALLOW never applied to them
    from fastmcp import FastMCP

    monkeypatch.setenv("OSMCP_CODE_MODE", "1")
    monkeypatch.setenv("OSMCP_TOOLS_DENY", "search")
    mcp = FastMCP("t")

    @mcp.tool(name="noop")
    def noop() -> str:
        return "x"

    mcp.add_transform(tool_policy.code_mode_transform())
    assert _tool_names(mcp) == {"get_schema", "execute"}


def test_code_mode_refuses_hidden_execute(monkeypatch):
    # Validates: code mode without its execute tool is a contradictory config (every real
    # tool is reachable only through execute), so startup refuses it rather than serving
    # a server that can do nothing
    monkeypatch.setenv("OSMCP_CODE_MODE", "1")
    monkeypatch.setenv("OSMCP_TOOLS_ALLOW", "search,get_schema,apply_measure")
    with pytest.raises(RuntimeError, match="'execute'"):
        tool_policy.code_mode_transform()


# ------------------------------------------------------- enforce_http_sandbox

@pytest.mark.parametrize(("tier", "net", "override", "expect"), [
    ("clean-env", "deny", None, "full sandbox"),
    ("posix", "deny", None, "full sandbox"),
    ("off", "deny", None, "full sandbox"),
    ("landlock", "allow", None, "no network deny"),
    ("landlock", "deny", None, None),
    ("clean-env", "deny", "true", None),
    ("landlock", "allow", "true", None),
])
def test_http_gate(monkeypatch, tier, net, override, expect):
    # Validates: the HTTP server starts only on the landlock tier with network deny; any
    # weaker tier (or net allow) raises naming the tier, and OSMCP_ALLOW_UNSANDBOXED=true is
    # the only override
    import mcp_server.config as cfg

    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setattr(sandbox, "active_tier", lambda: tier)
    monkeypatch.setattr(cfg, "SANDBOX_NET", net)
    if override:
        monkeypatch.setenv("OSMCP_ALLOW_UNSANDBOXED", override)
    if expect is None:
        tool_policy.enforce_http_sandbox()
    else:
        with pytest.raises(RuntimeError, match=expect):
            tool_policy.enforce_http_sandbox()


def test_stdio_never_blocked(monkeypatch):
    # Validates: the gate is an HTTP (multi-tenant) control; a local stdio server with the
    # sandbox off still starts
    monkeypatch.setattr(sandbox, "active_tier", lambda: "off")
    tool_policy.enforce_http_sandbox()
