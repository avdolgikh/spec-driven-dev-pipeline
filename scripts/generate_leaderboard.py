"""CLI wrapper for leaderboard generation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from spec_driven_dev_pipeline.benchmark import leaderboard


def _resolve_path(repo_root: Path, raw: str | None, default: Path) -> Path:
    if raw is None:
        return default
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else repo_root / candidate


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render benchmark leaderboards.")
    parser.add_argument(
        "--results-dir",
        default=None,
        help="Directory containing summary.json and per-model artifacts.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path for the markdown leaderboard (default: <repo>/benchmarks/leaderboard.md).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    default_results = repo_root / "benchmarks" / "results"
    default_output = repo_root / "benchmarks" / "leaderboard.md"
    results_dir = _resolve_path(repo_root, args.results_dir, default_results)
    output_path = _resolve_path(repo_root, args.output, default_output)
    leaderboard.generate_leaderboard(results_dir=results_dir, output_path=output_path)


if __name__ == "__main__":
    main()
