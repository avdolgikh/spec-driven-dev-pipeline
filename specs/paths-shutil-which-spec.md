# Spec: Portable Executable Discovery

## Status

Draft

## Goal

Resolve provider CLI binaries (codex, gemini, opencode, claude) through a
single portable lookup so the pipeline runs on Linux, macOS, and Windows
without per-platform branching in provider modules. Today, several providers
hardcode `APPDATA/npm/*.cmd` fragments, which silently fail outside Windows
and leak user-specific paths into source.

## Scope

A small utility that wraps `shutil.which` with role-appropriate fallbacks,
and the provider modules that currently bake Windows paths into their
command construction. No change to provider public surface or CLI flags.

## Requirements

### REQ-1: Executable resolver

Core logic in `src/spec_driven_dev_pipeline/utils/` (new module):

- A resolver function that takes a logical tool name (e.g. `"codex"`,
  `"gemini"`, `"opencode"`) and returns an absolute path to the executable
  found on `PATH`, or raises a clear configuration error naming both the
  tool and the PATH directories searched.
- Caller may pass an explicit override path (from env var or config) which
  the resolver validates and returns without further lookup.
- Resolution rules are defined by the resolver, not by each provider.

### REQ-2: Provider call sites adopt the resolver

Every place that currently constructs an executable path by concatenating
`APPDATA`, `npm`, or `.cmd` suffixes uses the resolver instead. The
provider's `run_role()` behavior is otherwise unchanged. Providers must not
special-case Windows paths.

### REQ-3: Failure mode

If the tool is not on PATH and no override is supplied, the pipeline fails
fast at run start (not mid-stage) with a single message that states which
tool is missing and how to install it. Silent fallback to a wrong binary
is not acceptable.

## Acceptance Criteria

### AC-1: No hardcoded Windows paths remain in providers

- `grep` for `APPDATA`, `\\npm\\`, `.cmd` across `providers/` returns no
  matches outside of comments or tests that exercise the resolver directly.

### AC-2: Linux parity

- A pipeline run against a trivial spec (e.g. `smoke-test-spec.md`) using
  `--provider codex` completes on Linux/WSL without any environment
  modification beyond installing the CLI tool itself.

### AC-3: Windows parity

- The same run completes unchanged on Windows. No regression against the
  current working state.

### AC-4: Missing-tool diagnostic

- Running the pipeline with a provider whose CLI is not installed produces
  an error message that names the tool and the searched PATH, and exits
  before any stage begins.

## Package Layout

```
src/spec_driven_dev_pipeline/
  utils/
    __init__.py
    executables.py     # REQ-1: resolver (new)
  providers/
    codex.py           # REQ-2: use resolver (modified)
    gemini.py          # REQ-2: use resolver (modified)
    opencode.py        # REQ-2: use resolver (modified)
    claude.py          # REQ-2: use resolver if it constructs paths (modified)
tests/
  test_executables.py  # unit tests for the resolver (new)
```

Existing files modified: the providers listed above; no other changes.
