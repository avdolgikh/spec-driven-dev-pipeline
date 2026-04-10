"""CLI wrapper for judge evaluations."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from spec_driven_dev_pipeline.benchmark import judge


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run judge evaluations for benchmark outputs.")
    parser.add_argument(
        "--results-dir",
        required=True,
        help="Path to a model directory or the results root when using --all.",
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=["codex", "claude", "gemini"],
        help="Judge provider to use.",
    )
    parser.add_argument(
        "--spec",
        default="specs/benchmark-calc-spec.md",
        help="Path to the benchmark spec file.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate all model subdirectories contained in --results-dir.",
    )
    return parser.parse_args(argv)


def _resolve_path(base: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (base / path)


def main(argv: Sequence[str] | None = None) -> list[dict]:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    results_dir = _resolve_path(repo_root, args.results_dir)
    spec_path = _resolve_path(repo_root, args.spec)
    evaluations: list[dict] = []
    if args.all:
        for child in sorted(results_dir.iterdir()):
            if child.is_dir():
                evaluations.append(
                    judge.run_judge(model_dir=child, provider=args.provider, spec_path=spec_path)
                )
    else:
        evaluations.append(
            judge.run_judge(model_dir=results_dir, provider=args.provider, spec_path=spec_path)
        )
    return evaluations


if __name__ == "__main__":
    main()
