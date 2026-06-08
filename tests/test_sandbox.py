"""Confirm the measure-exec vulnerabilities that the sandbox (planned) will close.

Context: docs/plans/measure-exec-sandbox.md. Today an applied measure runs as
root, with the server's full environment, unconfined filesystem, and open
network — see skills/measures/operations.py (`env=os.environ.copy()`, no UID
drop, no FS policy). These tests PROVE each hole exists, safely, using canaries
and decoys only (no real secret/file/host is touched, nothing leaves the box).

Design — "prove the problem exists now" half of the dual-run plan:
  - Server is spawned with OSMCP_SANDBOX=off, so these document the explicit
    passthrough/escape-hatch behaviour and remain valid once the sandbox lands
    (off = full passthrough, by design — the Codex `danger-full-access` model).
  - Each probe attempts an attack and reports via runner.registerInfo("PROBE ...").
    The AUTHORITATIVE check is external ground truth (escape file on disk, bytes
    the listener received, the uid value), not just the measure's self-report.

Fix increment 1 has landed (clean-env floor + unconditional measure_dir check):
  - test_measure_exec_unconfined_today (OSMCP_SANDBOX=off) still proves all five
    holes — off is a true passthrough by design.
  - test_clean_env_blocks_secret_leak (OSMCP_SANDBOX=posix) proves the env-secret
    leak is closed and a normal run still succeeds (allowlist complete enough).
  - test_measure_dir_traversal_blocked proves arbitrary out-of-root measure paths
    are rejected (check is unconditional, not gated by OSMCP_SANDBOX).
Fix increment 2 (UID drop + rlimits) and increment 3 (Landlock FS + seccomp
net-deny) have landed:
  - test_posix_drops_root_and_applies_rlimits — per-tenant non-root uid, NPROC
    rlimit, DAC blocks a root-owned write (OSMCP_SANDBOX=posix).
  - test_full_tier_blocks_read_escape_and_network — Landlock blocks reading a
    world-readable file outside the run dir, blocks writing outside it, and
    seccomp blocks outbound IP networking (OSMCP_SANDBOX=auto), while the run
    still succeeds.
With the full tier, all five holes are closed; off remains a true passthrough.

Safety notes:
  - Decoys live under RUN_ROOT / a tmpdir on the disposable runs volume and are
    deleted in finally blocks.
  - The network probe targets a localhost listener owned by this test process,
    inside the same container — no traffic leaves the machine.
"""
import asyncio
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import uuid
from pathlib import Path

import pytest
from conftest import (
    EPW_PATH,
    http_server,
    http_session,
    integration_enabled,
    setup_example,
    unwrap,
)

pytestmark = pytest.mark.integration

RUN_ROOT = Path(
    os.environ.get("OPENSTUDIO_MCP_RUN_ROOT", os.environ.get("OSMCP_RUN_ROOT", "/runs")),
)
_FIXTURE_MEASURE = Path(__file__).parent / "assets" / "measures" / "set_building_name"

# Each probe attempts one attack and registers a "PROBE <name>=<value>" line.
# victim_path / escape_path / net_target are passed as measure arguments, so the
# same measure body exercises all five holes in a single `openstudio run`.
_RB_PROBE_BODY = """
require 'socket'
runner.registerInfo("PROBE uid=#{Process.uid}")
runner.registerInfo("PROBE nproc=#{Process.getrlimit(:NPROC)[0]}")
runner.registerInfo("PROBE env=#{ENV['OSMCP_CANARY_SECRET'] || '<absent>'}")
begin
  runner.registerInfo("PROBE read=#{File.read(victim_path).strip}")
rescue => e
  runner.registerInfo("PROBE read_err=#{e.class}")
end
begin
  File.write(escape_path, "ESCAPED")
  runner.registerInfo("PROBE wrote=#{escape_path}")
rescue => e
  runner.registerInfo("PROBE write_err=#{e.class}")
end
begin
  host, port = net_target.split(":")
  s = TCPSocket.new(host, port.to_i)
  s.write("CANARY_EXFIL")
  s.close
  runner.registerInfo("PROBE net=sent")
rescue => e
  runner.registerInfo("PROBE net_err=#{e.class}")
end
"""

_PY_PROBE_BODY = """
import os
import socket
import resource
runner.registerInfo("PROBE uid=%d" % os.getuid())
runner.registerInfo("PROBE nproc=%d" % resource.getrlimit(resource.RLIMIT_NPROC)[0])
runner.registerInfo("PROBE env=%s" % os.environ.get("OSMCP_CANARY_SECRET", "<absent>"))
try:
    with open(victim_path) as f:
        runner.registerInfo("PROBE read=%s" % f.read().strip())
except Exception as e:
    runner.registerInfo("PROBE read_err=%s" % type(e).__name__)
try:
    with open(escape_path, "w") as f:
        f.write("ESCAPED")
    runner.registerInfo("PROBE wrote=%s" % escape_path)
except Exception as e:
    runner.registerInfo("PROBE write_err=%s" % type(e).__name__)
try:
    host, port = net_target.split(":")
    s = socket.create_connection((host, int(port)), timeout=5)
    s.sendall(b"CANARY_EXFIL")
    s.close()
    runner.registerInfo("PROBE net=sent")
except Exception as e:
    runner.registerInfo("PROBE net_err=%s" % type(e).__name__)
"""

