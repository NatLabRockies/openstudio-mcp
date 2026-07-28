"""validate_osw / run_osw honoring OSW file_paths (issue #99).

Unit tests drive validate_osw directly (no OpenStudio import needed);
integration tests prove run_osw stages file_paths-resolved seed/weather
into the run dir so the sandboxed CLI child can read them.
"""
import asyncio
import json
import shutil
import uuid
from pathlib import Path

import pytest
from conftest import (
    integration_enabled,
    poll_until_done,
    server_params,
    unwrap,
)
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_osw99") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# EPW with companion .stat + .ddy (same source as test_weather.py)
EPW_PATH = (
    "/opt/comstock-measures/ChangeBuildingLocation"
    "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
)
EPW_NAME = "USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"


# ---- Unit tests: validate_osw resolution semantics ----


@pytest.fixture
def allowed_root(tmp_path, monkeypatch):
    """Scope is_path_allowed's run root to a temp dir (unit-tier config mock)."""
    import mcp_server.config as config
    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setattr(config, "RUN_ROOT", root)
    return root


@pytest.mark.unit
def test_validate_osw_honors_absolute_file_paths(allowed_root):
    # Regression: issue #99 — validator resolved seed/weather only against the
    # OSW dir, rejecting workflows the CLI runs via file_paths search
    from mcp_server.skills.simulation.operations import validate_osw

    assets = allowed_root / "assets"
    assets.mkdir()
    (assets / "seed.osm").touch()
    (assets / "weather.epw").touch()
    wf_dir = allowed_root / "wf"
    wf_dir.mkdir()
    osw = wf_dir / "workflow.osw"
    osw.write_text(json.dumps({
        "seed_file": "seed.osm",
        "weather_file": "weather.epw",
        "file_paths": [str(assets)],
        "steps": [],
    }))
    result = validate_osw(str(osw))
    assert result["ok"] is True, f"CLI-runnable OSW rejected: {result['issues']}"
    assert result["issues"] == []


@pytest.mark.unit
def test_validate_osw_honors_relative_file_paths(allowed_root):
    # Regression: issue #99 — relative file_paths entries resolve against the
    # OSW dir (WorkflowJSON::findFile semantics), not the server cwd
    from mcp_server.skills.simulation.operations import validate_osw

    assets = allowed_root / "assets"
    assets.mkdir()
    (assets / "seed.osm").touch()
    (assets / "weather.epw").touch()
    wf_dir = allowed_root / "wf"
    wf_dir.mkdir()
    osw = wf_dir / "workflow.osw"
    osw.write_text(json.dumps({
        "seed_file": "seed.osm",
        "weather_file": "weather.epw",
        "file_paths": ["../assets"],
        "steps": [],
    }))
    result = validate_osw(str(osw))
    assert result["ok"] is True, f"relative file_paths entry ignored: {result['issues']}"


@pytest.mark.unit
def test_validate_osw_resolves_subdir_reference_via_file_paths(allowed_root):
    # Validates: findFile appends the WHOLE relative reference to each search
    # dir (models/seed.osm), not just the basename
    from mcp_server.skills.simulation.operations import validate_osw

    assets = allowed_root / "assets"
    (assets / "models").mkdir(parents=True)
    (assets / "models" / "seed.osm").touch()
    wf_dir = allowed_root / "wf"
    wf_dir.mkdir()
    osw = wf_dir / "workflow.osw"
    osw.write_text(json.dumps({
        "seed_file": "models/seed.osm",
        "file_paths": [str(assets)],
        "steps": [],
    }))
    result = validate_osw(str(osw))
    assert result["ok"] is True, f"subdir reference not searched via file_paths: {result['issues']}"


@pytest.mark.unit
def test_validate_osw_missing_file_reports_search_dirs(allowed_root):
    # Validates: a genuinely-missing seed still fails, and the message names the
    # file_paths search list instead of one misleading resolved path
    from mcp_server.skills.simulation.operations import validate_osw

    wf_dir = allowed_root / "wf"
    wf_dir.mkdir()
    osw = wf_dir / "workflow.osw"
    osw.write_text(json.dumps({
        "seed_file": "nope.osm",
        "file_paths": ["/does/not/exist"],
        "steps": [],
    }))
    result = validate_osw(str(osw))
    assert result["ok"] is False
    joined = " ".join(result["issues"])
    assert "nope.osm" in joined
    assert "/does/not/exist" in joined, \
        f"error should name the searched file_paths, got: {joined}"


