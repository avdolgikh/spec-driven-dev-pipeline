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

### Rule #10: Wrapping Up — Skip Red Tests For Unfinished Slices Before Pushing
- TDD produces naturally-red test suites while an implementation is in-flight. A push with red tests breaks CI for everyone.
- Before `git push`: run `uv run ruff check . && uv run ruff format --check . && uv run pyright src/ && uv run pytest`. Any red must be resolved.
- If the red is a frozen test file whose implementation slice is not yet landed, skip the **whole file** with a file-level `pytestmark = pytest.mark.skip(reason="Slice <id> (<slice-name>) implementation pending; remove this skip when <target module> lands. See AGENTS.md Known Gaps.")`.
  - Place `pytestmark` **after** all imports (otherwise ruff E402 fires).
  - Never edit individual assertions or delete tests to make CI green — the test contract is frozen, and patching it defeats the reviewer's approval.
  - The skip is a temporary CI-green measure, not a test rewrite. The implementation slice unskips by deleting the `pytestmark` block in the same commit that lands the impl.
- If the red is a formatting / lint / typecheck regression, fix it directly — never skip lint.
- Pattern applies equally to `ruff format --check` failures on files touched by an in-flight slice: run `uv run ruff format <file>` before pushing.
- When skipping a file, add a one-line Known-Gaps entry so the skip is discoverable from AGENTS.md, not only from the test file itself.

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

### NEXT STEP: Pipeline Improvements — 2026-04-20

The bundled `pipeline-improvement-plan-spec.md` was reviewed against its critique (`pipeline-improvement-plan-critique.md`) and superseded by a ruthlessly-split plan. The industry-review PDFs in `docs/` (gpt, gemini) were filtered through the same pain-first lens; most enterprise patterns were rejected as out of scope for a single-user public tool.

- **Master plan:** `specs/pipeline-improvements-2026apr-plan.md`
- **Tier 1 specs (ship in order):**
  1. `specs/paths-shutil-which-spec.md` — portable executable discovery (~1 day, mechanical). Replaces hardcoded `APPDATA/npm/*.cmd` in providers with a `shutil.which`-based resolver; unblocks Linux/macOS.
  2. `specs/clarify-stage-spec.md` — new Stage 0 that surfaces spec ambiguities before test-writing. Structural fix for the 6c-class oscillation failure mode (test-writer silently pins under-specified shapes → reviewer objects → cap-exit). Advisory-first rollout; `off` mode preserves current behavior.
  3. `specs/otel-tracing-spec.md` — OTel spans around existing stage seams, export via standard `OTEL_*` env vars; no-op when unset. Pays back on every future cap-exit post-mortem.
- **Tier 2 (parking lot, not yet specced):** optional YAML frontmatter on specs, then per-role model routing. Only after all three Tier 1 slices ship green.
- **Tier 3 (explicitly rejected this cycle):** SDK provider adapters, GBNF grammar enforcement, Rich TUI dashboard, MCP tool manifests, permission tiers, worktree-based CIV parallelism, skeleton repos, `gh skill` portability, DORA / PR-acceptance dashboards. Rationale lives in the master plan's "Tier 3" section and in the critique.
- **Execution model — "AI builds AI":** Slice 1 (`paths-shutil-which-spec.md`) is the first pipeline improvement implemented *through the pipeline itself*, using Codex as the provider. First time the tool builds on its own source. Specs stay intent-level per Rule #9; test-writer and implementer own the design.

### Local Model Benchmarking (2026-04-10) — DONE

Full report: `benchmarks/benchmark-calc-report.md`

- **Task:** `specs/benchmark-calc-spec.md` (expression evaluator, 4 functions, 10 ACs)
- **Framework:** `specs/benchmark-framework-spec.md` (runner, judge, metrics, leaderboard)
- **Result:** All 4 local models failed early. GLM-4.7-Flash best at 1.8/5. Structured output (FILE: blocks) is the main bottleneck.
- **Artifacts:** `benchmarks/results/`, `benchmarks/leaderboard.md`, `benchmarks/leaderboard.json`

### Improving Local Model Scores (2026-04-10)

**Specs ready:**
- `specs/pipeline-improvement-plan-spec.md` — Infrastructure hardening: direct SDK adapters, GBNF grammar constraints for local models, OpenTelemetry tracing, and a Rich-based TUI. **SUPERSEDED 2026-04-20** by the split plan (`specs/pipeline-improvements-2026apr-plan.md`); see `specs/pipeline-improvement-plan-critique.md` for rationale.
- `specs/format-repair-spec.md` — Post-processing repair layer: converts markdown fences, tool-call JSON, and filename comments into `FILE:` blocks before parsing.
- `specs/few-shot-prompts-spec.md` — Role-specific few-shot examples appended to OpenCode prompts so models see the exact expected output format.