_PROBE_ARGS = [
    {"name": "victim_path", "type": "String", "required": True, "default_value": ""},
    {"name": "escape_path", "type": "String", "required": True, "default_value": ""},
    {"name": "net_target", "type": "String", "required": True, "default_value": ""},
]


def _unique(prefix: str = "pytest_sandbox") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _probe_body(language: str) -> str:
    """Indent the probe body to the base indent create_measure injects at."""
    if language == "Ruby":
        return textwrap.indent(textwrap.dedent(_RB_PROBE_BODY).strip("\n"), "    ")
    return textwrap.indent(textwrap.dedent(_PY_PROBE_BODY).strip("\n"), "        ")


class _CanaryListener:
    """Localhost TCP listener that records the first payload it receives.

    Owned by the test process, bound to 127.0.0.1 inside the container — the
    measure subprocess connects to it; nothing leaves the machine.
    """

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.sock.settimeout(30)
        self.port = self.sock.getsockname()[1]
        self.received = b""
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
            with conn:
                conn.settimeout(5)
                self.received = conn.recv(1024)
        except OSError:
            pass
        finally:
            self.sock.close()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


@pytest.fixture(scope="module")
def sandbox_server():
    """One HTTP server for the module, with a fake canary secret in its env.

    OSMCP_SANDBOX=off pins the current unconfined passthrough so these stay valid
    once the sandbox exists. The canary is a fake value — never a real credential.
    """
    if not integration_enabled():
        pytest.skip("integration disabled")
    canary = f"do-not-leak-{uuid.uuid4().hex[:8]}"
    with http_server({
        "MCP_AUTH": "none",
        "OSMCP_SANDBOX": "off",
        "OSMCP_CANARY_SECRET": canary,
    }) as (url, _proc):
        yield url, canary


@pytest.fixture(scope="module")
def confined_server():
    """An HTTP server with the POSIX floor on (OSMCP_SANDBOX=posix)."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    canary = f"do-not-leak-{uuid.uuid4().hex[:8]}"
    with http_server({
        "MCP_AUTH": "none",
        "OSMCP_SANDBOX": "posix",
        "OSMCP_CANARY_SECRET": canary,
    }) as (url, _proc):
        yield url, canary


@pytest.fixture(scope="module")
def full_server():
    """An HTTP server with the full tier (OSMCP_SANDBOX=auto: posix + Landlock + seccomp)."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    canary = f"do-not-leak-{uuid.uuid4().hex[:8]}"
    with http_server({
        "MCP_AUTH": "none",
        "OSMCP_SANDBOX": "auto",
        "OSMCP_CANARY_SECRET": canary,
    }) as (url, _proc):
        yield url, canary


