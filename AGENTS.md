# AGENTS.md - Repo-Wide Rules & Context

All agents (test-writer, implementer, reviewer) inherit these rules automatically.

---

## Project

**spec-driven-dev-pipeline** -- A provider-agnostic, spec-driven autonomous TDD pipeline.
This tool automates the TDD cycle: spec -> tests -> implementation -> validation -> review.

---

## Rules

### Rule #1: Document Everything On The Fly
Every significant decision, convention, or discovery must be documented immediately.

### Rule #2: UV Only - No Pip
- Use `uv` for all package management, venv creation, and script execution.
- Commands: `uv sync`, `uv run pytest`, `uv run python`.

### Rule #3: Spec-Driven Development
- Every feature starts as an approved spec in `specs/`.
- Tests are written first, reviewed, then frozen.
- Implementation is written against frozen tests.
- No ad-hoc coding outside this cycle.

### Rule #4: No Unnecessary Files
- Only create files required by the current spec.

### Rule #5: Reproducibility
- No global mutable state.
- Tests must be deterministic.

### Rule #6: Git Commits
- Commit messages are one line only.
- Never mention AI, co-authors, or tools.

### Rule #7: Keep It Simple
- Minimal dependencies.
- Prefer the smallest correct diff.

### Rule #8: Testable Architecture in Specs
- Logic must live in **importable library modules** under `src/`, not in scripts.
- Scripts (`scripts/`) are **thin CLI wrappers**: argparse + call library functions.
- Specs must list library module functions with signatures in the Package Layout section.
- This ensures tests can import and exercise functions directly, without subprocess hacks or AST parsing.

### Rule #9: Specs Are High-Level Intent, Not Pseudo-Code
- Target ~150 lines for a spec. If it looks like pseudo-code, it is too detailed.
- DO specify: Goal, Scope, REQ prose, observable ACs, Package Layout hints, Source Files.
- DO NOT specify: exact class signatures, full method signatures, attribute names, span name strings, event topic strings, enum values, per-test assertions, Return-on-Failure tables, detailed span-tree diagrams.
- Rationale: the pipeline's value is autonomous generation by test-writer + implementer. Over-specified specs (a) do the agents' design work, (b) create ambiguity vectors at every pinned string (literal vs enum vs symbolic reference), (c) bloat the spec until reviewers nitpick micro-details instead of meaning.
- Evidence: over-detailed spec (580 lines, Public Contracts + Test Matrix with assertions + span tree with literal names) burned 3 pipeline runs on `hybrid-foundation` (2026-04-18) before being slimmed back. The minimal M1 template successfully shipped 4 prior specs.

---

## Spec Template

