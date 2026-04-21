"""Behavioral tests for the tracing init module."""

from __future__ import annotations

import importlib
import sys
import time

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider as RealTracerProvider
from opentelemetry.sdk.trace import export as sdk_export
import opentelemetry.sdk.trace as sdk_trace
from opentelemetry.trace import StatusCode


MODULE_NAME = "spec_driven_dev_pipeline.utils.tracing"
OTLP_EXPORTER_MODULES = (
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
)


class FakeSpan:
    """Captures span interactions without requiring a real SDK span."""

    def __init__(self) -> None:
        self.attributes: list[tuple[str, object]] = []
        self.recorded_exceptions: list[BaseException] = []
        self.statuses: list[object] = []

    def set_attribute(self, key, value, *args, **kwargs):  # noqa: ANN001
        self.attributes.append((key, value))

    def set_attributes(self, attributes, *args, **kwargs):  # noqa: ANN001
        if hasattr(attributes, "items"):
            items = attributes.items()
        else:
            items = attributes
        for key, value in items:
            self.attributes.append((key, value))

    def record_exception(self, exception, *args, **kwargs):  # noqa: ANN001
        self.recorded_exceptions.append(exception)

    def set_status(self, status, *args, **kwargs):  # noqa: ANN001
        self.statuses.append(status)


class FakeSpanContextManager:
    """Yields a fake span without adding exception-recording behavior."""

    def __init__(self, span: FakeSpan) -> None:
        self.span = span

    def __enter__(self):
        return self.span

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


class FakeTracer:
    """Tracer double that exposes a span object to bounded-span helpers."""

    def __init__(self, span: FakeSpan | None = None) -> None:
        self.span = span or FakeSpan()
        self.started_spans: list[tuple[tuple, dict]] = []

    def start_as_current_span(self, *args, **kwargs):  # noqa: ANN001
        self.started_spans.append((args, kwargs))
        return FakeSpanContextManager(self.span)

    def start_span(self, *args, **kwargs):  # noqa: ANN001
        self.started_spans.append((args, kwargs))
        return self.span


class FakeExporter:
    """Records OTLP exporter construction and shutdown."""

    instances: list["FakeExporter"] = []

    def __init__(self, *args, **kwargs):  # noqa: ANN001
        self.args = args
        self.kwargs = kwargs
        self.shutdown_called = False
        self.__class__.instances.append(self)

    def shutdown(self):
        self.shutdown_called = True


class FakeBatchSpanProcessor(sdk_trace.SpanProcessor):
    """Records exporter wiring and shutdown propagation."""

    instances: list["FakeBatchSpanProcessor"] = []

    def __init__(self, span_exporter, *args, **kwargs):  # noqa: ANN001
        self.span_exporter = span_exporter
        self.args = args
        self.kwargs = kwargs
        self.ended_spans: list[object] = []
        self.flushed_spans: list[object] = []
        self.force_flush_called = False
        self.shutdown_called = False
        self.__class__.instances.append(self)

    def on_start(self, span, parent_context=None):  # noqa: ANN001
        return None

    def on_end(self, span):
        self.ended_spans.append(span)

    def force_flush(self, timeout_millis=30000):  # noqa: ANN001
        self.force_flush_called = True
        self.flushed_spans = list(self.ended_spans)
        return True

    def shutdown(self):
        self.shutdown_called = True
        self.flushed_spans = list(self.ended_spans)
        self.span_exporter.shutdown()


class FakeTracerProvider(RealTracerProvider):
    """Tracer provider that tracks processors and shutdown calls."""

    instances: list["FakeTracerProvider"] = []

    def __init__(self, *args, **kwargs):  # noqa: ANN001
        self.added_span_processors: list[object] = []
        self.shutdown_called = False
        super().__init__(*args, **kwargs)
        self.__class__.instances.append(self)

    def add_span_processor(self, processor):
        self.added_span_processors.append(processor)
        return super().add_span_processor(processor)

    def shutdown(self):
        self.shutdown_called = True
        return super().shutdown()


