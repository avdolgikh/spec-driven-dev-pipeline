"""Leaderboard rendering helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_summary(results_dir: Path) -> dict[str, Any]:
    summary_path = results_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary.json in {results_dir}")
    return _read_json(summary_path)


def load_results(results_dir: Path) -> list[dict[str, Any]]:
    """Combine summary metadata with per-model records."""
    summary = _load_summary(results_dir)
    entries: list[dict[str, Any]] = []
    for model_info in summary.get("models", []):
        sanitized = model_info["sanitized_tag"]
        model_dir = results_dir / sanitized
        metrics = _read_json(model_dir / "metrics.json")
        judge = _read_json(model_dir / "judge_evaluation.json")
        entries.append(
            {
                **model_info,
                "result_dir": str(model_dir),
                "metrics": metrics,
                "judge": judge,
                "composite_score": judge.get("composite_score", 0.0),
            }
        )
    entries.sort(key=lambda item: item.get("composite_score", 0.0), reverse=True)
    return entries


def _format_completed(metrics: dict[str, Any]) -> str:
    if metrics.get("pipeline_completed"):
        return "Yes"
    stage = metrics.get("final_stage", "UNKNOWN")
    return f"Partial ({stage})"


def _format_tests(metrics: dict[str, Any]) -> str:
    passed = metrics.get("test_pass_count", 0)
    failed = metrics.get("test_fail_count", 0)
    total = passed + failed
    return f"{passed}/{total}" if total else "-"


def _format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "-"
    total_seconds = int(round(float(seconds)))
    minutes, secs = divmod(total_seconds, 60)
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def render_markdown(entries: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    """Render a markdown leaderboard sorted by composite score."""
    entries = sorted(entries, key=lambda item: item.get("composite_score", 0.0), reverse=True)
    lines = [
        "# Local Model Benchmark Leaderboard",
        f"**Task:** {metadata.get('task', 'unknown')}",
        f"**Date:** {metadata.get('date', 'unknown')}",
        f"**Hardware:** {metadata.get('hardware', 'unknown')}",
        f"**Judge:** {metadata.get('judge', 'unknown')}",
        "",
        "| Rank | Model | Completed | Tests Pass | Revisions | Composite | Time |",
        "|------|-------|-----------|------------|-----------|-----------|------|",
    ]
    for idx, entry in enumerate(entries, start=1):
        metrics = entry.get("metrics", {})
        composite = entry.get("composite_score", 0.0)
        time_cell = _format_duration(metrics.get("wall_clock_seconds"))
        lines.append(
            f"| {idx} | {entry['model']} | {_format_completed(metrics)} | {_format_tests(metrics)} | "
            f"{metrics.get('revision_cycles', 0)} | {composite:.1f} | {time_cell} |"
        )

    lines.extend(
        [
            "",
            "## Score Breakdown",
            "",
            "| Model | Test Coverage | Test Quality | Correctness | Code Quality | Format |",
            "|-------|---------------|--------------|-------------|--------------|--------|",
        ]
    )
    for entry in entries:
        scores = entry.get("judge", {}).get("scores", {})
        row = (
            f"| {entry['model']} | "
            f"{scores.get('test_coverage', '-')} | "
            f"{scores.get('test_quality', '-')} | "
            f"{scores.get('code_correctness', '-')} | "
            f"{scores.get('code_quality', '-')} | "
            f"{scores.get('format_compliance', '-')} |"
        )
        lines.append(row)
    return "\n".join(lines)


def render_json(entries: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    """Render a JSON leaderboard sorted by composite score."""
    payload = {
        "metadata": metadata,
        "entries": [
            {
                "model": entry["model"],
                "sanitized_tag": entry.get("sanitized_tag", entry["model"]),
                "composite_score": entry.get("composite_score", 0.0),
                "metrics": entry.get("metrics", {}),
                "judge": entry.get("judge", {}),
            }
            for entry in entries
        ],
    }
    payload["entries"].sort(key=lambda item: item.get("composite_score", 0.0), reverse=True)
    return json.dumps(payload, indent=2)


def generate_leaderboard(*, results_dir: Path, output_path: Path) -> None:
    """Load result entries and emit markdown plus JSON outputs."""
    summary = _load_summary(results_dir)
    entries = load_results(results_dir)
    markdown = render_markdown(entries, summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    json_payload = render_json(entries, summary)
    json_path = output_path.with_suffix(".json")
    json_path.write_text(json_payload, encoding="utf-8")
