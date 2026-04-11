# Spec: Direct Ollama Provider Adapter

## Status

Draft

## Goal

Replace the OpenCode CLI middleman with a direct Ollama API adapter that gives the pipeline full control over how prompts are sent to local models. The current adapter pipes everything through `opencode run` as a single user-message string, which means no system prompts, no structured output constraints, no model-native tool calling, and no parameter tuning. The benchmark showed all 4 local models failing at Stage 1 — but the root cause may be the adapter, not the models. This spec addresses that by talking to Ollama directly.

## Context

The 2026-04-10 benchmark (`benchmarks/benchmark-calc-report.md`) tested 4 Ollama models via the OpenCode CLI adapter. Key failure modes:

- **Gemma 4, Qwen3-Coder:** ignored `FILE:` format instructions entirely (prose / tool-call JSON).
- **Qwen 3.5:** correct format, wrong filename.
- **GLM-4.7-Flash:** produced `FILE:` blocks initially but lost format compliance on revision.

All format instructions were appended as plain text at the end of the user message. No Ollama API features were used. Before concluding that local models cannot drive the pipeline, we should test them with proper API integration.

## Scope

- New provider `ollama` (separate from `opencode`) that calls the Ollama HTTP API directly.
- System/user message separation.
- Ollama `options` parameter support (temperature, top_p, num_predict).
- Ollama `format` parameter for reviewer JSON output.
- Model-native tool calling for models that support it (e.g., Qwen3-Coder).
- No changes to existing providers (codex, claude, gemini, opencode).
- Integrates with existing `format_repair` and `few_shot` modules once those are implemented.

## Requirements

### REQ-1: Ollama Chat API Client

Core logic in `src/spec_driven_dev_pipeline/providers/ollama_client.py` (importable, testable):

- `OllamaClient(base_url: str = "http://localhost:11434")` -- Thin wrapper around Ollama's `/api/chat` endpoint.
- `OllamaClient.chat(model: str, messages: list[dict], options: dict | None = None, format: str | None = None, tools: list[dict] | None = None) -> OllamaResponse` -- Send a chat completion request. Returns parsed response.
- `OllamaResponse` -- Dataclass with `content: str`, `tool_calls: list[dict] | None`, `total_duration_ns: int`.

**Behavior:**

1. Uses `requests` (or `httpx`) to POST to `/api/chat` with `stream=False`.
2. Passes `options` dict directly to Ollama (controls `temperature`, `top_p`, `num_predict`, `num_ctx`, etc.).
3. When `format="json"` is set, Ollama constrains output to valid JSON (useful for reviewer role).
4. When `tools` is provided, Ollama uses model-native function calling (if the model supports it).
5. Raises `PipelineError(EXIT_PROVIDER_EXEC_FAILED)` on connection errors or non-200 responses.

### REQ-2: System/User Message Separation

Core logic in `src/spec_driven_dev_pipeline/providers/ollama.py`:

- `OllamaProvider._build_messages(prompt: str, role: str) -> list[dict]` -- Split the augmented prompt into a system message (format instructions, role identity) and a user message (spec content, task details).

**Behavior:**

1. System message contains: role identity ("You are a test-writer / implementer / reviewer"), `FILE:` output format instructions, and few-shot examples (when available).
2. User message contains: the spec content and task-specific context from the pipeline prompt.
3. For the reviewer role, the system message includes the JSON schema constraint and the user message contains the code to review.
4. This separation lets the model's chat template place format instructions where they have the most influence (many models weight system messages differently than user content).

### REQ-3: Ollama Provider

Core logic in `src/spec_driven_dev_pipeline/providers/ollama.py` (importable, testable):

- `OllamaProvider(base_url: str = "http://localhost:11434")` -- Provider that talks to Ollama directly.
- `OllamaProvider.run_role(role, prompt, repo_root, state_dir, schema) -> ProviderExecution` -- Standard provider interface.

Model selection via environment variables:

- `OLLAMA_MODEL` -- Default model for all roles (default: `qwen3.5:latest`).
- `OLLAMA_MODEL_TEST_WRITER`, `OLLAMA_MODEL_IMPLEMENTER`, `OLLAMA_MODEL_REVIEWER` -- Per-role overrides.

Generation parameters via environment variables:

