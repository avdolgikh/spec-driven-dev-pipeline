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

- **Codex**: Models `gpt-5.1-codex-mini` (test-writer/implementer), `gpt-5.1-codex` (implementer), `gpt-5.2-codex` (reviewer). Uses `--ephemeral --skip-git-repo-check` and stdin for prompts.
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

**Cleanup of Codex's hardening implementation** -- tracked in `specs/hardening-cleanup-plan.md`.
Codex implemented `pipeline-hardening-spec.md` correctly but with scope creep and noise. Manual cleanup in progress before pipeline runs.

---

## Known Gaps

Tracked in `specs/pipeline-hardening-spec.md`. The four gaps found during the smoke-test validation:

1. **No final pytest gate before VERIFIED** -- after Code Review approves, pipeline skips straight to VERIFIED without running tests. Proven by OpenCode run (reviewer approved failing code).
2. **No retry on transient provider failures** -- a single provider error crashes the pipeline. Proven by Claude run (transient empty exit 1 required manual resume).
3. **Stage 1 effect check too loose** -- `allow_existing=True` lets test generation pass even if no task-specific tests were written. Proven by gemma4 run (no smoke-test tests created, Stage 1 passed on pre-existing pipeline tests).
4. **Gemini output extraction loses tool-use context** -- when Gemini creates files via tools, the JSON response field is empty. Pipeline log shows no useful output.
