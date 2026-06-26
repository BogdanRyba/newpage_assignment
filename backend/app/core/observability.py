"""OpenTelemetry tracing setup (harness component 2, observability).

Self-contained by default: a console span exporter, no external collector or key. If
`OTEL_EXPORTER_OTLP_ENDPOINT` is set we also export OTLP. `instrument()` creates spans via the
global tracer, which is a no-op until this runs — so importing it is always safe.
"""

from __future__ import annotations

import os

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("otel")
_configured = False


def setup_tracing(service_name: str = "ariadne") -> None:
    global _configured
    if _configured or not get_settings().otel_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        else:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        _configured = True
        log.info("otel_configured", service=service_name)
    except Exception as exc:  # pragma: no cover - tracing must never break the app
        log.info("otel_setup_skipped", error=str(exc))