@pytest.fixture(scope="module")
def net_allow_server():
    """Full tier but with the network deny opted out (OSMCP_SANDBOX_NET=allow)."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    with http_server({
        "MCP_AUTH": "none",
        "OSMCP_SANDBOX": "auto",
        "OSMCP_SANDBOX_NET": "allow",
    }) as (url, _proc):
        yield url


async def _create_probe_measure(session, language: str) -> str:
    res = unwrap(await session.call_tool("create_measure", {
        "name": _unique("sandbox_probe_" + ("rb" if language == "Ruby" else "py")),
        "description": "Sandbox vulnerability probe (test fixture).",
        "run_body": _probe_body(language),
        "language": language,
        "arguments": _PROBE_ARGS,
    }))
    assert res.get("ok") is True, f"create_measure failed: {res}"
    return res["measure_dir"]


@pytest.mark.parametrize("language", ["Ruby", "Python"])
def test_measure_exec_unconfined_today(language, sandbox_server):
    # Validates: an applied measure today runs as root, sees the server's secret
    # env, reads outside its run dir, writes outside its run dir, and opens the
    # network — the five holes the sandbox must close. Proven safely via canaries.
    url, canary = sandbox_server
    tag = uuid.uuid4().hex[:8]
    victim_secret = f"VICTIM_SECRET_{tag}"
    victim_dir = RUN_ROOT / f"_decoy_victim_{tag}"
    victim_dir.mkdir(parents=True, exist_ok=True)
    victim_file = victim_dir / "secret.txt"
    victim_file.write_text(victim_secret, encoding="utf-8")
    escape_file = RUN_ROOT / f"_decoy_escape_{tag}.txt"
    listener = _CanaryListener()
    listener.start()

    try:
        async def _run():
            async with http_session(url) as s:
                # --- Arrange ---
                await setup_example(s, _unique())
                measure_dir = await _create_probe_measure(s, language)

                # --- Act ---
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": measure_dir,
                    "arguments": {
                        "victim_path": str(victim_file),
                        "escape_path": str(escape_file),
                        "net_target": f"127.0.0.1:{listener.port}",
                    },
                }))
                assert res.get("ok") is True, f"apply_measure failed: {res}"
                return "\n".join(res.get("runner_messages", {}).get("info", []))

        info = asyncio.run(_run())

        # --- Assert: each hole is real ---
        # 1. Runs as root — no privilege drop.
        assert "PROBE uid=0" in info, \
            f"measure should run as root (uid 0) today; info=\n{info}"
        # 2. Server's secret env leaks into the measure (os.environ.copy()).
        assert f"PROBE env={canary}" in info, \
            f"canary secret should leak into measure env today; info=\n{info}"
        # 3. Reads a file outside its run dir (another run's area).
        assert f"PROBE read={victim_secret}" in info, \
            f"measure should read the decoy victim file today; info=\n{info}"
        # 4. Writes a file outside its run dir — ground truth: file on disk.
        assert "PROBE wrote=" in info, f"measure should report a write; info=\n{info}"
        assert escape_file.is_file() and escape_file.read_text() == "ESCAPED", \
            "measure should write outside its run dir today (escape file on disk)"
        # 5. Opens the network — ground truth: listener received the payload.
        assert "PROBE net=sent" in info, f"measure should report net send; info=\n{info}"
        listener._thread.join(timeout=5)
        assert listener.received == b"CANARY_EXFIL", \
            f"localhost listener should receive exfil today; got {listener.received!r}"
    finally:
        listener.close()
        shutil.rmtree(victim_dir, ignore_errors=True)
        escape_file.unlink(missing_ok=True)


def test_measure_dir_traversal_blocked(sandbox_server):
    # Regression: apply_measure must reject a measure_dir outside all allowed
    # roots (own run area / shared read roots), closing the traversal hole where
    # any /tmp path holding a measure.rb was copied and executed. The check is
    # unconditional (not gated by OSMCP_SANDBOX), so it holds even with sandbox off.
    url, _canary = sandbox_server
    outside_dir = Path(tempfile.mkdtemp(prefix="osmcp_decoy_measure_"))
    decoy_measure = outside_dir / "set_building_name"
    shutil.copytree(_FIXTURE_MEASURE, decoy_measure)

    try:
        async def _run():
            async with http_session(url) as s:
                # --- Arrange ---
                await setup_example(s, _unique())
                # --- Act ---
                return unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": str(decoy_measure),
                    "arguments": {"building_name": "Traversal Test"},
                }))

        res = asyncio.run(_run())

        # --- Assert: out-of-root measure path is refused before any execution ---
        assert res.get("ok") is False, \
            f"apply_measure must reject a measure_dir outside allowed roots; got {res}"
        assert "not allowed" in str(res.get("error", "")).lower(), \
            f"error should explain the path is not allowed; got {res.get('error')}"
    finally:
        shutil.rmtree(outside_dir, ignore_errors=True)


@pytest.mark.parametrize("language", ["Ruby", "Python"])
def test_clean_env_blocks_secret_leak(language, confined_server):
    # Validates: OSMCP_SANDBOX=posix strips the server's secret env via the
    # allowlist, so an applied measure no longer sees host secrets — AND a normal
    # measure run still succeeds, proving the allowlist is complete enough.
    url, canary = confined_server

    async def _run():
        async with http_session(url) as s:
            # --- Arrange ---
            await setup_example(s, _unique())
            measure_dir = await _create_probe_measure(s, language)
            # --- Act ---
            res = unwrap(await s.call_tool("apply_measure", {
                "measure_dir": measure_dir,
                "arguments": {"victim_path": "", "escape_path": "", "net_target": ""},
            }))
            assert res.get("ok") is True, f"apply_measure under posix failed: {res}"
            return "\n".join(res.get("runner_messages", {}).get("info", []))

    info = asyncio.run(_run())

    # --- Assert: canary secret is gone, the run still produced output ---
    assert "PROBE env=<absent>" in info, \
        f"clean-env should hide the canary under posix; info=\n{info}"
    assert canary not in info, \
        f"canary secret must not appear anywhere under posix; info=\n{info}"


@pytest.mark.parametrize("language", ["Ruby", "Python"])
def test_posix_drops_root_and_applies_rlimits(language, confined_server):
    # Validates: OSMCP_SANDBOX=posix runs the measure as the unprivileged sandbox
    # uid (1001), applies the NPROC rlimit, and DAC then denies a write to a
    # root-owned location outside the run dir (/opt — in-image, not a bind mount,
    # so ownership is enforced regardless of host). Read/network are NOT yet closed
    # at this tier (Landlock/seccomp follow) — not asserted here.
    url, _canary = confined_server
    tag = uuid.uuid4().hex[:8]
    escape_file = Path(f"/opt/_sbx_escape_{tag}.txt")  # root-owned, in-image

    async def _run():
        async with http_session(url) as s:
            # --- Arrange ---
            await setup_example(s, _unique())
            measure_dir = await _create_probe_measure(s, language)
            # --- Act ---
            res = unwrap(await s.call_tool("apply_measure", {
                "measure_dir": measure_dir,
                "arguments": {
                    "victim_path": "", "escape_path": str(escape_file), "net_target": "",
                },
            }))
            assert res.get("ok") is True, f"apply_measure under posix failed: {res}"
            return "\n".join(res.get("runner_messages", {}).get("info", []))

    info = asyncio.run(_run())

    # --- Assert: privilege dropped to a per-tenant uid, rlimit applied, DAC blocks
    # the escape write. The HTTP fixture is session-keyed, so the measure drops to a
    # derived per-tenant uid (M1/M2), not the shared base 1001. ---
    m = re.search(r"PROBE uid=(\d+)", info)
    assert m, f"probe must report uid; info=\n{info}"
    uid = int(m.group(1))
    assert uid != 0, "measure must not run as root under posix"
    assert 2000 <= uid < 62000, \
        f"HTTP tenant must drop to a per-tenant sandbox uid (2000..61999), got {uid}; info=\n{info}"
    assert "PROBE nproc=1024" in info, f"NPROC rlimit (1024) should be applied; info=\n{info}"
    assert "PROBE write_err=" in info, \
        f"write to root-owned /opt should be denied under posix; info=\n{info}"
    assert not escape_file.exists(), "DAC must block writing a root-owned out-of-run-dir path"


@pytest.mark.parametrize("language", ["Ruby", "Python"])
def test_full_tier_blocks_read_escape_and_network(language, full_server):
    # Validates: OSMCP_SANDBOX=auto (Landlock FS + seccomp net-deny on top of the
    # POSIX floor) blocks reading a world-readable file outside the run dir
    # (root-owned /opt, not in the read-only allowlist — so DAC alone would NOT
    # block it; Landlock does), blocks writing outside the run dir, and blocks
    # outbound IP networking — while the measure run itself still succeeds.
    url, _canary = full_server
    tag = uuid.uuid4().hex[:8]
    victim_secret = f"VICTIM_SECRET_{tag}"
    victim_file = Path(f"/opt/_sbx_victim_{tag}.txt")   # root-owned, in-image, not allowlisted
    victim_file.write_text(victim_secret, encoding="utf-8")
    escape_file = Path(f"/opt/_sbx_escape_{tag}.txt")
    listener = _CanaryListener()
    listener.start()

    try:
        async def _run():
            async with http_session(url) as s:
                # --- Arrange ---
                await setup_example(s, _unique())
                measure_dir = await _create_probe_measure(s, language)
                # --- Act ---
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": measure_dir,
                    "arguments": {
                        "victim_path": str(victim_file),
                        "escape_path": str(escape_file),
                        "net_target": f"127.0.0.1:{listener.port}",
                    },
                }))
                assert res.get("ok") is True, f"apply_measure under full tier failed: {res}"
                return "\n".join(res.get("runner_messages", {}).get("info", []))

        info = asyncio.run(_run())

        # --- Assert: read escape, write escape, and network all denied ---
        assert "PROBE read_err=" in info, f"read outside run dir should be denied; info=\n{info}"
        assert victim_secret not in info, "victim secret must not leak under the full tier"
        assert "PROBE write_err=" in info, f"write outside run dir should be denied; info=\n{info}"
        assert not escape_file.exists(), "Landlock must block the out-of-run-dir write"
        assert "PROBE net_err=" in info, f"outbound network should be denied; info=\n{info}"
        listener._thread.join(timeout=3)
        assert listener.received == b"", f"seccomp must block exfil; got {listener.received!r}"
    finally:
        listener.close()
        victim_file.unlink(missing_ok=True)
        escape_file.unlink(missing_ok=True)


def test_landlock_confines_without_root():
    # Validates: the unprivileged confinement layer (Landlock) applies even when
    # the shim runs as a NON-root uid — so a local non-root server still confines
    # measure filesystem access; the uid-drop is simply skipped (no hard fail).
    # This is what protects a local user, not just the root Docker server.
    workdir = tempfile.mkdtemp()
    cmd = [
        sys.executable, "-m", "mcp_server._sandbox_exec",
        "--uid", "1001", "--gid", "1001",
        "--landlock-ro", "/usr", "--landlock-ro", "/lib", "--landlock-ro", "/lib64",
        "--landlock-rw", workdir,
        "--", "cat", "/etc/hostname",  # /etc not granted -> must be denied
    ]
    try:
        # Run the shim AS uid 1001 (non-root) to exercise the no-root path.
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, capture_output=True, text=True, cwd="/repo",
            user=1001, group=1001, check=False,
        )
        out = (proc.stdout + proc.stderr).lower()
        assert proc.returncode != 0, \
            f"Landlock must block /etc read even without root; rc=0 out={out}"
        assert "denied" in out, f"expected a permission-denied error; out={out}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_local_host_files_protected(sandbox_server, full_server):
    # Validates THE LOCAL ISSUE (dual-run, vuln -> fixed): the server bind-mounts
    # the user's real host directories (here /repo). Unconfined, a measure an LLM
    # authored writes straight into the user's checked-out repo on their machine;
    # the sandbox blocks it. Benign — one canary file at the repo root, asserted
    # PRESENT under off (the vulnerability) and ABSENT under auto (the fix),
    # cleaned up either way. /repo is read-only in the sandbox allowlist, so the
    # write is denied without breaking measures that legitimately read the repo.
    tag = uuid.uuid4().hex[:8]
    host_file = Path(f"/repo/_sandbox_local_canary_{tag}.txt")  # /repo = bind-mounted host source

    async def _attempt_write(url):
        async with http_session(url) as s:
            await setup_example(s, _unique())
            measure_dir = await _create_probe_measure(s, "Ruby")
            res = unwrap(await s.call_tool("apply_measure", {
                "measure_dir": measure_dir,
                "arguments": {"victim_path": "", "escape_path": str(host_file), "net_target": ""},
            }))
            assert res.get("ok") is True, f"apply_measure failed: {res}"
            return "\n".join(res.get("runner_messages", {}).get("info", []))

    try:
        # --- Vulnerability: unconfined (off) writes into the user's host repo ---
        off_info = asyncio.run(_attempt_write(sandbox_server[0]))
        assert "PROBE wrote=" in off_info, f"off: expected a successful write; {off_info}"
        assert host_file.is_file(), \
            "VULN: an unconfined measure wrote into the user's bind-mounted host dir (/repo)"
        host_file.unlink(missing_ok=True)

        # --- Fixed: confined (auto) denies the write ---
        auto_info = asyncio.run(_attempt_write(full_server[0]))
        assert "PROBE write_err=" in auto_info, f"auto: expected the write to be denied; {auto_info}"
        assert not host_file.is_file(), \
            "FIXED: the sandbox (Landlock, /repo read-only) blocks writing to the user's host dir"
    finally:
        host_file.unlink(missing_ok=True)


def test_sandbox_net_allow_permits_network(net_allow_server):
    # Validates: OSMCP_SANDBOX_NET=allow leaves outbound networking open under the
    # full tier (the knob is actually wired into wrap_cmd; default deny is tested
    # by test_full_tier_blocks_read_escape_and_network).
    listener = _CanaryListener()
    listener.start()
    try:
        async def _run():
            async with http_session(net_allow_server) as s:
                await setup_example(s, _unique())
                measure_dir = await _create_probe_measure(s, "Ruby")
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": measure_dir,
                    "arguments": {
                        "victim_path": "", "escape_path": "",
                        "net_target": f"127.0.0.1:{listener.port}",
                    },
                }))
                assert res.get("ok") is True, f"apply_measure failed: {res}"
                return "\n".join(res.get("runner_messages", {}).get("info", []))

        info = asyncio.run(_run())
        assert "PROBE net=sent" in info, f"net should be allowed; info=\n{info}"
        listener._thread.join(timeout=5)
        assert listener.received == b"CANARY_EXFIL", \
            f"OSMCP_SANDBOX_NET=allow should permit the connection; got {listener.received!r}"
    finally:
        listener.close()


def _trivial_body(language: str) -> str:
    indent = "    " if language == "Ruby" else "        "
    return f'{indent}runner.registerInfo("measure ok")'


async def _create_trivial_measure(session, language: str) -> str:
    res = unwrap(await session.call_tool("create_measure", {
        "name": _unique("tm_" + ("rb" if language == "Ruby" else "py")),
        "description": "Trivial measure for test_measure confinement check.",
        "run_body": _trivial_body(language),
        "language": language,
        "arguments": [],
    }))
    assert res.get("ok") is True, f"create_measure failed: {res}"
    return res["measure_dir"]


_EVIL_TEST = (
    "import socket\n"
    "def test_zzz_exfil():\n"
    "    try:\n"
    "        s = socket.create_connection(('127.0.0.1', {port}), timeout=5)\n"
    "        s.sendall(b'CANARY_EXFIL')\n"
    "        s.close()\n"
    "    except Exception:\n"
    "        pass\n"
)


def test_measure_test_code_confined(sandbox_server, full_server):
    # Validates THE COPILOT FINDING fix (dual-run): test_measure now runs untrusted
    # test code under the sandbox. Inject a test that exfils to a localhost
    # listener; under off it connects (vuln — test code was unconfined), under auto
    # seccomp blocks it (fixed). Asserts on the listener (ground truth). The off
    # leg is the falsifiability control: it proves the evil test actually runs.
    async def _run_test_measure(url, port):
        async with http_session(url) as s:
            measure_dir = await _create_trivial_measure(s, "Python")
            evil = Path(measure_dir) / "tests" / "test_zzz_evil.py"
            evil.write_text(_EVIL_TEST.format(port=port), encoding="utf-8")
            await s.call_tool("test_measure", {"measure_dir": measure_dir})

    # --- Vulnerability: off lets the (untrusted) test code reach the network ---
    off_listener = _CanaryListener()
    off_listener.start()
    try:
        asyncio.run(_run_test_measure(sandbox_server[0], off_listener.port))
        off_listener._thread.join(timeout=5)
        assert off_listener.received == b"CANARY_EXFIL", \
            "VULN: test_measure ran test code that reached the network under off"
    finally:
        off_listener.close()

    # --- Fixed: auto confines test_measure (seccomp blocks the exfil) ---
    auto_listener = _CanaryListener()
    auto_listener.start()
    try:
        asyncio.run(_run_test_measure(full_server[0], auto_listener.port))
        auto_listener._thread.join(timeout=5)
        assert auto_listener.received == b"", \
            f"FIXED: test_measure code must be net-confined under auto; got {auto_listener.received!r}"
    finally:
        auto_listener.close()


def test_measure_xml_refresh_does_not_execute_rewritten_measure_unconfined(full_server):
    # Regression: sandboxed test code could rewrite measure.rb, then test_measure
    # ran `openstudio measure -u` unsandboxed as root and evaluated the rewritten
    # file. A disposable /repo canary proves no post-test evaluation escapes.
    url, _ = full_server
    canary = Path(f"/repo/_sandbox_xml_refresh_{uuid.uuid4().hex[:10]}.txt")

    async def _run():
        async with http_session(url) as s:
            await setup_example(s, _unique())
            created = unwrap(await s.call_tool("create_measure", {
                "name": _unique("xml_refresh_probe"),
                "description": "Benign post-test XML refresh confinement probe.",
                "run_body": "    runner.registerInfo('normal measure body')",
                "language": "Ruby",
                "arguments": [],
            }))
            assert created["ok"] is True, f"create_measure failed: {created}"

            measure_dir = Path(created["measure_dir"])
            test_files = sorted((measure_dir / "tests").glob("*_test.rb"))
            assert len(test_files) == 1, (
                f"generated Ruby measure should have exactly one test file, got {test_files}"
            )
            test_files[0].write_text(
                textwrap.dedent(
                    f"""
                    require 'openstudio'
                    require 'minitest/autorun'
                    require_relative '../measure'

                    class XmlRefreshRewriteTest < Minitest::Test
                      def test_rewrite_measure_after_load
                        measure_path = File.expand_path('../measure.rb', __dir__)
                        original = File.read(measure_path)
                        payload = "File.write('{canary}', 'UNSANDBOXED_XML_REFRESH')\\n"
                        File.write(measure_path, payload + original)
                        assert_equal(false, File.exist?('{canary}'))
                      end
                    end
                    """,
                ).lstrip(),
                encoding="utf-8",
            )

            return unwrap(await s.call_tool("test_measure", {
                "measure_dir": str(measure_dir),
            }))

    try:
        result = asyncio.run(_run())
        assert result["ok"] is True, f"sandboxed measure test should pass: {result}"
        assert not canary.exists(), (
            "post-test `openstudio measure -u` evaluated rewritten measure.rb "
            "outside the sandbox and created the host-mounted canary"
        )
    finally:
        canary.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Codex review reproductions (confirm-now): each PASSES today by demonstrating
# the open hole, run under the FULL tier (OSMCP_SANDBOX=auto) so it proves the
# sandbox does NOT yet stop it. Tagged with the Codex finding id + how to INVERT
# the assertion once the fix lands. All use canaries/decoys only.
# Not yet reproduced here (need heavier setup): C1 reporting-measure test path
# (needs a completed sim/SQL), C2 `openstudio measure -u` Ruby injection,
# H1 seccomp arch fail-open (needs an i386/x32 binary), H2 fail-open on a kernel
# without Landlock.
# ---------------------------------------------------------------------------

def test_c3_escaping_symlink_rejected(full_server):
    # Codex C3 (FIXED): a measure dir containing a symlink that escapes the measure
    # root is rejected before any copy — no host-file content is inlined into the
    # readable run dir.
    url, _ = full_server
    tag = uuid.uuid4().hex[:8]
    secret_file = Path(f"/opt/_sbx_c3_{tag}.txt")  # outside the measure dir
    secret_file.write_text(f"C3_SECRET_{tag}", encoding="utf-8")
    try:
        async def _run():
            async with http_session(url) as s:
                await setup_example(s, _unique())
                mdir = Path(await _create_trivial_measure(s, "Ruby"))
                (mdir / "evil_link.txt").symlink_to(secret_file)  # escaping symlink
                return unwrap(await s.call_tool("apply_measure", {"measure_dir": str(mdir)}))

        res = asyncio.run(_run())
        assert res.get("ok") is False and "symlink" in str(res.get("error", "")).lower(), \
            f"C3: an escaping symlink in the measure dir must be rejected; got {res}"
    finally:
        secret_file.unlink(missing_ok=True)


def test_c4_run_simulation_rejects_out_of_root_osm(full_server):
    # Codex C4 (FIXED): run_simulation rejects an OSM outside all allowed roots
    # (no staging arbitrary host files into the run dir).
    url, _ = full_server
    tag = uuid.uuid4().hex[:8]
    outside_osm = Path(f"/opt/_sbx_c4_{tag}.osm")  # outside every allowed root
    try:
        async def _run():
            async with http_session(url) as s:
                cr = unwrap(await s.call_tool("create_example_osm", {"name": _unique()}))
                assert cr["ok"] is True, cr
                shutil.copy2(cr["osm_path"], outside_osm)  # a valid OSM at a host path
                res = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": str(outside_osm), "epw_path": EPW_PATH}))
                if res.get("ok") and res.get("run_id"):
                    await s.call_tool("cancel_run", {"run_id": res["run_id"]})
                return res

        res = asyncio.run(_run())
        assert res.get("ok") is False and "not allowed" in str(res.get("error", "")).lower(), \
            f"C4: out-of-root OSM must be rejected; got {res}"
    finally:
        outside_osm.unlink(missing_ok=True)


def test_c5_test_measure_rejects_out_of_root_dir(full_server):
    # Codex C5 (FIXED): test_measure rejects a measure_dir outside all allowed
    # roots (before it would chown / Landlock-grant an arbitrary path).
    url, _ = full_server
    outside = Path(tempfile.mkdtemp(prefix="osmcp_c5_"))
    decoy = outside / "set_building_name"
    shutil.copytree(_FIXTURE_MEASURE, decoy)
    try:
        async def _run():
            async with http_session(url) as s:
                await setup_example(s, _unique())
                return unwrap(await s.call_tool("test_measure", {"measure_dir": str(decoy)}))

        res = asyncio.run(_run())
        assert res.get("ok") is False and "not allowed" in str(res.get("error", "")).lower(), \
            f"C5: out-of-root measure_dir must be rejected; got {res}"
    finally:
        shutil.rmtree(outside, ignore_errors=True)


@pytest.fixture(scope="module")
def uid0_server():
    """Full tier but with a misconfigured sandbox uid of 0 (OSMCP_SANDBOX_UID=0)."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    with http_server({
        "MCP_AUTH": "none", "OSMCP_SANDBOX": "auto",
        "OSMCP_SANDBOX_UID": "0", "OSMCP_SANDBOX_GID": "0",
    }) as (url, _proc):
        yield url


