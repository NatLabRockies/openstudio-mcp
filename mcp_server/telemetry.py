"""OpenLLMetry (Traceloop) tracing for the openstudio-mcp server.

Dev-only: a no-op unless traceloop-sdk is installed (included in [dev] extras).
Zero overhead in production: no import errors, all calls become pass-throughs.

Environment variables:
    TRACELOOP_BASE_URL    OTLP / Traceloop-compatible endpoint, e.g.:
                            http://localhost:4318  (local OTEL collector)
                            https://api.traceloop.com  (Traceloop cloud, needs API key)
                          Unset -> telemetry disabled (no-op).
    TRACELOOP_API_KEY     API key for Traceloop cloud (not required for generic OTLP).
    OTEL_SERVICE_NAME     Service name emitted on every span. Default: "openstudio-mcp".
    OTEL_EXPORT_BATCH     "false" -> sync exporting (dev). Default: batch mode.
    TRACELOOP_TRACE_CONTENT  "false" -> omit tool args from spans (privacy).

Usage:
    from mcp_server.telemetry import init_telemetry, trace_operation, traced

    # In main() before mcp.run():
    init_telemetry()

    # Decorate a key operation:
    @traced()
    def run_simulation(osm_path: str, ...) -> dict: ...

    # Or use a context manager for finer control:
    with trace_operation("prepare_model", {"path": osm_path}) as span:
        result = do_work()
"""
from __future__ import annotations

import importlib.util
import json
import logging
import sys
from contextlib import contextmanager
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

_TELEMETRY_INITIALIZED = False
# True only after Traceloop.init() succeeds with a valid endpoint.
# traced() checks this at call time to avoid traceloop stdout warnings.
_TELEMETRY_ENABLED = False
try:
    _SDK_AVAILABLE = importlib.util.find_spec("traceloop.sdk") is not None
except (ModuleNotFoundError, ValueError):
    _SDK_AVAILABLE = False

# Max chars for any single span attribute value.
_MAX_ATTR_LEN = 512

F = TypeVar("F", bound=Callable[..., Any])


def init_telemetry() -> bool:
    """Initialize OpenLLMetry tracing.  Idempotent — safe to call multiple times.

    Returns True if telemetry was enabled, False otherwise (SDK absent, no endpoint).
    When the SDK is installed and an endpoint is configured, calls
    McpInstrumentor().instrument() to auto-trace every FastMCP tool call and
    Traceloop.init() to configure the OTLP exporter.
    """
    global _TELEMETRY_INITIALIZED, _TELEMETRY_ENABLED

    if _TELEMETRY_INITIALIZED:
        return _TELEMETRY_ENABLED

    import os

    if not _SDK_AVAILABLE:
        endpoint = os.environ.get("TRACELOOP_BASE_URL", "").strip()
        if endpoint:
            logger.warning(
                "TRACELOOP_BASE_URL is set but traceloop-sdk is not installed. "
                "Install dev extras: pip install 'openstudio-mcp[dev]'"
            )
        _TELEMETRY_INITIALIZED = True
        return False

    endpoint = os.environ.get("TRACELOOP_BASE_URL", "").strip()
    if not endpoint:
        logger.debug("TRACELOOP_BASE_URL not set -- telemetry disabled")
        _TELEMETRY_INITIALIZED = True
        return False

    try:
        from opentelemetry.instrumentation.mcp import McpInstrumentor
        from traceloop.sdk import Traceloop

        service_name = os.environ.get("OTEL_SERVICE_NAME", "openstudio-mcp")
        disable_batch = os.environ.get("OTEL_EXPORT_BATCH", "true").lower() == "false"

        # Initialize Traceloop FIRST so its TracerProvider is live before we
        # patch FastMCP.  McpInstrumentor wraps FastMCP tool calls; if the
        # provider isn't established yet those spans have nowhere to go.
        # Traceloop.init() uses print() for status messages — redirect sys.stdout
        # to stderr to avoid corrupting the MCP JSON-RPC stdio pipe.
        _orig_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            Traceloop.init(
                app_name=service_name,
                api_endpoint=endpoint,
                disable_batch=disable_batch,
            )
        finally:
            sys.stdout = _orig_stdout

        # Patch FastMCP AFTER the provider is live so auto-traced tool calls
        # have a real exporter destination.
        McpInstrumentor().instrument()

        _TELEMETRY_INITIALIZED = True
        _TELEMETRY_ENABLED = True
        logger.info(
            "OpenLLMetry enabled: endpoint=%s service=%s batch=%s",
            endpoint,
            service_name,
            not disable_batch,
        )
        return True

    except Exception:
        logger.exception("Failed to initialize OpenLLMetry -- telemetry disabled")
        _TELEMETRY_INITIALIZED = True
        return False


