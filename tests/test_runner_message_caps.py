"""Unit tests for runner-message parsing and size caps (issue #98).

Fixture: tests/assets/bson-repro/out.osw.gz — real generic_qaqc out.osw from a
27-zone medium-office run: 74 step_warnings totalling 18.9MB (largest single
message 9.45MB). Uncapped, this payload flowed into the run_qaqc_checks MCP
response and killed the stdio JSON-RPC session (server exit 0 mid-call).
Regenerate with tests/assets/bson-repro/workflow.osw (cycle-1 benchmark seed +
Boston EPW + generic_qaqc with all 10 check_* true).
"""
import gzip
import json
import os
from pathlib import Path

import pytest

from mcp_server.skills.measures.runner_messages import (
    MAX_MESSAGE_CHARS,
    MESSAGE_LIMITS,
    parse_all_step_messages,
    parse_runner_messages,
)

ASSET = Path(__file__).parent / "assets" / "bson-repro" / "out.osw.gz"


@pytest.fixture
def giant_out_osw(tmp_path):
    out = tmp_path / "out.osw"
    out.write_bytes(gzip.decompress(ASSET.read_bytes()))
    return out


@pytest.mark.unit
def test_giant_qaqc_out_osw_is_capped(giant_out_osw):
    # Regression: #98 — generic_qaqc emitted 18.9MB of step_warnings into
    # runner_messages; the ~19MB tool response killed the stdio MCP session
    msgs = parse_runner_messages(giant_out_osw)
    assert msgs["result"] == "Success"
    assert msgs["warning_count"] == 74, "fixture out.osw has 74 step_warnings"
    assert len(msgs["warnings"]) == MESSAGE_LIMITS["warnings"]
    for w in msgs["warnings"]:
        assert len(w) <= MAX_MESSAGE_CHARS + 40, f"warning not clipped: {len(w)} chars"
    assert msgs["truncated"] is True
    serialized = json.dumps(msgs)
    assert len(serialized) < 20_000, (
        f"runner_messages must stay far below JSON-RPC framing limits, "
        f"got {len(serialized)} chars"
    )


@pytest.mark.unit
def test_small_messages_pass_through_unclipped(tmp_path):
    # Validates: caps only engage on oversized payloads — normal measure output
    # (short info/warnings) is returned verbatim with accurate counts
    out = tmp_path / "out.osw"
    out.write_text(json.dumps({
        "steps": [{"result": {
            "step_result": "Success",
            "step_initial_condition": "Starting",
            "step_final_condition": "Done",
            "step_info": ["applied name change"],
            "step_warnings": ["minor warning"],
            "step_errors": [],
        }}],
    }), encoding="utf-8")
    msgs = parse_runner_messages(out)
    assert msgs == {
        "result": "Success",
        "initial_condition": "Starting",
        "final_condition": "Done",
        "info": ["applied name change"],
        "info_count": 1,
        "warnings": ["minor warning"],
        "warning_count": 1,
    }


@pytest.mark.unit
def test_single_oversized_message_is_clipped(tmp_path):
    # Regression: #98 — the fixture's worst warning is a single 9.45MB string;
    # count limits alone don't help, each message must be clipped individually
    out = tmp_path / "out.osw"
    big = "x" * 1_000_000
    out.write_text(json.dumps({
        "steps": [{"result": {"step_result": "Success", "step_errors": [big]}}],
    }), encoding="utf-8")
    msgs = parse_runner_messages(out)
    assert msgs["error_count"] == 1
    assert len(msgs["errors"][0]) <= MAX_MESSAGE_CHARS + 40
    assert "1000000 chars" in msgs["errors"][0], "clip suffix should state original size"
    assert msgs["truncated"] is True


@pytest.mark.unit
@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW is POSIX-only")
def test_symlinked_out_osw_refused(tmp_path):
    # Regression: PR #105 Copilot — a confined measure can swap out.osw for a
    # symlink (e.g. to another tenant's out.osw, which IS valid JSON with steps);
    # the unconfined server must refuse the link and return None, not parse the
    # target and leak its runner messages into this tenant's response.
    target = tmp_path / "other_tenant_out.osw"
    target.write_text(json.dumps({
        "steps": [{"result": {"step_result": "Success", "step_errors": ["SECRET"]}}],
    }), encoding="utf-8")
    link = tmp_path / "out.osw"
    link.symlink_to(target)
    assert parse_runner_messages(link) is None
    assert parse_all_step_messages(link) is None


@pytest.mark.unit
def test_missing_and_invalid_out_osw(tmp_path):
    # Validates: absent or corrupt out.osw yields None, not an exception
    assert parse_runner_messages(tmp_path / "nope.osw") is None
    bad = tmp_path / "bad.osw"
    bad.write_text("{not json", encoding="utf-8")
    assert parse_runner_messages(bad) is None
