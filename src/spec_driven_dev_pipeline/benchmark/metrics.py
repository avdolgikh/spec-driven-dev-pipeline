"""Metrics extraction helpers for benchmark runs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SUMMARY_PATTERN = re.compile(r"===\s*(?P<body>.+?)\s*===", re.DOTALL)


def parse_pytest_output(output: str) -> dict[str, Any]:
    """Extract pass/fail counts from the pytest summary line."""
    text = output or ""
    passed_match = re.search(r"(\d+)\s+passed", text)
    failed_match = re.search(r"(\d+)\s+failed", text)
    passed = int(passed_match.group(1)) if passed_match else 0
    failed = int(failed_match.group(1)) if failed_match else 0
    total = passed + failed
    rate = (passed / total) if total else 0.0
    return {
        "test_pass_count": passed,
        "test_fail_count": failed,
        "test_pass_rate": rate,
    }


def parse_pipeline_log(log: str) -> dict[str, Any]:
    """Pull structured metrics from the pipeline log.

    Real pipeline log lines include:
    - State transitions: ``[state] TESTS_GENERATED (iteration=0 provider=codex)``
    - Test-format lines containing ``Stage:`` for compatibility with test fixtures.
    """
    text = log or ""
    # Match real state transitions like ``[state] CODE_VALIDATED``
    state_stages = re.findall(r"\[state\]\s+(\S+)", text)
    # Also match test fixture format ``Stage: <name>``
    colon_stages = [
        line.split("Stage:", 1)[1].strip()
        for line in text.splitlines()
        if "Stage:" in line and "[state]" not in line
    ]
    all_stages = state_stages + colon_stages
    final_stage = all_stages[-1] if all_stages else "UNKNOWN"
    # Count revision iterations from both real and test formats
    revision_cycles = len(
        re.findall(
            r"(?:Revision|Test Revision|revision)\s*\(?(?:iter\s*)?\d+",
            text,
            re.IGNORECASE,
        )
    )
    format_failures = len(re.findall(r"failed to parse", text, flags=re.IGNORECASE))
    return {
        "final_stage": final_stage,
        "revision_cycles": revision_cycles,
        "format_parse_failures": format_failures,
    }


def _count_generated_files(model_dir: Path) -> int:
    tests_dir = model_dir / "tests"
    impl_dir = model_dir / "src" / "spec_driven_dev_pipeline" / "utils"
    count = 0
    if tests_dir.exists():
        count += sum(1 for _ in tests_dir.rglob("*.py"))
    if impl_dir.exists():
        count += sum(1 for _ in impl_dir.rglob("*.py"))
    return count


def collect_metrics(model_dir: Path, *, exit_code: int, wall_clock: float) -> dict[str, Any]:
    """Aggregate metrics from a completed model directory."""
    pipeline_log_path = model_dir / "pipeline.log"
    pytest_output_path = model_dir / "pytest_output.txt"
    pipeline_log = (
        pipeline_log_path.read_text(encoding="utf-8") if pipeline_log_path.exists() else ""
    )
    pytest_output = (
        pytest_output_path.read_text(encoding="utf-8") if pytest_output_path.exists() else ""
    )

    log_metrics = parse_pipeline_log(pipeline_log)
    pytest_metrics = parse_pytest_output(pytest_output)
    record: dict[str, Any] = {
        **log_metrics,
        **pytest_metrics,
        "pipeline_completed": exit_code == 0,
        "exit_code": exit_code,
        "wall_clock_seconds": wall_clock,
        "files_generated": _count_generated_files(model_dir),
        "format_parse_failures": log_metrics["format_parse_failures"],
    }

    metrics_path = model_dir / "metrics.json"
    metrics_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
