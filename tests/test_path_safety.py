"""Unit tests for security fixes — path traversal, OSError, SQL injection, input guards.

No Docker/OpenStudio needed — these test pure Python logic.
"""
from __future__ import annotations

import json
import os
import subprocess as _subprocess

import pytest

from mcp_server.util import read_file_bounded

pytestmark = pytest.mark.unit


class TestReadFileBounded:
    """read_file_bounded — bounded, symlink-refusing copy-back read used after
    confined `openstudio measure -u` regenerates measure.xml/README.md."""

    def test_reads_within_bound(self, tmp_path):
        # Validates: a normal generated file is returned verbatim.
        f = tmp_path / "measure.xml"
        f.write_bytes(b"<measure/>" * 5)
        assert read_file_bounded(f, 1000) == b"<measure/>" * 5

    def test_rejects_oversize(self, tmp_path):
        # Regression: untrusted measure -u could write a giant measure.xml; the
        # read is bounded (max_bytes+1) so it can't be slurped wholesale into
        # the unconfined server's memory (Copilot C1).
        f = tmp_path / "big.xml"
        f.write_bytes(b"A" * 200)
        with pytest.raises(ValueError, match="exceeds"):
            read_file_bounded(f, 100)

    @pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW is POSIX-only")
    def test_refuses_to_follow_symlink(self, tmp_path):
        # Regression: measure -u (untrusted) could swap the output for a symlink
        # to a host secret; O_NOFOLLOW means copy-back never reads the link
        # target (TOCTOU). A naive read_bytes() would return the secret here.
        secret = tmp_path / "secret"
        secret.write_bytes(b"TOPSECRET")
        link = tmp_path / "measure.xml"
        link.symlink_to(secret)
        with pytest.raises(ValueError, match="symlink"):
            read_file_bounded(link, 1000)

    @pytest.mark.skipif(not hasattr(os, "O_NONBLOCK"), reason="POSIX fifo test")
    def test_refuses_non_regular_file(self, tmp_path):
        # Validates: a fifo/dir masquerading as a generated file is rejected
        # (not a regular file) instead of blocking or reading junk.
        d = tmp_path / "README.md"
        d.mkdir()
        with pytest.raises(ValueError, match="not a regular file"):
            read_file_bounded(d, 1000)


class TestReadTailBounded:
    """read_tail_bounded — symlink-refusing tail read for subprocess-produced
    logs (PR #105 Copilot): log_tail goes back to the client verbatim, so a
    confined subprocess swapping openstudio.log for a symlink would otherwise
    turn the tail read into arbitrary host-file disclosure."""

    def test_small_file_returned_whole(self, tmp_path):
        # Validates: a log under the cap comes back verbatim.
        from mcp_server.util import read_tail_bounded
        f = tmp_path / "openstudio.log"
        f.write_bytes(b"line1\nline2\n")
        assert read_tail_bounded(f, 1000) == b"line1\nline2\n"

    def test_oversize_returns_last_bytes_only(self, tmp_path):
        # Validates: only the LAST max_bytes are read (seek, not slurp) — a giant
        # failure log is never loaded wholesale just to show a 50-line tail.
        from mcp_server.util import read_tail_bounded
        f = tmp_path / "openstudio.log"
        f.write_bytes(b"A" * 500 + b"TAIL")
        assert read_tail_bounded(f, 100) == (b"A" * 500 + b"TAIL")[-100:]

    @pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW is POSIX-only")
    def test_refuses_to_follow_symlink(self, tmp_path):
        # Regression: PR #105 — the sandboxed openstudio subprocess can delete
        # openstudio.log mid-run and recreate it as a symlink to a host file; the
        # unconfined server's tail read must refuse the link, not return the
        # target's content as log_tail.
        from mcp_server.util import read_tail_bounded
        secret = tmp_path / "secret"
        secret.write_bytes(b"TOPSECRET")
        link = tmp_path / "openstudio.log"
        link.symlink_to(secret)
        with pytest.raises(ValueError, match="symlink"):
            read_tail_bounded(link, 1000)

    def test_refuses_non_regular_file(self, tmp_path):
        # Validates: a dir masquerading as the log is rejected, not read as junk.
        from mcp_server.util import read_tail_bounded
        d = tmp_path / "openstudio.log"
        d.mkdir()
        with pytest.raises(ValueError, match="not a regular file"):
            read_tail_bounded(d, 1000)


