# Critique: `pipeline-improvement-plan-spec.md`

## Meta

- **Target spec:** `specs/pipeline-improvement-plan-spec.md`
- **Type:** Review feedback (not a spec to implement)
- **Date:** 2026-04-19
- **Reviewer:** Claude (orchestrator)

## TL;DR

The spec bundles four unrelated initiatives behind a vague "hardening" label, silently reverses the project's core architectural commitment (CLI-as-provider), and prescribes implementation details (module paths, class names, dependencies) instead of intent — violating the project's own spec philosophy. Two of four requirements oversell what they actually deliver.

## Concerns (each grounded in code/spec evidence)

### 1. REQ-1 contradicts the project's stated value proposition

`README.md:9–32` and `src/spec_driven_dev_pipeline/providers/base.py:21` define the abstraction as: *each provider wraps a CLI tool, exposes `run_role()`, returns `ProviderExecution`.* That's why `--provider codex|claude|gemini|opencode` all work via `subprocess`.

**Switching Gemini and Claude to SDKs creates two provider patterns** in the same codebase (SDK + CLI), doubles the test/auth surface, and breaks the "I already have my CLI authed" UX. It also only names two providers — Codex stays CLI (`providers/codex.py:117`), OpenCode stays CLI (`providers/opencode.py:193`) — so the inconsistency is permanent.

The actual pain (`providers/codex.py:47`, `providers/gemini.py:35`, `providers/opencode.py:134` — hardcoded `APPDATA/npm/*.cmd`) is solved by **`shutil.which`**, which is REQ-4. REQ-1 conflates "fix Windows path leakage" with "rewrite the provider layer."

### 2. REQ-2 overstates GBNF and ignores its real architecture cost

- *"physically unable to produce prose or invalid formats"* — only true at the llama.cpp generation layer. GBNF doesn't validate path correctness, file completeness, or that the model targets the right test name. The benchmark report (`README.md:135–145`) showed format failure was only one of several issues; **GLM-4.7-Flash already produced parseable blocks but failed across revisions** — GBNF doesn't address that.
- `OpenCodeProvider` doesn't call Ollama; it shells out to `opencode.cmd` (`providers/opencode.py:183`). To "attach a grammar constraint" you must bypass OpenCode and talk to Ollama directly. The spec hand-waves this pivot.

### 3. REQ-3 bundles two unrelated features and picks the wrong UX

OTel tracing (legitimate) is glued to a `rich.live` TUI dashboard (preference). The pipeline's primary mode is **unattended**: `scripts/run_benchmark.py` captures stdout per model, the existing user workflow orchestrates it from another agent session and reads `.pipeline-state/`, and CI logs hate ANSI-cursored TUIs. Tracing has a clean industry boundary (OTLP env vars) — ship that. The dashboard is a separate, optional concern that should not block observability.

### 4. The spec violates the project's own spec philosophy

Per established convention (intent-level specs, ~150 lines, leave room for agents): this spec dictates:

- Exact module paths (`providers/registry.py`, `utils/grammar.py`, `utils/observability.py`)
- Exact symbol names and signatures (`ProviderRegistry.register(name, provider_class)`, `TraceManager.start_span(name, attributes)`, `generate_file_block_grammar() -> str`)
- Exact third-party deps (`google-generativeai`, `anthropic`, GBNF)

That's a design doc, not a spec. The agents have nothing to design.

### 5. Acceptance criteria are mostly unmeasurable

- **AC-1** *"works without `gemini-cli` installed"* — passes trivially if you only import the module. Needs: "complete an end-to-end pipeline run using SDK provider against recorded fixtures."
- **AC-3** *"generates a trace file or sends data"* — should enumerate required spans/attributes (e.g., `pipeline.stage`, `provider.model`, `review.decision`) so reviewers can verify.
- **AC-4** *"all tests pass on Windows and Linux"* — passing tests ≠ shell-out parity. Needs an actual CI matrix.
- **AC-2** is the only sharp one (100% over 10 runs).

### 6. Bundling makes it un-shippable in pieces

REQ-1, 2, 3, 4 share no design rationale, no common files, and no common rollback boundary. For a **public tool**, each should be its own spec with its own ACs, its own benchmark, its own ADR. Bundled, a partial failure (say AC-2 misses on some models) blocks the rest.

### 7. Title / filename collision

File is `pipeline-improvement-plan-spec.md` but title is `# Spec: Pipeline Hardening` — duplicating the already-shipped `specs/pipeline-hardening-spec.md`. Future readers will confuse the two.

### 8. Silent dependency creep & risk not discussed

Adding `anthropic` + `google-generativeai` introduces two vendor SDKs that ship breaking changes quarterly. No version-pinning policy, no "what happens when the SDK breaks" plan, no mention that the SDK path requires API keys (vs. existing CLI auth). For a public tool, that's a maintenance debt owed upfront.

## Recommended split

Cut into four independent specs, in this priority order:

1. **`paths-shutil-which-spec.md`** — REQ-4 only. Tiny, mechanical, ships in a day.
2. **`otel-tracing-spec.md`** — REQ-3 stripped to OTel only. No TUI. Standard exporter env vars.
3. **`grammar-output-spec.md`** — REQ-2 with honest scope: "direct Ollama path, only for test-writer/implementer roles, only when local backend supports GBNF; falls back to current FILE: parser otherwise." Acknowledge the cross-revision failure mode.
4. **`provider-registry-spec.md`** — REQ-1 split into two:
   - (a) plugin registry that works for the existing CLI providers (no scope change),
   - (b) optional SDK adapters as a *separate* spec, justified by a concrete user need (not "modern feels better").

Drop the dashboard requirement entirely or move it to a `dx-tui-spec.md` for later.

## Bottom line

The current spec reads like a wish list for a v2 rewrite, not an improvement plan for a working tool. Rewrite it as four focused, intent-level specs and the agents will actually have room to design — yielding cleaner reviews, smaller PRs, and a healthier public-tool surface.
