"""OpenTelemetry tracing helpers for pipeline instrumentation."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode


_DEFAULT_SERVICE_NAME = "spec-driven-pipeline"
_INSTRUMENTATION_SCOPE = "spec_driven_dev_pipeline"
_tracer_provider: TracerProvider | None = None
_tracer = None


def _parse_otlp_headers(headers: str | None) -> dict[str, str] | None:
    if not headers:
        return None

    try:
        from opentelemetry.util.re import parse_env_headers

        parsed_headers = dict(parse_env_headers(headers, liberal=True))
    except ModuleNotFoundError:
        parsed_headers = {}
        for header in headers.split(","):
            key, _, value = header.partition("=")
            key = key.strip().lower()
            if not key:
                continue
            parsed_headers[key] = value.strip()

    return parsed_headers or None


def _build_otlp_exporter(endpoint: str, headers: str | None) -> Any:
    exporter_kwargs: dict[str, Any] = {"endpoint": endpoint}
    parsed_headers = _parse_otlp_headers(headers)
    if parsed_headers:
        exporter_kwargs["headers"] = parsed_headers

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(**exporter_kwargs)
    except ModuleNotFoundError:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(**exporter_kwargs)


def _get_tracer():
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(_INSTRUMENTATION_SCOPE)
    return _tracer


def init_tracing() -> None:
    """Initialize OTel exporter/provider when endpoint configuration exists."""
    global _tracer_provider

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    service_name = os.environ.get("OTEL_SERVICE_NAME", _DEFAULT_SERVICE_NAME)
    headers = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS")

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = _build_otlp_exporter(endpoint=endpoint, headers=headers)
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    _get_tracer()


def shutdown_tracing() -> None:
    """Flush and shutdown tracing provider if tracing was configured."""
    global _tracer_provider

    if _tracer_provider is None:
        return

    try:
        _tracer_provider.shutdown()
    finally:
        _tracer_provider = None


@contextmanager
def span(name: str, **kwargs: Any) -> Iterator[Any]:
    """Start a bounded span and mark exceptions as failures."""
    tracer = _get_tracer()
    use_noop_context = _tracer_provider is None and tracer.__class__.__module__.startswith(
        "opentelemetry."
    )
    context = (
        nullcontext(trace.get_current_span())
        if use_noop_context
        else tracer.start_as_current_span(name, **kwargs)
    )
    with context as active_span:
        try:
            yield active_span
        except Exception as exc:
            record_exception(exc, span_obj=active_span)
            raise


def set_span_attributes(**attributes: Any) -> None:
    """Set attributes on the active span."""
    if not attributes:
        return
    trace.get_current_span().set_attributes(attributes)


def record_exception(exception: BaseException, *, span_obj: Any | None = None) -> None:
    """Record an exception on a span and mark it with error status."""
    active_span = span_obj if span_obj is not None else trace.get_current_span()
    active_span.record_exception(exception)
    active_span.set_status(Status(StatusCode.ERROR, str(exception)))
