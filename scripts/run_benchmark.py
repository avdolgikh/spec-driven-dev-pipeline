"""CLI wrapper for the benchmark runner."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from spec_driven_dev_pipeline.benchmark import runner


def _parse_models(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _resolve_path(repo_root: Path, raw: str | None) -> Path:
    if raw is None:
        return repo_root / "benchmarks" / "results"
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else repo_root / candidate


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local model benchmark pipeline.")
    parser.add_argument(
        "--models",
        required=True,
        help="Comma-separated list of Ollama model tags.",
    )
    parser.add_argument(
        "--task",
        default="benchmark-calc",
        help="Benchmark task id (default: benchmark-calc).",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Directory to store benchmark artifacts (default: <repo>/benchmarks/results).",
    )
    parser.add_argument(
        "--max-revisions",
        type=int,
        default=4,
        help="Maximum revision attempts per pipeline run.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    output_dir = _resolve_path(repo_root, args.output_dir)
    models = _parse_models(args.models)
    if not models:
        raise SystemExit("No models specified.")
    return runner.run_benchmark(
        models=models,
        task=args.task,
        output_dir=output_dir,
        repo_root=repo_root,
        max_revisions=args.max_revisions,
    )


if __name__ == "__main__":
    main()