- `OLLAMA_TEMPERATURE` -- Sampling temperature (default: `0.2` — lower than typical chat defaults to improve format compliance).
- `OLLAMA_NUM_CTX` -- Context window size (default: model's built-in default).
- `OLLAMA_NUM_PREDICT` -- Max tokens to generate (default: `-1`, unlimited).

**Behavior:**

1. Builds messages via `_build_messages()`.
2. Calls `OllamaClient.chat()` with appropriate `options` and `format`.
3. For test-writer/implementer: extracts `FILE:` blocks from response content, writes to disk (same as current opencode adapter).
4. For reviewer: parses JSON response (Ollama `format="json"` ensures valid JSON).
5. Applies `repair_output()` before `extract_file_blocks()` when `format_repair` module is available.
6. Applies few-shot examples via `get_few_shot_examples()` when `few_shot` module is available.

### REQ-4: Model-Native Tool Calling

Logic in `src/spec_driven_dev_pipeline/providers/ollama.py`:

- `OllamaProvider._supports_tools(model: str) -> bool` -- Check if the model supports Ollama's tool-calling interface.
- `OllamaProvider._build_tool_spec() -> list[dict]` -- Define a `create_file` tool with `path` and `content` parameters.
- `OllamaProvider._extract_from_tool_calls(tool_calls: list[dict]) -> list[tuple[str, str]]` -- Extract (path, content) pairs from tool-call responses.

**Behavior:**

1. When enabled (via `OLLAMA_USE_TOOLS=1` env var, off by default), the provider sends a `create_file` tool definition to Ollama.
2. If the model responds with tool calls, file blocks are extracted from the tool-call arguments instead of parsing `FILE:` blocks from text.
3. If the model responds with plain text despite tool definitions being sent, falls back to `FILE:` block parsing.
4. This addresses the Qwen3-Coder failure mode — instead of fighting its tool-calling training, we use it.

### REQ-5: Provider Registration

Modify `src/spec_driven_dev_pipeline/providers/__init__.py`:

- Register `"ollama"` as a new provider name alongside existing providers.
- `--provider ollama` becomes available in the pipeline CLI.

## Acceptance Criteria

### AC-1: Basic Chat

- `OllamaClient.chat()` sends a well-formed POST to `/api/chat` with `model`, `messages`, and `stream: false`.
- Response is parsed into `OllamaResponse` with `content` populated.

### AC-2: System Message Separation

- For test-writer and implementer roles, `_build_messages()` produces a list with at least two messages: one with `role: "system"` and one with `role: "user"`.
- The system message contains `FILE:` format instructions.
- The user message contains spec content.

### AC-3: Generation Parameters

- When `OLLAMA_TEMPERATURE=0.1` is set, the `options` dict sent to Ollama includes `"temperature": 0.1`.
- When `OLLAMA_NUM_CTX=8192` is set, the `options` dict includes `"num_ctx": 8192`.

### AC-4: Reviewer JSON Format

- For reviewer role, `OllamaClient.chat()` is called with `format="json"`.
- The returned content is valid JSON parseable by `json.loads()`.

### AC-5: Tool Calling

- When `OLLAMA_USE_TOOLS=1`, `_build_tool_spec()` returns a list with a `create_file` tool definition.
- `_extract_from_tool_calls()` correctly extracts path and content from Ollama tool-call response format.
- When the model returns plain text instead of tool calls, the provider falls back to `FILE:` block extraction.

### AC-6: Provider Registration

- `--provider ollama` is accepted by the pipeline CLI.
- Running `OllamaProvider.run_role()` with a test-writer role produces a `ProviderExecution` with `provider="ollama"`.

### AC-7: Connection Error Handling

- When Ollama is not running (connection refused), a `PipelineError` with `EXIT_PROVIDER_EXEC_FAILED` is raised with a clear message.

## Package Layout

```
src/spec_driven_dev_pipeline/
  providers/
    ollama_client.py   # REQ-1: OllamaClient, OllamaResponse
    ollama.py          # REQ-2, REQ-3, REQ-4: OllamaProvider
    __init__.py        # REQ-5: register "ollama" provider
tests/
  test_ollama_provider.py  # unit tests for ollama_client and ollama provider
```

Existing files modified: `src/spec_driven_dev_pipeline/providers/__init__.py`.

## Relationship to Other Specs

- **format-repair-spec.md** (Approved): `repair_output()` is called on raw model output when available. This spec does not depend on it but benefits from it.
- **few-shot-prompts-spec.md** (Approved): Few-shot examples are included in the system message when available. Same — benefits from but does not depend on.
- This spec **supersedes** the OpenCode adapter for local model use. The `opencode` provider remains for backward compatibility but is no longer the recommended path for Ollama models.

## Re-Benchmark Plan

After implementation, re-run the benchmark-calc task with all 4 models using `--provider ollama` and compare results against the OpenCode baseline. Key metrics to compare: best stage reached, format compliance score, and composite score.