**Future improvements (no spec yet):**
- **Relaxed filename matching** — Accept `calc_test.py` in addition to `test_calc.py`. Qwen 3.5 produced correct format but wrong naming. Low effort, high impact for that failure mode.
- **Smaller task granularity** — Split benchmark tasks into sub-tasks (e.g., tokenizer-only, parser-only). 4 functions + 10 ACs in one shot may exceed small model capacity.
- **Ollama grammar constraints** — Use GBNF grammars to force `FILE:` block structure at the generation level. Guarantees format compliance but requires Ollama API integration (not CLI).

---

## Known Gaps

All four gaps from `specs/pipeline-hardening-spec.md` are now implemented (REQ-1 through REQ-4). Additionally, REQ-3's Stage 1 effect check now derives valid test file names from source files mentioned in the spec (e.g., spec mentions `seed.py` → `test_seed` is accepted as a task-specific test term).

### `src/spec_driven_dev_pipeline/core.py` is too long (2026-04-21) — KNOWN, OPEN

- Through Slices 1–3b `core.py` has grown past ~1700 lines. Readable end-to-end but at the upper edge of "one file I can hold in my head."
- Candidate split (validate during design, not prescriptive): state machine / enforcement (hash, freeze, reviewer-immutability) / stage orchestration (runner) / prompt+config dataclasses / tracing-wiring helpers.
- Treat as its own pipeline slice (spec-driven). Don't bundle with a feature slice. Slice after Tier 2 (`spec-frontmatter`, `per-role-model-routing`) lands so the refactor sees the fuller shape.

### Stage 5 reviewer can prescribe new tests, which Stage 5b freeze then rejects (2026-04-21, Slice 3b) — KNOWN, OPEN

- Observed during 3b attempt 3: reviewer blocked with *"Clear or shut down prior tracing state … and add a wiring test for the configured-then-unconfigured sequence."* Codex's Stage 5b revision complied literally, modifying the frozen test file; `_enforce_test_freeze` (correctly) rejected the run with `FAIL: frozen test files were modified after the test-freeze boundary.` Pipeline exited without advancing past `CODE_VALIDATED`.
- Root cause is a prompt scope issue: the reviewer role should assess the implementation against the *existing* spec ACs, not prescribe test additions that belong in an earlier stage. Fix belongs in `prompts/reviewer.md` — constrain Stage 5 reviewer output to impl-side findings; test-coverage asks are out of scope post-freeze.
- Worked around manually: reverted the test-file mutation and relaunched; reviewer approved on the second attempt once no new tests were requested.

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

### Test-writer helpers now constrained (2026-04-20) — ADDED

- **Motivation:** consumer project (multi-agent `hybrid-foundation-orchestrator`) cap-exited with all-over-pin blockers even though direct `assert` lines were behavioral. Root cause: test helpers (`_build_orchestrator`, `_find_validator_class`, etc.) used `inspect.signature` kwarg enumeration, class-name substring scanning, and "exactly-N-fields" model acceptance — structural pins dressed as "detection logic". The existing "test observable behavior, not internal shape" principle only governed assertions, not helpers.
- **Change:** `src/spec_driven_dev_pipeline/prompts/test_writer.md` gained a new principle "Helpers and fixtures are assertions too" that forbids:
  - `inspect.signature` / kwarg-layout enumeration / preset accepted-parameter lists
  - class-name or attribute-name substring matching to "discover" the target
  - "exactly N fields" restrictions on a model
  - requiring the implementer to expose an EXTRA public API (transition callable, hook, setter) just to make a scenario exercisable
  - final guidance: "If you cannot construct the scenario through behavior alone, the spec gap is the problem — flag it, don't invent a structural workaround."

### Reviewer acknowledges minimum-necessary pinning (2026-04-20) — ADDED

- **Motivation:** after the test-writer prompt fix above, `hybrid-foundation-orchestrator` still cap-exited. Root cause was reviewer miscalibration: the reviewer was flagging any constructor-signature or entry-method commitment as over-constraint, even though a test against a spec-named class necessarily commits to *some* shape. The test-writer was in an impossible position — "don't enumerate alternatives" + "don't pin any single shape" has no solution.
- **Change:** `src/spec_driven_dev_pipeline/prompts/reviewer.md` gained a new principle "Minimum-necessary pinning is not over-constraining" that treats the following as acceptable, NOT blockers:
  - constructing a spec-named class with required injected collaborators under one chosen keyword/positional layout
  - calling one public entry-point method (e.g. `run`)
  - passing a spec-named dependency under a specific parameter name
- **Line the reviewer must enforce:** one committed shape per construction/entry surface is fine; enumerated alternatives, substring-scanning, "exactly N fields", or mandated EXTRA public APIs are blockers. Also added: "Under-specified spec surfaces" rule — if a REQ implies a public class but the spec does not name the signature, tests necessarily commit to something; that commitment is not a blocker. Spec feedback belongs at the spec stage, not in test-suite blockers.
- **Both prompt changes are uncommitted in this repo.** When the user commits next, both prompt fixes should go in together.

### Stage-1 effect check: bare `.py` filename extraction (2026-04-21, Slice 1) — FIXED

