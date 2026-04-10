# Spec: Local Model Benchmarking Framework

## Status

Approved

## Goal

Create a repeatable, automated framework for benchmarking local Ollama models through the spec-driven TDD pipeline. The framework runs each candidate model against a standardized task, collects metrics automatically, evaluates quality using a capable judge agent, and produces a leaderboard.

## Context

### Why Benchmark Local Models?

The pipeline supports local models via the OpenCode provider + Ollama. Model quality varies enormously -- from models that can't follow structured output to models that rival API providers. A systematic benchmark answers: which local models are worth using with this pipeline?

### Hardware Constraints

Target hardware: NVIDIA RTX 4070 (12GB VRAM). Models must either fit in 12GB VRAM or use MoE architecture where active parameters fit. Larger models spill to system RAM (slower but functional via Ollama).

### Candidate Models (Initial Round)

| Model | Ollama Tag | Architecture | Disk Size | Notes |
|-------|-----------|-------------|-----------|-------|
| Qwen 3.5 | `qwen3.5:latest` | Dense 4B | 6.6 GB | Baseline. Previously tested in smoke-test (PASS with caveats). |
| Gemma 4 | `gemma4:e4b` | Dense ~9B | 9.6 GB | Google's latest small model. Untested with pipeline. |
| GLM-4.7-Flash | `glm-4.7-flash:latest` | MoE 30B/3B active | 19 GB | Strong SWE-bench scores (59.2% Verified). Already pulled. |
| Qwen3-Coder | `qwen3-coder:latest` | MoE 30B/3.3B active | ~17 GB | RL-trained on SWE-bench. Purpose-built for agentic coding. Needs to be pulled. |

### Benchmark Task

The benchmark task is defined in `specs/benchmark-calc-spec.md` -- an expression evaluator module with 4 functions, 3 custom types, and 10 acceptance criteria. This task was designed to differentiate model capability across:

- Multi-component architecture (tokenizer/parser/evaluator)
- Algorithmic reasoning (operator precedence)
- Error handling (3 categories of errors)
- Structured output compliance (FILE: format, JSON review)

---

## Requirements

### REQ-1: Benchmark Runner

Core logic lives in `src/spec_driven_dev_pipeline/benchmark/runner.py` (importable, testable):

- `sanitize_model_tag(tag: str) -> str` -- converts model tag to filesystem-safe directory name (replace `/` and `:` with `-`).
- `ensure_ollama_prefix(tag: str) -> str` -- prepends `ollama/` if missing.
- `cleanup_task(repo_root: Path, task: str, config: PipelineConfig) -> None` -- deletes `.pipeline-state/<task>.json`, `.pipeline-state/<task>.log`, generated test files (`tests/test_calc*.py`), and generated source files (`src/spec_driven_dev_pipeline/utils/calc.py`).
- `run_model(model_tag: str, task: str, repo_root: Path, output_dir: Path, max_revisions: int) -> dict` -- runs one model: cleanup, set `OPENCODE_MODEL` env, invoke pipeline via `subprocess`, capture exit code + wall-clock time + log, copy artifacts to `<output_dir>/<sanitized-tag>/`, collect metrics (REQ-3), return per-model result dict.
- `run_benchmark(models: list[str], task: str, output_dir: Path, repo_root: Path, max_revisions: int) -> dict` -- iterates models, calls `run_model` for each, writes `<output-dir>/summary.json`.

CLI wrapper `scripts/run_benchmark.py`:

1. Accepts command-line arguments:
   - `--models` (required): comma-separated list of Ollama model tags (e.g. `qwen3.5:latest,glm-4.7-flash:latest`)
   - `--task` (default: `benchmark-calc`): task name matching a spec in `specs/`
   - `--output-dir` (default: `benchmarks/results`): where to store run results
   - `--max-revisions` (default: 4): passed through to pipeline
2. Calls `benchmark.runner.run_benchmark()`.

**Cleanup between runs is critical** -- the pipeline checks for provider mismatch in state files and for pre-existing test files.

### REQ-2: Judge Evaluation

After each model completes its pipeline run, evaluate the quality of the output using a capable API agent (Codex or Claude) as a judge.

**Judge Input:**

The judge receives a structured prompt containing:

1. The original spec (`specs/benchmark-calc-spec.md`).
2. The test file the model wrote (if any).
3. The implementation file the model wrote (if any).
4. The pytest output (if pipeline reached that stage).
5. The pipeline log (abbreviated -- last 200 lines).

**Judge Rubric:**

The judge scores each dimension on a 1--5 scale:

| Dimension | 1 (Poor) | 3 (Adequate) | 5 (Excellent) |
|-----------|----------|--------------|---------------|
| **Test Coverage** | Tests cover <30% of ACs | Tests cover 50-70% of ACs | Tests cover all ACs including edge cases |
| **Test Quality** | Tests are broken or trivially pass | Tests run and assert basic behavior | Tests are well-structured, independent, with descriptive names |
| **Code Correctness** | Implementation fails most tests | Implementation passes basic tests, fails edge cases | All tests pass, handles all edge cases correctly |
| **Code Quality** | Unreadable, monolithic, no types | Functional but messy | Clean, idiomatic, good abstractions, types used properly |
| **Format Compliance** | Model output couldn't be parsed | Partially parseable, some manual intervention needed | All FILE: blocks and review JSON parsed correctly |