class TestSafeReadBytesNoFollow:
    """safe_read_bytes — refactored onto read_tail_bounded so its caller
    (results HTML via safe_read_text) inherits the no-follow bounded read."""

    @pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW is POSIX-only")
    def test_refuses_symlink(self, tmp_path):
        # Regression: PR #105 — safe_read_bytes followed symlinks and slurped the
        # whole file before truncating; simulation-produced eplustbl.htm read via
        # safe_read_text had the same swap exposure as out.osw/openstudio.log.
        from mcp_server.util import safe_read_bytes
        secret = tmp_path / "secret"
        secret.write_bytes(b"TOPSECRET")
        link = tmp_path / "eplustbl.htm"
        link.symlink_to(secret)
        with pytest.raises(ValueError, match="symlink"):
            safe_read_bytes(link)

    def test_tail_truncation_semantics_kept(self, tmp_path):
        # Validates: the existing keep-the-LAST-max_bytes contract survives the
        # refactor (results HTML reads tail-truncate, callers rely on it).
        from mcp_server.util import safe_read_bytes
        f = tmp_path / "big.htm"
        f.write_bytes(b"HEAD" + b"B" * 300)
        assert safe_read_bytes(f, max_bytes=100) == (b"HEAD" + b"B" * 300)[-100:]


class TestPerTenantSandboxUid:
    """Per-tenant sandbox uid derivation (M1/M2). Each remote tenant gets its own
    uid so RLIMIT_NPROC (per-uid) is a private budget and DAC isolates run dirs
    even without Landlock; the local single user keeps the baked-in base uid."""

    def test_local_keeps_base_uid(self, monkeypatch):
        # Validates: stdio/off-request single user keeps the baked sandbox uid —
        # preserves today's behavior, no per-tenant derivation.
        import mcp_server.config as cfg
        monkeypatch.setattr("mcp_server.identity.user_key", lambda: "local")
        assert cfg.sandbox_ids() == (cfg.SANDBOX_UID, cfg.SANDBOX_GID)

    def test_distinct_uid_per_tenant(self, monkeypatch):
        # Regression (M1/M2): all tenants shared uid 1001 -> one shared NPROC
        # budget (cross-tenant fork-bomb DoS) and zero DAC isolation in the posix
        # tier. Each tenant key must map to its OWN non-root uid.
        import mcp_server.config as cfg
        monkeypatch.setattr("mcp_server.identity.user_key", lambda: "alice")
        a = cfg.sandbox_ids()
        monkeypatch.setattr("mcp_server.identity.user_key", lambda: "bob")
        b = cfg.sandbox_ids()
        assert a != b, "distinct tenants must get distinct sandbox uids"
        assert a[0] >= 2000 and b[0] >= 2000, "derived uids must be above the system/sandbox range"
        assert a[0] != cfg.SANDBOX_UID, "a tenant uid must differ from the local base uid"
        assert a[1] == a[0] and b[1] == b[0], "gid tracks uid"

    def test_uid_stable_for_same_key(self, monkeypatch):
        # Validates: derivation is stable across calls (hashlib, not randomized
        # hash()) so a request's chown and setuid agree on the same uid.
        import mcp_server.config as cfg
        monkeypatch.setattr("mcp_server.identity.user_key", lambda: "carol")
        assert cfg.sandbox_ids() == cfg.sandbox_ids()

    def test_sandbox_uid_zero_clamped(self):
        # Regression (Codex H5): OSMCP_SANDBOX_UID<=0 must clamp to a non-root uid
        # so the local base uid can never be root (kept as a unit test now that the
        # HTTP h5 path exercises per-tenant derivation instead of the base uid).
        import mcp_server.config as cfg
        assert cfg._safe_sandbox_id("0", 1001) == 1001
        assert cfg._safe_sandbox_id("-5", 1001) == 1001
        assert cfg._safe_sandbox_id("4242", 1001) == 4242

# ---------------------------------------------------------------------------
# C-1: seed_file path traversal guard in run_osw
# ---------------------------------------------------------------------------

