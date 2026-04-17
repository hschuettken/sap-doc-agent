"""OpenTelemetry instrumentation for Spec2Sphere.

Full tracing when OTEL_EXPORTER_OTLP_ENDPOINT is set; zero-cost no-op when not.

Instruments:
- FastAPI HTTP requests (via opentelemetry-instrumentation-fastapi)
- Celery tasks (via opentelemetry-instrumentation-celery)
- httpx outbound calls (via opentelemetry-instrumentation-httpx)
- asyncpg DB queries (via opentelemetry-instrumentation-asyncpg)
- Manual spans on LLM generate/generate_json (llm.model, llm.tier, llm.quality)
- Manual spans on scanner runs
"""

from __future__ import annotations

import functools
import logging
import os

logger = logging.getLogger(__name__)
_tracer = None


def init_telemetry(service_name: str = "spec2sphere") -> None:
    """Initialise OpenTelemetry.  No-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    try:
        from opentelemetry import trace  # noqa: PLC0415
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # noqa: PLC0415
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

        global _tracer  # noqa: PLW0603
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)
        logger.info("OpenTelemetry initialised, exporting to %s", endpoint)

        # Auto-instrument httpx (outbound LLM / DSP calls)
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor  # noqa: PLC0415

            HTTPXClientInstrumentor().instrument()
            logger.debug("OTel: httpx instrumented")
        except ImportError:
            logger.debug("opentelemetry-instrumentation-httpx not installed, skipping")

        # Auto-instrument asyncpg (DB queries)
        try:
            from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor  # noqa: PLC0415

            AsyncPGInstrumentor().instrument()
            logger.debug("OTel: asyncpg instrumented")
        except ImportError:
            logger.debug("opentelemetry-instrumentation-asyncpg not installed, skipping")

        # Auto-instrument Celery (scan tasks, chain builders)
        try:
            from opentelemetry.instrumentation.celery import CeleryInstrumentor  # noqa: PLC0415

            CeleryInstrumentor().instrument()
            logger.debug("OTel: Celery instrumented")
        except ImportError:
            logger.debug("opentelemetry-instrumentation-celery not installed, skipping")

    except ImportError:
        logger.debug("opentelemetry-sdk not installed, tracing disabled")


def instrument_fastapi(app) -> None:  # type: ignore[type-arg]
    """Attach FastAPI instrumentation to *app*.

    Must be called after init_telemetry() and after all routes are added.
    Safe to call even when tracing is disabled (becomes a no-op).
    """
    if _tracer is None:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: PLC0415

        FastAPIInstrumentor.instrument_app(app)
        logger.debug("OTel: FastAPI instrumented")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-fastapi not installed, skipping")


def get_tracer():
    """Return the active tracer, or None when tracing is disabled."""
    return _tracer


def trace_span(name: str):
    """Decorator that creates a named span when tracing is active.

    Works on both async and sync functions.
    """

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

        import asyncio  # noqa: PLC0415

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator
