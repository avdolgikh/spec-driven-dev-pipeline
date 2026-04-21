# Spec: OTel Tracing — Init Module

## Status

Draft

## Goal

Provide a small, self-contained tracing utility that the rest of the
pipeline can call into. No pipeline instrumentation yet — that's a
follow-on slice. This slice only delivers the init/shutdown/helper
surface and the no-op behavior when OTel is unconfigured.

## Scope

A single new module under `src/spec_driven_dev_pipeline/utils/` exposing
tracer initialization, clean shutdown, and span helpers. Honors standard
`OTEL_*` environment variables. When no collector is configured, every
entry point is a cheap no-op.

## Requirements

### REQ-1: Tracer initialization and shutdown

`src/spec_driven_dev_pipeline/utils/tracing.py` exposes an init function
that reads standard `OTEL_*` environment variables and wires up an OTLP
exporter only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. A shutdown entry
point flushes pending spans so runs that exit promptly still deliver
their trace.

Service name defaults to something identifiable (e.g.
`spec-driven-pipeline`) and may be overridden by `OTEL_SERVICE_NAME`.
`OTEL_EXPORTER_OTLP_HEADERS` is honored if set.

### REQ-2: No-op when unconfigured

When `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, init sets up no exporter and
no span processor. Any span helpers the module exposes do not make
network calls and do not raise. This must remain true across all entry
points in the module.

### REQ-3: Span helper surface

The module exposes a minimum surface for callers to start spans and
record outcomes without reaching into the OTel SDK directly. A
context-manager or decorator-style helper for bounded spans, and a way
to set attributes and record exceptions on the active span. The exact
function names and signatures are the implementer's call; they should
be ergonomic for the pipeline's eventual wiring slice.

## Acceptance Criteria

### AC-1: No network when unconfigured

With all `OTEL_*` variables unset, calling init + exercising the span
helpers makes no network calls and completes within noise of a bare
function call. Verified via mocked exporter and absence of OTLP
configuration.

### AC-2: Exporter wired when endpoint is set

With `OTEL_EXPORTER_OTLP_ENDPOINT` set, init configures an OTLP exporter
and installs a batch span processor on the tracer provider. `OTEL_SERVICE_NAME`
and `OTEL_EXPORTER_OTLP_HEADERS` flow through to the resource/exporter
configuration.

### AC-3: Shutdown flushes

Calling the shutdown entry point invokes the exporter/provider shutdown
path. Spans started before shutdown are flushed; the call returns
without raising even when tracing is unconfigured.

### AC-4: Exceptions recorded, not swallowed

The span helper's exception path records the exception on the active
span (status=error, type/message captured) and re-raises. It does not
swallow or transform the exception.

## Package Layout

New files:

```
src/spec_driven_dev_pipeline/
  utils/
    tracing.py
tests/
  test_tracing.py
```

Existing files modified:

- `pyproject.toml` to declare the OTel SDK + OTLP exporter dependency if
  not already present.

No change to `core.py`, CLI flags, provider interfaces, or
`.pipeline-state/` artifacts — pipeline wiring is a separate slice.

## Out of Scope

- Instrumenting `PipelineRunner.run` with spans at stage seams.
- Attribute vocabulary for slice/stage/iteration/provider/model/outcome.
- Phoenix integration test / live-run verification.
- `README.md` documentation of the Phoenix workflow.

These land in the follow-on `otel-tracing-wiring` slice.
