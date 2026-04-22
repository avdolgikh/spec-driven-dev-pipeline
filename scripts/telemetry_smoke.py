"""Telemetry smoke test: drive one full PipelineRunner.run() against a stub
provider with OTLP export enabled, so Phoenix (or any OTLP collector) receives
a representative trace of the 6-stage run.

Usage (with Phoenix running on http://localhost:6006):

    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
    OTEL_SERVICE_NAME=spec-driven-pipeline \
    uv run python scripts/telemetry_smoke.py

The stub provider completes in well under a second, so this exists purely to
validate the wiring end-to-end without burning real LLM calls.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from spec_driven_dev_pipeline.core import (  # noqa: E402
    EXIT_CODE_REVISION_CAP,
    PipelineConfig,
    PipelineRunner,
)
from spec_driven_dev_pipeline.providers.base import ProviderExecution  # noqa: E402
from spec_driven_dev_pipeline.utils import tracing  # noqa: E402


@dataclass
class _StubProvider:
    name: str = "smoke-provider"

    def __post_init__(self) -> None:
        self._reviews = iter(
            [
                json.dumps({"decision": "approve", "summary": "tests ok", "blocking": []}),
                json.dumps({"decision": "revise", "summary": "once more", "blocking": ["retry"]}),
                json.dumps({"decision": "revise", "summary": "still", "blocking": ["retry"]}),
                json.dumps({"decision": "revise", "summary": "still", "blocking": ["retry"]}),
            ]
        )

    def run_role(self, *, role, prompt, repo_root, state_dir, schema=None):  # noqa: ANN001
        if role == "clarify":
            return ProviderExecution(
                provider=self.name,
                role=role,
                tier="economy",
                model="stub-clarify",
                output='{"ambiguities":[]}',
            )
        if role == "test-writer":
            (Path(repo_root) / "tests" / "test_smoke_telemetry.py").write_text(
                "def test_smoke_telemetry():\n    assert True\n", encoding="utf-8"
            )
            return ProviderExecution(
                provider=self.name,
                role=role,
                tier="economy",
                model="stub-writer",
                output="tests written",
            )
        if role == "reviewer":
            return ProviderExecution(
                provider=self.name,
                role=role,
                tier="premium",
                model="stub-reviewer",
                output=next(self._reviews),
            )
        if role == "implementer":
            return ProviderExecution(
                provider=self.name,
                role=role,
                tier="economy",
                model="stub-implementer",
                output="implemented",
            )
        raise AssertionError(f"Unexpected role: {role}")


def _prepare_repo(root: Path) -> None:
    (root / "specs").mkdir(parents=True, exist_ok=True)
    (root / "specs" / "smoke-telemetry-spec.md").write_text("# smoke spec\n", encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    prompts = root / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    for name in ("clarify", "test_writer", "implementer", "reviewer"):
        (prompts / f"{name}.md").write_text(f"{name} prompt", encoding="utf-8")


def main() -> int:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        print(
            "OTEL_EXPORTER_OTLP_ENDPOINT is not set — this smoke test requires a "
            "running OTLP collector (e.g. Phoenix on http://localhost:4317).",
            file=sys.stderr,
        )
        return 2

    print(
        f"Emitting spans to {endpoint} (service={os.environ.get('OTEL_SERVICE_NAME', 'default')})"
    )

    tmp = Path(tempfile.mkdtemp(prefix="pipeline-smoke-"))
    try:
        _prepare_repo(tmp)
        import subprocess as _subprocess
        import spec_driven_dev_pipeline.core as _core

        def _fake_pytest(command, **kwargs):  # noqa: ANN001
            return _subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        _core.subprocess.run = _fake_pytest  # type: ignore[assignment]

        runner = PipelineRunner(
            repo_root=tmp,
            task="smoke-telemetry",
            provider=_StubProvider(),
            max_revisions=2,
            config=PipelineConfig(prompts_dir="prompts"),
        )
        try:
            exit_code = runner.run()
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            exit_code = getattr(exc, "exit_code", 1)
    finally:
        tracing.shutdown_tracing()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"Pipeline exit_code={exit_code} (EXIT_CODE_REVISION_CAP={EXIT_CODE_REVISION_CAP})")
    print("Spans flushed. Open the Phoenix UI to inspect the trace.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
