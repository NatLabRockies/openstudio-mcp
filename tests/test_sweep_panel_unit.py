"""Unit tests for the sweep panel: measure limits, server-side validation, the OSA bounds
check, the ui:// resource, and the signed single-submit browser link (HTTP only)."""
import asyncio
import json
import logging

import pytest
from starlette.requests import Request

from mcp_server.access_log import RedactSignedUrlFilter
from mcp_server.skills.analysis import operations as analysis
from mcp_server.skills.analysis.measure_bounds import argument_limits
from mcp_server.skills.file_transfer import signing
from mcp_server.skills.sweep_panel import operations, routes

pytestmark = pytest.mark.unit

SETCOP = "set_co_pfor_single_speed_dx_cooling_units"  # has a bundled bounds file: cop 2-7 W/W


def _measure(tmp_path, name=SETCOP, extra_xml=""):
    """A measure.xml shaped like SetCOPforSingleSpeedDXCoolingUnits (no limits of its own)."""
    d = tmp_path / name
    d.mkdir()
    (d / "measure.rb").write_text("class M; end")
    (d / "measure.xml").write_text(f"""<?xml version="1.0"?>
<measure><schema_version>3.1</schema_version><name>{name}</name><uid>u</uid><version_id>v</version_id>
<class_name>M</class_name><display_name>Set COP</display_name><description>d</description>
<arguments>
<argument><name>cop</name><display_name>Rated COP</display_name><type>Double</type>
<required>true</required><default_value>4</default_value></argument>
<argument><name>material_cost</name><display_name>Cost</display_name><type>Double</type>
<required>true</required><default_value>0</default_value></argument>
<argument><name>remove_costs</name><display_name>Remove</display_name><type>Boolean</type>
<required>true</required><default_value>true</default_value></argument>{extra_xml}
</arguments>
<attributes><attribute><name>Measure Type</name><value>ModelMeasure</value>
<datatype>string</datatype></attribute></attributes>
</measure>""")
    return str(d)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr("mcp_server.config.is_path_allowed", lambda _path, write=False: True)  # noqa: ARG005
    monkeypatch.setattr(operations, "run_root_for", lambda key: tmp_path / "runs" / key)
    monkeypatch.setattr("mcp_server.skills.file_transfer.operations._public_url", lambda p: "http://test" + p)
    monkeypatch.setattr("mcp_server.identity.user_key", lambda: "alice")
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)


def test_measure_xml_limits_win_over_bundled_file():
    # Validates: a range declared in measure.xml overrides the bundled bounds file; units/label fill gaps
    limits = argument_limits(SETCOP, {"cop": {"units": None, "min": "2.5", "max": None}})
    assert limits == {"cop": {"units": "W/W", "min": 2.5, "max": 7.0, "label": "Rated COP"}}
    assert argument_limits("unknown_measure", {"x": {"units": "m", "min": "1", "max": None}}) == {}


def test_panel_schema_lists_only_numeric_arguments_with_a_range(tmp_path):
    # Validates: only cop is sweepable (material_cost has no range, remove_costs isn't numeric)
    info = operations.panel_schema(_measure(tmp_path))
    assert info["measure_name"] == SETCOP
    assert info["schema"] == {"cop": {"type": "number", "units": "W/W", "min": 2.0, "max": 7.0,
                                      "default": 4.0, "label": "Rated COP"}}


def test_open_panel_on_stdio_has_no_link_and_names_its_submit_tool(tmp_path):
    # Validates: stdio gets the inline panel only; the panel knows which tool and measure_dir to submit with
    out = operations.open_measure_panel_op(_measure(tmp_path))
    assert out["ok"] is True
    assert out["submit_tool"] == "submit_measure_sweep"
    assert out["submit_args"] == {"measure_dir": str(tmp_path / SETCOP)}
    assert "fallback" not in out


