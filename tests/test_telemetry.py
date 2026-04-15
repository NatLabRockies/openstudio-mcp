"""Unit tests for mcp_server/telemetry.py (OpenLLMetry / traceloop-sdk integration).

These tests run without OpenStudio and without Docker.

Validates:
- Telemetry is a no-op when TRACELOOP_BASE_URL is not set
- init_telemetry() calls McpInstrumentor().instrument() and Traceloop.init()
- init_telemetry() is idempotent
- traced() returns the original function when traceloop-sdk is unavailable
- traced() wraps with @task() and marks ERROR on ok=False when SDK is available
- trace_operation() creates a child span when a TracerProvider is configured
- _truncate() caps values at _MAX_ATTR_LEN

Regression: these tests guard against the telemetry module breaking server
startup or silently swallowing init errors.
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _reset_telemetry_module():
    """Force a clean re-import of telemetry so _TELEMETRY_INITIALIZED resets."""
    mod_name = "mcp_server.telemetry"
    old = sys.modules.pop(mod_name, None)
    try:
        yield
    finally:
        sys.modules.pop(mod_name, None)
        if old is not None:
            sys.modules[mod_name] = old


def _make_in_memory_setup():
    """Return (provider, exporter, tracer) using the OTel SDK InMemorySpanExporter."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    return provider, exporter, tracer


# ---------------------------------------------------------------------------
# init_telemetry tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_init_no_endpoint_returns_false(monkeypatch):
    """Validates: init_telemetry returns False and does not call Traceloop.init when
    TRACELOOP_BASE_URL is unset."""
    monkeypatch.delenv("TRACELOOP_BASE_URL", raising=False)

    mock_traceloop = MagicMock()
    mock_instrumentor = MagicMock()

    with _reset_telemetry_module():
        with patch.dict("sys.modules", {
            "traceloop.sdk": mock_traceloop,
            "traceloop.sdk.decorators": MagicMock(),
            "opentelemetry.instrumentation.mcp": mock_instrumentor,
        }):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True  # pretend SDK is installed
            result = tel.init_telemetry()

    assert result is False
    mock_traceloop.Traceloop.init.assert_not_called()


@pytest.mark.unit
def test_init_no_sdk_returns_false(monkeypatch):
    """Validates: init_telemetry returns False (no warning) when SDK is absent and
    no endpoint is configured."""
    monkeypatch.delenv("TRACELOOP_BASE_URL", raising=False)

    with _reset_telemetry_module():
        import mcp_server.telemetry as tel
        tel._SDK_AVAILABLE = False
        result = tel.init_telemetry()

    assert result is False


@pytest.mark.unit
def test_init_sdk_missing_with_endpoint_logs_warning(monkeypatch, caplog):
    """Validates: a warning is logged when endpoint is set but SDK is not installed."""
    import logging
    monkeypatch.setenv("TRACELOOP_BASE_URL", "http://localhost:4318")

    with _reset_telemetry_module():
        import mcp_server.telemetry as tel
        tel._SDK_AVAILABLE = False
        with caplog.at_level(logging.WARNING, logger="mcp_server.telemetry"):
            tel.init_telemetry()

    assert any("traceloop-sdk is not installed" in r.message for r in caplog.records)


@pytest.mark.unit
def test_init_instruments_mcp_and_calls_traceloop_init(monkeypatch):
    """Validates: when endpoint is set, McpInstrumentor().instrument() and
    Traceloop.init() are both called."""
    monkeypatch.setenv("TRACELOOP_BASE_URL", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "test-svc")

    mock_traceloop_class = MagicMock()
    mock_instrumentor_class = MagicMock()
    mock_instrumentor_instance = MagicMock()
    mock_instrumentor_class.return_value = mock_instrumentor_instance

    mock_otel_mcp_mod = MagicMock()
    mock_otel_mcp_mod.McpInstrumentor = mock_instrumentor_class

    mock_traceloop_mod = MagicMock()
    mock_traceloop_mod.Traceloop = mock_traceloop_class

    with _reset_telemetry_module():
        with patch.dict("sys.modules", {
            "traceloop": MagicMock(),
            "traceloop.sdk": mock_traceloop_mod,
            "traceloop.sdk.decorators": MagicMock(),
            "opentelemetry.instrumentation.mcp": mock_otel_mcp_mod,
            "traceloop": MagicMock(),
        }):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True
            result = tel.init_telemetry()

    assert result is True
    mock_instrumentor_instance.instrument.assert_called_once()
    mock_traceloop_class.init.assert_called_once()
    _, kwargs = mock_traceloop_class.init.call_args
    assert kwargs["app_name"] == "test-svc"
    assert kwargs["api_endpoint"] == "http://localhost:4318"