def test_h5_sandbox_uid_zero_clamped(uid0_server):
    # Codex H5 (FIXED): OSMCP_SANDBOX_UID=0 is rejected/clamped to the safe default,
    # so confined code never runs as root even with the bad override.
    async def _run():
        async with http_session(uid0_server) as s:
            await setup_example(s, _unique())
            measure_dir = await _create_probe_measure(s, "Ruby")
            res = unwrap(await s.call_tool("apply_measure", {
                "measure_dir": measure_dir,
                "arguments": {"victim_path": "", "escape_path": "", "net_target": ""},
            }))
            assert res.get("ok") is True, f"apply_measure failed: {res}"
            return "\n".join(res.get("runner_messages", {}).get("info", []))

    info = asyncio.run(_run())
    # OSMCP_SANDBOX_UID=0 must never yield a root-running measure. The base-uid
    # clamp is unit-tested (test_sandbox_uid_zero_clamped); this HTTP fixture is
    # session-keyed, so the measure drops to a per-tenant derived uid (also never
    # root) regardless of the bad base override.
    m = re.search(r"PROBE uid=(\d+)", info)
    assert m, f"H5: probe must report uid; info=\n{info}"
    uid = int(m.group(1))
    assert uid != 0, f"H5: measure must NOT run as root with OSMCP_SANDBOX_UID=0; info=\n{info}"
    assert 2000 <= uid < 62000, \
        f"H5: confined code must run as a non-root per-tenant uid, got {uid}; info=\n{info}"


