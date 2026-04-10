"""Judge evaluation helpers for benchmark results."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, Callable

from spec_driven_dev_pipeline.core import PipelineConfig
from spec_driven_dev_pipeline.providers.claude import ClaudeProvider
from spec_driven_dev_pipeline.providers.codex import CodexProvider
from spec_driven_dev_pipeline.providers.gemini import GeminiProvider

SCORE_KEYS = [
    "test_coverage",
    "test_quality",
    "code_correctness",
    "code_quality",
    "format_compliance",
]

PROVIDER_FACTORIES: dict[str, Callable[[], Any]] = {
    "codex": CodexProvider,
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
}


def build_judge_prompt(
    spec_text: str,
    test_code: str,
    impl_code: str,
    pytest_output: str,
    log_tail: str,
) -> str:
    """Compose a normalized prompt for the judge provider."""
    sections = [
        "# Local Model Benchmark Judge",
        "Evaluate the candidate output for the benchmark task.",
        "Score each rubric dimension from 1 (poor) to 5 (excellent):",
        "| Dimension | 1 (Poor) | 3 (Adequate) | 5 (Excellent) |",
        "|-----------|----------|--------------|---------------|",
        "| Test Coverage | Tests cover <30% ACs | Tests cover 50-70% ACs | Tests cover all ACs incl. edges |",
        "| Test Quality | Broken or trivial tests | Basic assertions only | Clean, descriptive, independent |",
        "| Code Correctness | Implementation fails | Handles basics only | Passes all tests incl. edges |",
        "| Code Quality | Unreadable, no structure | Functional but messy | Clean, idiomatic abstractions |",
        "| Format Compliance | Output unparseable | Partially parseable | All FILE blocks + JSON valid |",
        "Return JSON with keys: model, task, scores, notes.",
        "",
        "## Spec",
        spec_text.strip(),
        "",
        "## Tests",
        test_code.strip() or "No tests generated.",
        "",
        "## Implementation",
        impl_code.strip() or "No implementation generated.",
        "",
        "## Pytest Output",
        pytest_output.strip() or "Tests did not run.",
        "",
        "## Pipeline Log (tail)",
        log_tail.strip() or "No log available.",
    ]
    return "\n".join(sections)


def _extract_json_blob(output: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", output, re.DOTALL)
    if fenced:
        return fenced.group(1)

    if "{" not in output:
        raise ValueError("Judge response did not contain JSON.")

    start = output.index("{")
    depth = 0
    for idx, char in enumerate(output[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return output[start : idx + 1]
    raise ValueError("Could not locate balanced JSON payload.")


def parse_judge_response(output: str) -> dict[str, Any]:
    """Parse the provider output and compute a composite score."""
    blob = _extract_json_blob(output)
    data = json.loads(blob)
    scores = data.get("scores") or {}
    values: list[float] = []
    for key in SCORE_KEYS:
        if key not in scores:
            raise ValueError(f"Missing score: {key}")
        values.append(float(scores[key]))
    data["composite_score"] = sum(values) / len(values)
    return data


def _read_py_payload(base: Path) -> str:
    if not base.exists():
        return ""
    contents: list[str] = []
    for path in sorted(base.rglob("*.py")):
        contents.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(contents)


def _read_tail(path: Path, limit: int = 200) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-limit:])


def run_judge(*, model_dir: Path, provider: str, spec_path: Path) -> dict[str, Any]:
    """Invoke the selected provider to evaluate a model directory."""
    spec_path = spec_path if spec_path.is_absolute() else (Path.cwd() / spec_path)
    spec_text = spec_path.read_text(encoding="utf-8")
    repo_root = spec_path.resolve().parents[1]

    test_code = _read_py_payload(model_dir / "tests")
    impl_code = _read_py_payload(model_dir / "src")
    pytest_output_path = model_dir / "pytest_output.txt"
    pytest_output = (
        pytest_output_path.read_text(encoding="utf-8") if pytest_output_path.exists() else ""
    )
    log_tail = _read_tail(model_dir / "pipeline.log")
    prompt = build_judge_prompt(spec_text, test_code, impl_code, pytest_output, log_tail)

    provider_key = provider.lower()
    if provider_key not in PROVIDER_FACTORIES:
        raise ValueError(f"Unsupported provider: {provider}")
    provider_class = PROVIDER_FACTORIES[provider_key]
    provider_instance = provider_class()
    config = PipelineConfig()
    state_dir = repo_root / config.state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    run_role_attr = getattr(provider_class, "run_role")
    params = list(inspect.signature(run_role_attr).parameters.values())
    needs_instance = bool(params) and params[0].kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    call_kwargs = {
        "role": "reviewer",
        "prompt": prompt,
        "repo_root": repo_root,
        "state_dir": state_dir,
        "schema": None,
    }
    if needs_instance:
        execution = run_role_attr(provider_instance, **call_kwargs)
    else:
        execution = run_role_attr(**call_kwargs)  # type: ignore[misc]
    evaluation = parse_judge_response(execution.output)
    if not evaluation.get("model"):
        evaluation["model"] = model_dir.name
    if not evaluation.get("task"):
        evaluation["task"] = spec_path.stem.replace("-spec", "")

    output_path = model_dir / "judge_evaluation.json"
    output_path.write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
    return evaluation
