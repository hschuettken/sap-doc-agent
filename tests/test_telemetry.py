"""Tests for OpenTelemetry instrumentation in spec2sphere.telemetry."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


def _reload_telemetry():
    """Reload telemetry module so that module-level state (_tracer) is reset."""
    import spec2sphere.telemetry as _tel

    # Reset the module-level tracer before each test
    _tel._tracer = None
    return _tel


class TestInitTelemetryNoOp:
    """init_telemetry() must be a complete no-op when the env var is absent."""

    def test_no_env_var_tracer_is_none(self):
        tel = _reload_telemetry()
        env = {k: v for k, v in os.environ.items() if k != "OTEL_EXPORTER_OTLP_ENDPOINT"}
        with patch.dict(os.environ, env, clear=True):
            tel.init_telemetry()
        assert tel._tracer is None

    def test_get_tracer_returns_none_without_init(self):
        tel = _reload_telemetry()
        assert tel.get_tracer() is None

    def test_no_import_error_when_sdk_missing(self, monkeypatch):
        """init_telemetry must not raise even if opentelemetry-sdk is not installed."""
        tel = _reload_telemetry()
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        # Should complete without exception
        tel.init_telemetry()
        assert tel._tracer is None


class TestInitTelemetryWithEndpoint:
    """init_telemetry() sets _tracer when endpoint is configured and SDK is present."""

    def test_tracer_set_when_endpoint_configured(self, monkeypatch):
        tel = _reload_telemetry()

        # Build lightweight mocks for the SDK objects
        mock_tracer = MagicMock()
        mock_provider = MagicMock()
        mock_trace_module = MagicMock()
        mock_trace_module.get_tracer.return_value = mock_tracer

        mock_resource_cls = MagicMock()
        mock_resource_cls.create.return_value = MagicMock()

        mock_provider_cls = MagicMock(return_value=mock_provider)
        mock_exporter = MagicMock()
        mock_processor = MagicMock()

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

        with (
            patch.dict(
                "sys.modules",
                {
                    "opentelemetry": MagicMock(trace=mock_trace_module),
                    "opentelemetry.trace": mock_trace_module,
                    "opentelemetry.sdk.trace": MagicMock(TracerProvider=mock_provider_cls),
                    "opentelemetry.sdk.trace.export": MagicMock(
                        BatchSpanProcessor=MagicMock(return_value=mock_processor)
                    ),
                    "opentelemetry.sdk.resources": MagicMock(Resource=mock_resource_cls),
                    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": MagicMock(
                        OTLPSpanExporter=MagicMock(return_value=mock_exporter)
                    ),
                    # Instrumentation packages may or may not be present — simulate absent
                    "opentelemetry.instrumentation.httpx": None,
                    "opentelemetry.instrumentation.asyncpg": None,
                    "opentelemetry.instrumentation.celery": None,
                    "opentelemetry.instrumentation.fastapi": None,
                },
            ),
        ):
            tel.init_telemetry("test-service")

        assert tel._tracer is mock_tracer
        mock_trace_module.get_tracer.assert_called_once_with("test-service")

    def test_import_error_in_sdk_leaves_tracer_none(self, monkeypatch):
        """If opentelemetry-sdk is not importable at all, _tracer must stay None."""
        tel = _reload_telemetry()
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _block_opentelemetry(name, *args, **kwargs):
            if name.startswith("opentelemetry"):
                raise ImportError(f"mocked missing: {name}")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_block_opentelemetry):
            tel.init_telemetry()

        assert tel._tracer is None


class TestInstrumentFastapi:
    """instrument_fastapi() is a no-op when _tracer is None."""

    def test_no_op_without_tracer(self):
        tel = _reload_telemetry()
        mock_app = MagicMock()
        # Should not raise, should not call anything on app
        tel.instrument_fastapi(mock_app)
        mock_app.assert_not_called()

    def test_calls_instrumentor_when_tracer_set(self, monkeypatch):
        tel = _reload_telemetry()
        tel._tracer = MagicMock()  # Pretend tracing is active

        mock_instrumentor_cls = MagicMock()
        mock_instrumentor_instance = MagicMock()
        mock_instrumentor_cls.return_value = mock_instrumentor_instance

        with patch.dict(
            "sys.modules",
            {
                "opentelemetry.instrumentation.fastapi": MagicMock(FastAPIInstrumentor=mock_instrumentor_cls),
            },
        ):
            mock_app = MagicMock()
            tel.instrument_fastapi(mock_app)

        mock_instrumentor_cls.instrument_app.assert_called_once_with(mock_app)


class TestTraceSpanDecorator:
    """trace_span decorator works correctly in both no-tracer and active-tracer modes."""

    def test_async_function_called_without_tracer(self):
        import asyncio

        tel = _reload_telemetry()

        @tel.trace_span("test.span")
        async def my_coro():
            return 42

        result = asyncio.get_event_loop().run_until_complete(my_coro())
        assert result == 42

    def test_sync_function_called_without_tracer(self):
        tel = _reload_telemetry()

        @tel.trace_span("test.sync_span")
        def my_func():
            return "hello"

        assert my_func() == "hello"

    def test_async_function_wrapped_with_active_tracer(self):
        import asyncio

        tel = _reload_telemetry()
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span
        tel._tracer = mock_tracer

        @tel.trace_span("test.active_span")
        async def my_coro():
            return 99

        result = asyncio.get_event_loop().run_until_complete(my_coro())
        assert result == 99
        mock_tracer.start_as_current_span.assert_called_once_with("test.active_span")