def test_unknown_sandbox_mode_fails_closed():
    # Regression: a typo'd OSMCP_SANDBOX (e.g. 'atuo') left enabled()=True but
    # _full()=False, silently downgrading the default Landlock+seccomp tier to
    # posix-only. An unknown value must normalize to 'auto' (fail-closed).
    from mcp_server import config
    assert config._normalize_sandbox_mode("atuo") == "auto"
    assert config._normalize_sandbox_mode("landlok") == "auto"
    assert config._normalize_sandbox_mode("AUTO") == "auto"
    assert config._normalize_sandbox_mode(" posix ") == "posix"
    assert config._normalize_sandbox_mode("off") == "off"
    assert config._normalize_sandbox_mode("") == ""  # explicit off-alias, honored


def test_safe_float_rejects_non_finite():
    # Regression: a NaN/inf SIM_TIMEOUT made both `<= 0` and the elapsed-time
    # comparison false, silently disabling wall-clock timeout enforcement.
    from mcp_server import config
    assert config._safe_float("nan", 7200.0) == 7200.0
    assert config._safe_float("inf", 7200.0) == 7200.0
    assert config._safe_float("-inf", 7200.0) == 7200.0
    assert config._safe_float("bad", 7200.0) == 7200.0
    assert config._safe_float("3.5", 7200.0) == pytest.approx(3.5)


