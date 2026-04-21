"""Portable executable discovery for provider CLIs.

Replaces hardcoded Windows ``%APPDATA%\\npm\\<tool>.cmd`` paths with a
platform-neutral lookup via ``shutil.which``. An explicit override
(e.g. set on ``provider.executable``) takes precedence and is validated
but not searched.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from spec_driven_dev_pipeline.core import EXIT_PROVIDER_EXEC_FAILED, PipelineError


def resolve_executable(
    logical_tool_name: str,
    override: str | os.PathLike[str] | None = None,
) -> str:
    """Resolve a provider CLI to an absolute filesystem path.

    When ``override`` is provided, it is validated to exist and returned as an
    absolute path; ``shutil.which`` is NOT consulted. Otherwise the logical
    tool name is looked up on ``PATH``. Missing tools raise ``PipelineError``
    with ``EXIT_PROVIDER_EXEC_FAILED`` and a diagnostic that names the tool,
    the searched PATH entries, and an install hint.
    """
    if override is not None:
        override_path = Path(override)
        if not override_path.exists():
            raise PipelineError(
                f"FAIL: configured executable override for {logical_tool_name!r} "
                f"does not exist: {override_path}. Unset the override or install "
                f"the CLI at that location.",
                EXIT_PROVIDER_EXEC_FAILED,
            )
        return str(override_path.resolve())

    found = shutil.which(logical_tool_name)
    if found is None:
        raw_path = os.environ.get("PATH", "")
        searched = [entry for entry in raw_path.split(os.pathsep) if entry]
        entries = "\n".join(f"  - {entry}" for entry in searched) or "  (empty PATH)"
        raise PipelineError(
            f"FAIL: {logical_tool_name!r} CLI was not found on PATH. "
            f"Install the {logical_tool_name} CLI and ensure its executable is "
            f"on your PATH, then retry.\n"
            f"Searched PATH entries:\n{entries}",
            EXIT_PROVIDER_EXEC_FAILED,
        )
    return str(Path(found).resolve())
