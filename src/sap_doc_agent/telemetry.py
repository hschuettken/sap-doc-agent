"""OpenTelemetry skeleton — stub for Phase 3, full instrumentation deferred."""

import functools
import logging
import os

logger = logging.getLogger(__name__)
_tracer = None


def init_telemetry(service_name: str = "sap-doc-agent") -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        global _tracer
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)
        logger.info("OpenTelemetry initialized, exporting to %s", endpoint)
    except ImportError:
        logger.debug("opentelemetry-sdk not installed, tracing disabled")


def get_tracer():
    return _tracer


def trace_span(name: str):
    """Decorator that creates a span if tracing is active."""

    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if _tracer:
                with _tracer.start_as_current_span(name):
                    return await func(*args, **kwargs)
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if _tracer:
                with _tracer.start_as_current_span(name):
                    return func(*args, **kwargs)
            return func(*args, **kwargs)

        import asyncio

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator
