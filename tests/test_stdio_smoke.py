import json
import os
import queue
import subprocess
import threading
import time

import pytest

# ---- helpers ---------------------------------------------------------------

class StreamReader(threading.Thread):
    """Continuously read lines from a stream into a Queue."""
    def __init__(self, stream, out_queue: queue.Queue):
        super().__init__(daemon=True)
        self.stream = stream
        self.out_queue = out_queue

    def run(self):
        try:
            for line in iter(self.stream.readline, ""):
                self.out_queue.put(line)
        finally:
            try:
                self.stream.close()
            except Exception:
                pass


def _drain(q: queue.Queue) -> list[str]:
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            break
    return items


def _write_json(proc: subprocess.Popen, obj: dict):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def _read_json_line(stdout_q: queue.Queue, *, timeout_s: float) -> dict:
    """
    Read exactly one JSON object line from stdout.
    Fail if any non-JSON appears (protocol-breaking).
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            line = stdout_q.get(timeout=0.1)
        except queue.Empty:
            continue

        s = line.strip()
        if not s:
            continue

        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            raise AssertionError(
                f"Protocol-breaking stdout (not JSON): {line!r}\n{e}",
            )

        if not isinstance(obj, dict):
            raise AssertionError(f"Protocol-breaking stdout (JSON but not object): {obj!r}")

        return obj

    raise AssertionError("Timed out waiting for JSON message on stdout")


# ---- test -----------------------------------------------------------------

@pytest.mark.timeout(30)
def test_openstudio_mcp_stdio_is_clean_through_tool_call():
    """
    Verifies:
      1) stdout is JSON-only during initialize
      2) stdout is JSON-only during tools/list
      3) stdout remains JSON-only during a real tool call
    """
    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    extra_args = os.environ.get("MCP_SERVER_ARGS", "").split()

    proc = subprocess.Popen(
        [server_cmd, *extra_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    stdout_q: queue.Queue[str] = queue.Queue()
    stderr_q: queue.Queue[str] = queue.Queue()

    StreamReader(proc.stdout, stdout_q).start()
    StreamReader(proc.stderr, stderr_q).start()

    try:
        time.sleep(0.2)

        if proc.poll() is not None:
            err = "".join(_drain(stderr_q))
            raise AssertionError(
                f"Server exited early with code {proc.returncode}\nStderr:\n{err}",
            )

        # --- initialize -----------------------------------------------------
        _write_json(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "pytest", "version": "0"},
                "capabilities": {},
            },
        })

        init_resp = _read_json_line(stdout_q, timeout_s=10)
        assert init_resp.get("id") == 1
        assert "result" in init_resp

        # --- tools/list -----------------------------------------------------
        _write_json(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })

        tools_resp = _read_json_line(stdout_q, timeout_s=10)
        tools = {
            t.get("name")
            for t in tools_resp["result"].get("tools", [])
            if isinstance(t, dict)
        }

        expected = {
            "run_osw",
            "get_run_status",
            "get_run_logs",
            "get_run_artifacts",
            "validate_osw",
            "get_server_status",
        }
        missing = expected - tools
        assert not missing, f"Missing tools: {missing}"

        # --- NEW ASSERTION: call a real tool --------------------------------
        _write_json(proc, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_server_status",
                "arguments": {},
            },
        })

        status_resp = _read_json_line(stdout_q, timeout_s=10)
        assert status_resp.get("id") == 3
        assert "result" in status_resp

        # --- ensure no stray stdout after tool call -------------------------
        extra = [ln for ln in _drain(stdout_q) if ln.strip()]
        for ln in extra:
            try:
                json.loads(ln)
            except Exception:
                raise AssertionError(
                    f"Protocol-breaking stdout after tool call: {ln!r}",
                )

    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


@pytest.mark.integration
@pytest.mark.timeout(60)
def test_complex_model_stdout_purity():
    """Load a 44-zone complex model and call query tools — stdout must stay JSON-clean.

    Regression test for SWIG memory-leak warnings corrupting MCP transport
    on large models. Uses SystemD_baseline.osm (44 zones, 2 DOAS, 3 plant loops).
    """
    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    extra_args = os.environ.get("MCP_SERVER_ARGS", "").split()

    proc = subprocess.Popen(
        [server_cmd, *extra_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    stdout_q: queue.Queue[str] = queue.Queue()
    stderr_q: queue.Queue[str] = queue.Queue()
    StreamReader(proc.stdout, stdout_q).start()
    StreamReader(proc.stderr, stderr_q).start()

    try:
        time.sleep(0.2)
        if proc.poll() is not None:
            err = "".join(_drain(stderr_q))
            raise AssertionError(f"Server exited early: {proc.returncode}\n{err}")

        # --- initialize ---
        _write_json(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "pytest", "version": "0"},
                "capabilities": {},
            },
        })
        init_resp = _read_json_line(stdout_q, timeout_s=10)
        assert init_resp.get("id") == 1

        # --- load complex model ---
        _write_json(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": "load_osm_model",
                "arguments": {"osm_path": "/repo/tests/assets/SystemD_baseline.osm"},
            },
        })
        load_resp = _read_json_line(stdout_q, timeout_s=20)
        assert load_resp.get("id") == 2, f"Unexpected response: {load_resp}"
        assert "result" in load_resp

        # --- query tools that iterate many SDK objects ---
        query_tools = [
            ("get_building_info", {}),
            ("list_air_loops", {"max_results": 0}),
            ("list_plant_loops", {"max_results": 0}),
            ("list_thermal_zones", {"max_results": 0}),
            ("list_surfaces", {"max_results": 20}),
        ]
        for idx, (tool_name, tool_args) in enumerate(query_tools, start=3):
            _write_json(proc, {
                "jsonrpc": "2.0", "id": idx, "method": "tools/call",
                "params": {"name": tool_name, "arguments": tool_args},
            })
            resp = _read_json_line(stdout_q, timeout_s=15)
            assert resp.get("id") == idx, f"Tool {tool_name}: unexpected id in {resp}"
            assert "result" in resp, f"Tool {tool_name}: no result in {resp}"

        # --- verify no protocol-breaking bytes leaked ---
        time.sleep(0.5)
        extra = [ln for ln in _drain(stdout_q) if ln.strip()]
        for ln in extra:
            try:
                json.loads(ln)
            except Exception:
                raise AssertionError(
                    f"Protocol-breaking stdout after complex-model queries: {ln!r}",
                )

    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass