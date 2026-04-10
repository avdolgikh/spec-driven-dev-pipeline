# Spec: Output Format Repair Layer

## Status

Approved

## Goal

Add a post-processing repair layer to the OpenCode provider that converts common alternative output formats into the expected `FILE: <path>` block structure. Local models often produce valid code but in the wrong wrapper (markdown fences with filename comments, tool-call JSON, inline prose with embedded code). A repair step between raw model output and `extract_file_blocks()` can recover these cases without changing the pipeline's core parser.

## Scope

- New module `src/spec_driven_dev_pipeline/providers/format_repair.py` with pure-function repair logic.
- Integration into `OpenCodeProvider.run_role()` — repair runs on raw output before `extract_file_blocks()`.
- No changes to `_FILE_BLOCK_RE` or `extract_file_blocks()` — repair normalizes output *into* the existing format.
- No changes to other providers (Codex, Claude, Gemini already produce structured output via their own mechanisms).

## Requirements

### REQ-1: Repair Functions

Core logic in `src/spec_driven_dev_pipeline/providers/format_repair.py` (importable, testable):

- `repair_output(raw: str) -> str` -- Apply all repair strategies in sequence. Returns the repaired output string. If no repairs are needed, returns input unchanged.
- `repair_markdown_fences(raw: str) -> str` -- Convert markdown code fences with filename annotations into `FILE:` blocks. Handles patterns like `` ```python # filename.py ``, `` ```python\n# File: path/to/file.py ``, and `` <!-- filename.py --> `` before a fence.
- `repair_tool_calls(raw: str) -> str` -- Extract file paths and content from tool-call JSON structures (e.g. `{"name": "create_file", "arguments": {"path": "...", "content": "..."}}`) and convert to `FILE:` blocks.
- `repair_filename_comments(raw: str) -> str` -- Detect code fences preceded or followed by a line containing only a file path (e.g. `tests/test_calc.py`) and convert to `FILE:` blocks.

**Behavior:**

1. `repair_output` applies each strategy in order: `repair_markdown_fences` → `repair_tool_calls` → `repair_filename_comments`.
2. Each strategy is idempotent — running it twice produces the same result.
3. If the output already contains valid `FILE:` blocks, no changes are made (strategies only act on unrecognized patterns).
4. Repair preserves any non-code text (explanations, reasoning) — it only transforms code block wrappers.

### REQ-2: Integration into OpenCode Provider

Modify `OpenCodeProvider.run_role()` in `src/spec_driven_dev_pipeline/providers/opencode.py`:

- After receiving raw stdout and before calling `extract_file_blocks()`, call `repair_output(output)`.
- Only apply repair for non-reviewer roles (test-writer, implementer) — reviewer output is JSON, not file blocks.

**Behavior:**

1. Raw model output → `repair_output()` → `extract_file_blocks()` → write files to disk.
2. If repair produces valid `FILE:` blocks from previously unparseable output, the pipeline proceeds normally instead of hitting EXIT_STAGE_NO_EFFECT.

## Acceptance Criteria

### AC-1: Markdown Fence Repair

- Input with `` ```python # tests/test_calc.py `` on the first line of a fence is converted to `FILE: tests/test_calc.py` + fence.
- Input with `# File: path/to/file.py` as the first line inside a fence is converted to `FILE: path/to/file.py` + fence (comment line removed from content).
- Input with `<!-- tests/test_calc.py -->` immediately before a fence is converted to `FILE: tests/test_calc.py` + fence.

### AC-2: Tool Call Repair

- Input containing `{"name": "create_file", "arguments": {"path": "tests/test_calc.py", "content": "..."}}` produces a `FILE: tests/test_calc.py` block.
- Input containing `{"tool": "write_file", "input": {"path": "...", "content": "..."}}` produces a `FILE:` block.
- Multiple tool calls in one output produce multiple `FILE:` blocks.

### AC-3: Filename Comment Repair

- A bare path line like `tests/test_calc.py` immediately followed by a code fence is converted to `FILE: tests/test_calc.py` + fence.
- A bare path line immediately after a code fence's closing ``` is not treated as a filename for the *next* fence (no false positives on trailing text).

### AC-4: Idempotency

- Output already containing valid `FILE:` blocks passes through unchanged.
- Running `repair_output` twice on any input produces the same result as running it once.

### AC-5: Integration

- `OpenCodeProvider.run_role()` applies repair before file extraction for test-writer and implementer roles.
- Reviewer role output is not repaired.

## Package Layout

```
src/spec_driven_dev_pipeline/
  providers/
    format_repair.py   # REQ-1: repair_output(), repair_markdown_fences(), repair_tool_calls(), repair_filename_comments()
    opencode.py        # REQ-2: modified to call repair_output() before extract_file_blocks()
tests/
  test_format_repair.py  # unit tests for format_repair + integration test for opencode repair path
```

Existing files modified: `src/spec_driven_dev_pipeline/providers/opencode.py`.