def test_open_panel_refuses_a_measure_with_nothing_to_sweep(tmp_path):
    # Validates: a measure with no known ranges gives a clear error instead of an empty panel
    out = operations.open_measure_panel_op(_measure(tmp_path, name="no_bounds_measure"))
    assert out["ok"] is False
    assert "no sweepable arguments" in out["error"]


@pytest.mark.parametrize(("values", "error"), [
    ({"cop": 9.0}, "cop: 9.0 W/W outside [2.0, 7.0]"),
    ({"cop": [1.0, 5.0, 3]}, "cop: 1.0 W/W outside [2.0, 7.0]"),
    ({"cop": "4"}, "cop: '4' is not a number"),
    ({"cop": [3.0, 5.0, 0]}, "cop: steps 0 must be a whole number from 1 to 20"),
    ({"cop": [5.0, 3.0, 3]}, "cop: low 5.0 is above high 3.0"),
    ({"material_cost": 1.0}, "material_cost: not a sweepable argument (choose from ['cop'])"),
    ({}, "values must be a non-empty object"),
])
def test_submit_rejects_bad_values_with_the_reason(tmp_path, values, error):
    # Validates: the server, not the panel, is the gate; each bad value is refused with its reason
    out = operations.submit_measure_sweep_op(_measure(tmp_path), values)
    assert out["ok"] is False
    assert out["errors"] == [error]
    assert out["values"] == values  # the model is told what was tried


def test_valid_submit_echoes_values_and_returns_the_osa_call(tmp_path):
    # Regression: Claude Desktop's model couldn't name the submitted values because only ok/n_points came back
    out = operations.submit_measure_sweep_op(_measure(tmp_path), {"cop": [3.0, 5.0, 5]})
    assert out["ok"] is True
    assert out["values"] == {"cop": [3.0, 5.0, 5]}
    assert out["n_points"] == 5
    assert out["next"] == {
        "tool": "openstudio_analysis_add_measure_to_osa_json", "measure_dir": str(tmp_path / SETCOP),
        "variables": [{"argument_name": "cop",
                       "distribution": {"type": "uniform", "minimum": 3.0, "maximum": 5.0, "mode": 4.0}}],
    }


def test_add_measure_to_osa_json_refuses_out_of_range_variables_and_arguments(tmp_path):
    # Regression: COP -5 to 50 was added and validated ok; the OSA layer accepted any range
    osa = tmp_path / "osa.json"
    osa.write_text(json.dumps({"analysis": {"name": "COP sweep", "problem": {"workflow": []}}}))
    measure_dir = _measure(tmp_path)
    bad = analysis.add_measure_to_osa_json(str(osa), measure_dir, variables=[{
        "argument_name": "cop", "distribution": {"type": "uniform", "minimum": -5, "maximum": 50, "mode": 4}}])
    assert bad["ok"] is False
    assert bad["error"].startswith("cop: -5 W/W outside [2.0, 7.0]")
    fixed = analysis.add_measure_to_osa_json(str(osa), measure_dir, arguments={"cop": 9})
    assert fixed["ok"] is False
    assert fixed["error"].startswith("cop: 9.0 W/W outside [2.0, 7.0]")
    nxt = operations.submit_measure_sweep_op(measure_dir, {"cop": [3.0, 5.0, 3]})["next"]
    good = analysis.add_measure_to_osa_json(str(osa), nxt["measure_dir"], variables=nxt["variables"])
    assert good["ok"] is True, good
    assert good["measure_step"]["variables"][0]["minimum"] == pytest.approx(3.0)


def test_measure_xml_range_is_enforced_without_a_bounds_file(tmp_path):
    # Validates: a measure that declares <min_value>/<max_value> is checked even with no bundled file
    xml = ("<argument><name>wwr</name><display_name>WWR</display_name><type>Double</type><units>fraction</units>"
           "<required>true</required><default_value>0.4</default_value><min_value>0</min_value>"
           "<max_value>0.9</max_value></argument>")
    measure_dir = _measure(tmp_path, name="set_wwr_test", extra_xml=xml)
    assert operations.panel_schema(measure_dir)["schema"]["wwr"]["max"] == pytest.approx(0.9)
    assert operations.submit_measure_sweep_op(measure_dir, {"wwr": 0.95})["errors"] == [
        "wwr: 0.95 fraction outside [0.0, 0.9]"]


