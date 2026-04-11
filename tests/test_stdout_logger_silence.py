"""Verify silence_openstudio_stdout_logger keeps Polyhedron/Space warnings off fd 1."""

import os
import sys
import tempfile

import pytest


@pytest.mark.integration
def test_silence_openstudio_stdout_logger_sets_fatal_level():
    # Validates: silence_openstudio_stdout_logger raises standardOutLogger level to Fatal
    import openstudio

    from mcp_server.stdout_suppression import silence_openstudio_stdout_logger

    silence_openstudio_stdout_logger()
    level = openstudio.Logger.instance().standardOutLogger().logLevel()
    assert level.is_initialized(), "standardOutLogger level must be set"
    assert level.get() == openstudio.Fatal, (
        f"expected Fatal (2), got {level.get()} — Polyhedron warnings will still leak"
    )


@pytest.mark.integration
def test_polyhedron_warnings_do_not_reach_stdout_after_silence():
    # Regression: [utilities.Polyhedron] / [openstudio.model.Space] warnings were
    # reaching C stdout during Space::volume() on non-enclosed geometry, corrupting
    # MCP JSON-RPC. silence_openstudio_stdout_logger() is the primary fix.
    import openstudio

    from mcp_server.stdout_suppression import silence_openstudio_stdout_logger

    silence_openstudio_stdout_logger()

    # Build a Space with non-enclosed geometry (5 of 6 cube faces — roof missing)
    m = openstudio.model.Model()
    space = openstudio.model.Space(m)
    P = openstudio.Point3d

    def poly(*pts):
        v = openstudio.Point3dVector()
        for p in pts:
            v.append(p)
        return v

    floor = openstudio.model.Surface(
        poly(P(0, 0, 0), P(1, 0, 0), P(1, 1, 0), P(0, 1, 0)), m,
    )
    floor.setSpace(space)
    for verts in [
        poly(P(0, 0, 0), P(1, 0, 0), P(1, 0, 1), P(0, 0, 1)),
        poly(P(1, 0, 0), P(1, 1, 0), P(1, 1, 1), P(1, 0, 1)),
        poly(P(1, 1, 0), P(0, 1, 0), P(0, 1, 1), P(1, 1, 1)),
        poly(P(0, 1, 0), P(0, 0, 0), P(0, 0, 1), P(0, 1, 1)),
    ]:
        openstudio.model.Surface(verts, m).setSpace(space)

    # Capture fd 1 at OS level around the Polyhedron trigger
    cap = tempfile.NamedTemporaryFile(mode="r+", delete=False)
    saved_fd1 = os.dup(1)
    os.dup2(cap.fileno(), 1)
    try:
        _ = space.volume()
        _ = space.floorArea()
    finally:
        sys.stdout.flush()
        os.dup2(saved_fd1, 1)
        os.close(saved_fd1)

    cap.seek(0)
    captured = cap.read()

    assert captured == "", (
        f"expected clean stdout after silence_openstudio_stdout_logger, "
        f"but captured {len(captured)} bytes: {captured[:300]!r}"
    )


@pytest.mark.integration
def test_without_silence_polyhedron_still_prints_to_stdout():
    # Validates: the bug exists — without our fix, Polyhedron Logger goes to fd 1.
    # This test resets the level to Warn and confirms the pollution returns,
    # so the previous test can't pass trivially by silencing something else.
    import openstudio

    # Reset to default Warn level
    openstudio.Logger.instance().standardOutLogger().setLogLevel(openstudio.Warn)
    level = openstudio.Logger.instance().standardOutLogger().logLevel()
    assert level.get() == openstudio.Warn

    m = openstudio.model.Model()
    space = openstudio.model.Space(m)
    P = openstudio.Point3d

    def poly(*pts):
        v = openstudio.Point3dVector()
        for p in pts:
            v.append(p)
        return v

    openstudio.model.Surface(
        poly(P(0, 0, 0), P(1, 0, 0), P(1, 1, 0), P(0, 1, 0)), m,
    ).setSpace(space)
    for verts in [
        poly(P(0, 0, 0), P(1, 0, 0), P(1, 0, 1), P(0, 0, 1)),
        poly(P(1, 0, 0), P(1, 1, 0), P(1, 1, 1), P(1, 0, 1)),
        poly(P(1, 1, 0), P(0, 1, 0), P(0, 1, 1), P(1, 1, 1)),
        poly(P(0, 1, 0), P(0, 0, 0), P(0, 0, 1), P(0, 1, 1)),
    ]:
        openstudio.model.Surface(verts, m).setSpace(space)

    cap = tempfile.NamedTemporaryFile(mode="r+", delete=False)
    saved_fd1 = os.dup(1)
    os.dup2(cap.fileno(), 1)
    try:
        _ = space.volume()
    finally:
        sys.stdout.flush()
        os.dup2(saved_fd1, 1)
        os.close(saved_fd1)

    cap.seek(0)
    captured = cap.read()

    # Restore silence so remaining tests in the file see Fatal
    openstudio.Logger.instance().standardOutLogger().setLogLevel(openstudio.Fatal)

    assert "Polyhedron" in captured or "Space" in captured, (
        f"expected Polyhedron/Space Logger output on stdout at Warn level, "
        f"got {captured!r} — if this fails, openstudio upstream may have "
        f"changed the default sink and our fix can be simplified"
    )