def test_build_env_drops_lc_prefixed_secret(monkeypatch, tmp_path):
    # Regression: a bare 'LC_' allowlist prefix copied any LC_*-named host var
    # (e.g. LC_API_TOKEN) into untrusted measure code. Only standard locale
    # categories may pass; arbitrary names — even LC_-prefixed — are dropped.
    from mcp_server import sandbox
    monkeypatch.setattr(sandbox, "SANDBOX_MODE", "posix")  # force enabled() + filtering
    monkeypatch.setenv("LC_CTYPE", "en_US.UTF-8")
    monkeypatch.setenv("LC_API_TOKEN", "supersecret")
    monkeypatch.setenv("MY_SECRET", "nope")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = sandbox.build_env(tmp_path, redirect_tmp=False)
    assert env.get("LC_CTYPE") == "en_US.UTF-8", "standard locale var must pass"
    assert "LC_API_TOKEN" not in env, "LC_-prefixed secret must be dropped"
    assert "MY_SECRET" not in env, "non-allowlisted secret must be dropped"
    assert env.get("PATH") == "/usr/bin", "PATH is required and allowlisted"


def test_wrap_cmd_grants_device_files_not_whole_dev(monkeypatch, tmp_path):
    # Regression: granting /dev rw also exposed writable /dev/shm + /dev/mqueue
    # (shared storage/IPC outside the run dir) and permitted mknod. Confine to the
    # specific device FILES instead (file-level Landlock rules).
    from mcp_server import sandbox
    monkeypatch.setattr(sandbox, "SANDBOX_MODE", "auto")   # full tier
    monkeypatch.setattr(sandbox, "SANDBOX_NET", "deny")
    monkeypatch.setattr(sandbox, "_has_backend", lambda: True)
    wrapped = sandbox.wrap_cmd(["echo", "hi"], tmp_path)
    rw = [wrapped[i + 1] for i, a in enumerate(wrapped) if a == "--landlock-rw"]
    ro = [wrapped[i + 1] for i, a in enumerate(wrapped) if a == "--landlock-ro"]
    assert "/dev" not in rw, f"must not grant the whole /dev dir rw: {rw}"
    assert "/dev/null" in rw and "/dev/zero" in rw, f"missing rw device files: {rw}"
    assert "/dev/urandom" in ro and "/dev/random" in ro, f"missing ro device files: {ro}"
    assert "/dev/shm" not in rw and "/dev/shm" not in ro, "/dev/shm must never be granted"  # noqa: S108