class TestSeedFilePathTraversal:
    """C-1: seed_file with '..' is flattened into run_dir."""

    @pytest.fixture
    def osw_setup(self, tmp_path):
        """Create a minimal OSW + seed file for testing."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        seed = src_dir / "model.osm"
        seed.write_text("fake osm content")
        return src_dir, seed

    def test_parent_ref_seed_flattened(self, tmp_path, osw_setup, monkeypatch):
        # Regression: seed_file with '../' could escape run_dir — now flattened to basename
        """seed_file='../model.osm' is flattened to 'model.osm' in run_dir."""
        src_dir, _seed = osw_setup

        # Put seed one level up from the OSW
        parent_dir = src_dir.parent
        parent_seed = parent_dir / "model.osm"
        parent_seed.write_text("parent osm")

        osw_data = {"seed_file": "../model.osm"}
        osw_path = src_dir / "workflow.osw"
        osw_path.write_text(json.dumps(osw_data))

        from mcp_server.skills.simulation.operations import run_osw
        run_root = tmp_path / "runs"
        run_root.mkdir()
        # Per-user run dirs: run_osw resolves its run dir via user_run_root().
        monkeypatch.setattr(
            "mcp_server.skills.simulation.operations.user_run_root",
            lambda: run_root,
        )
        # Don't start the background dispatcher thread in-process (it would race
        # other unit tests that drive _dispatch_once manually).
        monkeypatch.setattr(
            "mcp_server.skills.simulation.operations._ensure_dispatcher",
            lambda: None,
        )

        # Stub Popen so staging completes but subprocess "fails"
        class _FakePopen:
            def __init__(self, *a, **kw):
                self.returncode = 1
                self.pid = 999
            def communicate(self, timeout=None):
                return (b"", b"stubbed")
            def poll(self):
                return self.returncode
            def wait(self, timeout=None):
                return self.returncode
            def kill(self):
                pass

        monkeypatch.setattr(_subprocess, "Popen", _FakePopen)

        result = run_osw(str(osw_path), _internal=True)  # exercise staging/flatten, not the access gate
        # Staging happens before subprocess — verify unconditionally
        assert "escapes" not in result.get("error", ""), f"Path traversal error: {result}"
        run_dirs = list(run_root.iterdir())
        assert len(run_dirs) == 1, f"Expected 1 run dir, got {len(run_dirs)}"
        rd = run_dirs[0]
        assert (rd / "model.osm").exists(), "Seed should be staged in run_dir"
        staged_osw = json.loads((rd / "workflow.osw").read_text())
        assert staged_osw["seed_file"] == "model.osm", f"Seed not flattened: {staged_osw['seed_file']}"

    def test_normal_seed_unchanged(self, tmp_path, osw_setup, monkeypatch):
        # Validates: normal seed_file without path traversal is not rejected
        """seed_file='model.osm' (same dir) stays unchanged."""
        src_dir, _seed = osw_setup

        osw_data = {"seed_file": "model.osm"}
        osw_path = src_dir / "workflow.osw"
        osw_path.write_text(json.dumps(osw_data))

        from mcp_server.skills.simulation.operations import run_osw
        run_root = tmp_path / "runs"
        run_root.mkdir()
        # Per-user run dirs: run_osw resolves its run dir via user_run_root().
        monkeypatch.setattr(
            "mcp_server.skills.simulation.operations.user_run_root",
            lambda: run_root,
        )
        # Don't start the background dispatcher thread in-process (it would race
        # other unit tests that drive _dispatch_once manually).
        monkeypatch.setattr(
            "mcp_server.skills.simulation.operations._ensure_dispatcher",
            lambda: None,
        )

        # Stub Popen so staging completes but subprocess "fails"
        class _FakePopen:
            def __init__(self, *a, **kw):
                self.returncode = 1
                self.pid = 999
            def communicate(self, timeout=None):
                return (b"", b"stubbed")
            def poll(self):
                return self.returncode
            def wait(self, timeout=None):
                return self.returncode
            def kill(self):
                pass

        monkeypatch.setattr(_subprocess, "Popen", _FakePopen)

        result = run_osw(str(osw_path), _internal=True)  # exercise staging/flatten, not the access gate
        # Staging happens before subprocess — verify unconditionally
        assert "escapes" not in result.get("error", ""), "Normal seed incorrectly rejected"
        run_dirs = list(run_root.iterdir())
        assert len(run_dirs) == 1
        rd = run_dirs[0]
        assert (rd / "model.osm").exists(), "Normal seed should be staged"
        staged_osw = json.loads((rd / "workflow.osw").read_text())
        assert staged_osw["seed_file"] == "model.osm", "Normal seed path should be unchanged"


# ---------------------------------------------------------------------------
# C-2: _run_cmd OSError handling
# ---------------------------------------------------------------------------

class TestRunCmdOSError:
    """C-2: _run_cmd must not crash on FileNotFoundError/OSError."""

    def test_missing_binary_returns_error_tuple(self):
        # Regression: FileNotFoundError from missing binary crashed _run_cmd — now returns (-1, msg)
        """Nonexistent binary returns (-1, error_msg)."""
        from mcp_server.skills.server_info.operations import _run_cmd
        rc, msg = _run_cmd(["__nonexistent_binary_12345__", "--version"])
        assert rc == -1
        assert "not found" in msg.lower() or "no such file" in msg.lower() or "error" in msg.lower(), \
            f"Expected descriptive error message, got: {msg}"

    def test_valid_command_still_works(self):
        # Validates: OSError catch doesn't break normal command execution
        """Valid commands still work after adding OSError catch."""
        from mcp_server.skills.server_info.operations import _run_cmd
        rc, msg = _run_cmd(["python", "--version"])
        assert rc == 0
        assert "Python" in msg


# ---------------------------------------------------------------------------
# H-1: path validation (set_weather_file removed — change_building_location
# uses apply_measure which validates paths via measure runner)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# H-3: run_registry SQL column whitelist
# ---------------------------------------------------------------------------

class TestRunRegistryColumnWhitelist:
    """H-3: insert_run/update_run reject unknown column names."""

    def test_insert_bad_column(self, tmp_path):
        # Regression: unvalidated column names allowed SQL injection via insert_run
        from mcp_server.run_registry import insert_run
        bad_row = {
            "run_id": "x", "status": "q", "created_at": 0,
            "run_dir": "/a", "osw_path": "/b", "evil_col": "DROP TABLE",
        }
        with pytest.raises(ValueError, match="Invalid column"):
            insert_run(tmp_path, bad_row)

    def test_update_bad_column(self, tmp_path):
        # Regression: unvalidated column names allowed SQL injection via update_run
        from mcp_server.run_registry import update_run
        with pytest.raises(ValueError, match="Invalid column"):
            update_run(tmp_path, "x", evil_col="DROP TABLE")

    def test_insert_good_columns(self, tmp_path):
        # Validates: valid column names pass whitelist and row is retrievable
        from mcp_server.run_registry import get_run, insert_run
        good_row = {"run_id": "r1", "status": "pending", "created_at": 1.0, "run_dir": "/a", "osw_path": "/b"}
        insert_run(tmp_path, good_row)
        row = get_run(tmp_path, "r1")
        assert row["run_id"] == "r1"
        assert row["status"] == "pending"
        assert row["run_dir"] == "/a"

    def test_update_good_columns(self, tmp_path):
        # Validates: valid column update via whitelist changes row value correctly
        from mcp_server.run_registry import get_run, insert_run, update_run
        good_row = {"run_id": "r2", "status": "pending", "created_at": 1.0, "run_dir": "/a", "osw_path": "/b"}
        insert_run(tmp_path, good_row)
        update_run(tmp_path, "r2", status="running")
        row = get_run(tmp_path, "r2")
        assert row["status"] == "running"


# ---------------------------------------------------------------------------
# H-11: config._safe_int
# ---------------------------------------------------------------------------

class TestConfigSafeInt:
    """H-11: _safe_int returns default on bad input."""

    def test_valid_int(self):
        # Validates: _safe_int parses valid integer string correctly
        from mcp_server.config import _safe_int
        assert _safe_int("42", 10) == 42

    def test_invalid_string(self):
        # Regression: non-numeric env var crashed config parsing — now returns default
        from mcp_server.config import _safe_int
        assert _safe_int("bad", 10) == 10

    def test_none_value(self):
        # Validates: _safe_int returns default when input is None
        from mcp_server.config import _safe_int
        assert _safe_int(None, 5) == 5



# ---------------------------------------------------------------------------
# H-32: run_qaqc_checks unknown check names
# ---------------------------------------------------------------------------

class TestQaqcUnknownChecks:
    """H-32: unknown check names return error instead of silent pass-through."""

    def test_unknown_check_returns_error(self):
        # Regression: unknown QAQC check names silently passed through — now rejected
        from mcp_server.skills.common_measures.wrappers import run_qaqc_checks_op
        result = run_qaqc_checks_op(checks=["bogus_check"])
        assert result["ok"] is False
        assert "Unknown check" in result["error"]

    def test_valid_short_name_accepted(self):
        # Validates: valid QAQC check short names pass validation (may fail downstream on measure dir)
        # This will fail downstream (no measure dir) but should NOT fail validation
        result_fn = None
        try:
            from mcp_server.skills.common_measures.wrappers import run_qaqc_checks_op
            result_fn = run_qaqc_checks_op
        except ImportError:
            pytest.skip("imports unavailable")
        result = result_fn(checks=["envelope"])
        # Should not be "Unknown check" error — may be "Measure not found" instead
        assert "Unknown check" not in result.get("error", "")


# ---------------------------------------------------------------------------
# H-31: view_simulation_data empty variable_names
# ---------------------------------------------------------------------------

class TestViewSimDataEmptyVars:
    """H-31: empty variable_names list returns error instead of IndexError."""

    def test_empty_list_returns_error(self):
        # Regression: empty variable_names caused IndexError — now falls back to defaults
        from mcp_server.skills.common_measures.wrappers import view_simulation_data_op
        result = view_simulation_data_op(variable_names=[])
        # Empty list should use defaults, not crash with IndexError
        assert isinstance(result.get("ok"), bool), f"Expected ok field: {result}"
        assert "IndexError" not in result.get("error", ""), \
            "Empty variable_names should not cause IndexError"
        if not result["ok"]:
            assert result["error"].strip(), "Error message should not be empty"


# ---------------------------------------------------------------------------
# H-16: XOR validation in load creation (unit-level)
# ---------------------------------------------------------------------------

class TestLoadXORValidation:
    """H-16: create_* functions reject when BOTH sizing params provided."""

    def test_people_both_params(self):
        # Regression: providing both people_per_area and num_people caused ambiguous sizing
        from mcp_server.skills.loads.operations import create_people_definition
        result = create_people_definition("test", "space", people_per_area=0.1, num_people=10)
        assert result["ok"] is False
        assert "not both" in result["error"]

    def test_lights_both_params(self):
        # Regression: providing both watts_per_area and lighting_level_w caused ambiguous sizing
        from mcp_server.skills.loads.operations import create_lights_definition
        result = create_lights_definition("test", "space", watts_per_area=10.0, lighting_level_w=100.0)
        assert result["ok"] is False
        assert "not both" in result["error"]

    def test_electric_equipment_both_params(self):
        # Regression: providing both watts_per_area and design_level_w caused ambiguous sizing
        from mcp_server.skills.loads.operations import create_electric_equipment
        result = create_electric_equipment("test", "space", watts_per_area=10.0, design_level_w=100.0)
        assert result["ok"] is False
        assert "not both" in result["error"]

    def test_gas_equipment_both_params(self):
        # Regression: providing both watts_per_area and design_level_w caused ambiguous sizing
        from mcp_server.skills.loads.operations import create_gas_equipment
        result = create_gas_equipment("test", "space", watts_per_area=10.0, design_level_w=100.0)
        assert result["ok"] is False
        assert "not both" in result["error"]

    def test_infiltration_both_params(self):
        # Regression: providing both flow_per_exterior_surface_area and ach caused ambiguous sizing
        from mcp_server.skills.loads.operations import create_infiltration
        result = create_infiltration("test", "space", flow_per_exterior_surface_area=0.001, ach=0.5)
        assert result["ok"] is False
        assert "not both" in result["error"]


# ---------------------------------------------------------------------------
# H-17: reject unknown schedule_type
# ---------------------------------------------------------------------------

class TestScheduleTypeValidation:
    """H-17: create_schedule_ruleset rejects unknown schedule_type."""

    def test_unknown_type_rejected(self):
        # Regression: unknown schedule_type passed through silently — now returns error
        from mcp_server.skills.schedules.operations import create_schedule_ruleset
        result = create_schedule_ruleset("test", schedule_type="Bogus")
        assert result["ok"] is False
        assert "Invalid schedule_type" in result["error"]

    def test_valid_types_accepted(self):
        # Validates: Fractional/Temperature/OnOff schedule types pass validation
        from mcp_server.skills.schedules.operations import create_schedule_ruleset
        for st in ("Fractional", "Temperature", "OnOff"):
            # Will fail downstream (no model loaded) but should NOT fail validation
            result = create_schedule_ruleset("test", schedule_type=st)
            assert "Invalid schedule_type" not in result.get("error", "")


# ---------------------------------------------------------------------------
# H-18: validate default_value per schedule type
# ---------------------------------------------------------------------------

class TestScheduleDefaultValueValidation:
    """H-18: default_value range check per schedule_type."""

    def test_fractional_out_of_range(self):
        # Regression: Fractional schedule with default_value > 1.0 not rejected
        from mcp_server.skills.schedules.operations import create_schedule_ruleset
        result = create_schedule_ruleset("test", schedule_type="Fractional", default_value=1.5)
        assert result["ok"] is False
        assert "0.0-1.0" in result["error"]

    def test_fractional_negative(self):
        # Regression: Fractional schedule with negative default_value not rejected
        from mcp_server.skills.schedules.operations import create_schedule_ruleset
        result = create_schedule_ruleset("test", schedule_type="Fractional", default_value=-0.1)
        assert result["ok"] is False
        assert "0.0-1.0" in result["error"]

    def test_onoff_invalid(self):
        # Regression: OnOff schedule with non-binary default_value not rejected
        from mcp_server.skills.schedules.operations import create_schedule_ruleset
        result = create_schedule_ruleset("test", schedule_type="OnOff", default_value=0.5)
        assert result["ok"] is False
        assert "0 or 1" in result["error"]

    def test_temperature_no_range_check(self):
        # Validates: Temperature schedule allows any default_value (no range restriction)
        from mcp_server.skills.schedules.operations import create_schedule_ruleset
        # Temperature allows any value — should not fail on value range
        result = create_schedule_ruleset("test", schedule_type="Temperature", default_value=-40.0)
        assert "default_value" not in result.get("error", "")


# ---------------------------------------------------------------------------
# H-19: validate add_design_day inputs
# ---------------------------------------------------------------------------

class TestDesignDayValidation:
    """H-19: add_design_day rejects bad day_type, month, day, humidity_type."""

    def test_bad_day_type(self):
        # Regression: invalid day_type in add_design_day passed through to OpenStudio SDK
        from mcp_server.skills.weather.operations import add_design_day
        result = add_design_day("test", "Bogus", 1, 21, -17.8, 0.0)
        assert result["ok"] is False
        assert "Invalid day_type" in result["error"]

    def test_bad_month(self):
        # Regression: month=13 in add_design_day not caught before SDK call
        from mcp_server.skills.weather.operations import add_design_day
        result = add_design_day("test", "WinterDesignDay", 13, 21, -17.8, 0.0)
        assert result["ok"] is False
        assert "month" in result["error"]

    def test_bad_day(self):
        # Regression: day=0 in add_design_day not caught before SDK call
        from mcp_server.skills.weather.operations import add_design_day
        result = add_design_day("test", "WinterDesignDay", 1, 0, -17.8, 0.0)
        assert result["ok"] is False
        assert "day" in result["error"]

    def test_bad_humidity_type(self):
        # Regression: invalid humidity_type in add_design_day not validated
        from mcp_server.skills.weather.operations import add_design_day
        result = add_design_day("test", "WinterDesignDay", 1, 21, -17.8, 0.0, humidity_type="Bogus")
        assert result["ok"] is False
        assert "humidity_type" in result["error"]


# ---------------------------------------------------------------------------
# H-20: range checks in sim control + run period
# ---------------------------------------------------------------------------

class TestSimControlValidation:
    """H-20: set_simulation_control rejects invalid timesteps_per_hour."""

    def test_bad_timesteps(self):
        # Regression: non-divisor timesteps_per_hour (e.g. 7) not rejected
        from mcp_server.skills.weather.operations import set_simulation_control
        result = set_simulation_control(timesteps_per_hour=7)
        assert result["ok"] is False
        assert "timesteps_per_hour" in result["error"]

    def test_valid_timesteps_not_rejected(self):
        # Validates: valid timesteps_per_hour values (1,4,6,60) pass validation
        from mcp_server.skills.weather.operations import set_simulation_control
        for ts in (1, 4, 6, 60):
            result = set_simulation_control(timesteps_per_hour=ts)
            assert "timesteps_per_hour" not in result.get("error", "")


class TestRunPeriodValidation:
    """H-20: set_run_period rejects invalid month/day values."""

    def test_bad_begin_month(self):
        # Regression: begin_month=0 not caught by run period validation
        from mcp_server.skills.weather.operations import set_run_period
        result = set_run_period(begin_month=0, begin_day=1, end_month=12, end_day=31)
        assert result["ok"] is False
        assert "begin_month" in result["error"]

    def test_bad_end_day(self):
        # Regression: end_day=32 not caught by run period validation
        from mcp_server.skills.weather.operations import set_run_period
        result = set_run_period(begin_month=1, begin_day=1, end_month=12, end_day=32)
        assert result["ok"] is False
        assert "end_day" in result["error"]

    def test_bad_end_month(self):
        # Regression: end_month=13 not caught by run period validation
        from mcp_server.skills.weather.operations import set_run_period
        result = set_run_period(begin_month=1, begin_day=1, end_month=13, end_day=31)
        assert result["ok"] is False
        assert "end_month" in result["error"]


class TestRunOswAccessControl:
    """#2 (Codex): the PUBLIC run_osw must reject an OSW outside the caller's
    allowed roots — it copies the OSW's whole parent dir into the run dir, so an
    un-gated path is a cross-tenant / host file-disclosure vector."""

    def _stub(self, monkeypatch, run_root):
        monkeypatch.setattr(
            "mcp_server.skills.simulation.operations.user_run_root", lambda: run_root)
        monkeypatch.setattr(
            "mcp_server.skills.simulation.operations._ensure_dispatcher", lambda: None)

    def test_out_of_policy_osw_rejected(self, tmp_path, monkeypatch):
        # Regression: run_osw skipped is_path_allowed and _copy_tree'd the OSW's whole
        # parent dir into the run dir, disclosing arbitrary host / other-tenant files.
        outside = tmp_path / "other_tenant"
        outside.mkdir()
        (outside / "secret.osm").write_text("another tenant's model")
        (outside / "workflow.osw").write_text(json.dumps({"seed_file": "secret.osm"}))
        run_root = tmp_path / "runs"
        run_root.mkdir()
        self._stub(monkeypatch, run_root)

        from mcp_server.skills.simulation.operations import run_osw
        result = run_osw(str(outside / "workflow.osw"))  # public call (no _internal)
        assert result["ok"] is False, f"out-of-policy OSW must be rejected: {result}"
        assert "not allowed" in result.get("error", "").lower(), result
        assert list(run_root.iterdir()) == [], "nothing may be staged from a rejected path"

    def test_internal_trusted_path_still_stages(self, tmp_path, monkeypatch):
        # Validates: the internal staging path (run_simulation's server-built temp OSW)
        # still works via _internal=True, even from a dir outside the allowed roots.
        stage = tmp_path / "stage"
        stage.mkdir()
        (stage / "model.osm").write_text("seed")
        (stage / "workflow.osw").write_text(json.dumps({"seed_file": "model.osm"}))
        run_root = tmp_path / "runs"
        run_root.mkdir()
        self._stub(monkeypatch, run_root)

        class _FakePopen:
            def __init__(self, *a, **kw):
                self.returncode = 1
                self.pid = 999
            def poll(self):
                return self.returncode
            def wait(self, timeout=None):
                return self.returncode
            def kill(self):
                pass

        monkeypatch.setattr(_subprocess, "Popen", _FakePopen)
        from mcp_server.skills.simulation.operations import run_osw
        result = run_osw(str(stage / "workflow.osw"), _internal=True)
        assert "not allowed" not in result.get("error", "").lower(), result
        assert len(list(run_root.iterdir())) == 1, f"internal staging should create a run dir: {result}"
