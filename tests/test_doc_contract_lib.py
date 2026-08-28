"""Pure unit tests for the doc-contract validator and eval-parser machinery.

Synthetic sources/calls only — no OpenStudio, no MCP server, no LLM. These
prove the PR-1 validators can actually catch the finding classes (A1-A8, C5,
E3) before any content fix lands.
"""
from __future__ import annotations

import pytest
from doc_contract_lib import (
    DocCall,
    extract_calls,
    parse_tools_source,
    validate_doc_calls,
)
from llm.eval_parser import (
    CriticalParam,
    calls_from_code,
    check_critical_params,
    normalize_calls,
    parse_critical_params,
    parse_eval_files,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# AST registry extraction
# ---------------------------------------------------------------------------

SYNTH_TOOLS = '''
def register(mcp):
    @mcp.tool(name="alpha_tool", tags={"core"})
    def alpha(osm_path: str, epw_path: str | None = None):
        """doc"""
        return None

    @mcp.tool(tags={"hvac"}, name="beta_tool")
    def beta(loop_name: str, properties: str) -> str:
        return ""
'''


def test_parse_tools_source_extracts_names_params_required():
    # Validates: AST extraction captures MCP name, param order, and required set
    sigs = {s.name: s for s in parse_tools_source(SYNTH_TOOLS, "synth")}
    assert set(sigs) == {"alpha_tool", "beta_tool"}
    assert sigs["alpha_tool"].params == ("osm_path", "epw_path")
    assert sigs["alpha_tool"].required == frozenset({"osm_path"})
    assert sigs["alpha_tool"].tags == frozenset({"core"})
    assert sigs["beta_tool"].required == frozenset({"loop_name", "properties"})


def test_parse_tools_source_rejects_implicit_name():
    # Validates: @mcp.tool without literal name= fails loudly instead of
    # silently registering under the function name
    src = "def register(mcp):\n    @mcp.tool(tags={'x'})\n    def foo(a):\n        return a\n"
    with pytest.raises(ValueError, match=r"no\s+literal name="):
        parse_tools_source(src, "synth")


# ---------------------------------------------------------------------------
# Call extraction from markdown
# ---------------------------------------------------------------------------

def _registry():
    return {s.name: s for s in parse_tools_source(SYNTH_TOOLS, "synth")}


def test_extract_calls_finds_fenced_and_inline_calls():
    # Validates: calls inside fenced blocks (where ~90% of served examples
    # live) and inline backtick prose are both extracted (plan E1)
    md = (
        'Use `alpha_tool(osm_path="/runs/a.osm")` inline.\n'
        "```\nbeta_tool(loop_name=\"CHW\", properties='{\"a\": 1}')\n```\n"
    )
    calls = {c.name: c for c in extract_calls(md, "t")}
    assert set(calls) == {"alpha_tool", "beta_tool"}
    assert calls["alpha_tool"].kwargs == {"osm_path": '"/runs/a.osm"'}
    assert calls["beta_tool"].kwargs["loop_name"] == '"CHW"'


def test_extract_calls_skips_measure_body_fences_and_strings():
    # Validates: ruby/python fences and quoted run_body strings never
    # fabricate tool calls or kwargs (SQL/Ruby text is opaque)
    md = (
        "```ruby\nfake_tool_call(bogus_kwarg=1)\n```\n"
        "```python\nother_fake_call(x=2)\n```\n"
        '```\ncreate_thing(run_body="inner_fake(a=1, b=2)")\n```\n'
    )
    calls = extract_calls(md, "t")
    assert [c.name for c in calls] == ["create_thing"]
    assert calls[0].kwargs == {"run_body": '"inner_fake(a=1, b=2)"'}


def test_extract_calls_multiline_with_comment_and_elision():
    # Validates: multi-line calls parse across lines; unquoted # comments do
    # not corrupt args; bare ... marks the call as elided
    md = (
        "```\nalpha_tool(\n"
        '    osm_path="/runs/x.osm",  # explains the path\n'
        "    ...)\n```\n"
    )
    calls = extract_calls(md, "t")
    assert len(calls) == 1
    assert calls[0].elided is True
    assert calls[0].kwargs == {"osm_path": '"/runs/x.osm"'}


def test_extract_calls_ignores_dotted_method_calls():
    # Validates: obj.some_method(x) is never mistaken for an MCP tool call
    md = "```\nmodel.get_thing(a=1)\nsql.exec_and_return(b=2)\n```\n"
    assert extract_calls(md, "t") == []


# ---------------------------------------------------------------------------
# Call validation
# ---------------------------------------------------------------------------

def test_validate_flags_unknown_tool():
    # Regression: ghost tool names (E3's list_infiltration) escaped the old
    # backtick-only validator
    calls = [DocCall("ghost_tool", {}, [], False, 1, "doc")]
    errors = validate_doc_calls(calls, _registry())
    assert len(errors) == 1 and "unknown tool 'ghost_tool" in errors[0]


def test_validate_flags_unknown_kwarg():
    # Regression: save_osm_model(save_path=...) shipped in 8 served examples
    # (A1) — kwargs must exist on the real signature
    calls = [DocCall(
        "alpha_tool",
        {"save_path": '"/x.osm"', "osm_path": '"/x.osm"'}, [], False, 3, "doc",
    )]
    errors = validate_doc_calls(calls, _registry())
    assert len(errors) == 1
    assert "no parameter 'save_path'" in errors[0] and "doc:3" in errors[0]


def test_validate_flags_bare_identifier_positional():
    # Regression: compare_runs(run_id_a, run_id_b) taught fake kwarg names
    # positionally (A3) — doc examples must name real parameters
    calls = [DocCall("beta_tool", {}, ["run_id_a", "run_id_b"], False, 9, "doc")]
    errors = validate_doc_calls(calls, _registry())
    assert any("bare identifier" in e for e in errors)


def test_validate_flags_missing_required_args():
    # Regression: MCP prompts emitted run_simulation() / get_run_status()
    # with no required args (C5)
    calls = [DocCall("alpha_tool", {}, [], False, 2, "prompt:x")]
    errors = validate_doc_calls(calls, _registry())
    assert len(errors) == 1 and "missing required argument(s) ['osm_path']" in errors[0]


def test_validate_elided_call_skips_required_check():
    # Validates: an explicitly elided example — alpha_tool(...) — is not a
    # contract violation, but its named kwargs are still checked
    ok = [DocCall("alpha_tool", {}, [], True, 1, "doc")]
    assert validate_doc_calls(ok, _registry()) == []
    bad = [DocCall("alpha_tool", {"bogus": "1"}, [], True, 1, "doc")]
    assert len(validate_doc_calls(bad, _registry())) == 1


def test_validate_known_exception_is_tolerated():
    # Validates: the B1 bridge — (context, tool, kwarg) triples are tolerated
    # until the PR that exposes the kwarg removes them
    calls = [DocCall("alpha_tool", {"run_id": '"r"', "osm_path": '"m"'}, [], False, 1, "x/SKILL.md")]
    errors = validate_doc_calls(
        calls, _registry(),
        known_exceptions=frozenset({("x/SKILL.md", "alpha_tool", "run_id")}),
    )
    assert errors == []


def test_validate_literal_positionals_satisfy_required_in_order():
    # Validates: quoted-literal positionals ("name") count toward required
    # params in order — search_api("X") style examples stay legal
    calls = [DocCall("alpha_tool", {}, ['"/runs/m.osm"'], False, 1, "doc")]
    assert validate_doc_calls(calls, _registry()) == []


# ---------------------------------------------------------------------------
# Critical-params grammar
# ---------------------------------------------------------------------------

def test_parse_critical_params_grammar():
    # Validates: documented grammar — bare name / 'name present' / name=value;
    # em dash means no assertions
    assert parse_critical_params("—") == []
    assert parse_critical_params("run_id") == [CriticalParam("run_id", "present", None)]
    assert parse_critical_params("epw_path present") == [
        CriticalParam("epw_path", "present", None)]
    assert parse_critical_params('system_type=7, stream="energyplus"') == [
        CriticalParam("system_type", "equals", "7"),
        CriticalParam("stream", "equals", "energyplus"),
    ]


def test_parse_critical_params_reports_prose():
    # Regression: the critical-params column was parsed-then-ignored (E3);
    # prose cells must surface as format errors, not silent drops
    errors: list[str] = []
    parse_critical_params("the run id from step 2", "here", errors)
    assert len(errors) == 1 and "unparseable critical param" in errors[0]


# ---------------------------------------------------------------------------
# Negative-table parsing (synthetic eval.md trees)
# ---------------------------------------------------------------------------

def _write_eval(tmp_path, body: str):
    d = tmp_path / "some-skill"
    d.mkdir()
    (d / "eval.md").write_text(body, encoding="utf-8")
    return tmp_path


def test_parse_eval_files_new_negative_format(tmp_path):
    # Validates: | Query | Forbidden tools | Expected alternatives | rows
    # become assertable negative cases
    root = _write_eval(tmp_path, (
        "## Should trigger\n"
        "| Query | Expected tools | Critical params |\n|---|---|---|\n"
        '| "Do it" | alpha_tool | osm_path |\n\n'
        "## Should NOT trigger\n"
        "| Query | Forbidden tools | Expected alternatives |\n|---|---|---|\n"
        '| "Other thing" | alpha_tool | beta_tool |\n'
    ))
    parsed = parse_eval_files(root)
    assert parsed["errors"] == []
    assert parsed["negative_cases"] == [{
        "prompt": "Other thing",
        "forbidden_tools": ["alpha_tool"],
        "alternatives": ["beta_tool"],
        "skill": "some-skill",
    }]


def test_parse_eval_files_rejects_prose_negative_table(tmp_path):
    # Regression: old | Query | Why | tables were parsed but unassertable —
    # they must be reported as format errors (E3)
    root = _write_eval(tmp_path, (
        "## Should NOT trigger\n"
        "| Query | Why |\n|---|---|\n"
        '| "Other thing" | use beta skill |\n'
    ))
    parsed = parse_eval_files(root)
    assert parsed["negative_cases"] == []
    assert any("unassertable" in e for e in parsed["errors"])


def test_parse_eval_files_rejects_wildcard_expected_tools(tmp_path):
    # Regression: 'extract_* tools' rows were silently filtered by the old
    # parser (E3) — wildcards must be format errors
    root = _write_eval(tmp_path, (
        "## Should trigger\n"
        "| Query | Expected tools | Critical params |\n|---|---|---|\n"
        '| "Report" | extract_* tools | — |\n'
    ))
    parsed = parse_eval_files(root)
    assert parsed["cases"] == []
    assert any("extract_*" in e for e in parsed["errors"])


# ---------------------------------------------------------------------------
# Normalized calls (direct + CodeMode) and the critical matcher
# ---------------------------------------------------------------------------

def test_normalize_calls_direct_and_code_mode():
    # Validates: direct MCP calls keep inputs; CodeMode execute blocks expand
    # into the tools they invoke with best-effort parsed inputs
    raw = [
        {"tool": "mcp__openstudio__alpha_tool", "input": {"osm_path": "/x"}},
        {"tool": "mcp__openstudio__execute",
         "input": {"code": 'call_tool("beta_tool", {loop_name: "CHW"})'}},
    ]
    calls = normalize_calls(raw)
    assert calls == [
        {"tool": "alpha_tool", "input": {"osm_path": "/x"}},
        {"tool": "beta_tool", "input": {"loop_name": "CHW"}},
    ]


def test_calls_from_code_json_and_python_args():
    # Validates: JSON and Python-literal arg objects both parse; unparseable
    # objects degrade to {} instead of crashing the matcher
    code = (
        'call_tool("a_b", {"x": 1})\n'
        "call_tool('c_d', {'y': 2})\n"
        'call_tool("e_f", make_args())\n'
    )
    assert calls_from_code(code) == [
        {"tool": "a_b", "input": {"x": 1}},
        {"tool": "c_d", "input": {"y": 2}},
        {"tool": "e_f", "input": {}},
    ]


_MATCH_REGISTRY = {"alpha_tool": {"osm_path", "system_type"}, "beta_tool": {"loop_name"}}


def test_check_critical_params_presence_and_equality():
    # Validates: presence + equality assertions match against calls to
    # expected tools whose schema carries the param (numeric-normalized)
    calls = [{"tool": "alpha_tool", "input": {"system_type": 7}}]
    crits = [CriticalParam("system_type", "equals", "7")]
    assert check_critical_params(crits, ["alpha_tool"], calls, _MATCH_REGISTRY) == []
    crits = [CriticalParam("system_type", "equals", "5")]
    failures = check_critical_params(crits, ["alpha_tool"], calls, _MATCH_REGISTRY)
    assert len(failures) == 1 and "system_type" in failures[0]


def test_check_critical_params_requires_a_carrying_call():
    # Regression: the old harness ignored criticals entirely — an agent that
    # never called the tool carrying the param must FAIL the assertion
    calls = [{"tool": "beta_tool", "input": {"loop_name": "CHW"}}]
    crits = [CriticalParam("osm_path", "present", None)]
    failures = check_critical_params(crits, ["alpha_tool", "beta_tool"], calls,
                                     _MATCH_REGISTRY)
    assert len(failures) == 1 and "no call to an expected tool" in failures[0]
