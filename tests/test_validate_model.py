"""Tests for validate_model — requires OpenStudio (Docker).

Marked with RUN_OPENSTUDIO_INTEGRATION so they only run in Docker.
"""
from __future__ import annotations

import os

from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_OPENSTUDIO_INTEGRATION"),
    reason="requires OpenStudio (set RUN_OPENSTUDIO_INTEGRATION=1)",
)


@pytest.fixture(autouse=True)
def _clear_model():
    """Ensure no model is loaded before/after each test."""
    from mcp_server.model_manager import clear_model
    clear_model()
    yield
    clear_model()


class TestValidateModel:
    def test_no_model_loaded(self):
        from mcp_server.skills.simulation.operations import validate_model_op
        # get_model raises when no model loaded
        with pytest.raises(Exception):
            validate_model_op()

    def test_example_model_passes(self):
        """Example model has weather + design days — should pass basic checks."""
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

    def test_empty_model_fails(self):
        """Empty model should have errors (no weather, no design days)."""
        import openstudio
        import mcp_server.model_manager as mm
        from mcp_server.skills.simulation.operations import validate_model_op

        model = openstudio.model.Model()
        mm._current_model = model
        mm._current_model_path = "/tmp/empty.osm"

        v = validate_model_op()
        assert v["ok"] is False
        assert any("design day" in e.lower() for e in v["errors"])
        # Weather is a warning, not error
        assert any("weather" in w.lower() for w in v["warnings"])