- **Motivation:** Slice 1 `paths-shutil-which` first run: Codex correctly produced `tests/test_executables.py` + edits to `tests/test_pipeline_providers.py`, but the pipeline's Stage 1 effect check rejected the run with `FAIL: ... did not modify tests/ with files for task 'paths-shutil-which'`.
- **Root cause:** `_build_task_test_terms` in `core.py` only scanned `.py` filenames inside single backticks (`` `x.py` ``). The `paths-shutil-which` spec listed the files under a triple-backtick Package Layout block, which the single-backtick regex did not match. Zero `.py` terms extracted → no test file was recognised as task-specific.
- **Fix (2026-04-21):** Added a second regex `\b([A-Za-z_][A-Za-z0-9_]*\.py)\b` that scans the whole spec text for bare `.py` filenames. The backtick path is preserved (higher precision for inline mentions). Existing tests pass.

### Reviewer oscillation / iteration-weighted approval gap (2026-04-21, Slice 3) — KNOWN, OPEN

- **Motivation:** Original `otel-tracing-spec.md` (5 REQs + 5 ACs, ~121 lines) cap-exited Codex at Stage 2 iter 8 with 10 distinct, legitimate reviewer blockers accumulated across iterations — no single iteration's concern was wrong, but the pipeline couldn't converge within `--max-revisions 8`. Gemini retry hit quota. Slice was split into `otel-tracing-init` + `otel-tracing-wiring` and both narrower slices landed (3a) or made progress (3b).
- **Finding:** The `reviewer.md` anti-oscillation rule covers contradictory-flip-flop oscillation ("would invert a previous request → prefer approval"), but NOT the sibling failure mode where each iteration surfaces a *different* legitimate gap. By iter 5+ on a Stage-2 review loop, a reviewer that keeps finding new nits is effectively preventing convergence even if each individual blocker is valid.
- **Candidate fix (not yet implemented):** Add an "iteration-weighted approval" rule to `reviewer.md`: by Stage-2 iter ≥5, the reviewer should approve unless the current blocker is either (a) a newly-introduced regression from the last revision, or (b) an AC that is not exercised *at all* (not just imperfectly exercised). Also: confirmed in-run reviewer reversal at 3a iter 3→4 ("assert no tracer acquisition occurs" → "don't forbid tracer acquisition"), which the existing rule *should* already catch but apparently didn't.

### Stage-1 effect check false-positive when spec omits new test file (2026-04-21, Slice 3b) — KNOWN, OPEN

- **Motivation:** Slice 3b attempt 1: test-writer correctly created a new file `tests/test_pipeline_tracing_wiring.py` (sensibly separated from 3a's `tests/test_tracing.py`), but the effect check reported `FAIL: Stage 1: Test Generation did not modify tests/ with files for task 'otel-tracing-wiring'. Existing task-specific test files were not modified: tests/test_tracing.py.`
- **Root cause:** The spec's Package Layout did not name `test_pipeline_tracing_wiring.py`, so `_build_task_test_terms` only extracted `test_tracing.py` (the 3a-shipped file) as "task-specific" via substring match on the task name. The effect check then demanded modifications to *that* file, which is exactly the wrong file for this slice.
- **Workaround (applied):** Update the spec's Package Layout to explicitly list the new test file AND add a "do not modify" note for sibling-slice test files.
- **Candidate fix (not yet implemented):** When Stage 1 adds a brand-new file under `tests/`, treat it as task-specific regardless of whether the spec names it. Alternatively: only flag the effect-check failure when the spec's Package Layout explicitly names an existing test file AND that file was not touched.

### Cross-provider resume blocked on state mismatch (2026-04-21, Slice 3b) — BY DESIGN, DOCUMENTED

- **Observation:** After Codex hit usage quota mid-Stage-2b, relaunching with `--provider gemini` on the same task failed immediately with `FAIL: resume provider mismatch. State recorded provider=codex, requested provider=gemini.`
- **Status:** This is by design (the per-provider role config and output formats don't cleanly interchange mid-slice), but it defeats the "silent provider switch" pre-auth when it happens mid-revision loop. Documented here so we don't re-diagnose. Workaround: reset state (`rm -rf .pipeline-state/<task>*`) before switching provider.

### Slice-3a success story: Stage-5 caught a mocked-test blind-spot (2026-04-21)

- **Context:** Slice 3a's frozen tests monkey-patched the OTLP exporter to accept any `headers=` value and asserted wiring based on constructor kwargs. Stage-5 code review spotted that the real `opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter` raises `ValueError` when `OTEL_EXPORTER_OTLP_HEADERS` is passed as a raw string (not a dict), meaning the implementation would be broken in production even though all tests passed.
- **Fix (applied in-pipeline):** Implementer added `_parse_otlp_headers` using `opentelemetry.util.re.parse_env_headers(..., liberal=True)` with a minimal fallback parser, and passed the parsed dict to the exporter.
- **Lesson:** Stage-5 reviewing against real dependency behavior (not just mocked tests) caught a bug the test-writer couldn't have surfaced without an integration test. This is the premium-tier reviewer paying off.
