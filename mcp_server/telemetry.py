"""OpenTelemetry / OpenLlmetry integration for the openstudio-mcp server.

Telemetry is opt-in: a no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set.
The opentelemetry-api package (transitively installed via fastmcp) provides
no-op stubs when no SDK is configured, so this module is safe to import
even when the [telemetry] extras are not installed.

Environment variables:
    OTEL_EXPORTER_OTLP_ENDPOINT  OTLP HTTP endpoint, e.g. http://localhost:4318
                                  Unset -> telemetry disabled (no-op).
    OTEL_SERVICE_NAME             Span service name. Default: "openstudio-mcp".
    OTEL_SERVICE_VERSION          Span service version. Default: package version.
    OTEL_EXPORT_BATCH             "false" -> SimpleSpanProcessor (sync, for dev).
                                  Any other value / unset -> BatchSpanProcessor.
    OTEL_RESOURCE_ATTRIBUTES      Extra resource attributes (standard OTEL passthrough).

Usage:
    from mcp_server.telemetry import init_telemetry, get_tracer, trace_operation, traced

    # In main():
    init_telemetry()

    # Decorate a key operation (minimal diff -- no re-indenting):
    @traced()
    def run_simulation(osm_path, ...):
        ...

    # Or use as a context manager for more control:
    with trace_operation("my_op", {"key": value}) as span:
        result = do_work()
        span.set_attribute("run_id", result["run_id"])
"""
from __future__ import annotations

import functools
import importlib.util
import inspect
import json
import logging
from contextlib import contextmanager
from typing import Any, Callable, Generator, TypeVar

from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, Span, SpanKind, StatusCode

logger = logging.getLogger(__name__)

_TELEMETRY_INITIALIZED = False
_SDK_AVAILABLE = importlib.util.find_spec("opentelemetry.sdk") is not None

# Max bytes for any single span attribute value (args, results, etc.)
_MAX_ATTR_LEN = 512

F = TypeVar("F", bound=Callable[..., Any])


def _truncate(value: Any) -> str:
    """Serialize a value to a JSON string, capped at _MAX_ATTR_LEN chars."""
    try:
        s = json.dumps(value, default=str)
    except Exception:
        s = str(value)
    if len(s) > _MAX_ATTR_LEN:
        return s[:_MAX_ATTR_LEN] + "..."
    return s


def init_telemetry() -> bool:
    """Initialize the OpenTelemetry TracerProvider with an OTLP HTTP exporter.

    Returns True if telemetry was configured, False if disabled (no endpoint set
    or SDK not installed).  Idempotent -- safe to call multiple times.
    """
    global _TELEMETRY_INITIALIZED

    if _TELEMETRY_INITIALIZED:
        return True

    import os

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        logger.debug("OTEL_EXPORTER_OTLP_ENDPOINT not set -- telemetry disabled")
        return False

    if not _SDK_AVAILABLE:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but opentelemetry-sdk is not installed. "
            "Install the [telemetry] extras: pip install 'openstudio-mcp[telemetry]'"
        )
        return False

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import (
            SERVICE_NAME,
            SERVICE_VERSION,
            Resource,
        )
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
        )

        from mcp_server.version import __version__

        service_name = os.environ.get("OTEL_SERVICE_NAME", "openstudio-mcp")
        service_version = os.environ.get("OTEL_SERVICE_VERSION", __version__)

        resource = Resource.create(
            {
                SERVICE_NAME: service_name,
                SERVICE_VERSION: service_version,
            }
        )

        provider = TracerProvider(resource=resource)

        # Normalize endpoint: OTLPSpanExporter expects the traces path
        traces_endpoint = endpoint.rstrip("/") + "/v1/traces"
        exporter = OTLPSpanExporter(endpoint=traces_endpoint)

        use_batch = os.environ.get("OTEL_EXPORT_BATCH", "true").lower() != "false"
        processor = BatchSpanProcessor(exporter) if use_batch else SimpleSpanProcessor(exporter)
        provider.add_span_processor(processor)

        trace.set_tracer_provider(provider)
        _TELEMETRY_INITIALIZED = True
        logger.info(
            "OpenTelemetry telemetry enabled: endpoint=%s service=%s version=%s batch=%s",
            endpoint,
            service_name,
            service_version,
            use_batch,
        )
        return True

    except Exception:
        logger.exception("Failed to initialize OpenTelemetry -- telemetry disabled")
        return False


def get_tracer() -> trace.Tracer:
    """Return the openstudio-mcp tracer.

    Returns a no-op tracer when telemetry is not initialized.
    """
    return trace.get_tracer("openstudio-mcp")


@contextmanager
def trace_operation(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Generator[Span, None, None]:
    """Context manager that wraps a block in a child OTel span.

    No-op (passes through) when telemetry is disabled.

    Args:
        name: Span name, e.g. "run_simulation".
        attributes: Optional dict of initial span attributes (values truncated).

    Yields:
        The active Span so callers can add attributes mid-execution.

    Example::

        with trace_operation("apply_measure", {"measure_dir": measure_dir}) as span:
            result = _do_apply(...)
            span.set_attribute("ok", result.get("ok", False))
    """
    tracer = get_tracer()
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
    """Decorator that wraps a synchronous operation function in a child OTel span.

    Captures the first positional argument as an attribute and marks the span
    ERROR when the function returns a dict with ``ok=False``.  No-op when
    telemetry is disabled.

    Args:
        op_name: Override for the span name. Defaults to the function name.

    Example::

        @traced()
        def run_simulation(osm_path: str, ...) -> dict:
            ...
    """
    def decorator(fn: F) -> F:
        name = op_name or fn.__name__
        sig = inspect.signature(fn)
        param_names = list(sig.parameters.keys())

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attrs: dict[str, Any] = {}
            # Include first positional arg (usually the primary input path/name)
            if param_names and args:
                attrs[param_names[0]] = args[0]
            elif param_names and param_names[0] in kwargs:
                attrs[param_names[0]] = kwargs[param_names[0]]

            with trace_operation(name, attrs) as span:
                result = fn(*args, **kwargs)
                if isinstance(result, dict) and result.get("ok") is False:
                    record_tool_error(span, result)
                return result

        return wrapper  # type: ignore[return-value]

    return decorator


def record_tool_error(span: Span, result: dict[str, Any]) -> None:
    """Mark a span as failed based on an operation result dict with ok=False."""
    if isinstance(span, NonRecordingSpan):
        return
    error_msg = result.get("error") or result.get("message") or "tool returned ok=False"
    span.set_status(StatusCode.ERROR, error_msg)
    span.set_attribute("error.message", str(error_msg)[:_MAX_ATTR_LEN])
