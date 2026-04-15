"""Unit tests for mcp_server/telemetry.py (OpenLLMetry / traceloop-sdk integration).

These tests run without OpenStudio and without Docker.

Validates:
- Telemetry is a no-op when TRACELOOP_BASE_URL is not set
- init_telemetry() calls McpInstrumentor().instrument() and Traceloop.init()
- init_telemetry() is idempotent and returns correct value on second call
- McpInstrumentor is only called when endpoint is configured
- traced() is a no-op when telemetry is not enabled
- traced() creates a span and marks ERROR on ok=False when telemetry is enabled
- trace_operation() creates a child span when a TracerProvider is configured
- _truncate() caps values at _MAX_ATTR_LEN
- sys.stdout is restored even when Traceloop.init() raises
- init_telemetry() handles Traceloop.init() exceptions gracefully

Regression: these tests guard against the telemetry module breaking server
startup or silently swallowing init errors.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

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
    """Validates: init_telemetry returns False when TRACELOOP_BASE_URL is unset,
    and does NOT call McpInstrumentor or Traceloop.init."""
    monkeypatch.delenv("TRACELOOP_BASE_URL", raising=False)

    mock_traceloop = MagicMock()
    mock_instrumentor = MagicMock()

    with _reset_telemetry_module():
        with patch.dict("sys.modules", {
            "traceloop": MagicMock(),
            "traceloop.sdk": mock_traceloop,
            "traceloop.sdk.decorators": MagicMock(),
            "opentelemetry.instrumentation.mcp": mock_instrumentor,
        }):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True
            result = tel.init_telemetry()

    assert result is False
    mock_traceloop.Traceloop.init.assert_not_called()
    # McpInstrumentor should NOT be called when no endpoint is set
    mock_instrumentor.McpInstrumentor.assert_not_called()


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
        }):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True
            r1 = tel.init_telemetry()
            r2 = tel.init_telemetry()

    assert mock_traceloop_class.init.call_count == 1
    assert r1 is True
    assert r2 is True


@pytest.mark.unit
def test_init_idempotent_returns_false_when_disabled(monkeypatch):
    """Validates: second call returns False (not True) when first call disabled telemetry."""
    monkeypatch.delenv("TRACELOOP_BASE_URL", raising=False)

    with _reset_telemetry_module():
        import mcp_server.telemetry as tel
        tel._SDK_AVAILABLE = True
        r1 = tel.init_telemetry()
        r2 = tel.init_telemetry()

    assert r1 is False
    assert r2 is False


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
        }):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True
            tel.init_telemetry()

    _, kwargs = mock_traceloop_class.init.call_args
    assert kwargs["disable_batch"] is True


@pytest.mark.unit
def test_init_restores_stdout_on_exception(monkeypatch):
    """Validates: sys.stdout is restored even when Traceloop.init() raises."""
    monkeypatch.setenv("TRACELOOP_BASE_URL", "http://localhost:4318")

    mock_traceloop_class = MagicMock()
    mock_traceloop_class.init.side_effect = RuntimeError("init boom")
    mock_traceloop_mod = MagicMock()
    mock_traceloop_mod.Traceloop = mock_traceloop_class
    mock_otel_mcp_mod = MagicMock()
    mock_otel_mcp_mod.McpInstrumentor.return_value = MagicMock()

    original_stdout = sys.stdout

    with _reset_telemetry_module():
        with patch.dict("sys.modules", {
            "traceloop": MagicMock(),
            "traceloop.sdk": mock_traceloop_mod,
            "traceloop.sdk.decorators": MagicMock(),
            "opentelemetry.instrumentation.mcp": mock_otel_mcp_mod,
        }):
            import mcp_server.telemetry as tel
            tel._SDK_AVAILABLE = True
            result = tel.init_telemetry()

    assert result is False
    assert sys.stdout is original_stdout


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
def test_trace_operation_noop_span_on_import_error():
    """Validates: trace_operation yields a _NoopSpan when opentelemetry is absent.

    Regression: trace_operation() must not raise ImportError in production
    environments where dev extras (opentelemetry-api) are not installed.
    """
    import sys

    from mcp_server.telemetry import _NoopSpan, trace_operation

    # Simulate opentelemetry being absent
    otel_keys = {"opentelemetry", "opentelemetry.trace"}
    with patch.dict(sys.modules, dict.fromkeys(otel_keys, None)):
        ran = []
        with trace_operation("test_noop") as span:
            ran.append(True)
            assert isinstance(span, _NoopSpan)
            span.set_attribute("key", "value")
            span.set_status("ok")
            span.record_exception(None)
        assert ran == [True]


@pytest.mark.unit
def test_trace_operation_child_span():
    """Validates: trace_operation creates a named child span when a TracerProvider
    is configured."""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    from mcp_server.telemetry import trace_operation
    with patch.object(otel_trace, "get_tracer", return_value=provider.get_tracer("t")):
        with trace_operation("my_op", {"key": "val"}):
            pass

    spans = exporter.get_finished_spans()
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
def test_traced_noop_when_telemetry_disabled():
    """Validates: traced() wrapper calls the original function directly when
    _TELEMETRY_ENABLED is False (SDK installed but no endpoint configured)."""
    with _reset_telemetry_module():
        import mcp_server.telemetry as tel
        tel._TELEMETRY_ENABLED = False

        call_log: list[str] = []

        def my_fn(x: int) -> dict:
            call_log.append("called")
            return {"ok": True, "value": x}

        wrapped = tel.traced()(my_fn)
        result = wrapped(42)

    assert result == {"ok": True, "value": 42}
    assert call_log == ["called"]


@pytest.mark.unit
def test_traced_creates_span_when_enabled():
    """Validates: traced() creates a span via trace_operation when _TELEMETRY_ENABLED
    is True."""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with _reset_telemetry_module():
        import mcp_server.telemetry as tel
        tel._TELEMETRY_ENABLED = True

        @tel.traced(op_name="custom_name")
        def my_fn() -> dict:
            return {"ok": True}

        with patch.object(otel_trace, "get_tracer", return_value=provider.get_tracer("t")):
            result = my_fn()

    assert result == {"ok": True}
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "custom_name"


@pytest.mark.unit
def test_traced_marks_error_on_ok_false():
    """Validates: traced() marks the span ERROR when result has ok=False."""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import StatusCode

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with _reset_telemetry_module():
        import mcp_server.telemetry as tel
        tel._TELEMETRY_ENABLED = True

        @tel.traced()
        def failing_op() -> dict:
            return {"ok": False, "error": "something failed"}

        with patch.object(otel_trace, "get_tracer", return_value=provider.get_tracer("t")):
            result = failing_op()

    assert result == {"ok": False, "error": "something failed"}
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR
    assert spans[0].attributes.get("error.message") == "something failed"


@pytest.mark.unit
def test_traced_uses_function_name_as_default_span_name():
    """Validates: traced() uses the function name when op_name is not specified."""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with _reset_telemetry_module():
        import mcp_server.telemetry as tel
        tel._TELEMETRY_ENABLED = True

        @tel.traced()
        def run_simulation(osm_path: str) -> dict:
            return {"ok": True}

        with patch.object(otel_trace, "get_tracer", return_value=provider.get_tracer("t")):
            run_simulation("/tmp/test.osm")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "run_simulation"
