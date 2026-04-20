# Spec: OTel Tracing for Pipeline Runs

## Status

Draft

## Goal

Emit OpenTelemetry traces from pipeline runs so post-mortems on cap-exits and
long reviews stop depending on manual log scraping. The multi-agent project
already exports to Phoenix; this spec brings the pipeline itself under the
same lens so a single trace tells the story of a slice from start to finish.

## Scope

An observability module that initializes an OTel tracer, a small set of
span boundaries placed at the pipeline's existing stage and iteration seams,
and honoring of the standard OTLP environment variables. No new dependencies
beyond the OTel SDK/exporter already used elsewhere in the author's stack.

## Requirements

### REQ-1: Tracer initialization

Core logic in `src/spec_driven_dev_pipeline/utils/` (new module):

- Initialization that reads the standard `OTEL_*` environment variables and
  sets up an exporter only when a collector endpoint is configured. When
  unset, all tracing calls are no-ops with negligible overhead.
- Service name is set to something identifiable (e.g. `spec-driven-pipeline`)
  and may be overridden by `OTEL_SERVICE_NAME`.
- Clean shutdown flushes pending spans so runs that exit promptly still
  deliver their trace.

### REQ-2: Span hierarchy

The pipeline emits spans along its existing structural seams. A single run
produces one root span; each stage (clarify, test-writer, reviewer, revision
iteration, implementation, stage 4, stage 5) is a child span; provider
invocations within a stage are leaf spans.

The shape is dictated by the code's existing stage boundaries, not pinned
to a fixed string vocabulary here.

### REQ-3: Span attributes

Each span carries enough attributes for a reader to reconstruct what
happened without reading logs: at minimum the slice name, stage identity,
iteration index (where applicable), provider name, model name, and the
outcome of the stage (approved, revise, cap-exit, error). Exact attribute
names are chosen by the implementer; they should be namespaced consistently
(e.g. `pipeline.*`).

### REQ-4: No-op when unconfigured

With no `OTEL_*` environment variables set, the pipeline runs identically
to today: no network calls, no measurable overhead, no dependency on an
exporter being reachable. This is a hard requirement — the feature must
not make offline or disconnected runs slower or more fragile.

### REQ-5: Error capture

Exceptions raised inside a traced stage are recorded on the active span
(span status set to error, exception message captured) and then re-raised.
The feature does not swallow or transform exceptions.

## Acceptance Criteria

### AC-1: Full-run trace renders in Phoenix

- With `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at a running Phoenix instance,
  a complete pipeline run on any approved spec produces a single trace
  with a visible stage hierarchy that matches the run's actual progression.

### AC-2: Unconfigured runs are unchanged

- With all `OTEL_*` variables unset, wall-clock runtime on a short spec is
  within noise of the pre-change baseline, and no network calls are made
  from the pipeline process.

### AC-3: Cap-exit is visible in the trace

- When a run hits `--max-revisions`, the trace shows each revision
  iteration as a distinct span and the outcome attribute on the relevant
  spans identifies the cap-exit path.

### AC-4: Errors surfaced

- When a stage raises, its span carries error status and the exception
  type/message. The root span also reflects the failure.

### AC-5: Standard env vars respected

- Changing `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, and
  `OTEL_EXPORTER_OTLP_HEADERS` takes effect without code changes. No
  pipeline-specific tracing env vars are introduced.

## Package Layout

New files:

```
src/spec_driven_dev_pipeline/
  utils/
    tracing.py         # REQ-1: init + shutdown, span helpers
tests/
  test_tracing.py      # unit tests for no-op behavior and attribute shape
```

Existing files modified:

- The pipeline entry script / orchestration module to initialize tracing at
  run start, wrap the run in a root span, and wrap stages/iterations at
  existing seams.
- `pyproject.toml` to declare the OTel SDK + OTLP exporter dependency if
  not already present.
- `README.md` to document the `OTEL_*` env vars and the Phoenix workflow.

No change to CLI flags, provider interfaces, or the shape of
`.pipeline-state/` artifacts.