def test_panel_resource_is_the_mcp_apps_bundle():
    # Validates: the ui:// resource ships the built panel with the ext-apps client and the submit_args hook
    html = operations.PANEL_HTML.read_text()
    assert html.startswith("<!doctype html>")
    assert "callServerTool({name:" in html
    assert "submit_args" in html
    assert "/panel/submit" in html


# --- signed browser link (HTTP only) -------------------------------------------------------

def _req(method, token, body=b""):
    msgs = iter([{"type": "http.request", "body": body, "more_body": False}])

    async def receive():
        return next(msgs)

    scope = {"type": "http", "method": method, "scheme": "http", "http_version": "1.1",
             "server": ("test", 80), "client": ("127.0.0.1", 1), "root_path": "", "path": "/panel",
             "raw_path": b"/panel", "query_string": f"t={token}".encode(), "headers": [], "path_params": {}}
    return Request(scope, receive)


def _open_http(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    out = operations.open_measure_panel_op(_measure(tmp_path))
    return out["fallback"], out["fallback"]["panel_url"].split("t=", 1)[1]


def _submit(token, values):
    r = asyncio.run(routes.submit_route(_req("POST", token, json.dumps({"values": values}).encode())))
    return r.status_code, json.loads(r.body)


def test_link_round_trip_is_single_submit_and_per_user(monkeypatch, tmp_path):
    # Validates: a bad submit can be retried, the first valid one closes the link, and only its owner reads it
    link, tok = _open_http(monkeypatch, tmp_path)
    assert link["panel_url"].startswith("http://test/panel?t=")
    assert asyncio.run(routes.page_route(_req("GET", tok))).status_code == 200
    schema = json.loads(asyncio.run(routes.schema_route(_req("GET", tok))).body)["schema"]
    assert list(schema) == ["cop"]
    assert _submit(tok, {"cop": 9.0})[0] == 422
    status, body = _submit(tok, {"cop": [3.0, 5.0, 3]})
    assert (status, body["ok"]) == (200, True)
    reused = (409, {"ok": False, "errors": ["this link was already used; ask for a new panel"]})
    assert _submit(tok, {"cop": 4.0}) == reused
    result = operations.get_panel_result_op(link["link_id"])
    assert [r["ok"] for r in result["results"]] == [False, True]
    monkeypatch.setattr("mcp_server.identity.user_key", lambda: "bob")
    assert operations.get_panel_result_op(link["link_id"]) == {"ok": False, "error": "unknown link"}


def test_link_token_cannot_be_forged_expired_or_reused_for_another_op(monkeypatch, tmp_path):
    # Validates: the HMAC token is the only authority on the unauthenticated browser routes
    link, tok = _open_http(monkeypatch, tmp_path)
    _, sig = tok.split(".")
    forged = signing._b64u(json.dumps({"u": "bob", "f": link["link_id"], "op": "p", "exp": 9999999999}).encode())
    for bad in (f"{forged}.{sig}", tok[:-2] + "AA", "",
                signing.make_token("alice", link["link_id"], "p", -1),
                signing.make_token("alice", link["link_id"], "d", 60),
                signing.make_token("alice", "../../etc", "p", 60)):
        assert asyncio.run(routes.page_route(_req("GET", bad))).status_code == 403
        assert asyncio.run(routes.schema_route(_req("GET", bad))).status_code == 403
        assert _submit(bad, {"cop": 4.0})[0] == 403


def test_panel_link_token_is_redacted_from_access_log():
    # Regression: signed ?t= tokens in uvicorn's access line could be replayed by a log reader (#170)
    args = ("c", "GET", "/panel?t=abc.def")
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s"', args, None)
    RedactSignedUrlFilter().filter(rec)
    assert rec.args == ("c", "GET", "/panel?[redacted]")