def test_test_measure_does_not_mutate_shared_source(tmp_path, monkeypatch):
    # Regression (Codex #3): test_measure executed in the caller's measure dir,
    # writing test_model.osm + chowning + Landlock-granting it. For a measure under a
    # SHARED read-only root (e.g. a bundled measure) that mutates shared/host content.
    # The fix copies a non-writable-root measure into a private run dir and tests the
    # copy, leaving the source untouched. (Monkeypatches config ROOTS — environment
    # setup, like RUN_ROOT — not the unit under test.)
    from mcp_server import config
    from mcp_server.skills.measure_authoring import operations as mops

    shared_root = tmp_path / "shared"
    measure = shared_root / "mymeasure"
    (measure / "tests").mkdir(parents=True)
    (measure / "measure.rb").write_text("# fake ModelMeasure\nclass M\nend\n")
    (measure / "tests" / "mymeasure_test.rb").write_text("require 'openstudio'\n")
    model = shared_root / "seed.osm"
    model.write_text("OS:Version,;\n")  # a readable file to copy as the test model

    # Treat shared_root as a shared READ-ONLY root; private writable area elsewhere.
    monkeypatch.setattr(config, "_SHARED_READ_ROOTS",
                        [*config._SHARED_READ_ROOTS, shared_root.resolve()])
    run_root = tmp_path / "runs"
    run_root.mkdir()
    monkeypatch.setattr(mops, "user_run_root", lambda: run_root)

    mops.test_measure_op(str(measure), model_path=str(model))

    assert not (measure / "tests" / "test_model.osm").exists(), \
        "test_model.osm was written into the SHARED measure source — must use a private copy"
    assert sorted(p.name for p in (measure / "tests").iterdir()) == ["mymeasure_test.rb"], \
        "shared measure source/tests was mutated"


