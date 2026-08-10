"""Arm C — codegen baseline: no MCP server, agent scripts the SDK itself.

Answers reviewer R1 ("is MCP even needed vs letting the agent write
openstudio Python?"). The agent gets ONLY shell/file tools plus a long-lived
container with the same image (OpenStudio SDK + CLI + EnergyPlus) and must
script everything. Grading is outcome-only (D6 spirit): files produced,
values written, sims parsed with the same non-LLM extraction code the
verifier uses — never tool identity.

Opt-in: runs only with LLM_TESTS_ARM=codegen (excluded from the default
suite and from the full/noskills arms).

  LLM_TESTS_ENABLED=1 LLM_TESTS_ARM=codegen pytest tests/llm/test_11_codegen_arm.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from .conftest import _RUNS_DIR, fail_with_mode
from .runner import run_agent

pytestmark = [pytest.mark.llm, pytest.mark.tier2]

# Same extraction code the D6 verifier's server tools use — pure sqlite3 /
# string parsing, no openstudio import (verified 2026-08-05)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mcp_server.skills.results.err_parser import parse_err_file  # noqa: E402
from mcp_server.skills.results.sql_extract import extract_eui  # noqa: E402

ASSETS = Path(__file__).resolve().parents[1] / "assets"
IMAGE = os.environ.get("LLM_TESTS_IMAGE", "openstudio-mcp:dev")

CODEGEN_SYSTEM_PROMPT = (
    "You are a building energy modeling expert with shell access. "
    "A Docker container named {name} is running with OpenStudio 3.11.0 "
    "(python bindings importable as `import openstudio`), the OpenStudio CLI "
    "(`openstudio`), and EnergyPlus. Do ALL modeling work inside it via "
    '`docker exec {name} python -c "..."` or `docker exec {name} bash -lc '
    '"..."`. Reference models are under /inputs (read-only); write every '
    "output under /runs. Complete all steps before stopping."
)


def _codegen_arm_enabled() -> bool:
    return os.environ.get("LLM_TESTS_ARM") == "codegen"


@pytest.fixture(scope="module")
def sdk_container():
    """Long-lived container the agent drives via docker exec."""
    if not _codegen_arm_enabled():
        pytest.skip("Set LLM_TESTS_ARM=codegen to run the codegen baseline arm")
    name = f"llm-codegen-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name,
         "-v", f"{_RUNS_DIR}:/runs",
         "-v", f"{ASSETS}:/inputs:ro",
         "--entrypoint", "sleep", IMAGE, "infinity"],
        check=True, capture_output=True, text=True,
    )
    try:
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name],
                       check=False, capture_output=True)


def _run_task(container: str, prompt: str, timeout: int = 300):
    return run_agent(
        prompt,
        timeout=timeout,
        allowed_tools="Bash,Read,Write,Edit,Glob,Grep",
        system_prompt=CODEGEN_SYSTEM_PROMPT.format(name=container),
        use_mcp=False,
        max_turns=30,
    )


def _out(rel: str) -> Path:
    """Host path of a container /runs output."""
    return _RUNS_DIR / rel


def _answer(rel: str) -> str:
    p = _out(rel)
    assert p.exists(), f"expected answer file missing: {p}"
    return p.read_text(encoding="utf-8", errors="replace").strip()


# (id, prompt-under-/runs/codegen/<id>/, grader) — graders assert outcomes only
def test_codegen_create_model(sdk_container, request):
    # Validates: Arm C agent can create + save a multi-zone OSM via raw SDK
    result = _run_task(
        sdk_container,
        "Create a 2-story office building model with at least 4 thermal "
        "zones and save it to /runs/codegen/create/model.osm",
    )
    osm = _out("codegen/create/model.osm")
    if not osm.exists():
        fail_with_mode(request, "outcome_mismatch",
                       f"model.osm not produced. Text: {result.final_text[:300]}")
    text = osm.read_text(encoding="utf-8", errors="replace")
    assert text.count("OS:ThermalZone,") >= 4, (
        f"expected >=4 thermal zones, found {text.count('OS:ThermalZone,')}"
    )


def test_codegen_inspect_zones(sdk_container, request):
    # Validates: Arm C agent can load a real model and count zones (44)
    _run_task(
        sdk_container,
        "How many thermal zones does /inputs/SystemD_baseline.osm contain? "
        "Write ONLY the number to /runs/codegen/zones/answer.txt",
    )
    try:
        answer = _answer("codegen/zones/answer.txt")
    except AssertionError as e:
        fail_with_mode(request, "outcome_mismatch", str(e))
    assert answer == "44", f"SystemD_baseline has 44 zones, agent wrote {answer!r}"


def test_codegen_modify_model(sdk_container, request):
    # Validates: Arm C agent can load-modify-save (building rename survives)
    _run_task(
        sdk_container,
        "Copy /inputs/SystemD_baseline.osm, set its Building name to "
        "'CodegenTest', and save the result to /runs/codegen/rename/model.osm",
    )
    osm = _out("codegen/rename/model.osm")
    if not osm.exists():
        fail_with_mode(request, "outcome_mismatch", "renamed model.osm not produced")
    assert "CodegenTest" in osm.read_text(encoding="utf-8", errors="replace"), (
        "Building name 'CodegenTest' not found in saved OSM"
    )


def test_codegen_parse_err(sdk_container, request):
    # Validates: Arm C agent can parse an E+ err file (261 warnings)
    _run_task(
        sdk_container,
        "How many Warning entries does /inputs/eplusout.err contain? "
        "Count '** Warning **' entries (continuation '**   ~~~   **' lines "
        "are not new warnings). Write ONLY the number to "
        "/runs/codegen/err/answer.txt",
    )
    try:
        answer = _answer("codegen/err/answer.txt")
    except AssertionError as e:
        fail_with_mode(request, "outcome_mismatch", str(e))
    assert answer == "261", f"asset has 261 warnings, agent wrote {answer!r}"


def test_codegen_run_simulation(sdk_container, request):
    # Validates: Arm C flagship — agent runs an annual sim via CLI; graded by
    # the same non-LLM extraction as D6 (clean err + EUI vs 28.21 pin)
    _run_task(
        sdk_container,
        "Run an annual EnergyPlus simulation of /inputs/SystemD_baseline.osm "
        "with the weather file /inputs/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw "
        "using the OpenStudio CLI. Put all outputs under /runs/codegen/sim/. "
        "When it finishes, write the site EUI in kBtu/ft2 to "
        "/runs/codegen/sim/eui.txt",
        timeout=900,
    )
    sim_dir = _out("codegen/sim")
    sqls = list(sim_dir.rglob("eplusout.sql")) if sim_dir.exists() else []
    if not sqls:
        fail_with_mode(request, "outcome_mismatch",
                       f"no eplusout.sql under {sim_dir} — simulation not run")

    errs = list(sim_dir.rglob("eplusout.err"))
    assert errs, "eplusout.err missing despite sql present"
    parsed = parse_err_file(errs[0].read_text(errors="replace"))
    assert len(parsed["fatal"]) == 0, f"fatal errors: {parsed['fatal'][:2]}"
    assert len(parsed["severe"]) == 0, f"severe errors: {parsed['severe'][:2]}"

    eui = extract_eui(sqls[0])
    got = eui.get("eui_kBtu_ft2") if isinstance(eui, dict) else None
    assert got == pytest.approx(28.21, rel=0.05), (
        f"SystemD+Boston EUI pinned 28.21 kBtu/ft2, sim produced {got}"
    )

    reported = _answer("codegen/sim/eui.txt")
    # The prompt itself names the unit, so "28.21 kBtu/ft2" is a valid answer —
    # grade the leading number, not the formatting
    assert float(reported.split()[0]) == pytest.approx(28.21, rel=0.05), (
        f"agent reported EUI {reported!r} outside 5% of pinned 28.21"
    )


def test_codegen_convert_idf(sdk_container, request):
    # Validates: Arm C agent can forward-translate OSM -> IDF
    _run_task(
        sdk_container,
        "Convert /inputs/SystemD_baseline.osm to an EnergyPlus IDF at "
        "/runs/codegen/idf/model.idf",
    )
    idf = _out("codegen/idf/model.idf")
    if not idf.exists():
        fail_with_mode(request, "outcome_mismatch", "model.idf not produced")
    head = idf.read_text(encoding="utf-8", errors="replace")[:20000]
    assert "Building," in head or "Version," in head, (
        "file at model.idf does not look like an IDF"
    )
