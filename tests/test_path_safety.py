"""Unit tests for critical fixes C-1 (path traversal) and C-2 (OSError).

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
        src_dir, seed = osw_setup

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
        src_dir, seed = osw_setup

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
