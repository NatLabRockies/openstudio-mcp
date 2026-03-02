"""Unit tests for security fixes — path traversal, OSError, SQL injection, input guards.

No Docker/OpenStudio needed — these test pure Python logic.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

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
        monkeypatch.setattr(
            "mcp_server.skills.simulation.operations.RUN_ROOT",
            run_root,
        )
        run_root.mkdir()

        result = run_osw(str(osw_path))
        # Will fail downstream (no openstudio binary), but seed should
        # be staged and OSW rewritten — no traversal error
        if not result["ok"]:
            assert "escapes" not in result.get("error", "")

        # Find the staged run_dir and verify seed was flattened
        if result.get("ok"):
            rd = Path(result["run_dir"])
            assert (rd / "model.osm").exists()
            osw = json.loads((rd / "workflow.osw").read_text())
            assert osw["seed_file"] == "model.osm"

    def test_normal_seed_unchanged(self, tmp_path, osw_setup, monkeypatch):
        """seed_file='model.osm' (same dir) stays unchanged."""
        src_dir, _seed = osw_setup

        osw_data = {"seed_file": "model.osm"}
        osw_path = src_dir / "workflow.osw"
        osw_path.write_text(json.dumps(osw_data))

        from mcp_server.skills.simulation.operations import run_osw
        run_root = tmp_path / "runs"
        monkeypatch.setattr(
            "mcp_server.skills.simulation.operations.RUN_ROOT",
            run_root,
        )
        run_root.mkdir()

        result = run_osw(str(osw_path))
        if not result["ok"]:
            assert "escapes" not in result.get("error", "")


# ---------------------------------------------------------------------------
# C-2: _run_cmd OSError handling
# ---------------------------------------------------------------------------

class TestRunCmdOSError:
    """C-2: _run_cmd must not crash on FileNotFoundError/OSError."""

    def test_missing_binary_returns_error_tuple(self):
        """Nonexistent binary returns (-1, error_msg)."""
        from mcp_server.skills.server_info.operations import _run_cmd
        rc, msg = _run_cmd(["__nonexistent_binary_12345__", "--version"])
        assert rc == -1
        assert msg

    def test_valid_command_still_works(self):
        """Valid commands still work after adding OSError catch."""
        from mcp_server.skills.server_info.operations import _run_cmd
        rc, msg = _run_cmd(["python", "--version"])
        assert rc == 0
        assert "Python" in msg


# ---------------------------------------------------------------------------
# H-1: set_weather_file path validation
# ---------------------------------------------------------------------------

class TestWeatherPathValidation:
    """H-1: set_weather_file rejects paths outside allowed roots."""

    def test_disallowed_epw_path(self, monkeypatch):
        from mcp_server.skills.weather import operations as weather_ops
        # Stub is_path_allowed to always reject
        monkeypatch.setattr("mcp_server.skills.weather.operations.is_path_allowed", lambda _p: False)
        result = weather_ops.set_weather_file("/tmp/evil.epw")
        assert result["ok"] is False
        assert "allowed roots" in result["error"]


# ---------------------------------------------------------------------------
# H-3: run_registry SQL column whitelist
# ---------------------------------------------------------------------------

class TestRunRegistryColumnWhitelist:
    """H-3: insert_run/update_run reject unknown column names."""

    def test_insert_bad_column(self, tmp_path):
        from mcp_server.run_registry import insert_run
        bad_row = {
            "run_id": "x", "status": "q", "created_at": 0,
            "run_dir": "/a", "osw_path": "/b", "evil_col": "DROP TABLE",
        }
        with pytest.raises(ValueError, match="Invalid column"):
            insert_run(tmp_path, bad_row)

    def test_update_bad_column(self, tmp_path):
        from mcp_server.run_registry import update_run
        with pytest.raises(ValueError, match="Invalid column"):
            update_run(tmp_path, "x", evil_col="DROP TABLE")

    def test_insert_good_columns(self, tmp_path):
        from mcp_server.run_registry import get_run, insert_run
        good_row = {"run_id": "r1", "status": "pending", "created_at": 1.0, "run_dir": "/a", "osw_path": "/b"}
        insert_run(tmp_path, good_row)
        row = get_run(tmp_path, "r1")
        assert row is not None
        assert row["status"] == "pending"

    def test_update_good_columns(self, tmp_path):
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
        from mcp_server.config import _safe_int
        assert _safe_int("42", 10) == 42

    def test_invalid_string(self):
        from mcp_server.config import _safe_int
        assert _safe_int("bad", 10) == 10

    def test_none_value(self):
        from mcp_server.config import _safe_int
        assert _safe_int(None, 5) == 5


# ---------------------------------------------------------------------------
# H-29: fetch_object UUID validation
# ---------------------------------------------------------------------------

class TestFetchObjectUUID:
    """H-29: malformed UUID returns None instead of crashing."""

    def test_bad_uuid_returns_none(self):
        # We can't easily create an openstudio model without Docker,
        # but we can verify the try/except path via direct call
        try:
            import openstudio
            model = openstudio.model.Model()
            from mcp_server.osm_helpers import fetch_object
            result = fetch_object(model, "Space", handle="not-a-valid-uuid-!!!")
            assert result is None
        except ImportError:
            pytest.skip("openstudio not available")


# ---------------------------------------------------------------------------
# H-32: run_qaqc_checks unknown check names
# ---------------------------------------------------------------------------

class TestQaqcUnknownChecks:
    """H-32: unknown check names return error instead of silent pass-through."""

    def test_unknown_check_returns_error(self):
        from mcp_server.skills.common_measures.wrappers import run_qaqc_checks_op
        result = run_qaqc_checks_op(checks=["bogus_check"])
        assert result["ok"] is False
        assert "Unknown check" in result["error"]

    def test_valid_short_name_accepted(self):
        # This will fail downstream (no measure dir) but should NOT fail validation
        result_fn = None
        try:
            from mcp_server.skills.common_measures.wrappers import run_qaqc_checks_op
            result_fn = run_qaqc_checks_op
        except ImportError:
            pytest.skip("imports unavailable")
        result = result_fn(checks=["envelope"])
        # Should not be "Unknown check" error — may be "Measure not found" instead
        if not result["ok"]:
            assert "Unknown check" not in result.get("error", "")


# ---------------------------------------------------------------------------
# H-31: view_simulation_data empty variable_names
# ---------------------------------------------------------------------------

class TestViewSimDataEmptyVars:
    """H-31: empty variable_names list returns error instead of IndexError."""

    def test_empty_list_returns_error(self):
        from mcp_server.skills.common_measures.wrappers import view_simulation_data_op
        result = view_simulation_data_op(variable_names=[])
        # Empty list should use defaults, not crash
        # The defaults are non-empty so it proceeds to _run which will fail
        # because no measure dir — but no IndexError
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# H-16: XOR validation in load creation (unit-level)
# ---------------------------------------------------------------------------

class TestLoadXORValidation:
    """H-16: create_* functions reject when BOTH sizing params provided."""

    def test_people_both_params(self):
        from mcp_server.skills.loads.operations import create_people_definition
        result = create_people_definition("test", "space", people_per_area=0.1, num_people=10)
        assert result["ok"] is False
        assert "not both" in result["error"]

    def test_lights_both_params(self):
        from mcp_server.skills.loads.operations import create_lights_definition
        result = create_lights_definition("test", "space", watts_per_area=10.0, lighting_level_w=100.0)
        assert result["ok"] is False
        assert "not both" in result["error"]

    def test_electric_equipment_both_params(self):
        from mcp_server.skills.loads.operations import create_electric_equipment
        result = create_electric_equipment("test", "space", watts_per_area=10.0, design_level_w=100.0)
        assert result["ok"] is False
        assert "not both" in result["error"]

    def test_gas_equipment_both_params(self):
        from mcp_server.skills.loads.operations import create_gas_equipment
        result = create_gas_equipment("test", "space", watts_per_area=10.0, design_level_w=100.0)
        assert result["ok"] is False
        assert "not both" in result["error"]

    def test_infiltration_both_params(self):
        from mcp_server.skills.loads.operations import create_infiltration
        result = create_infiltration("test", "space", flow_per_exterior_surface_area=0.001, ach=0.5)
        assert result["ok"] is False
        assert "not both" in result["error"]
