"""Benchmark runner orchestration helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_driven_dev_pipeline.core import PipelineConfig

from . import metrics

PIPELINE_SCRIPT = ["uv", "run", "python", "scripts/run_pipeline.py"]
DEFAULT_HARDWARE = "RTX 4070 12GB / Ollama"
DEFAULT_JUDGE = "codex (gpt-5.1-codex)"


def sanitize_model_tag(tag: str) -> str:
    """Replace characters that cannot be used for directories."""
    return tag.replace("/", "-").replace(":", "-")


def ensure_ollama_prefix(tag: str) -> str:
    """Ensure tags align with the provider convention."""
    return tag if tag.startswith("ollama/") else f"ollama/{tag}"


def cleanup_task(repo_root: Path, task: str, config: PipelineConfig) -> None:
    """Remove per-task state prior to running another model."""
    state_dir = repo_root / config.state_dir
    for suffix in (".json", ".log"):
        target = state_dir / f"{task}{suffix}"
        if target.exists():
            target.unlink()

    tests_dir = repo_root / config.tests_dir
    if tests_dir.exists():
        for pattern in ("test_calc*.py", "calc_test*.py", "*calc*.py"):
            for path in tests_dir.glob(pattern):
                path.unlink()

    impl_path = repo_root / "src" / "spec_driven_dev_pipeline" / "utils" / "calc.py"
    if impl_path.exists():
        impl_path.unlink()


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def _copy_artifacts(repo_root: Path, result_dir: Path, config: PipelineConfig) -> None:
    """Copy only the model-generated files, not the entire tests/src dirs."""
    # Copy task-specific test files only
    tests_src = repo_root / config.tests_dir
    tests_dst = result_dir / config.tests_dir
    if tests_src.exists():
        tests_dst.mkdir(parents=True, exist_ok=True)
        for pattern in ("test_calc*.py", "calc_test*.py", "*calc*.py"):
            for path in tests_src.glob(pattern):
                shutil.copy2(path, tests_dst / path.name)

    # Copy task-specific implementation files only
    impl_file = repo_root / "src" / "spec_driven_dev_pipeline" / "utils" / "calc.py"
    if impl_file.exists():
        impl_dst = result_dir / "src" / "spec_driven_dev_pipeline" / "utils"
        impl_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(impl_file, impl_dst / "calc.py")


def run_model(
    model_tag: str,
    task: str,
    repo_root: Path,
    output_dir: Path,
    max_revisions: int,
) -> dict[str, Any]:
    """Run the pipeline once for a candidate model and collect metrics."""
    config = PipelineConfig()
    cleanup_task(repo_root, task, config)

    sanitized = sanitize_model_tag(model_tag)
    result_dir = output_dir / sanitized
    output_dir.mkdir(parents=True, exist_ok=True)
    if result_dir.exists():
        shutil.rmtree(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["OPENCODE_MODEL"] = ensure_ollama_prefix(model_tag)

    command = [
        *PIPELINE_SCRIPT,
        task,
        "--provider",
        "opencode",
        "--repo-root",
        str(repo_root),
        "--max-revisions",
        str(max_revisions),
    ]

    start = time.perf_counter()
    completed = subprocess.run(  # noqa: PLW1510 - explicitly capture output
        command,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - start

    # Pipeline writes its log to stdout; copy the state log if available for richer data.
    full_output = completed.stdout or ""
    state_log = repo_root / config.state_dir / f"{task}.log"
    if state_log.exists():
        full_output = state_log.read_text(encoding="utf-8")
    (result_dir / "pipeline.log").write_text(full_output, encoding="utf-8")
    (result_dir / "pytest_output.txt").write_text(completed.stdout or "", encoding="utf-8")
    _copy_artifacts(repo_root, result_dir, config)

    metrics_record = metrics.collect_metrics(
        result_dir, exit_code=completed.returncode, wall_clock=elapsed
    )
    result = {
        "model": model_tag,
        "sanitized_tag": sanitized,
        "result_dir": str(result_dir),
        "exit_code": completed.returncode,
        "metrics": metrics_record,
    }
    return result


def run_benchmark(
    models: list[str],
    *,
    task: str,
    output_dir: Path,
    repo_root: Path,
    max_revisions: int,
) -> dict[str, Any]:
    """Run the requested models and write a summary file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_models: list[dict[str, Any]] = []
    for tag in models:
        result = run_model(tag, task, repo_root, output_dir, max_revisions)
        model_entry = {
            "model": tag,
            "sanitized_tag": result["sanitized_tag"],
            "result_dir": result["result_dir"],
        }
        if "exit_code" in result:
            model_entry["exit_code"] = result["exit_code"]
        summary_models.append(model_entry)

    summary: dict[str, Any] = {
        "task": task,
        "date": datetime.now().date().isoformat(),
        "hardware": DEFAULT_HARDWARE,
        "judge": DEFAULT_JUDGE,
        "models": summary_models,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
