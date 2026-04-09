# Cleanup Plan: Pipeline Hardening Implementation

## Context

Codex implemented `specs/pipeline-hardening-spec.md` (REQ-1 through REQ-4). The core logic is correct, but the implementation has scope creep, duplication, and noise. This plan tracks the manual cleanup before running the pipeline for OpenCode/Gemini/Claude.

## Status Legend

- `[ ]` pending
- `[~]` in progress
- `[x]` done

---

## 1. Revert scope creep (not in spec)

### 1a. Restore `__init__.py` `[x]`
Codex replaced public API re-exports with `# Package init - empty is fine`. Restore the original content (git show HEAD version).

### 1b. Remove `format_command` / `_run_format` / `_format_hint` `[x]`
- Remove `format_command` field from `PipelineConfig`
- Remove `_format_hint` from `PipelineRunner.__init__`
- Remove `_run_format()` method
- Remove `self._run_format()` call in `_run_role`
- Remove all `{self._format_hint}` injections from stage instruction strings
- ~40 lines of unasked-for code coupling prompts to `ruff`

### 1c. Remove `uv` fallback logic in `_run_pytest_gate` `[x]`
- Remove `_should_retry_pytest_without_uv()` method
- Remove `_uv_fallback_command()` method
- Remove the fallback branch inside `_run_pytest_gate`
- Keep the core refactor (nested `_execute` helper is fine)

### 1d. Revert curly-quote prompt additions `[x]`
- Remove added line from `prompts/implementer.md`
- Remove added line from `prompts/reviewer.md`
- Remove added line from `prompts/test_writer.md`

---

## 2. Clean up core.py design

### 2a. Simplify snapshot caching `[x]`
`_tests_hash()` silently populates `_tests_snapshot_cache` as a side effect. Decouple: make snapshot capture explicit at call sites that need it (Stage 1 effect check), keep `_tests_hash()` as a clean one-liner.

### 2b. Consolidate task-term matching `[x]`
`_compute_task_test_terms()` duplicates intent of `_spec_priority_terms()`. Evaluate whether we can reuse `_spec_priority_terms` for the Stage 1 check. If not, at minimum remove the overly broad word-part splitting (`re.split(r"[^a-z0-9]+"`) that makes task `pipeline-hardening` match any path containing `pipeline`.

### 2c. Clean up `_ensure_tests_stage_effect` `[x]`
- The `stage_label == "Stage 1: Test Generation"` check at the bottom (line ~793) is dead code -- the `require_task_specific` branch always handles Stage 1 first
- Remove `not require_task_specific` guard (always False when we reach that point)
- Simplify the ternary for the `detail` error message

### 2d. Remove `hasattr(time, "sleep")` guard `[x]`
`time.sleep` always exists. Replace with plain `time.sleep(2)`.

---

## 3. Clean up tests

### 3a. Deduplicate test boilerplate `[x]`
Extract shared fixtures for:
- `tmp_path` spec dir setup
- `DummyProvider` / `ProviderExecution` creation
- `PipelineRunner` construction with minimal scaffolding
Goal: cut repetition across the ~6 new Stage 1 tests and ~6 new retry/final-gate tests.

### 3b. Remove tests for removed features `[x]`
If uv-fallback or format-command had test coverage, remove those tests.

---

## 4. Clean up Gemini provider `[x]`
Review `_extract_response` for unnecessary defensiveness. The logic is mostly correct but overly cautious with type checks.

---

## 5. Verify `[x]`
Run `uv run pytest` and `uv run ruff check .` to confirm nothing broke.

---

## Files touched
```
src/spec_driven_dev_pipeline/__init__.py     # 1a
src/spec_driven_dev_pipeline/core.py         # 1b, 1c, 2a-2d
src/spec_driven_dev_pipeline/prompts/*.md    # 1d
src/spec_driven_dev_pipeline/providers/gemini.py  # 4
tests/test_pipeline_core.py                  # 3a, 3b
tests/test_pipeline_providers.py             # 3b (if needed)
```
