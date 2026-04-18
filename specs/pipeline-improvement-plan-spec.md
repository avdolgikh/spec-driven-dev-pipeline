# Spec: Pipeline Hardening

## Status

Draft

## Goal

Transition the pipeline from a CLI-dependent prototype into a robust, extensible, and observable platform by moving to direct SDK adapters, enforcing structured output via grammars, and adding comprehensive observability.

## Scope

- **Provider Infrastructure**: Direct SDK adapters for Gemini and Claude; dynamic registry.
- **Reliability**: GBNF grammar support for Ollama to enforce `FILE:` blocks.
- **Observability**: OpenTelemetry tracing and a Rich-based TUI for real-time monitoring.
- **DX**: Cross-platform path resolution and YAML frontmatter for specs.

## Requirements

### REQ-1: SDK-Based Providers & Dynamic Registry

Core logic in `src/spec_driven_dev_pipeline/providers/`:

- `ProviderRegistry.register(name, provider_class)` -- Dynamic plugin system.
- `GeminiSDKProvider` -- Implementation using `google-generativeai`.
- `ClaudeSDKProvider` -- Implementation using `anthropic`.

**Behavior:**
1. Providers use official SDKs instead of calling external CLI binaries via `subprocess`.
2. Model tiers (Economy/Premium) are handled natively by the provider class.
3. Errors (429s, 500s) are caught and raised as structured `PipelineError` types.

### REQ-2: Structured Output Enforcement (GBNF)

Core logic in `src/spec_driven_dev_pipeline/utils/grammar.py`:

- `generate_file_block_grammar() -> str` -- Returns a GBNF string for Ollama.
- `OpenCodeProvider` updated to pass grammar to the Ollama API.

**Behavior:**
1. When using local models via OpenCode/Ollama, the pipeline attaches a grammar constraint.
2. The LLM is physically unable to produce prose or invalid formats; it must emit `FILE:` blocks.

### REQ-3: Observability & Rich Dashboard

Core logic in `src/spec_driven_dev_pipeline/utils/observability.py`:

- `TraceManager.start_span(name, attributes)` -- Wraps pipeline stages in OTLP spans.
- `PipelineDashboard` -- A `rich.live` dashboard for the CLI.

**Behavior:**
1. `run_pipeline.py` initializes a `TraceManager`.
2. Each stage (Test Generation, Review, Implementation) creates a child span.
3. The CLI output is replaced with a clean, multi-column dashboard showing agent status and test metrics.

### REQ-4: Cross-Platform Robustness

Logic in `src/spec_driven_dev_pipeline/core.py` and `providers/`:

- Replace all hardcoded Windows strings (e.g., `APPDATA`, `.cmd`) with `shutil.which` and `pathlib.Path`.

## Acceptance Criteria

### AC-1: CLI Independence
- `GeminiSDKProvider` works without `gemini-cli` installed on the system.
- `ClaudeSDKProvider` works without `claude-code` installed.

### AC-2: Format Reliability
- A "Small" model (e.g., Qwen 3.5) produces 100% valid `FILE:` blocks over 10 consecutive runs when GBNF is enabled.

### AC-3: Observability
- Pipeline execution generates a trace file or sends data to an OTLP-compatible collector (e.g., Jaeger, Phoenix).
- CLI shows a live progress bar and agent status table.

### AC-4: Platform Parity
- All pipeline tests pass on both Windows and Linux without manual environment modifications.

## Package Layout

```
src/spec_driven_dev_pipeline/
  providers/
    registry.py        # REQ-1: ProviderRegistry
    gemini_sdk.py      # REQ-1: GeminiSDKProvider
    claude_sdk.py      # REQ-1: ClaudeSDKProvider
    base.py            # Updated: Registry hooks
  utils/
    grammar.py         # REQ-2: generate_file_block_grammar()
    observability.py   # REQ-3: TraceManager, PipelineDashboard
scripts/
  run_pipeline.py      # Updated: Registry initialization, TUI startup
tests/
  test_provider_registry.py
  test_grammar_gen.py
  test_observability.py
```