**Judge Output:**

```json
{
  "model": "<model tag>",
  "task": "<task name>",
  "scores": {
    "test_coverage": 4,
    "test_quality": 3,
    "code_correctness": 5,
    "code_quality": 4,
    "format_compliance": 5
  },
  "composite_score": 4.2,
  "notes": "Brief qualitative summary of strengths and weaknesses."
}
```

The `composite_score` is the arithmetic mean of the five dimension scores.

**Implementation:**

Core logic lives in `src/spec_driven_dev_pipeline/benchmark/judge.py` (importable, testable):

- `build_judge_prompt(spec_text, test_code, impl_code, pytest_output, log_tail) -> str` -- assembles the judge prompt. Truncates log to last 200 lines.
- `parse_judge_response(output: str) -> dict` -- extracts and validates JSON from judge output, computes `composite_score` as arithmetic mean.
- `run_judge(model_dir: Path, provider: str, spec_path: Path) -> dict` -- reads artifacts from a single model directory, builds prompt, invokes provider, parses response, saves `judge_evaluation.json`.

CLI wrapper `scripts/judge_benchmark.py`:

1. Accepts `--results-dir` (path to a model's result directory) and `--provider` (judge agent: `codex`, `claude`, or `gemini`).
2. Calls `benchmark.judge.run_judge()`.
3. Supports `--all` flag to iterate all model subdirectories in `--results-dir`.

### REQ-3: Automated Metrics Collection

Core logic lives in `src/spec_driven_dev_pipeline/benchmark/metrics.py` (importable, testable):

- `parse_pytest_output(output: str) -> dict` -- extracts `test_pass_count`, `test_fail_count`, `test_pass_rate` from pytest summary line.
- `parse_pipeline_log(log: str) -> dict` -- extracts `final_stage`, `revision_cycles`, `format_parse_failures` from pipeline log.
- `collect_metrics(model_dir: Path, exit_code: int, wall_clock: float) -> dict` -- reads `pipeline.log` and `pytest_output.txt` from `model_dir`, calls parsers, assembles full metrics dict, saves as `metrics.json`.

Metrics collected:

| Metric | Source | Type |
|--------|--------|------|
| `pipeline_completed` | Exit code == 0 | bool |
| `final_stage` | Last stage in pipeline log | string |
| `exit_code` | Process exit code | int |
| `test_pass_count` | pytest output parsing | int |
| `test_fail_count` | pytest output parsing | int |
| `test_pass_rate` | pass / (pass + fail) | float (0.0--1.0) |
| `revision_cycles` | Count of "Revision" entries in pipeline log | int |
| `wall_clock_seconds` | Start-to-finish timer | float |
| `files_generated` | Count of files written by model | int |
| `format_parse_failures` | Count of FILE: blocks that failed regex extraction | int |

Save as `<results-dir>/<model>/metrics.json`.

### REQ-4: Leaderboard Generation

Core logic lives in `src/spec_driven_dev_pipeline/benchmark/leaderboard.py` (importable, testable):

- `load_results(results_dir: Path) -> list[dict]` -- reads `summary.json` plus per-model `metrics.json` and `judge_evaluation.json`.
- `render_markdown(entries: list[dict], metadata: dict) -> str` -- produces markdown table sorted by composite score.
- `render_json(entries: list[dict], metadata: dict) -> str` -- produces JSON leaderboard.
- `generate_leaderboard(results_dir: Path, output_path: Path) -> None` -- loads results, renders both formats, writes files.

CLI wrapper `scripts/generate_leaderboard.py` calls `benchmark.leaderboard.generate_leaderboard()`.

Output: `benchmarks/leaderboard.md` -- a markdown table sorted by composite score:

```markdown
# Local Model Benchmark Leaderboard

**Task:** benchmark-calc (Expression Evaluator)
**Date:** 2026-04-10
**Hardware:** RTX 4070 12GB / Ollama
**Judge:** codex (gpt-5.1-codex)

| Rank | Model | Completed | Tests Pass | Revisions | Composite | Time |
|------|-------|-----------|------------|-----------|-----------|------|
| 1 | glm-4.7-flash | Yes | 18/18 | 1 | 4.6 | 8m32s |
| 2 | qwen3-coder | Yes | 16/18 | 2 | 4.2 | 12m15s |
| 3 | gemma4:e4b | Yes | 14/18 | 3 | 3.4 | 6m20s |
| 4 | qwen3.5 | Partial (CODE_VALIDATED) | 12/18 | 4 | 2.8 | 15m10s |

## Score Breakdown

| Model | Test Coverage | Test Quality | Correctness | Code Quality | Format |
|-------|-------------|-------------|-------------|-------------|--------|
| glm-4.7-flash | 5 | 4 | 5 | 4 | 5 |
| ... | ... | ... | ... | ... | ... |
```

3. Also produces `benchmarks/leaderboard.json` for programmatic consumption.

### REQ-5: Model Configuration

The framework uses the existing OpenCode provider. Model selection is controlled by the `OPENCODE_MODEL` environment variable, which the benchmark runner sets before each pipeline invocation.

No changes to the OpenCode provider are needed. The provider already reads `OPENCODE_MODEL` with a default of `ollama/qwen3.5:latest`.

**Ollama model tags** must use the `ollama/` prefix as required by the OpenCode CLI (e.g. `ollama/glm-4.7-flash:latest`). The benchmark runner should prepend `ollama/` if the user omits it.

---

## Workflow

### Running a Full Benchmark

```bash
# 1. Pull any missing models
ollama pull qwen3-coder

# 2. Run all models against the benchmark task
uv run python scripts/run_benchmark.py \
  --models "qwen3.5:latest,gemma4:e4b,glm-4.7-flash:latest,qwen3-coder:latest" \
  --task benchmark-calc

# 3. Run judge evaluation on all results (using Codex as judge)
uv run python scripts/judge_benchmark.py \
  --results-dir benchmarks/results \
  --provider codex \
  --all

# 4. Generate leaderboard
uv run python scripts/generate_leaderboard.py \
  --results-dir benchmarks/results \
  --output benchmarks/leaderboard.md
```

### Running a Single Model

```bash
# Run one model
OPENCODE_MODEL=ollama/glm-4.7-flash:latest \
uv run python scripts/run_pipeline.py benchmark-calc --provider opencode

# Judge it
uv run python scripts/judge_benchmark.py \
  --results-dir benchmarks/results/glm-4.7-flash \
  --provider codex
```

---

## Design Decisions

### Why use a judge agent instead of only automated metrics?

Automated metrics (test pass rate, pipeline completion) tell you IF the model succeeded but not HOW WELL. Two models might both pass all tests, but one writes elegant code with comprehensive edge-case tests while the other writes a monolithic mess that barely works. The judge captures this qualitative dimension.

### Why Codex/Claude as judge, not a local model?

The judge must be more capable than the models being evaluated. Using a local model as judge would be like having students grade each other's exams. A frontier API model provides a reliable, consistent evaluation baseline.

### Why one benchmark task instead of many?

Start simple. One well-designed task gives signal. Multiple tasks can be added later by creating additional `specs/benchmark-*-spec.md` files. The framework is task-agnostic -- `--task` selects which spec to run.

### Why clean up between runs?

The pipeline stores provider name in the state file. Running a different model without cleanup causes `EXIT_STATE_PROVIDER_MISMATCH` (exit 6). Also, pre-existing test/source files from a previous model would contaminate the next run.

---

### Why library modules instead of script-only?

The benchmark logic (cleanup, metrics parsing, judge prompt building, leaderboard rendering) must be unit-testable. Putting logic directly in scripts makes it hard to test without subprocess calls. The standard Python pattern is: importable library modules with testable functions, plus thin CLI scripts that parse args and call the library.

---

## Package Layout

New files:

```
src/spec_driven_dev_pipeline/
  benchmark/                   # library modules (importable, testable)
    __init__.py                # re-exports key functions
    runner.py                  # REQ-1: orchestration logic
                               #   sanitize_model_tag(tag) -> str
                               #   ensure_ollama_prefix(tag) -> str
                               #   cleanup_task(repo_root, task, config) -> None
                               #   run_model(model_tag, task, repo_root, config, max_revisions) -> dict
                               #   run_benchmark(models, task, output_dir, ...) -> dict (summary)
    judge.py                   # REQ-2: judge evaluation logic
                               #   build_judge_prompt(spec, tests, impl, pytest_out, log_tail) -> str
                               #   parse_judge_response(output) -> dict
                               #   run_judge(results_dir, provider, ...) -> dict
    metrics.py                 # REQ-3: automated metrics extraction
                               #   parse_pytest_output(output) -> dict (pass/fail counts)
                               #   parse_pipeline_log(log) -> dict (stage, revisions, etc.)
                               #   collect_metrics(model_dir) -> dict (full metrics.json content)
    leaderboard.py             # REQ-4: leaderboard generation
                               #   render_markdown(entries, metadata) -> str
                               #   render_json(entries, metadata) -> str
                               #   generate_leaderboard(results_dir, output_path) -> None
scripts/
  run_benchmark.py             # thin CLI: argparse -> benchmark.runner.run_benchmark()
  judge_benchmark.py           # thin CLI: argparse -> benchmark.judge.run_judge()
  generate_leaderboard.py      # thin CLI: argparse -> benchmark.leaderboard.generate_leaderboard()
tests/
  test_benchmark_framework.py  # unit tests for all benchmark modules (runner, judge, metrics, leaderboard)
benchmarks/
  results/                     # per-model run artifacts (gitignored)
    <model-tag>/
      pipeline.log
      metrics.json
      judge_evaluation.json
      tests/                   # copy of generated test files
      src/                     # copy of generated source files
  leaderboard.md               # REQ-4: rendered leaderboard
  leaderboard.json             # REQ-4: machine-readable leaderboard
specs/
  benchmark-calc-spec.md       # the benchmark task (already exists)
```

Existing files modified: none.