def _iter_text_fragments(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield from _iter_text_fragments(key)
            yield from _iter_text_fragments(nested)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _iter_text_fragments(item)
    else:
        yield str(value)


def _observes_text(observation, expected: str) -> bool:
    return any(expected in fragment for fragment in _iter_text_fragments(observation))


def _import_tracing(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current_span: FakeSpan | None = None,
    tracer: FakeTracer | None = None,
    tracer_calls: list[tuple[tuple, dict]] | None = None,
):
    FakeExporter.instances = []
    FakeBatchSpanProcessor.instances = []
    FakeTracerProvider.instances = []

    captured_provider: dict[str, object | None] = {"value": None}
    original_get_tracer_provider = otel_trace.get_tracer_provider
    original_get_tracer = otel_trace.get_tracer

    def capture_provider(provider):
        captured_provider["value"] = provider

    def get_tracer_provider():
        return captured_provider["value"] or original_get_tracer_provider()

    def get_tracer(*args, **kwargs):  # noqa: ANN001
        if tracer_calls is not None:
            tracer_calls.append((args, kwargs))
        if tracer is not None:
            return tracer
        return original_get_tracer(*args, **kwargs)

    monkeypatch.setattr(otel_trace, "set_tracer_provider", capture_provider)
    monkeypatch.setattr(otel_trace, "get_tracer_provider", get_tracer_provider)
    monkeypatch.setattr(otel_trace, "get_tracer", get_tracer)
    if tracer is not None:
        monkeypatch.setattr(
            otel_trace,
            "use_span",
            lambda span, *args, **kwargs: FakeSpanContextManager(span),
        )
    if current_span is not None:
        monkeypatch.setattr(otel_trace, "get_current_span", lambda: current_span)
    monkeypatch.setattr(sdk_trace, "TracerProvider", FakeTracerProvider)
    monkeypatch.setattr(sdk_export, "BatchSpanProcessor", FakeBatchSpanProcessor)

    # Patch every supported OTLP transport module so the test stays protocol-neutral.
    for module_name in OTLP_EXPORTER_MODULES:
        try:
            otlp_exporter = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        monkeypatch.setattr(otlp_exporter, "OTLPSpanExporter", FakeExporter)

    sys.modules.pop(MODULE_NAME, None)
    tracing = importlib.import_module(MODULE_NAME)
    return tracing, captured_provider


def test_init_is_noop_without_otlp_endpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    fake_span = FakeSpan()
    tracer_calls: list[tuple[tuple, dict]] = []
    tracing, _ = _import_tracing(
        monkeypatch,
        current_span=fake_span,
        tracer_calls=tracer_calls,
    )

    def bare_call() -> None:
        return None

    baseline_start = time.process_time()
    bare_call()
    baseline_cpu = time.process_time() - baseline_start

    start_cpu = time.process_time()
    tracing.init_tracing()
    with tracing.span("demo-run"):
        tracing.set_span_attributes(component="tests", outcome="noop")
    error = RuntimeError("boom")
    tracing.record_exception(error)
    tracing.shutdown_tracing()
    elapsed_cpu = time.process_time() - start_cpu

    assert FakeExporter.instances == []
    assert FakeBatchSpanProcessor.instances == []
    assert fake_span.attributes == [("component", "tests"), ("outcome", "noop")]
    assert fake_span.recorded_exceptions == [error]
    assert fake_span.statuses
    status = fake_span.statuses[0]
    status_code = getattr(status, "status_code", getattr(status, "code", status))
    assert status_code == StatusCode.ERROR
    description = getattr(status, "description", "")
    assert "boom" in str(description) or "boom" in str(status)
    assert elapsed_cpu <= baseline_cpu + 0.05


def test_init_wires_otlp_exporter_and_flushing_shutdown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.example:4318/v1/traces")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "spec-driven-dev-pipeline-test")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "x-api-key=abc,tenant=spec")

    tracing, _ = _import_tracing(monkeypatch)

    tracing.init_tracing()

    assert len(FakeExporter.instances) == 1
    assert len(FakeBatchSpanProcessor.instances) == 1
    assert len(FakeTracerProvider.instances) == 1

    exporter = FakeExporter.instances[0]
    processor = FakeBatchSpanProcessor.instances[0]
    provider = FakeTracerProvider.instances[0]

    assert _observes_text((exporter.args, exporter.kwargs), "collector.example")
    assert _observes_text((exporter.args, exporter.kwargs), "4318")
    assert _observes_text((exporter.args, exporter.kwargs), "x-api-key")
    assert _observes_text((exporter.args, exporter.kwargs), "abc")
    assert _observes_text((exporter.args, exporter.kwargs), "tenant")
    assert _observes_text((exporter.args, exporter.kwargs), "spec")
    assert provider.resource.attributes["service.name"] == "spec-driven-dev-pipeline-test"
    assert provider.added_span_processors == [processor]
    assert processor.span_exporter is exporter

    tracing.shutdown_tracing()

    assert provider.shutdown_called is True
    assert processor.shutdown_called is True
    assert exporter.shutdown_called is True


def test_init_uses_default_service_name_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.example:4318/v1/traces")
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    tracing, _ = _import_tracing(monkeypatch)

    tracing.init_tracing()

    provider = FakeTracerProvider.instances[0]
    service_name = provider.resource.attributes["service.name"]

    assert service_name
    assert "pipeline" in service_name
    assert service_name != "spec-driven-dev-pipeline-test"


def test_record_exception_marks_active_span(monkeypatch: pytest.MonkeyPatch):
    fake_span = FakeSpan()
    tracing, _ = _import_tracing(monkeypatch, current_span=fake_span)

    tracing.init_tracing()

    error = ValueError("boom")
    tracing.record_exception(error)

    assert len(fake_span.recorded_exceptions) == 1
    assert fake_span.recorded_exceptions[0] is error
    assert fake_span.statuses
    status = fake_span.statuses[0]
    status_code = getattr(status, "status_code", getattr(status, "code", status))
    assert status_code == StatusCode.ERROR
    description = getattr(status, "description", "")
    assert "boom" in str(description) or "boom" in str(status)


def test_shutdown_flushes_span_started_before_shutdown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.example:4318/v1/traces")
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    tracing, _ = _import_tracing(monkeypatch)

    tracing.init_tracing()
    processor = FakeBatchSpanProcessor.instances[0]

    with tracing.span("demo-run"):
        tracing.set_span_attributes(component="tests")

    assert len(processor.ended_spans) == 1
    assert processor.flushed_spans == []

    tracing.shutdown_tracing()

    assert processor.shutdown_called is True
    assert len(processor.flushed_spans) == 1
    assert processor.flushed_spans == processor.ended_spans


def test_span_helper_records_exception_and_reraises(monkeypatch: pytest.MonkeyPatch):
    fake_tracer = FakeTracer()
    tracing, _ = _import_tracing(monkeypatch, tracer=fake_tracer)

    tracing.init_tracing()

    with pytest.raises(ValueError, match="boom"):
        with tracing.span("demo-run"):
            raise ValueError("boom")

    assert len(fake_tracer.span.recorded_exceptions) == 1
    assert isinstance(fake_tracer.span.recorded_exceptions[0], ValueError)
    assert str(fake_tracer.span.recorded_exceptions[0]) == "boom"

    assert fake_tracer.span.statuses
    status = fake_tracer.span.statuses[0]
    status_code = getattr(status, "status_code", getattr(status, "code", status))
    assert status_code == StatusCode.ERROR
    description = getattr(status, "description", "")
    assert "boom" in str(description) or "boom" in str(status)