def test_proc_not_in_landlock_ro_allowlist():
    # Regression (H1): /proc was a Landlock RO root, so a confined measure could
    # read /proc/<pid>/environ. On a non-root server (measure uid == server uid)
    # that recovers the server secrets clean-env stripped — incl. HTTP auth
    # tokens. /proc must NOT be granted; Landlock then denies it for everyone.
    from mcp_server import sandbox
    ro = sandbox._ro_paths()
    assert "/proc" not in ro, f"/proc must not be a Landlock RO root (H1): {ro}"


def test_full_tier_denies_proc_environ_read():
    # Regression (H1, dual-proof): with /proc granted, a confined process could
    # read /proc/self/environ (DAC always allows self) — the same surface that
    # leaks /proc/<server>/environ on a non-root server. Built via the REAL
    # wrap_cmd so it tracks the actual allowlist; the read must now be DENIED.
    from mcp_server import sandbox
    if sandbox.active_tier() != "landlock":
        pytest.skip("needs full tier (OSMCP_SANDBOX=auto)")
    workdir = tempfile.mkdtemp()
    cmd = sandbox.wrap_cmd(["cat", "/proc/self/environ"], workdir)
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, capture_output=True, text=True, cwd="/repo",
            user=1001, group=1001, check=False,
        )
        out = (proc.stdout + proc.stderr).lower()
        assert proc.returncode != 0, f"/proc read must be denied (H1); rc=0 out={out[:200]}"
        assert ("denied" in out or "no such" in out
                or "operation not permitted" in out), f"expected denial; out={out[:300]}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_per_tenant_uid_gives_dac_isolation():
    # Regression (M2): every tenant shared uid 1001, so in the posix tier (no
    # Landlock) tenant B could read tenant A's run files by plain DAC. Per-tenant
    # uids restore DAC isolation — a 0600 file owned by tenant A's uid is
    # unreadable by tenant B's uid, with no Landlock involved.
    from mcp_server import config
    uid_a = config._derive_tenant_uid("tenantA")
    uid_b = config._derive_tenant_uid("tenantB")
    assert uid_a != uid_b, "distinct tenants must derive distinct uids"
    d = Path(tempfile.mkdtemp())
    try:
        secret = d / "modelA.osm"
        secret.write_text("TENANT_A_PRIVATE")
        os.chown(secret, uid_a, uid_a)
        secret.chmod(0o600)
        # dir must be traversable so the denial proven is the file's, not the dir's
        d.chmod(0o755)
        # absolute path (no PATH lookup), fixed argv, no shell
        proc = subprocess.run(  # noqa: S603
            ["/bin/cat", str(secret)],
            capture_output=True, text=True,
            user=uid_b, group=uid_b, check=False,
        )
        out = (proc.stdout + proc.stderr).lower()
        assert proc.returncode != 0, f"tenant B must not read tenant A's 0600 file; rc=0 out={out}"
        assert "permission denied" in out, f"expected DAC denial; out={out}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_input_root_not_in_landlock_ro_allowlist():
    # Regression (Codex #5): /inputs (INPUT_ROOT) is a SHARED multi-tenant dir;
    # granting it read in the Landlock policy let one tenant's confined measure read
    # another tenant's inputs. Inputs are staged into the run dir, so /inputs must
    # NOT be a read-only root.
    from mcp_server import sandbox
    from mcp_server.config import COMMON_MEASURES_DIR, COMSTOCK_MEASURES_DIR, INPUT_ROOT
    ro = sandbox._ro_paths()
    assert str(INPUT_ROOT) not in ro, f"INPUT_ROOT must not be a Landlock RO root: {ro}"
    # The legitimately-needed shared measure roots are still granted.
    assert str(COMSTOCK_MEASURES_DIR) in ro and str(COMMON_MEASURES_DIR) in ro, \
        f"bundled-measure roots must stay readable: {ro}"
