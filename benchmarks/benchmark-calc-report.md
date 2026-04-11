# Benchmark Report: Expression Evaluator (benchmark-calc)

**Date:** 2026-04-10
**Hardware:** RTX 4070 12GB VRAM / Ollama
**Judge:** Codex (gpt-5.1-codex, reviewer role)
**Task spec:** `specs/benchmark-calc-spec.md`
**Framework spec:** `specs/benchmark-framework-spec.md`

---

## Leaderboard

| Rank | Model | Architecture | Disk | Best Stage | Composite | Time |
|------|-------|-------------|------|-----------|-----------|------|
| 1 | GLM-4.7-Flash | MoE 30B/3B active | 19 GB | TESTS_GENERATED | 1.8/5 | 22m51s |
| 2 | Qwen 3.5 | Dense 4B | 6.6 GB | Stage 1 fail | 1.2/5 | 1m44s |
| 3 | Gemma 4 | Dense ~9B | 9.6 GB | Stage 1 fail | 1.0/5 | 21s |
| 4 | Qwen3-Coder | MoE 30B/3.3B active | 18 GB | Stage 1 fail | 1.0/5 | 36s |

## Score Breakdown

| Model | Test Coverage | Test Quality | Correctness | Code Quality | Format |
|-------|--------------|-------------|-------------|-------------|--------|
| GLM-4.7-Flash | 2 | 2 | 1 | 1 | 3 |
| Qwen 3.5 | 1 | 1 | 1 | 1 | 2 |
| Gemma 4 | 1 | 1 | 1 | 1 | 1 |
| Qwen3-Coder | 1 | 1 | 1 | 1 | 1 |

Scores are 1 (poor) to 5 (excellent). Composite = mean of all 5 dimensions.

---

## Per-Model Analysis

### 1. GLM-4.7-Flash (glm-4.7-flash:latest)

- **Exit code:** 10 (EXIT_STAGE_NO_EFFECT)
- **Reached:** Stage 2b (TESTS_GENERATED) -- furthest of all models
- **Revisions:** 1
- **Wall clock:** 22m51s
- **Judge notes:** Tests cover basic arithmetic, precedence, parentheses, and division-by-zero but miss many ACs (unary minus, invalid inputs, unmatched parens, complex expressions). Some tests are weak or non-assertive. Float precision test uses exact 0.3 which is brittle. No implementation produced. Output had a valid FILE block for tests but revision output wasn't in FILE format.

### 2. Qwen 3.5 (qwen3.5:latest)

- **Exit code:** 10 (EXIT_STAGE_NO_EFFECT)
- **Reached:** Stage 1 fail
- **Revisions:** 0
- **Wall clock:** 1m44s
- **Failure mode:** Followed FILE: format but used `calc_test.py` instead of `test_calc.py`. Pipeline requires `test_` prefix for task-term matching.
- **Judge notes:** Output included a FILE block for `tests/calc_test.py` (wrong naming) but mixed extensive prose and a second incomplete test dump with undefined `CalcExpressionError`. No test files were actually written into the results directory.

### 3. Gemma 4 (gemma4:e4b)

- **Exit code:** 10 (EXIT_STAGE_NO_EFFECT)
- **Reached:** Stage 1 fail
- **Revisions:** 0
- **Wall clock:** 21s
- **Failure mode:** Ignored FILE: output instructions entirely. Wrote tests as prose markdown.
- **Judge notes:** Output was prose, no FILE blocks. Tests targeted wrong module/path and used placeholder mocks/NotImplementedError bypasses. Error expectations use ValueError instead of CalcError. No implementation provided.

### 4. Qwen3-Coder (qwen3-coder:latest)

- **Exit code:** 10 (EXIT_STAGE_NO_EFFECT)
- **Reached:** Stage 1 fail
- **Revisions:** 0
- **Wall clock:** 36s
- **Failure mode:** Emitted tool-call format instead of FILE: blocks. OpenCode adapter requires text output.
- **Judge notes:** Output included an unsupported tool call and no FILE blocks, so nothing was parseable or runnable.

---

## Key Findings

1. **Structured output is the main bottleneck.** All 4 local models failed at or near Stage 1. The pipeline requires `FILE: path/to/file` blocks; 3 of 4 models couldn't produce them at all.

2. **GLM-4.7-Flash was the clear winner.** Only model to produce parseable test files and reach Stage 2b. Its MoE architecture (30B total, 3B active) gave it enough capacity to follow format instructions.

3. **Model size doesn't guarantee format compliance.** Qwen3-Coder (30B MoE) performed worse than Qwen 3.5 (4B dense) on format compliance. Qwen3-Coder tried to use tool calls, suggesting it's fine-tuned for a different interaction pattern.

4. **Naming conventions matter.** Qwen 3.5 produced the right format but wrong filename (`calc_test.py` vs `test_calc.py`). A small naming mismatch caused complete pipeline failure.

5. **No model completed the full pipeline.** None reached implementation, let alone code review. For the benchmark-calc task (4 functions, 10 ACs), local models on consumer GPU cannot yet drive the TDD pipeline end-to-end.

---

## Run Details

- **Provider:** OpenCode CLI via `opencode.json` Ollama adapter
- **Models registered in:** `opencode.json` under `provider.ollama.models`
- **Pipeline command:** `uv run python scripts/run_pipeline.py benchmark-calc --provider opencode`
- **Per-model results:** `benchmarks/results/<model-tag>/`
- **Auto-generated leaderboard:** `benchmarks/leaderboard.md`, `benchmarks/leaderboard.json`

### Issues Encountered During Benchmarking

| Issue | Resolution |
|-------|-----------|
| GLM missing from `opencode.json` | Added to `provider.ollama.models` |
| `generate_leaderboard()` TypeError (keyword-only args) | Fixed CLI to pass keyword args |
| `scripts/` not importable in tests | Added `__init__.py`, added `.` to `pythonpath` |
| Judge used `role='judge'` (unknown role) | Changed to `role='reviewer'` |
| Metrics parser didn't match real log format | Added `[state] STAGE_NAME` pattern |
| Runner copied all tests/src instead of task-specific files | Narrowed to `*calc*` patterns |