@contextmanager
def trace_operation(name: str, attributes: dict[str, Any] | None = None):
    """Context manager that wraps a block in a child INTERNAL span.

    Uses the active OpenTelemetry TracerProvider (configured by Traceloop.init()).
    Falls back to OTel API no-op tracer when telemetry is not configured — safe to
    use unconditionally.

    Args:
        name: Span name, e.g. "prepare_model".
        attributes: Optional initial attributes (values truncated to _MAX_ATTR_LEN).

    Yields:
        The active Span (may be a NonRecordingSpan when telemetry is off).

    Example::

        with trace_operation("apply_measure", {"measure_dir": measure_dir}) as span:
            result = _do_apply(...)
            span.set_attribute("ok", str(result.get("ok", False)))
    """
    from opentelemetry import trace
    from opentelemetry.trace import NonRecordingSpan, SpanKind, StatusCode

    tracer = trace.get_tracer("openstudio-mcp")
    with tracer.start_as_current_span(name, kind=SpanKind.INTERNAL) as span:
        if not isinstance(span, NonRecordingSpan) and attributes:
            for key, val in attributes.items():
                span.set_attribute(key, _truncate(val))
        try:
            yield span
        except Exception as exc:
            if not isinstance(span, NonRecordingSpan):
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, str(exc))
            raise


def traced(op_name: str | None = None) -> Callable[[F], F]:
    """Decorator that wraps a synchronous operation in a trace span.

    Uses trace_operation() context manager to create a span.  Only active when
    telemetry has been successfully enabled via init_telemetry().  This avoids
    traceloop stdout warnings when the SDK is installed but no endpoint is set.

    Marks the span ERROR when the function returns a dict with ok=False.

    Args:
        op_name: Span name override.  Defaults to the function name.

    Example::

        @traced()
        def run_simulation(osm_path: str, ...) -> dict: ...
    """
    import functools

    def decorator(fn: F) -> F:
        span_name = op_name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _TELEMETRY_ENABLED:
                return fn(*args, **kwargs)

            with trace_operation(span_name) as span:
                result = fn(*args, **kwargs)
                if isinstance(result, dict) and result.get("ok") is False:
                    _mark_span_error(span, result)
                return result

        return wrapper  # type: ignore[return-value]

    return decorator


def _mark_span_error(span: Any, result: dict[str, Any]) -> None:
    """Set ERROR status on the given span."""
    try:
        from opentelemetry.trace import NonRecordingSpan, StatusCode

        if isinstance(span, NonRecordingSpan):
            return
        error_msg = result.get("error") or result.get("message") or "tool returned ok=False"
        span.set_status(StatusCode.ERROR, str(error_msg))
        span.set_attribute("error.message", str(error_msg)[:_MAX_ATTR_LEN])
    except Exception:
        pass


def _truncate(value: Any) -> str:
    """Serialize a value to a JSON string capped at _MAX_ATTR_LEN chars."""
    try:
        s = json.dumps(value, default=str)
    except Exception:
        s = str(value)
    if len(s) > _MAX_ATTR_LEN:
        return s[:_MAX_ATTR_LEN] + "..."
    return s

