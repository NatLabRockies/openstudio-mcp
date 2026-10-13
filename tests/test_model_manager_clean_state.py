"""model_manager's per-path clean digests (issue #177), exercised in-process.

Integration tier (imports openstudio); no MCP transport needed.
"""
import contextlib
import threading
import uuid
from pathlib import Path

import pytest
from conftest import integration_enabled

pytestmark = pytest.mark.integration


@pytest.fixture
def mm():
    if not integration_enabled():
        pytest.skip("integration disabled")
    pytest.importorskip("openstudio")
    from mcp_server import model_manager
    model_manager.clear_model()
    yield model_manager
    model_manager.clear_model()


def _example_file(tmp_path: Path, extra_spaces: int = 0) -> Path:
    import openstudio
    m = openstudio.model.exampleModel()
    for i in range(extra_spaces):
        openstudio.model.Space(m).setName(f"extra_{i}_{uuid.uuid4().hex[:6]}")
    p = tmp_path / f"m_{uuid.uuid4().hex[:8]}.osm"
    assert m.save(str(p), True)
    return p


def _objects_on_disk(p: Path) -> int:
    import openstudio
    return openstudio.model.Model.load(str(p)).get().numObjects()


def test_reload_of_unchanged_same_version_file_is_clean(mm, tmp_path):
    # Validates: reload_model (apply_measure's reload) of a file whose content did not change
    # keeps the path clean; the digest is stable across loads of a same-version OSM. (A
    # version-translated file gets new handles on every load and is the documented exception.)
    p = _example_file(tmp_path)
    mm.load_model(p)
    assert mm.unsaved_edits_for(p) is False
    mm.reload_model(p)
    assert mm.unsaved_edits_for(p) is False, "unchanged reload must not look like an edit"
    import openstudio
    openstudio.model.Space(mm.get_model()).setName("edit after reload")
    assert mm.unsaved_edits_for(p) is True


def test_concurrent_saves_publish_digests_in_write_order(mm, tmp_path, monkeypatch):
    # Regression: two saves of different models to one path could write in one order and
    # publish their digests in the other, so `clean` described the model NOT on disk and
    # run_simulation stayed silent on a stale file (Codex review of #192).
    #
    # The interleaving is forced through model_manager's no-op suppress_openstudio_warnings()
    # shim, which wraps digest+write. Thread T captures the OLD model, then pauses before
    # writing until the main thread (now on model B) has written B. Without serialized saves
    # the order is: B written, OLD written, OLD published, B published -> clean says B while
    # the file holds OLD. With saves serialized per session, T holds the save lock, main
    # blocks, T's wait times out, and both write+publish pairs stay in order.
    a = _example_file(tmp_path)
    b = _example_file(tmp_path, extra_spaces=3)
    old_entered = threading.Event()
    main_written = threading.Event()
    old_done = threading.Event()
    roles: dict[str, threading.Thread] = {}
    main_saving = threading.Event()  # load_model uses the same shim; only act during the save

    @contextlib.contextmanager
    def pausing_shim():
        is_old = threading.current_thread() is roles.get("old")
        if is_old:
            old_entered.set()
            main_written.wait(timeout=1.5)  # times out when saves are serialized
        yield
        if not is_old and main_saving.is_set():
            main_written.set()
            old_done.wait(timeout=1.5)

    monkeypatch.setattr(mm, "suppress_openstudio_warnings", pausing_shim)

    mm.load_model(a)  # the OLD model

    def save_old():
        mm.save_model(a)  # captures the session model (OLD) before pausing in the shim
        old_done.set()

    roles["old"] = threading.Thread(target=save_old)
    roles["old"].start()
    assert old_entered.wait(timeout=10)
    mm.load_model(b)  # the session model is now B
    main_saving.set()
    mm.save_model(a)
    roles["old"].join(timeout=10)
    assert old_done.is_set()

    on_disk_is_session = _objects_on_disk(a) == mm.get_model().numObjects()
    assert mm.unsaved_edits_for(a) is (not on_disk_is_session), (
        f"clean digest must describe the content actually in the file "
        f"(file holds {'B' if on_disk_is_session else 'OLD'})"
    )
