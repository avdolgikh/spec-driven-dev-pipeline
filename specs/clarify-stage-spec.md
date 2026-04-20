# Spec: Clarify Stage

## Status

Draft

## Goal

Surface specification ambiguities before the test-writer commits to a shape,
so the pipeline stops oscillating on details the spec never decided. Today,
when a spec names a class but not its constructor signature (or an entry
method but not its name), the test-writer silently picks one, the reviewer
flags it as over-pinning, and the loop burns revisions without converging.
This feature gives the spec author a chance to answer ambiguities up front,
with the answers becoming first-class input to downstream stages.

## Scope

A new optional pipeline stage that runs before test-writing, an artifact
format that captures the ambiguities and their answers, and minimal
wiring into the existing prompts so downstream stages can read the answers.

## Requirements

### REQ-1: Clarify stage

Core logic in `src/spec_driven_dev_pipeline/` (new module or extension of
the existing stage set):

- A stage that takes a spec file, invokes the active provider with a
  dedicated clarify prompt, and produces a structured list of ambiguities.
- Each ambiguity identifies the section or phrase it came from, states the
  decision the spec left open, and proposes 2–4 plausible answers.
- The number of ambiguities is bounded (configurable, small default) so the
  output stays actionable.

### REQ-2: Advisory-first rollout

Clarify stage has three modes, controlled by a CLI flag or config key:

- `off` — stage does not run; current pipeline behavior is preserved
  (required so existing regression tests and benchmarks are unaffected).
- `advisory` — stage runs, writes its output, but does not block. Intended
  default during rollout so the team can calibrate on real specs.
- `blocking` — stage runs and halts until a user-answered artifact is present.

Mode precedence: CLI flag overrides config; config overrides default.

### REQ-3: Answer artifact feeds downstream prompts

When a clarify artifact with user answers is present, the test-writer and
reviewer prompts receive it as additional context alongside the spec. Answers
become binding for the current slice: the test-writer may rely on them, and
the reviewer treats them as part of the spec's intent.

If the artifact is absent or has no answers (advisory mode, or user skipped),
downstream stages behave exactly as they do today.

### REQ-4: State and resumability

The clarify artifact is written into the existing `.pipeline-state/` tree
for the slice, alongside test and review logs. Re-running the pipeline on
the same slice must not regenerate the artifact if one already exists with
user answers — it is treated as committed input, not regenerable state.

## Acceptance Criteria

### AC-1: Surfaces real ambiguities on a known-bad spec

- When run against a spec equivalent to `hybrid-foundation-orchestrator-spec.md`
  (which previously caused two cap-exits in the multi-agent repo), the
  clarify stage surfaces the constructor-shape and entry-method ambiguities
  among its top items.

### AC-2: Off-mode regression

- With clarify in `off` mode, a full pipeline run on an existing approved
  spec (e.g. `smoke-test-spec.md`) produces the same sequence of stages and
  outputs as before this feature.

### AC-3: Advisory-mode non-blocking

- In advisory mode, a run completes even when no user answers are supplied.
  The artifact is written; downstream stages proceed unchanged.

### AC-4: Answers influence downstream prompts

- When answers are present, the test-writer's prompt input contains them in
  a clearly delimited section. A review of two equivalent runs (with and
  without answers) shows the test-writer honoring the answered decision in
  the answered run.

### AC-5: Bounded output

- Clarify output never exceeds the configured cap, regardless of spec size.
  Unused slots are not padded.

## Package Layout

New files:

```
src/spec_driven_dev_pipeline/
  stages/              # or equivalent existing location for stage modules
    clarify.py         # REQ-1: stage implementation
  prompts/
    clarify.md         # REQ-1: clarify prompt (new)
tests/
  test_clarify_stage.py
```

Existing files modified:

- The pipeline entry script / orchestration module to register the new
  stage and honor its mode flag.
- `prompts/test_writer.md` and `prompts/reviewer.md` to include a
  "Clarifications" context block when the artifact is present.
- `pipeline-config.toml` (example or template) to document the new mode key.

Existing public flags and behavior remain backwards compatible.
