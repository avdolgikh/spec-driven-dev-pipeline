# Spec: <Title>

## Status

Draft | Approved

## Goal

One paragraph: what this feature does and why it matters.

## Scope

What is created or changed. Keep it narrow.

## Requirements

### REQ-1: <Name>

Core logic in `src/spec_driven_dev_pipeline/<module>.py` (importable, testable):

- `function_name(args) -> return_type` -- what it does.
- `another_function(args) -> return_type` -- what it does.

CLI wrapper (if applicable): `scripts/<script>.py` calls `<module>.function_name()`.

**Behavior:**

Numbered steps describing what happens.

### REQ-2: <Name>

(repeat pattern)

## Acceptance Criteria

### AC-1: <Name>

- Concrete, testable assertion.
- Another assertion.

### AC-2: <Name>

(repeat pattern)

## Package Layout

New files (library modules with function signatures, scripts as thin wrappers, test files):

```
src/spec_driven_dev_pipeline/
  <module>/
    __init__.py
    <file>.py          # REQ-N: function_a(), function_b()
scripts/
  <script>.py          # thin CLI: argparse -> <module>.<file>.function_a()
tests/
  test_<file>.py       # unit tests for <module>.<file>
```

Existing files modified: list or "none".
