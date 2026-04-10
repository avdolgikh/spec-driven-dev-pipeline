# Spec: Few-Shot Examples in Role Prompts

## Status

Approved

## Goal

Add concrete few-shot examples of the expected `FILE: <path>` output format to the OpenCode provider's prompt augmentation. Local models follow demonstrated examples far more reliably than written instructions alone. By showing 1-2 complete input/output examples, we increase the chance that models produce parseable `FILE:` blocks on the first attempt.

## Scope

- New module `src/spec_driven_dev_pipeline/providers/few_shot.py` with example templates and a builder function.
- Modify `OpenCodeProvider._augment_prompt()` to append few-shot examples after the `_FILE_OUTPUT_INSTRUCTIONS`.
- Examples are role-specific: test-writer sees a test example, implementer sees an implementation example.
- No changes to the base role prompts in `src/spec_driven_dev_pipeline/prompts/` — few-shot examples are OpenCode-specific (cloud providers don't need them).

## Requirements

### REQ-1: Few-Shot Example Templates

Core logic in `src/spec_driven_dev_pipeline/providers/few_shot.py` (importable, testable):

- `get_few_shot_examples(role: str) -> str` -- Return a formatted string of few-shot examples for the given role. Returns empty string for `"reviewer"` (reviewer uses JSON, not FILE: blocks).
- `TEST_WRITER_EXAMPLE: str` -- Module-level constant. A complete example showing: a short spec snippet, then the expected output with 1 `FILE:` block containing a pytest test file.
- `IMPLEMENTER_EXAMPLE: str` -- Module-level constant. A complete example showing: a short spec+test snippet, then the expected output with 1 `FILE:` block containing an implementation file.

**Behavior:**

1. Each example is a self-contained input→output demonstration, wrapped in a clear `## Example` section.
2. Examples use a trivial domain (e.g., an `add(a, b)` function) to avoid confusing the model with complex logic — the point is to demonstrate the format, not the content.
3. Examples show the exact `FILE: <path>` + triple-backtick structure that `extract_file_blocks()` parses.
4. `get_few_shot_examples("test-writer")` returns `TEST_WRITER_EXAMPLE`.
5. `get_few_shot_examples("implementer")` returns `IMPLEMENTER_EXAMPLE`.
6. `get_few_shot_examples("reviewer")` returns `""`.

### REQ-2: Integration into OpenCode Provider

Modify `OpenCodeProvider._augment_prompt()` in `src/spec_driven_dev_pipeline/providers/opencode.py`:

- For test-writer and implementer roles, append the few-shot examples after `_FILE_OUTPUT_INSTRUCTIONS`.
- Order: original prompt + `_FILE_OUTPUT_INSTRUCTIONS` + few-shot examples.

**Behavior:**

1. The augmented prompt ends with concrete examples immediately before the model generates its response.
2. Reviewer prompts are unchanged.

## Acceptance Criteria

### AC-1: Test-Writer Example

- `get_few_shot_examples("test-writer")` returns a non-empty string containing at least one `FILE:` block with a `test_` prefixed path and pytest-style test code.

### AC-2: Implementer Example

- `get_few_shot_examples("implementer")` returns a non-empty string containing at least one `FILE:` block with an implementation path under `src/` and a function definition.

### AC-3: Reviewer Excluded

- `get_few_shot_examples("reviewer")` returns an empty string.

### AC-4: Examples Parse Correctly

- Each example's `FILE:` blocks are extractable by the existing `extract_file_blocks()` function (i.e., they match `_FILE_BLOCK_RE`).

### AC-5: Integration

- `OpenCodeProvider._augment_prompt()` includes few-shot examples for test-writer and implementer roles.
- The few-shot section appears after the `_FILE_OUTPUT_INSTRUCTIONS` block.

## Package Layout

```
src/spec_driven_dev_pipeline/
  providers/
    few_shot.py        # REQ-1: get_few_shot_examples(), TEST_WRITER_EXAMPLE, IMPLEMENTER_EXAMPLE
    opencode.py        # REQ-2: modified _augment_prompt() to append few-shot examples
tests/
  test_few_shot.py     # unit tests for few_shot + integration test for augmented prompt
```

Existing files modified: `src/spec_driven_dev_pipeline/providers/opencode.py`.
