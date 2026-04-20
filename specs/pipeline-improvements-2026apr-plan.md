# Plan: Pipeline Improvements — April 2026

## Status

Draft (master plan, not an implementable spec)

## Purpose

This document sequences the pipeline improvement work for the April 2026 cycle.
It does not restate implementation detail; each slice below points at its own
daughter spec. Priorities are ruthless: ship what fixes a pain we actually
felt, defer everything else.

## Background

`pipeline-improvement-plan-spec.md` bundled four unrelated initiatives behind
a vague "hardening" label. `pipeline-improvement-plan-critique.md` (2026-04-19)
rejected that spec and recommended a split. This plan adopts the split and
reorders by measured pain, incorporating selected patterns from the April 2026
industry reviews (gpt, gemini) that directly address problems we hit this cycle.

The single largest pipeline pain observed to date: **test-writer silently
pins assumptions the spec did not make**, the reviewer objects, and the loop
oscillates to cap-exit. The 6c orchestrator slice hit this twice. Prompt
patches landed at the end of that session but do not address the structural
cause (agent has nowhere to ask).

## Strategy

1. Each slice is independently shippable. No cross-slice deps in Tier 1.
2. Specs stay intent-level per the pipeline's spec philosophy.
3. Every slice either fixes a concrete pain or removes an unambiguous blocker
   (portability, observability). Aspirational enterprise patterns are rejected.
4. When in doubt, defer.

## Tier 1 — Vital (ship in order)

### Slice 1 — Portable executable discovery
- Spec: `paths-shutil-which-spec.md`
- Pain: hardcoded `APPDATA/npm/*.cmd` in provider modules blocks Linux/macOS.
- Size: ≤1 day, mechanical.
- Lands first to build confidence in the new split before touching pipeline loop.

### Slice 2 — Clarify stage
- Spec: `clarify-stage-spec.md`
- Pain: agents pin under-specified details (constructor shapes, entry method
  names), reviewer objects, oscillation → cap-exit.
- Approach: insert a Stage 0 that surfaces top-N ambiguities *before*
  test-writing commits to a shape. Advisory by default; can be forced on.
- Highest-leverage item in this cycle. Direct structural fix for 6c-class failures.

### Slice 3 — OTel tracing
- Spec: `otel-tracing-spec.md`
- Pain: post-mortems on cap-exits rely on log scraping; pipeline internals are
  opaque even though the multi-agent project already emits OTel to Phoenix.
- Approach: wrap the run in OTel spans (run → stage → iteration), honor
  standard OTLP env vars, no-op when unset.
- Pays back on every future failure investigation.

## Tier 2 — Valuable (only after Tier 1 lands green)

### Slice 4 — Spec frontmatter
Add optional YAML frontmatter to specs (slice-size hints, dependencies,
future role-model overrides). Tiny, purely enabling. Defer until P5 needs it.

### Slice 5 — Per-role model routing
Allow pipeline-config.toml to override model per role (scout vs test-writer vs
reviewer). Local-first constraint preserved; this just unlocks "cheap model
for navigation, stronger model for review." Defer; requires P4.

## Tier 3 — Deferred or rejected

- **Provider plugin registry** — worth doing eventually, but nothing today
  requires plugin-level extensibility. Defer until a second provider family
  arrives.
- **GBNF grammar enforcement** — the critique showed 6c-class failures are
  semantic over-pinning, not format failures. Revisit only if a concrete
  format-failure benchmark appears.
- **SDK adapters (Gemini/Claude via SDK)** — contradicts the CLI-as-provider
  thesis the project is built on. Rejected.
- **Rich TUI dashboard** — pipeline is unattended; ANSI-cursor TUIs fight CI
  logs and the orchestrator-session workflow. Rejected.
- **MCP tool manifests, permission tiers, worktree-based CIV parallelism,
  skeleton repos, gh-skill portability, DORA/PR-acceptance dashboards** —
  enterprise-team patterns; single-user tool does not need them. Rejected
  for this cycle; re-evaluate if the tool grows users.

## Sequencing and gates

- P1 ships → verify WSL smoke run → mark P1 done.
- P2 ships in advisory mode → run on one prior cap-exit spec to confirm it
  surfaces the right ambiguities → switch default to blocking.
- P3 ships → verify Phoenix renders a full run → update README.
- Tier 2 gate: all three Tier 1 slices landed and a full slice run uses them
  successfully.

## Non-goals (this cycle)

- No changes to the test-writer or reviewer prompts beyond what Slice 2
  requires for clarify-context injection.
- No new provider families.
- No rewrite of `run_pipeline.py` beyond additive wrapping (OTel, clarify stage).
- No public-API breakage for existing `--provider` / `--max-revisions` flags.
