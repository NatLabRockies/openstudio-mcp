"""Unit tests for mcp_server.telemetry and mcp_server.otel_middleware.

These tests run without OpenStudio and without Docker.
They use an in-memory span exporter to verify span structure.

Validates:
- Telemetry is a no-op when OTEL_EXPORTER_OTLP_ENDPOINT is not set
- init_telemetry() configures a real TracerProvider when env vars are set
- OtelMiddleware creates a SERVER span per tool call
- ERROR status is set when tool result has ok=False
- Tool arguments are truncated to _MAX_ATTR_LEN chars
- trace_operation() produces a child INTERNAL span
- traced() decorator wraps a function and records ok=False as ERROR

Regression: these tests guard against the telemetry module breaking server
startup or incorrectly swallowing exceptions from tool calls.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_in_memory_setup():
    """Return (provider, exporter, tracer) using the SDK's InMemorySpanExporter.

    Each call returns a fresh isolated provider to avoid global state pollution.
    """
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    return provider, exporter, tracer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_telemetry_initialized():
    """Reset the _TELEMETRY_INITIALIZED flag before/after each test."""
    import mcp_server.telemetry as tel_mod
    original = tel_mod._TELEMETRY_INITIALIZED
    yield
    tel_mod._TELEMETRY_INITIALIZED = original


@pytest.fixture
def otel_setup():
    """Provide isolated (provider, exporter, tracer) and patch get_tracer in both modules."""
    provider, exporter, tracer = _make_in_memory_setup()
    with patch("mcp_server.telemetry.get_tracer", return_value=tracer), \
         patch("mcp_server.otel_middleware.get_tracer", return_value=tracer):
        yield provider, exporter


# ---------------------------------------------------------------------------
# init_telemetry() tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_telemetry_noop_when_no_endpoint(monkeypatch):
    """Validates: init_telemetry() returns False and leaves no provider when endpoint unset."""
    import mcp_server.telemetry as tel_mod

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    tel_mod._TELEMETRY_INITIALIZED = False

    result = tel_mod.init_telemetry()

    assert result is False
    assert tel_mod._TELEMETRY_INITIALIZED is False


@pytest.mark.unit
def test_telemetry_init_idempotent():
    """Validates: calling init_telemetry() when already initialized returns True immediately."""
    import mcp_server.telemetry as tel_mod

    tel_mod._TELEMETRY_INITIALIZED = True

    result = tel_mod.init_telemetry()

    assert result is True
    assert tel_mod._TELEMETRY_INITIALIZED is True


@pytest.mark.unit
def test_telemetry_warns_when_sdk_missing(monkeypatch, caplog):
    """Validates: warning is logged when endpoint is set but SDK is unavailable."""
    import logging

    import mcp_server.telemetry as tel_mod

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    tel_mod._TELEMETRY_INITIALIZED = False

    with patch.object(tel_mod, "_SDK_AVAILABLE", False):
        with caplog.at_level(logging.WARNING, logger="mcp_server.telemetry"):
            result = tel_mod.init_telemetry()

    assert result is False
    assert "telemetry" in caplog.text.lower() or "extras" in caplog.text.lower()


@pytest.mark.unit
def test_telemetry_init_creates_provider(monkeypatch):
    """Validates: init_telemetry() sets a TracerProvider when SDK + endpoint are available."""
    import mcp_server.telemetry as tel_mod

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "test-service")
    monkeypatch.setenv("OTEL_EXPORT_BATCH", "false")
    tel_mod._TELEMETRY_INITIALIZED = False

    # Patch the OTLP exporter so we don't make real HTTP calls, and patch
    # trace.set_tracer_provider to avoid polluting the global OTel state.
    with patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter") as mock_exp, \
         patch("opentelemetry.trace.set_tracer_provider") as mock_set:
        mock_exp.return_value = MagicMock()
        result = tel_mod.init_telemetry()

    assert result is True
    assert tel_mod._TELEMETRY_INITIALIZED is True
    mock_set.assert_called_once()


# ---------------------------------------------------------------------------
# _truncate() tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_truncate_short_value():
    """Validates: short values are returned unchanged as JSON."""
    from mcp_server.telemetry import _MAX_ATTR_LEN, _truncate

    result = _truncate({"key": "value"})
    assert len(result) <= _MAX_ATTR_LEN
    assert "value" in result


@pytest.mark.unit
def test_arg_truncation():
    """Validates: values longer than _MAX_ATTR_LEN are truncated with a '...' suffix."""
    from mcp_server.telemetry import _MAX_ATTR_LEN, _truncate

    long_value = "x" * (_MAX_ATTR_LEN + 100)
    result = _truncate(long_value)

    assert len(result) <= _MAX_ATTR_LEN + 10  # small slack for the suffix
    assert result.endswith("...")


# ---------------------------------------------------------------------------
# trace_operation() tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_trace_operation_noop_when_no_tracer():
    """Validates: trace_operation() is transparent when telemetry returns a no-op tracer."""
    from mcp_server.telemetry import trace_operation

    # No provider configured — should pass through silently
    sentinel = object()
    result = None
    with trace_operation("my_op") as span:
        result = sentinel

    assert result is sentinel


@pytest.mark.unit
def test_trace_operation_child_span(otel_setup):
    """Validates: trace_operation() creates an INTERNAL child span with correct attributes."""
    from opentelemetry.trace import SpanKind

    from mcp_server.telemetry import trace_operation

    _, exporter = otel_setup

    with trace_operation("child_op", {"key": "val"}) as span:
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    child = spans[0]
    assert child.name == "child_op"
    assert child.kind == SpanKind.INTERNAL
    # Attributes are JSON-serialized
    assert child.attributes.get("key") == '"val"'


@pytest.mark.unit
def test_trace_operation_records_exception(otel_setup):
    """Validates: exceptions inside trace_operation() are recorded on the span as ERROR."""
    from opentelemetry.trace import StatusCode

    from mcp_server.telemetry import trace_operation

    _, exporter = otel_setup

    with pytest.raises(ValueError, match="boom"):
        with trace_operation("failing_op") as span:
            raise ValueError("boom")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR


# ---------------------------------------------------------------------------
# traced() decorator tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_traced_decorator_passes_through():
    """Validates: @traced() passes arguments and return values unchanged."""
    from mcp_server.telemetry import traced

    @traced()
    def my_op(path: str, count: int = 1) -> dict:
        return {"ok": True, "path": path, "count": count}

    result = my_op("/some/path", count=3)
    assert result == {"ok": True, "path": "/some/path", "count": 3}


@pytest.mark.unit
def test_traced_decorator_records_ok_false(otel_setup):
    """Validates: @traced() marks span ERROR when function returns ok=False."""
    from opentelemetry.trace import StatusCode

    from mcp_server.telemetry import traced

    _, exporter = otel_setup

    @traced()
    def bad_op(path: str) -> dict:
        return {"ok": False, "error": "file not found"}

    result = bad_op("/missing/path")

    assert result["ok"] is False
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR
    assert spans[0].attributes.get("error.message") == "file not found"


@pytest.mark.unit
def test_traced_decorator_captures_first_arg(otel_setup):
    """Validates: @traced() records first positional arg as a span attribute."""
    from mcp_server.telemetry import traced

    _, exporter = otel_setup

    @traced()
    def do_thing(osm_path: str) -> dict:
        return {"ok": True}

    do_thing("/models/test.osm")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes.get("osm_path") == '"/models/test.osm"'


@pytest.mark.unit
def test_traced_decorator_uses_function_name(otel_setup):
    """Validates: @traced() uses the function name as the span name by default."""
    from mcp_server.telemetry import traced

    _, exporter = otel_setup

    @traced()
    def my_custom_operation(x: int) -> dict:
        return {"ok": True}

    my_custom_operation(42)

    spans = exporter.get_finished_spans()
    assert any(s.name == "my_custom_operation" for s in spans)


@pytest.mark.unit
def test_traced_decorator_custom_name(otel_setup):
    """Validates: @traced(op_name=...) overrides the span name."""
    from mcp_server.telemetry import traced

    _, exporter = otel_setup

    @traced(op_name="custom_span_name")
    def some_fn() -> dict:
        return {"ok": True}

    some_fn()

    spans = exporter.get_finished_spans()
    assert any(s.name == "custom_span_name" for s in spans)


# ---------------------------------------------------------------------------
# OtelMiddleware tests
# ---------------------------------------------------------------------------

def _make_mock_context(tool_name: str, args: dict | None = None) -> Any:
    """Build a minimal MiddlewareContext-like mock for tools/call."""
    msg = MagicMock()
    msg.name = tool_name
    msg.arguments = args or {}

    ctx = MagicMock()
    ctx.message = msg
    ctx.method = "tools/call"
    ctx.fastmcp_context = None
    return ctx


@pytest.mark.unit
def test_middleware_creates_tool_span(otel_setup):
    """Validates: OtelMiddleware.on_call_tool creates a SERVER span with correct attributes."""
    from opentelemetry.trace import SpanKind

    from mcp_server.otel_middleware import OtelMiddleware

    _, exporter = otel_setup

    middleware = OtelMiddleware()
    context = _make_mock_context("run_simulation", {"osm_path": "/test.osm"})

    mock_result = MagicMock()
    mock_result.isError = False

    async def fake_call_next(ctx):
        return mock_result

    asyncio.run(middleware.on_call_tool(context, fake_call_next))

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "run_simulation"
    assert span.kind == SpanKind.SERVER
    assert span.attributes.get("mcp.tool.name") == "run_simulation"
    assert span.attributes.get("mcp.method.name") == "tools/call"
    assert span.attributes.get("mcp.server.name") == "openstudio-mcp"
    assert span.attributes.get("mcp.tool.success") is True


@pytest.mark.unit
def test_middleware_records_error_on_ok_false(otel_setup):
    """Validates: OtelMiddleware marks span ERROR when tool result has ok=False."""
    from opentelemetry.trace import StatusCode

    from mcp_server.otel_middleware import OtelMiddleware

    _, exporter = otel_setup

    middleware = OtelMiddleware()
    context = _make_mock_context("load_osm_model", {"osm_path": "/missing.osm"})

    async def fake_call_next(ctx):
        return {"ok": False, "error": "file not found"}

    asyncio.run(middleware.on_call_tool(context, fake_call_next))

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes.get("mcp.tool.success") is False
    assert span.status.status_code == StatusCode.ERROR
    assert "file not found" in span.attributes.get("error.message", "")


@pytest.mark.unit
def test_middleware_records_exception(otel_setup):
    """Validates: OtelMiddleware records exceptions raised by tools as span errors."""
    from opentelemetry.trace import StatusCode

    from mcp_server.otel_middleware import OtelMiddleware

    _, exporter = otel_setup

    middleware = OtelMiddleware()
    context = _make_mock_context("some_tool")

    async def fake_call_next(ctx):
        raise RuntimeError("unexpected crash")

    with pytest.raises(RuntimeError, match="unexpected crash"):
        asyncio.run(middleware.on_call_tool(context, fake_call_next))

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR
    assert spans[0].attributes.get("mcp.tool.success") is False


@pytest.mark.unit
def test_middleware_arg_truncation(otel_setup):
    """Validates: tool arguments longer than 512 chars are truncated in span attributes."""
    from mcp_server.otel_middleware import OtelMiddleware
    from mcp_server.telemetry import _MAX_ATTR_LEN

    _, exporter = otel_setup

    middleware = OtelMiddleware()
    huge_args = {"data": "A" * 2000}
    context = _make_mock_context("some_tool", huge_args)

    async def fake_call_next(ctx):
        return {"ok": True}

    asyncio.run(middleware.on_call_tool(context, fake_call_next))

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    tool_args_attr = spans[0].attributes.get("mcp.tool.args", "")
    assert len(tool_args_attr) <= _MAX_ATTR_LEN + 10  # small slack for "..."