@pytest.mark.unit
def test_init_idempotent(monkeypatch):
    """Validates: calling init_telemetry twice only initializes once."""
    monkeypatch.setenv("TRACELOOP_BASE_URL", "http://localhost:4318")

    mock_traceloop_class = MagicMock()
    mock_instrumentor_class = MagicMock()
    mock_instrumentor_instance = MagicMock()
    mock_instrumentor_class.return_value = mock_instrumentor_instance

    mock_otel_mcp_mod = MagicMock()
    mock_otel_mcp_mod.McpInstrumentor = mock_instrumentor_class

    mock_traceloop_mod = MagicMock()
    mock_traceloop_mod.Traceloop = mock_traceloop_class

    with _reset_telemetry_module():
        with patch.dict("sys.modules", {
            "traceloop": MagicMock(),
            "traceloop.sdk": mock_traceloop_mod,
            "traceloop.sdk.decorators": MagicMock(),
            "opentelemetry.instrumentation.mcp": mock_otel_mcp_mod,
            "traceloop": MagicMock(),
        }):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True
            tel.init_telemetry()
            tel.init_telemetry()

    assert mock_traceloop_class.init.call_count == 1


@pytest.mark.unit
def test_init_disable_batch_flag(monkeypatch):
    """Validates: OTEL_EXPORT_BATCH=false sets disable_batch=True in Traceloop.init."""
    monkeypatch.setenv("TRACELOOP_BASE_URL", "http://localhost:4318")
    monkeypatch.setenv("OTEL_EXPORT_BATCH", "false")

    mock_traceloop_class = MagicMock()
    mock_traceloop_mod = MagicMock()
    mock_traceloop_mod.Traceloop = mock_traceloop_class
    mock_otel_mcp_mod = MagicMock()
    mock_otel_mcp_mod.McpInstrumentor.return_value = MagicMock()

    with _reset_telemetry_module():
        with patch.dict("sys.modules", {
            "traceloop": MagicMock(),
            "traceloop.sdk": mock_traceloop_mod,
            "traceloop.sdk.decorators": MagicMock(),
            "opentelemetry.instrumentation.mcp": mock_otel_mcp_mod,
            "traceloop": MagicMock(),
        }):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True
            tel.init_telemetry()

    _, kwargs = mock_traceloop_class.init.call_args
    assert kwargs["disable_batch"] is True


# ---------------------------------------------------------------------------
# _truncate tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_truncate_short_value():
    """Validates: short values are returned unchanged."""
    from mcp_server.telemetry import _MAX_ATTR_LEN, _truncate
    assert _truncate("hello") == '"hello"'
    assert len(_truncate("hello")) < _MAX_ATTR_LEN


@pytest.mark.unit
def test_truncate_long_value():
    """Validates: values longer than _MAX_ATTR_LEN are capped with ellipsis."""
    from mcp_server.telemetry import _MAX_ATTR_LEN, _truncate
    long_val = "x" * 2000
    result = _truncate(long_val)
    assert len(result) <= _MAX_ATTR_LEN + 10  # small slack for the suffix
    assert result.endswith("...")


# ---------------------------------------------------------------------------
# trace_operation tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_trace_operation_noop_when_no_provider():
    """Validates: trace_operation is safe to call when no provider is configured."""
    from mcp_server.telemetry import trace_operation
    ran = []
    with trace_operation("test_op") as span:
        ran.append(True)
        # NonRecordingSpan.set_attribute is a no-op -- this must not crash
        span.set_attribute("key", "value")
    assert ran == [True]