@pytest.mark.unit
def test_validate_osw_denied_file_paths_hit_flagged(allowed_root, tmp_path):
    # Validates: a file_paths entry outside the caller's allowed roots is not
    # silently used — file_paths is caller-controlled OSW content and hits get
    # staged by the root server (same read-primitive class as issue #104)
    from mcp_server.skills.simulation.operations import validate_osw

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "seed.osm").touch()
    wf_dir = allowed_root / "wf"
    wf_dir.mkdir()
    osw = wf_dir / "workflow.osw"
    osw.write_text(json.dumps({
        "seed_file": "seed.osm",
        "file_paths": [str(outside)],
        "steps": [],
    }))
    result = validate_osw(str(osw))
    assert result["ok"] is False
    joined = " ".join(result["issues"])
    assert "outside" in joined and "allowed" in joined, \
        f"denied file_paths hit should be flagged explicitly, got: {joined}"


@pytest.mark.unit
def test_validate_osw_relative_escape_seed_denied(allowed_root, tmp_path):
    # Validates: a seed_file escaping the OSW dir via ../ to a path outside
    # allowed roots is rejected — previously it validated (exists-check only)
    # and run_osw staged it root-privileged into the caller-readable run dir
    from mcp_server.skills.simulation.operations import validate_osw

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.osm").touch()
    wf_dir = allowed_root / "wf"
    wf_dir.mkdir()
    osw = wf_dir / "workflow.osw"
    osw.write_text(json.dumps({
        "seed_file": "../../outside/secret.osm",
        "steps": [],
    }))
    result = validate_osw(str(osw))
    assert result["ok"] is False
    joined = " ".join(result["issues"])
    assert "allowed" in joined, \
        f"escaping seed_file should be denied, got: {joined}"


# ---- Integration tests: run_osw stages file_paths-resolved files ----


@pytest.mark.integration
def test_run_osw_stages_file_paths_seed_and_weather():
    """OSW with seed+EPW on an external file_paths dir runs to success."""
    # Regression: issue #99 — run_osw refused CLI-runnable OSWs; and even past
    # validation the sandboxed CLI child can't read external dirs, so the
    # resolved files must be staged into the run dir (issue #104 pattern)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # Assets dir under the caller's run root, separate from OSW dir
                assets = Path(f"/runs/{_unique('osw99_assets')}")
                assets.mkdir(parents=True)
                cr = unwrap(await s.call_tool("create_example_osm", {"name": _unique()}))
                assert cr["ok"] is True, cr
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
                assert lr["ok"] is True, lr
                wr = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW_PATH,
                }))
                assert wr["ok"] is True, f"change_building_location failed: {wr.get('error')}"
                rp = unwrap(await s.call_tool("set_run_period", {
                    "begin_month": 7, "begin_day": 20, "end_month": 7, "end_day": 22,
                }))
                assert rp["ok"] is True, rp
                sv = unwrap(await s.call_tool("save_osm_model", {
                    "osm_path": str(assets / "seed_model.osm"),
                }))
                assert sv["ok"] is True, sv
                shutil.copy2(EPW_PATH, str(assets / EPW_NAME))

                wf_dir = Path(f"/runs/{_unique('osw99_wf')}")
                wf_dir.mkdir(parents=True)
                osw_path = wf_dir / "workflow.osw"
                osw_path.write_text(json.dumps({
                    "seed_file": "seed_model.osm",
                    "weather_file": EPW_NAME,
                    "file_paths": [str(assets)],
                    "steps": [],
                }))

                res = unwrap(await s.call_tool("run_osw", {"osw_path": str(osw_path)}))
                assert res["ok"] is True, \
                    f"run_osw rejected CLI-runnable OSW: {res.get('error')} {res.get('issues')}"

                run_dir = Path(res["run_dir"])
                assert (run_dir / "seed_model.osm").is_file(), \
                    "file_paths-resolved seed not staged into run dir"
                assert (run_dir / "files" / EPW_NAME).is_file(), \
                    "file_paths-resolved weather not staged into run files/"

                status = await poll_until_done(s, res["run_id"])
                assert status["run"]["status"] == "success", \
                    f"staged file_paths workflow should simulate: {status}"
    asyncio.run(_run())


@pytest.mark.integration
def test_run_osw_denied_file_paths_clean_error():
    """file_paths pointing outside allowed roots fails with a clear message."""
    # Validates: caller-controlled file_paths can't make the root server stage
    # host files (/etc) into the caller-readable run dir; error names the issue
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                wf_dir = Path(f"/runs/{_unique('osw99_denied')}")
                wf_dir.mkdir(parents=True)
                osw_path = wf_dir / "workflow.osw"
                osw_path.write_text(json.dumps({
                    "seed_file": "passwd",
                    "file_paths": ["/etc"],
                    "steps": [],
                }))
                res = unwrap(await s.call_tool("run_osw", {"osw_path": str(osw_path)}))
                assert res["ok"] is False
                joined = " ".join(res.get("issues") or [])
                assert "allowed" in joined, \
                    f"denied file_paths hit should be flagged, got: {res}"
    asyncio.run(_run())
