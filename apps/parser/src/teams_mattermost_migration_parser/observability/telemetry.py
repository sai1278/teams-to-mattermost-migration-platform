"""OpenTelemetry instrumentation setup for parser tracing."""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

LOGGER = logging.getLogger(__name__)

# Global flag to track if telemetry is initialized
_TELEMETRY_INITIALIZED = False


def setup_telemetry(service_name: str, enabled: bool = True) -> None:
    """Initialize OpenTelemetry tracer provider and register exporters."""
    global _TELEMETRY_INITIALIZED
    if _TELEMETRY_INITIALIZED:
        return

    if not enabled:
        _TELEMETRY_INITIALIZED = True
        return

    try:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        # By default, export spans to stdout in JSON-like console format
        exporter = ConsoleSpanExporter()
        processor = SimpleSpanProcessor(exporter)
        provider.add_span_processor(processor)

        trace.set_tracer_provider(provider)
        _TELEMETRY_INITIALIZED = True
        LOGGER.info(
            "OpenTelemetry telemetry initialized successfully",
            extra={
                "event": "telemetry_initialized",
                "details": {"service_name": service_name},
            },
        )
    except Exception as exc:
        LOGGER.warning(
            f"Failed to initialize OpenTelemetry tracing: {exc}",
            extra={
                "event": "telemetry_initialization_failed",
                "details": {"error": str(exc)},
            },
        )
