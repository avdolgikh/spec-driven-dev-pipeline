# Spec: OTel Tracing — Pipeline Wiring

## Status

Draft — depends on `otel-tracing-init` landing first.

## Goal

Wire the tracing utility into `PipelineRunner` so a single run produces
one coherent trace across stages and revision iterations. Post-mortems
on cap-exits and long reviews stop depending on manual log scraping.

## Scope

Instrumentation of existing stage and iteration seams in
`src/spec_driven_dev_pipeline/core.py` using the helpers introduced by
`otel-tracing-init`. No new files under `src/` beyond `core.py` edits.

## Requirements

### REQ-1: Span hierarchy at existing seams

One root span per `PipelineRunner.run()` call. Each stage (clarify,
test generation, test review + revision iterations, implementation,
code review, validation) is a child of the root. Provider invocations
within a stage are leaf spans under the stage.

Span placement follows the code's existing stage boundaries; exact
span names are the implementer's call, as long as the hierarchy
reflects the run's actual progression.

### REQ-2: Span attributes

Each span carries enough attributes for a reader to reconstruct what
happened without reading logs. At minimum, somewhere in the hierarchy
the following are available:

- slice / task name
- stage identity
- revision iteration index (on iteration spans)
- provider name
- model name
- stage outcome where applicable (approved, revise, cap-exit, error)

Attribute names are namespaced under a consistent prefix (e.g.
`pipeline.*`). Exact names are the implementer's call.

### REQ-3: Error capture

Exceptions raised inside a traced stage are recorded on the active
span (status=error, exception type/message captured) and the root span
reflects the failure. Exceptions are not swallowed or transformed —
the pipeline's existing error-exit behavior is preserved.

### REQ-4: Preserve unconfigured behavior

With no `OTEL_*` environment variables set, the instrumented pipeline
runs identically to today — same stdout, same exit codes, same
`.pipeline-state/` artifacts, no network calls. This is tested
independently of the init-slice's own no-op tests.

## Acceptance Criteria

### AC-1: Cap-exit visible in the trace

When a run hits `--max-revisions`, the trace shows each revision
iteration as a distinct span, and an outcome attribute on the relevant
span(s) identifies the cap-exit path. Verified against a mocked
exporter or captured span list — no live Phoenix required.

### AC-2: Errors surfaced on both levels

When a stage raises, its span has error status with the exception
type/message, and the root span also reflects the failure. Verified
via a test that injects an exception through a stub provider.

### AC-3: Unconfigured runs unchanged

With all `OTEL_*` variables unset, an end-to-end run via stub providers
produces identical stdout and exit code to a pre-change baseline, and
no OTLP export calls are made.

### AC-4: Attribute completeness

Inspecting the captured spans from a representative run, the
attributes listed in REQ-2 are present on at least one span in each
category (per-stage, per-iteration, per-provider-invocation).

## Package Layout

New files:

```
tests/
  test_pipeline_tracing_wiring.py   # behavioral tests for span hierarchy, attributes, error capture
```

Existing files modified:

- `src/spec_driven_dev_pipeline/core.py` — tracer init at run start,
  root span, child spans at stage and iteration seams, leaf spans at
  provider invocations, error recording.
- `README.md` — document the `OTEL_*` env vars and the Phoenix workflow.

Existing files referenced:

- `src/spec_driven_dev_pipeline/utils/tracing.py` — the helpers from
  the init slice (do not modify in this slice).
- `tests/test_tracing.py` — the init slice's unit tests (do not modify
  in this slice; wiring tests belong in the new file above).

No change to CLI flags, provider interfaces, or the shape of
`.pipeline-state/` artifacts.

## Out of Scope

- Live Phoenix integration / manual runbook — verified separately
  outside the pipeline.
- New tracer configuration beyond what `otel-tracing-init` already
  exposes.