See `specs/TEMPLATE.md`. All new specs must follow this structure (Rule #8: testable architecture).

---

## Tech Stack

| Concern | Tool |
|---------|------|
| Language | Python 3.11+ |
| Package manager | UV (only) |
| Testing | pytest |
| Linting/formatting | ruff |

## Package Layout
```text
src/spec_driven_dev_pipeline/     # library code
  core.py                         # PipelineConfig, PipelineRunner, PromptBuilder
  providers/                      # provider adapters (claude, codex, gemini, opencode)
  prompts/                        # bundled role prompt templates (.md)
  schemas/                        # JSON schemas (review_decision.json)
scripts/                          # runnable scripts (CLI entry points)
  run_pipeline.py                 # pipeline CLI (--provider, --config, --repo-root)
tests/                            # pytest tests
specs/                            # approved specs
opencode.json                     # opencode CLI config (registers Ollama provider)
```

---

## Provider Status (smoke-test-spec.md, 2026-04-08)

| Provider | CLI Version | Status | Notes |
|----------|-------------|--------|-------|
| Codex    | 0.115.0     | PASS   | Full pipeline. 1 test revision (reviewer caught missing numpy test). Code approved first pass. |
| Claude   | 2.1.97      | PASS   | Full pipeline. 1 test revision (opus caught missing numpy test). 1 transient reviewer failure (empty exit 1, resolved on resume). Code approved first pass. |
| Gemini   | 0.37.0      | PARTIAL | Stages 1-4 passed with all-flash override (`GEMINI_MODEL_PREMIUM=gemini-2.5-flash`). Stopped at Stage 5 Code Review due to quota (429). State saved at CODE_VALIDATED -- resumable. |
| OpenCode | 1.3.0       | PASS*  | Pipeline completed (exit 0) with qwen3.5. Adapter works: FILE: format, review JSON, implementation all functional. *One post-pipeline manual fix needed (np.random.seed 32-bit limit). Small models miss edge cases. |

### Provider-Specific Notes

- **Codex**: Models `gpt-5.4-mini` (test-writer), `gpt-5.3-codex` (implementer), `gpt-5.4` (reviewer). ChatGPT-account Codex CLI rejects `gpt-5`, `gpt-5-codex`, `gpt-5.1-*`, `gpt-5.2-*`, `gpt-5.3`, `gpt-5.4-codex` ("not supported when using Codex with a ChatGPT account"). Override via `CODEX_MODEL_TEST_WRITER` / `CODEX_MODEL_IMPLEMENTER` / `CODEX_MODEL_REVIEWER`. Uses `--ephemeral --skip-git-repo-check` and stdin for prompts.
- **Gemini**: Uses `-o json` output. `_extract_response` parses JSON for tool-using models. Quota is per-model; flash and pro have separate limits.
- **OpenCode**: Requires `opencode.json` in repo root to register Ollama as a custom provider. Without it, `ollama/` model prefix is not recognized. Local models need >30B parameters to reliably follow structured output formats.
- **Claude**: Uses `--permission-mode bypassPermissions`. Strips `CLAUDECODE` env var to avoid recursion.

### Cleanup Between Runs
When re-running the pipeline with a different provider on the same task:
1. Delete `.pipeline-state/<task>.json` and `.pipeline-state/<task>.log`
2. Delete any generated test files (e.g. `tests/test_seed*.py`)
3. Delete any generated source files (e.g. `src/spec_driven_dev_pipeline/utils/`)
4. State file records the provider name; mismatches cause EXIT_STATE_PROVIDER_MISMATCH (exit 6)

---

## Local Checks

Run all checks (same as CI):
```bash
uv run ruff check .          # lint
uv run ruff format --check . # format check (drop --check to auto-fix)
uv run pyright src/           # type check
uv run pytest                 # tests
```

---

## Active Work

### NEXT STEP: Pipeline Hardening (2026-04-18)
- **Primary Spec:** `specs/pipeline-improvement-plan-spec.md`
- **Goal:** Move to SDK-based providers, implement GBNF grammars for local models, and add OpenTelemetry/Rich observability.

### Local Model Benchmarking (2026-04-10) — DONE

Full report: `benchmarks/benchmark-calc-report.md`

- **Task:** `specs/benchmark-calc-spec.md` (expression evaluator, 4 functions, 10 ACs)
- **Framework:** `specs/benchmark-framework-spec.md` (runner, judge, metrics, leaderboard)
- **Result:** All 4 local models failed early. GLM-4.7-Flash best at 1.8/5. Structured output (FILE: blocks) is the main bottleneck.
- **Artifacts:** `benchmarks/results/`, `benchmarks/leaderboard.md`, `benchmarks/leaderboard.json`

### Improving Local Model Scores (2026-04-10)

**Specs ready:**
- `specs/pipeline-improvement-plan-spec.md` — Infrastructure hardening: direct SDK adapters, GBNF grammar constraints for local models, OpenTelemetry tracing, and a Rich-based TUI.
- `specs/format-repair-spec.md` — Post-processing repair layer: converts markdown fences, tool-call JSON, and filename comments into `FILE:` blocks before parsing.
- `specs/few-shot-prompts-spec.md` — Role-specific few-shot examples appended to OpenCode prompts so models see the exact expected output format.

**Future improvements (no spec yet):**
- **Relaxed filename matching** — Accept `calc_test.py` in addition to `test_calc.py`. Qwen 3.5 produced correct format but wrong naming. Low effort, high impact for that failure mode.
- **Smaller task granularity** — Split benchmark tasks into sub-tasks (e.g., tokenizer-only, parser-only). 4 functions + 10 ACs in one shot may exceed small model capacity.
- **Ollama grammar constraints** — Use GBNF grammars to force `FILE:` block structure at the generation level. Guarantees format compliance but requires Ollama API integration (not CLI).

---

## Known Gaps

All four gaps from `specs/pipeline-hardening-spec.md` are now implemented (REQ-1 through REQ-4). Additionally, REQ-3's Stage 1 effect check now derives valid test file names from source files mentioned in the spec (e.g., spec mentions `seed.py` → `test_seed` is accepted as a task-specific test term).

### Misleading `EXIT_REVIEWER_MODIFIED_FILES` on concurrent host edits (2026-04-12) — FIXED

- `_enforce_reviewer_immutability` hashed the full `hash_targets` list (`AGENTS.md`, `pyproject.toml`, `scripts`, `specs`, `src`, `tests`) and surfaced a generic error that blamed the reviewer. Host-side edits to any of those paths during a reviewer stage tripped the guard with no diagnostic detail — observed with the `multi-agent` project on 2026-04-12 (orchestration-code-analysis, Stage 2 iter 2; reproduced again at iter 3 after a host edit to `specs/observability-phase1-spec.md`).
- **Fix (2026-04-12):** `_repo_file_hashes()` now snapshots per-file hashes; `_enforce_reviewer_immutability` compares before/after dicts and the failure message lists `added`/`removed`/`modified` paths and notes that concurrent host edits are the most common cause. Call sites in Stage 2 and Stage 5 updated; existing test extended to assert the changed path is reported. 32/32 pipeline tests pass.

### Configurable validation suite (2026-04-12) — ADDED

- **Motivation:** `test_command` only ran pytest. Agents could produce code that passed tests but failed `ruff`/`pyright` on CI (observed twice on `multi-agent` after push). Per user directive, the pipeline agent must enforce the same checks CI runs.
- **Change:** `PipelineConfig.validation_commands: list[list[str]] | None` added. When set, `_run_pytest_gate` iterates each command in order and fails on the first non-zero exit; otherwise falls back to `test_command` for backward compat. Prompt/log strings use the new helper `_describe_validation_suite(config)` (renders as `"cmd_a && cmd_b && ..."`).
- **Usage:** consumers pass `--config <path.toml>` to `scripts/run_pipeline.py`. Example TOML:
  ```toml
  validation_commands = [
      ["uv", "run", "ruff", "check", "src/", "tests/"],
      ["uv", "run", "ruff", "format", "--check", "src/", "tests/"],
      ["uv", "run", "pyright", "src/"],
      ["uv", "run", "python", "-m", "pytest"],
  ]
  ```
- **Coverage:** two new tests in `test_pipeline_core.py` (order + early-exit; description formatting). 101/101 pipeline tests pass. Ruff/format/pyright clean.

### Gemini Retry Pending

Gemini smoke-test stopped at `CODE_VALIDATED` due to 429 quota. State saved — resumable when quota frees up.
