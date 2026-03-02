"""Verify no SWIG memory-leak warning on MCP subprocess exit.

Launches a real MCP server, loads a model, then shuts down via stdin close.
The atexit handler in model_manager should clear the SWIG Model* before
the SWIG leak detector fires.
"""

import json
import os
import queue
import subprocess
import threading
import time

import pytest

# ---- helpers (same pattern as test_stdio_smoke.py) --------------------------

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
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            line = stdout_q.get(timeout=0.1)
        except queue.Empty:
            continue
        s = line.strip()
        if not s:
            continue
        return json.loads(s)
    raise AssertionError("Timed out waiting for JSON on stdout")


# ---- test -------------------------------------------------------------------

@pytest.mark.timeout(60)
def test_no_swig_memory_leak_warning_on_exit():
    """After loading a model and closing stdin, stderr must not contain
    'memory leak' from SWIG's atexit leak detector."""
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
        assert proc.poll() is None, (
            f"Server exited early rc={proc.returncode}\n{''.join(_drain(stderr_q))}"
        )

        # 1. initialize
        _write_json(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "pytest", "version": "0"},
                "capabilities": {},
            },
        })
        resp = _read_json_line(stdout_q, timeout_s=10)
        assert resp.get("id") == 1

        # 2. create_example_osm to get a loadable file
        _write_json(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "create_example_osm", "arguments": {}},
        })
        resp = _read_json_line(stdout_q, timeout_s=30)
        assert resp.get("id") == 2
        # extract osm_path from tool result text
        content = resp["result"]["content"]
        text = content[0]["text"] if isinstance(content, list) else content
        result_data = json.loads(text)
        osm_path = result_data["osm_path"]

        # 3. load the model (so _current_model holds a SWIG Model*)
        _write_json(proc, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "load_osm_model", "arguments": {"osm_path": osm_path}},
        })
        resp = _read_json_line(stdout_q, timeout_s=15)
        assert resp.get("id") == 3

        # 4. close stdin → triggers MCP shutdown + atexit handlers
        proc.stdin.close()
        proc.wait(timeout=15)

    except Exception:
        proc.kill()
        proc.wait()
        raise

    # 5. drain stderr and check for SWIG memory leak warning
    time.sleep(0.5)
    stderr_lines = _drain(stderr_q)
    stderr_text = "".join(stderr_lines)

    assert "memory leak" not in stderr_text.lower(), (
        f"SWIG memory leak warning found in stderr:\n{stderr_text}"
    )
