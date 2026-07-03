"""Tests for validate_model — requires OpenStudio (Docker).

Marked with RUN_OPENSTUDIO_INTEGRATION so they only run in Docker.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_OPENSTUDIO_INTEGRATION"),
        reason="requires OpenStudio (set RUN_OPENSTUDIO_INTEGRATION=1)",
    ),
]


@pytest.fixture(autouse=True)
def _clear_model():
    """Ensure no model is loaded before/after each test."""
    from mcp_server.model_manager import clear_model
    clear_model()
    yield
    clear_model()


class TestValidateModel:
    def test_no_model_loaded(self):
        # Validates: validate_model_op raises when no model is loaded
        from mcp_server.skills.simulation.operations import validate_model_op
        with pytest.raises(RuntimeError, match="model"):
            validate_model_op()

    def test_example_model_passes(self):
        # Validates: example model passes validation with zones and design days, warns on weather
        from mcp_server.model_manager import load_model
        from mcp_server.skills.model_management.operations import create_example_osm
        from mcp_server.skills.simulation.operations import validate_model_op

        result = create_example_osm()
        assert result["ok"]
        load_model(Path(result["osm_path"]))

        v = validate_model_op()
        # Example model has design days and HVAC but no embedded weather file
        assert v["ok"] is True
        assert v["zone_count"] > 0
        assert v["design_day_count"] > 0
        assert v["errors"] == []
        # Weather file warning is expected (EPW passed via OSW)
        assert any("weather" in w.lower() for w in v["warnings"])

    def test_orphaned_spm_and_empty_loop_flagged(self):
        # Regression: #83 — stealing the example model's zone with a new air
        # loop orphans its SPM:SingleZone:Reheat and empties the old loop; both
        # are E+ input-processing fatals that validate_model previously missed
        from mcp_server.model_manager import load_model
        from mcp_server.skills.hvac.operations import add_air_loop
        from mcp_server.skills.model_management.operations import create_example_osm
        from mcp_server.skills.simulation.operations import validate_model_op

        result = create_example_osm()
        assert result["ok"]
        load_model(Path(result["osm_path"]))

        # Low-level add_air_loop takes over the zone; the example model's own
        # loop ("Air Loop HVAC 1") keeps its SZR SPM but loses its only zone.
        added = add_air_loop("Stealer Loop", ["Thermal Zone 1"])
        assert added["ok"] is True, added

        v = validate_model_op()
        assert v["ok"] is False
        empty_loop_errors = [e for e in v["errors"] if "serves no thermal zones" in e]
        assert len(empty_loop_errors) == 1, v["errors"]
        assert "Air Loop HVAC 1" in empty_loop_errors[0]
        orphan_errors = [e for e in v["errors"] if "has no control zone" in e]
        assert len(orphan_errors) == 1, v["errors"]
        assert "Setpoint Manager Single Zone Reheat 1" in orphan_errors[0]

    def test_empty_model_fails(self, tmp_path):
        # Validates: empty model fails validation with design day error and weather warning
        import openstudio

        from mcp_server.model_manager import load_model
        from mcp_server.skills.simulation.operations import validate_model_op

        # Inject an empty in-memory model via the public load path (the old
        # mm._current_model back-door was removed in the session-keyed refactor).
        model = openstudio.model.Model()
        osm = tmp_path / "empty.osm"
        model.save(str(osm), True)
        load_model(osm)

        v = validate_model_op()
        assert v["ok"] is False
        assert any("design day" in e.lower() for e in v["errors"])
        # Weather is a warning, not error
        assert any("weather" in w.lower() for w in v["warnings"])