@pytest.mark.unit
def test_trace_operation_child_span():
    """Validates: trace_operation creates a named child span when a TracerProvider
    is configured."""
    from opentelemetry import trace as otel_trace

    _, exporter, _ = _make_in_memory_setup()
    # Use a fresh provider so we can inspect spans
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter2 = InMemorySpanExporter()
    provider2 = TracerProvider()
    provider2.add_span_processor(SimpleSpanProcessor(exporter2))

    from mcp_server.telemetry import trace_operation
    with patch.object(otel_trace, "get_tracer", return_value=provider2.get_tracer("t")):
        with trace_operation("my_op", {"key": "val"}):
            pass

    spans = exporter2.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "my_op"
    assert spans[0].attributes.get("key") == '"val"'


@pytest.mark.unit
def test_trace_operation_records_exception():
    """Validates: trace_operation sets ERROR status when an exception is raised."""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import StatusCode

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    from mcp_server.telemetry import trace_operation
    with patch.object(otel_trace, "get_tracer", return_value=provider.get_tracer("t")):
        with pytest.raises(ValueError):
            with trace_operation("failing_op"):
                raise ValueError("boom")

    spans = exporter.get_finished_spans()
    assert spans[0].status.status_code == StatusCode.ERROR


# ---------------------------------------------------------------------------
# traced() decorator tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_traced_noop_when_sdk_unavailable():
    """Validates: traced() returns the original unwrapped function when SDK is absent."""
    with _reset_telemetry_module():
        import mcp_server.telemetry as tel
        tel._SDK_AVAILABLE = False

        def my_fn(x):
            return {"ok": True, "value": x}

        wrapped = tel.traced()(my_fn)
        assert wrapped is my_fn


@pytest.mark.unit
def test_traced_wraps_with_task_when_sdk_available():
    """Validates: traced() calls traceloop.sdk.decorators.task() to wrap the function."""
    mock_task_wrapped = MagicMock(return_value={"ok": True})
    mock_task = MagicMock(return_value=lambda fn: mock_task_wrapped)
    mock_decorators = MagicMock()
    mock_decorators.task = mock_task

    with _reset_telemetry_module():
        with patch.dict("sys.modules", {"traceloop.sdk.decorators": mock_decorators}):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True

            def my_fn(x: int) -> dict:
                return {"ok": True}

            wrapped = tel.traced(op_name="custom_name")(my_fn)
            wrapped(42)

    mock_task.assert_called_once_with(name="custom_name")


@pytest.mark.unit
def test_traced_marks_error_on_ok_false():
    """Validates: traced() calls _mark_current_span_error when result has ok=False."""
    mock_task_wrapped = MagicMock(return_value={"ok": False, "error": "something failed"})
    mock_task = MagicMock(return_value=lambda fn: mock_task_wrapped)
    mock_decorators = MagicMock()
    mock_decorators.task = mock_task

    with _reset_telemetry_module():
        with patch.dict("sys.modules", {"traceloop.sdk.decorators": mock_decorators}):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True

            with patch.object(tel, "_mark_current_span_error") as mock_mark:
                def my_fn() -> dict:
                    return {"ok": False, "error": "something failed"}

                wrapped = tel.traced()(my_fn)
                result = wrapped()

    mock_mark.assert_called_once_with({"ok": False, "error": "something failed"})
    assert result == {"ok": False, "error": "something failed"}


@pytest.mark.unit
def test_traced_uses_function_name_as_default_span_name():
    """Validates: traced() uses the function name when op_name is not specified."""
    mock_task = MagicMock(return_value=lambda fn: MagicMock(return_value={"ok": True}))
    mock_decorators = MagicMock()
    mock_decorators.task = mock_task

    with _reset_telemetry_module():
        with patch.dict("sys.modules", {"traceloop.sdk.decorators": mock_decorators}):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True

            def run_simulation(osm_path: str) -> dict:
                return {"ok": True}

            tel.traced()(run_simulation)

    mock_task.assert_called_once_with(name="run_simulation")
