"""Unit tests for mcp_server.skills.gbxml_import.zone_checks.

Pure Python — no `openstudio` import, no Docker. get_conditioned_zones() and
check_conditioned_zone_volumes() only call a handful of ThermalZone methods
(isPlenum, thermostat, volume, nameString), so lightweight fakes exercise the
actual branching logic without a real model — the real fixture used in the
Docker integration tests (tests/test_gbxml_import.py) happens to have zero
zero-volume conditioned zones, so this is the only coverage of the positive
"flag it" branch.
"""
from __future__ import annotations

from mcp_server.skills.gbxml_import.zone_checks import check_conditioned_zone_volumes, get_conditioned_zones


class _FakeOptional:
    def __init__(self, value=None):
        self._value = value

    def is_initialized(self) -> bool:
        return self._value is not None

    def get(self):
        return self._value


class _FakeThermalZone:
    def __init__(self, name, plenum=False, thermostat=None, volume=None):
        self._name = name
        self._plenum = plenum
        self._thermostat = _FakeOptional(thermostat)
        self._volume = _FakeOptional(volume)

    def nameString(self):
        return self._name

    def isPlenum(self):
        return self._plenum

    def thermostat(self):
        return self._thermostat

    def volume(self):
        return self._volume


class _FakeModel:
    def __init__(self, zones):
        self._zones = zones

    def getThermalZones(self):
        return self._zones


# Validates: plenums are excluded even with a thermostat assigned, and zones
# with no thermostat are excluded even when not a plenum — only
# non-plenum + thermostat-assigned zones count as "conditioned".
def test_get_conditioned_zones_excludes_plenums_and_unconditioned():
    zones = [
        _FakeThermalZone("Office", plenum=False, thermostat="thermostat", volume=50.0),
        _FakeThermalZone("Plenum", plenum=True, thermostat="thermostat", volume=20.0),
        _FakeThermalZone("Unconditioned", plenum=False, thermostat=None, volume=30.0),
    ]
    conditioned = get_conditioned_zones(_FakeModel(zones))
    assert [tz.nameString() for tz in conditioned] == ["Office"]


# Validates: a conditioned zone with a real volume >= 1.0 m3 is not flagged.
def test_check_conditioned_zone_volumes_ignores_healthy_zone():
    zones = [_FakeThermalZone("Office", thermostat="t", volume=50.0)]
    result = check_conditioned_zone_volumes(_FakeModel(zones))
    assert result == {
        "conditioned_zone_count": 1,
        "zero_volume_zone_count": 0,
        "zero_volume_zones": [],
        "zero_volume_warning": None,
    }


# Regression: this is the exact scenario the feature exists to catch — a
# gbXML zone-enclosure defect leaves ThermalZone.volume() either uninitialized
# or a near-zero value, which would otherwise silently corrupt autosized
# equipment capacities. Both cases must be flagged.
def test_check_conditioned_zone_volumes_flags_zero_and_missing_volume():
    zones = [
        _FakeThermalZone("Healthy", thermostat="t", volume=50.0),
        _FakeThermalZone("Broken1", thermostat="t", volume=0.0),
        _FakeThermalZone("Broken2", thermostat="t", volume=None),  # uninitialized
    ]
    result = check_conditioned_zone_volumes(_FakeModel(zones))
    assert result["conditioned_zone_count"] == 3
    assert result["zero_volume_zone_count"] == 2
    assert result["zero_volume_zones"] == [
        {"zone": "Broken1", "volume_m3": 0.0},
        {"zone": "Broken2", "volume_m3": None},
    ]
    assert result["zero_volume_warning"] == (
        "2 of 3 conditioned zones have zero or missing volume. Zone enclosure issues from "
        "gbXML import likely — equipment autosizing may be unreliable. Verify gbXML geometry "
        "before trusting simulation results."
    )


# Validates: MIN_ZONE_VOLUME_M3 is a "less than" threshold, not
# "less than or equal" — a volume of exactly 1.0 m3 is healthy.
def test_check_conditioned_zone_volumes_boundary_at_one_cubic_meter():
    zones = [_FakeThermalZone("Boundary", thermostat="t", volume=1.0)]
    result = check_conditioned_zone_volumes(_FakeModel(zones))
    assert result["zero_volume_zone_count"] == 0
