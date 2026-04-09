# Spec: Pipeline Hardening

## Status

Approved

## Goal

Close the gaps found during the smoke-test validation run (2026-04-08).

## Requirements

### REQ-1: Final pytest gate before VERIFIED

After Code Review approves (stage transitions from CODE_REVIEWED), run the configured test command before marking the pipeline VERIFIED. If tests fail, raise `PipelineError` with a new exit code `EXIT_FINAL_TESTS_FAILED`. This applies to specs both with and without an Artifact Pipeline section.

**Why:** The OpenCode smoke-test run proved this gap -- the reviewer approved code with a failing test (`np.random.seed` 32-bit limit), the pipeline marked VERIFIED, but `pytest` showed 1 failure.

### REQ-2: Automatic retry on transient provider failures

When a provider's `run_role` raises `PipelineError` with `EXIT_PROVIDER_EXEC_FAILED`, retry once after a short delay before propagating the error. The retry count should be configurable (default: 1). Log the retry attempt.

**Why:** The Claude smoke-test run hit a transient reviewer failure (exit 1, empty stdout/stderr). The pipeline crashed and required manual resume. Network blips, rate limits, and empty responses should be retried automatically.

### REQ-3: Tighten Stage 1 test-generation effect check

After Stage 1 (Test Generation), verify that at least one new test file related to the current task was created or modified in the tests directory. The current `allow_existing=True` flag lets Stage 1 pass even if no task-specific tests were written, as long as any test files already exist.

**Why:** The gemma4 OpenCode run produced no smoke-test tests at all, but Stage 1 passed because the pipeline's own 60 pre-existing tests satisfied the `allow_existing` check.

### REQ-4: Improve Gemini output extraction

The Gemini provider uses `-o json` and parses `data.get("response", "")`. When Gemini creates files via tool use, the response field is nearly empty. Investigate the Gemini CLI JSON output structure for tool-use sessions and extract meaningful output (e.g., tool call summaries, file paths created).

**Why:** During the smoke-test run, Gemini Flash created correct files via tools but the pipeline log showed only `</code>` -- no useful diagnostic output.

## Acceptance Criteria

### AC-1: Final pytest gate

- Pipeline runs `test_command` after CODE_REVIEWED and before VERIFIED.
- If tests fail, pipeline exits with `EXIT_FINAL_TESTS_FAILED` and does NOT write VERIFIED state.
- If tests pass, pipeline proceeds to VERIFIED normally.

### AC-2: Provider retry

- A single transient `EXIT_PROVIDER_EXEC_FAILED` is retried once automatically.
- Two consecutive failures propagate the error as before.
- Retry attempts are logged.

### AC-3: Stage 1 effect check

- Stage 1 fails with `EXIT_STAGE_NO_EFFECT` if no test file matching the task name was created or modified.
- Pre-existing unrelated test files do not satisfy the check.

### AC-4: Gemini output extraction

- Gemini provider extracts tool-use summaries from CLI JSON output when `response` field is empty.
- Pipeline log shows which files were created/modified by the Gemini agent.

## Package Layout

Changes are limited to existing files:
```
src/spec_driven_dev_pipeline/
  core.py                         # REQ-1, REQ-2, REQ-3
  providers/
    gemini.py                     # REQ-4
tests/
  test_pipeline_core.py           # tests for REQ-1, REQ-2, REQ-3
  test_pipeline_providers.py      # tests for REQ-4
```
