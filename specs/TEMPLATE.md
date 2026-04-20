# Spec: <Title>

> **Spec Philosophy (MANDATORY).** Specs are high-level intent + observable ACs,
> NOT pseudo-code. Target ~150 lines. If the spec can be copy-pasted into code,
> it is too detailed.
>
> **DO NOT include in a spec:** exact class signatures, full method signatures,
> attribute names on returned objects, exact span name strings, exact event
> topic strings, enum literal values, per-test assertions (counts, field-by-field
> equality), "Public Contracts" blocks, "Return-on-Failure" tables, detailed
> span-tree diagrams.
>
> **Why:** (1) the pipeline's value is autonomous generation — over-specification
> does the agents' design work. (2) Every pinned string becomes an ambiguity
> vector (literal vs enum vs symbolic reference). (3) Bloated specs cause
> reviewers to nitpick micro-details instead of verifying meaning.
>
> Leave room for the test-writer and implementer to pick names, shapes, and
> exact error types. Their job is design; your job is intent.

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
