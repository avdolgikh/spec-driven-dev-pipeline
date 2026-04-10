"""Tests for the benchmark-framework spec helpers."""

from __future__ import annotations

import json
from pathlib import Path
import textwrap

import pytest

from spec_driven_dev_pipeline.core import PipelineConfig
from spec_driven_dev_pipeline.providers.base import ProviderExecution
from spec_driven_dev_pipeline.benchmark import judge, leaderboard, metrics, runner
from scripts import generate_leaderboard as generate_leaderboard_script
from scripts import judge_benchmark as judge_benchmark_script
from scripts import run_benchmark as run_benchmark_script


### Runner helpers


def test_sanitize_model_tag_replaces_reserved_chars() -> None:
    tag = "ollama/glm-4.7-flash:latest"
    sanitized = runner.sanitize_model_tag(tag)
    assert sanitized == "ollama-glm-4.7-flash-latest"


def test_ensure_ollama_prefix_is_idempotent() -> None:
    bare = "qwen3.5:latest"
    prefixed = runner.ensure_ollama_prefix(bare)
    assert prefixed == "ollama/qwen3.5:latest"
    assert runner.ensure_ollama_prefix(prefixed) == prefixed


def test_cleanup_task_prunes_state_and_generated_files(tmp_path: Path) -> None:
    repo_root = tmp_path
    config = PipelineConfig()
    state_dir = repo_root / config.state_dir
    state_dir.mkdir(parents=True)
    (state_dir / "benchmark-calc.json").write_text("{}", encoding="utf-8")
    (state_dir / "benchmark-calc.log").write_text("log", encoding="utf-8")

    tests_dir = repo_root / config.tests_dir
    tests_dir.mkdir()
    (tests_dir / "test_calc_generated.py").write_text("pass", encoding="utf-8")
    (tests_dir / "test_mine.py").write_text("pass", encoding="utf-8")

    utils_dir = repo_root / "src/spec_driven_dev_pipeline/utils"
    utils_dir.mkdir(parents=True)
    (utils_dir / "calc.py").write_text("# generated", encoding="utf-8")
    (utils_dir / "keep.py").write_text("# keep", encoding="utf-8")

    runner.cleanup_task(repo_root, "benchmark-calc", config)

    assert not (state_dir / "benchmark-calc.json").exists()
    assert not (state_dir / "benchmark-calc.log").exists()
    assert not (tests_dir / "test_calc_generated.py").exists()
    assert (tests_dir / "test_mine.py").exists()
    assert not (utils_dir / "calc.py").exists()
    assert (utils_dir / "keep.py").exists()


def test_run_benchmark_calls_run_model_and_writes_summary(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = tmp_path / "benchmarks"
    models = ["qwen3.5:latest", "gemma4:e4b"]
    summoned: list[tuple[str, str, Path, Path, int]] = []

    def fake_run_model(
        model_tag: str,
        task: str,
        repo_root_arg: Path,
        output_dir_arg: Path,
        max_revisions: int,
    ) -> dict:
        summoned.append((model_tag, task, repo_root_arg, output_dir_arg, max_revisions))
        sanitized = runner.sanitize_model_tag(model_tag)
        result_dir = output_dir_arg / sanitized
        result_dir.mkdir(parents=True, exist_ok=True)
        return {"model": model_tag, "sanitized_tag": sanitized, "result_dir": str(result_dir)}

    monkeypatch.setattr(runner, "run_model", fake_run_model)

    summary = runner.run_benchmark(
        models, task="benchmark-calc", output_dir=output_dir, repo_root=repo_root, max_revisions=2
    )

    assert len(summoned) == len(models)
    assert all(call[1] == "benchmark-calc" for call in summoned)
    assert all(call[4] == 2 for call in summoned)
    summary_path = output_dir / "summary.json"
    assert summary_path.exists()
    parsed = json.loads(summary_path.read_text(encoding="utf-8"))
    assert parsed.get("task") == "benchmark-calc"
    serialized = json.dumps(parsed)
    for model in models:
        assert runner.sanitize_model_tag(model) in serialized
    assert summary == parsed


def test_run_model_cleans_up_invokes_pipeline_collects_metrics(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = tmp_path / "benchmarks"
    output_dir.mkdir()
    cleanup_sequence: list[str] = []

    (repo_root / "tests").mkdir()
    (repo_root / "tests/test_calc.py").write_text("assert True", encoding="utf-8")
    (repo_root / "tests/test_unrelated.py").write_text("unrelated", encoding="utf-8")
    utils_dir = repo_root / "src/spec_driven_dev_pipeline/utils"
    utils_dir.mkdir(parents=True)
    (utils_dir / "calc.py").write_text("# generated", encoding="utf-8")

    def fake_cleanup(repo_root_arg: Path, task: str, config: PipelineConfig) -> None:
        cleanup_sequence.append("cleanup")
        assert repo_root_arg == repo_root
        assert task == "benchmark-calc"
        assert isinstance(config, PipelineConfig)

    monkeypatch.setattr(runner, "cleanup_task", fake_cleanup)
    monkeypatch.setattr(runner, "sanitize_model_tag", lambda _: "ollama-qwen3.5-latest")

    def fake_ensure(tag: str) -> str:
        stripped = tag.split("ollama/")[-1]
        return f"ollama/{stripped}"

    monkeypatch.setattr(runner, "ensure_ollama_prefix", fake_ensure)

    subprocess_env: dict[str, str] = {}
    subprocess_call: dict[str, object] = {}

    class _FakeResult:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "Stage: CODE_VALIDATED\n=== 1 passed in 0.01s ==="
            self.stderr = ""

    def fake_run(*args: object, **kwargs: object) -> _FakeResult:
        cleanup_sequence.append("subprocess")
        subprocess_call["args"] = list(args)[0] if args else []
        subprocess_call["kwargs"] = kwargs
        env = kwargs.get("env", {})
        if isinstance(env, dict):
            subprocess_env.update(env)
        return _FakeResult()

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    metrics_data: dict[str, object] = {}

    def fake_collect_metrics(model_dir: Path, exit_code: int, wall_clock: float) -> dict:
        cleanup_sequence.append("metrics")
        metrics_data["dir"] = model_dir
        metrics_data["exit_code"] = exit_code
        metrics_data["wall_clock"] = wall_clock
        return {
            "files_generated": 1,
            "format_parse_failures": 0,
            "wall_clock_seconds": wall_clock,
        }

    monkeypatch.setattr(metrics, "collect_metrics", fake_collect_metrics)
    result = runner.run_model(
        "qwen3.5:latest",
        task="benchmark-calc",
        repo_root=repo_root,
        output_dir=output_dir,
        max_revisions=3,
    )

    assert cleanup_sequence == ["cleanup", "subprocess", "metrics"]
    assert result["sanitized_tag"] == "ollama-qwen3.5-latest"
    result_dir = Path(result["result_dir"])
    assert result_dir == output_dir / "ollama-qwen3.5-latest"
    assert metrics_data["dir"] == result_dir
    assert metrics_data["exit_code"] == 0
    assert metrics_data["wall_clock"] >= 0
    assert subprocess_env["OPENCODE_MODEL"] == "ollama/qwen3.5:latest"
    assert result["metrics"]["files_generated"] == 1

    assert (result_dir / "pipeline.log").exists()
    assert "Stage: CODE_VALIDATED" in (result_dir / "pipeline.log").read_text(encoding="utf-8")
    assert "=== 1 passed" in (result_dir / "pytest_output.txt").read_text(encoding="utf-8")
    copied_test = result_dir / "tests/test_calc.py"
    assert copied_test.exists()
    assert copied_test.read_text(encoding="utf-8") == "assert True"
    # Unrelated test files should NOT be copied
    assert not (result_dir / "tests/test_unrelated.py").exists()
    copied_impl = result_dir / "src/spec_driven_dev_pipeline/utils/calc.py"
    assert copied_impl.exists()
    assert copied_impl.read_text(encoding="utf-8") == "# generated"

    called_args = subprocess_call["args"]
    assert isinstance(called_args, list)
    assert "benchmark-calc" in called_args
    assert "--provider" in called_args and "opencode" in called_args

    def _flag_matches_value(flag: str, value: str) -> bool:
        if flag in called_args:
            idx = called_args.index(flag)
            if idx + 1 < len(called_args) and called_args[idx + 1] == value:
                return True
        return any(
            arg.startswith(f"{flag}=") and arg.split("=", 1)[1] == value for arg in called_args
        )

    assert _flag_matches_value("--repo-root", str(repo_root))
    assert _flag_matches_value("--max-revisions", "3")
    assert any("run_pipeline" in str(arg) for arg in called_args)
    called_kwargs = subprocess_call["kwargs"]
    capture_options = (
        called_kwargs.get("capture_output") is True,
        called_kwargs.get("stdout") == runner.subprocess.PIPE,
        called_kwargs.get("stderr") == runner.subprocess.PIPE,
        called_kwargs.get("stderr") == runner.subprocess.STDOUT,
    )
    assert any(capture_options)
    assert called_kwargs.get("cwd") == repo_root


### Judge helpers


def test_build_judge_prompt_includes_all_artifacts() -> None:
    spec_text = "# Benchmark spec"
    test_code = "def test_calc(): pass"
    impl_code = "def calc(): return 0"
    pytest_output = "=== 1 passed in 0.01s ==="
    log_tail = "Stage: CODE_VALIDATED"
    prompt = judge.build_judge_prompt(spec_text, test_code, impl_code, pytest_output, log_tail)
    assert spec_text in prompt
    assert test_code in prompt
    assert impl_code in prompt
    assert pytest_output in prompt
    assert log_tail in prompt
    assert "Test Coverage" in prompt


def test_parse_judge_response_calculates_composite() -> None:
    output = textwrap.dedent(
        """
        Some upstream prose
        ```json
        {
          "model": "ollama/glm-4.7-flash:latest",
          "task": "benchmark-calc",
          "scores": {
            "test_coverage": 4,
            "test_quality": 5,
            "code_correctness": 5,
            "code_quality": 4,
            "format_compliance": 5
          },
          "notes": "Clean output"
        }
        ```
        """
    )
    evaluation = judge.parse_judge_response(output)
    assert evaluation["model"] == "ollama/glm-4.7-flash:latest"
    assert evaluation["scores"]["test_quality"] == 5
    assert evaluation["composite_score"] == pytest.approx(4.6)


def _seed_model_artifacts(
    base: Path,
    name: str,
    test_body: str,
    impl_body: str,
    log_text: str,
    pytest_output: str,
) -> Path:
    model_dir = base / name
    tests_dir = model_dir / "tests"
    impl_dir = model_dir / "src/spec_driven_dev_pipeline/utils"
    pipeline_log = model_dir / "pipeline.log"
    pytest_file = model_dir / "pytest_output.txt"
    tests_dir.mkdir(parents=True, exist_ok=True)
    impl_dir.mkdir(parents=True, exist_ok=True)
    pipeline_log.write_text(log_text, encoding="utf-8")
    pytest_file.write_text(pytest_output, encoding="utf-8")
    (tests_dir / f"test_{name}.py").write_text(test_body, encoding="utf-8")
    (impl_dir / "calc.py").write_text(impl_body, encoding="utf-8")
    return model_dir


def test_run_judge_truncates_pipeline_log_tail(tmp_path: Path, monkeypatch) -> None:
    spec_path = tmp_path / "specs/benchmark-calc-spec.md"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_text = Path("specs/benchmark-calc-spec.md").read_text(encoding="utf-8")
    spec_path.write_text(spec_text, encoding="utf-8")
    results_dir = tmp_path / "benchmarks/results"
    model_dir = results_dir / "glm-4.7-flash-latest"

    log_lines = [f"Stage: revision {i}" for i in range(1, 251)]
    _seed_model_artifacts(
        base=results_dir,
        name="glm-4.7-flash-latest",
        test_body="def test_calc(): pass",
        impl_body="def calc(): return 'pass'",
        log_text="\n".join(log_lines),
        pytest_output="=== 1 passed ===",
    )

    prompt_calls: list[dict[str, str]] = []

    def fake_build_prompt(
        spec_text_arg: str,
        test_code: str,
        impl_code: str,
        pytest_output: str,
        log_tail: str,
    ) -> str:
        prompt_calls.append(
            {
                "spec": spec_text_arg,
                "test_code": test_code,
                "impl_code": impl_code,
                "pytest_output": pytest_output,
                "log_tail": log_tail,
            }
        )
        return "prompt-for-test"

    monkeypatch.setattr(judge, "build_judge_prompt", fake_build_prompt)

    def fake_parse_judge_response(output: str) -> dict:
        parsed = json.loads(output)
        parsed["composite_score"] = 5.0
        return parsed

    monkeypatch.setattr(judge, "parse_judge_response", fake_parse_judge_response)

    def fake_run_role(
        *,
        role: str,
        prompt: str,
        repo_root: Path,
        state_dir: Path,
        schema: dict | None = None,
    ) -> ProviderExecution:
        return ProviderExecution(
            provider="codex",
            role=role,
            tier="test",
            model="gpt-5.1-codex",
            output=json.dumps(
                {
                    "model": "glm-4.7-flash:latest",
                    "task": "benchmark-calc",
                    "scores": {
                        "test_coverage": 5,
                        "test_quality": 5,
                        "code_correctness": 5,
                        "code_quality": 5,
                        "format_compliance": 5,
                    },
                    "notes": "evaluated",
                }
            ),
        )

    monkeypatch.setattr(
        "spec_driven_dev_pipeline.providers.codex.CodexProvider.run_role",
        fake_run_role,
    )

    judge.run_judge(
        model_dir=model_dir,
        provider="codex",
        spec_path=spec_path,
    )

    assert len(prompt_calls) == 1
    log_tail_lines = [line for line in prompt_calls[0]["log_tail"].splitlines() if line.strip()]
    assert len(log_tail_lines) == 200
    assert log_tail_lines == log_lines[-200:]


def test_run_judge_builds_prompt_invokes_provider_and_writes_evaluation(
    tmp_path: Path, monkeypatch
) -> None:
    spec_path = tmp_path / "specs/benchmark-calc-spec.md"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_text = Path("specs/benchmark-calc-spec.md").read_text(encoding="utf-8")
    spec_path.write_text(spec_text, encoding="utf-8")
    results_dir = tmp_path / "benchmarks/results"

    model_tag = "glm-4.7-flash:latest"
    sanitized = "glm-4.7-flash-latest"
    test_code = "def test_glm(): assert True"
    impl_code = "def calc(): return 42"

    model_dir = _seed_model_artifacts(
        base=results_dir,
        name=sanitized,
        test_body=test_code,
        impl_body=impl_code,
        log_text="Stage: CODE_VALIDATED for glm",
        pytest_output="=== 1 passed (glm) ===",
    )

    prompt_calls: list[dict[str, str]] = []

    def fake_build_prompt(
        spec_text_arg: str,
        test_code_arg: str,
        impl_code_arg: str,
        pytest_output: str,
        log_tail: str,
    ) -> str:
        prompt_calls.append(
            {
                "spec": spec_text_arg,
                "test_code": test_code_arg,
                "impl_code": impl_code_arg,
                "pytest_output": pytest_output,
                "log_tail": log_tail,
            }
        )
        return "judge-prompt"

    monkeypatch.setattr(judge, "build_judge_prompt", fake_build_prompt)

    def fake_parse_judge_response(output: str) -> dict:
        parsed = json.loads(output)
        parsed["composite_score"] = 5.0
        return parsed

    monkeypatch.setattr(judge, "parse_judge_response", fake_parse_judge_response)

    def fake_run_role(
        *,
        role: str,
        prompt: str,
        repo_root: Path,
        state_dir: Path,
        schema: dict | None = None,
    ) -> ProviderExecution:
        return ProviderExecution(
            provider="codex",
            role=role,
            tier="test",
            model="gpt-5.1-codex",
            output=json.dumps(
                {
                    "model": model_tag,
                    "task": "benchmark-calc",
                    "scores": {
                        "test_coverage": 5,
                        "test_quality": 5,
                        "code_correctness": 5,
                        "code_quality": 5,
                        "format_compliance": 5,
                    },
                    "notes": "evaluated glm",
                }
            ),
        )

    monkeypatch.setattr(
        "spec_driven_dev_pipeline.providers.codex.CodexProvider.run_role",
        fake_run_role,
    )

    result = judge.run_judge(
        model_dir=model_dir,
        provider="codex",
        spec_path=spec_path,
    )

    assert len(prompt_calls) == 1
    assert prompt_calls[0]["test_code"].startswith("def test_")
    assert prompt_calls[0]["impl_code"].startswith("def calc")
    assert "(glm)" in prompt_calls[0]["pytest_output"]
    saved = json.loads((model_dir / "judge_evaluation.json").read_text(encoding="utf-8"))
    assert saved["model"] == model_tag
    assert result["model"] == model_tag


### Metrics helpers


def test_parse_pytest_output_identifies_pass_fail_and_rate() -> None:
    summary = "=== 7 passed, 3 failed in 0.04s ==="
    parsed = metrics.parse_pytest_output(summary)
    assert parsed["test_pass_count"] == 7
    assert parsed["test_fail_count"] == 3
    assert parsed["test_pass_rate"] == pytest.approx(7 / 10)


def test_parse_pipeline_log_extracts_stage_revision_and_failures() -> None:
    log = textwrap.dedent(
        """
        Stage: START
        Revision 1: tests generated
        Revision 2: implementation revised
        Stage: CODE_VALIDATED
        FILE: tests/test_calc.py (failed to parse)
        FILE: src/spec_driven_dev_pipeline/utils/calc.py (parsed)
        FILE: tests/test_extra.py (failed to parse)
        Stage: CLEANUP
        """
    )
    parsed = metrics.parse_pipeline_log(log)
    assert parsed["final_stage"] == "CLEANUP"
    assert parsed["revision_cycles"] == 2
    assert parsed["format_parse_failures"] == 2


def test_collect_metrics_assembles_record_and_writes_json(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "benchmarks/glm-4.7-flash-latest"
    model_dir.mkdir(parents=True)
    (model_dir / "pipeline.log").write_text("log stub", encoding="utf-8")
    (model_dir / "pytest_output.txt").write_text("output stub", encoding="utf-8")
    (model_dir / "tests").mkdir()
    (model_dir / "tests/test_calc.py").write_text("pass", encoding="utf-8")
    impl_dir = model_dir / "src/spec_driven_dev_pipeline/utils"
    impl_dir.mkdir(parents=True)
    (impl_dir / "calc.py").write_text("# generated", encoding="utf-8")

    monkeypatch.setattr(
        metrics,
        "parse_pipeline_log",
        lambda log: {
            "final_stage": "CODE_VALIDATED",
            "revision_cycles": 1,
            "format_parse_failures": 0,
        },
    )
    monkeypatch.setattr(
        metrics,
        "parse_pytest_output",
        lambda output: {"test_pass_count": 2, "test_fail_count": 0, "test_pass_rate": 1.0},
    )

    record = metrics.collect_metrics(model_dir, exit_code=0, wall_clock=12.5)
    assert record["pipeline_completed"] is True
    assert record["exit_code"] == 0
    assert record["final_stage"] == "CODE_VALIDATED"
    assert record["test_pass_rate"] == pytest.approx(1.0)
    assert record["test_pass_count"] == 2
    assert record["test_fail_count"] == 0
    expected_files_generated = sum(
        1
        for path in (
            model_dir / "tests/test_calc.py",
            impl_dir / "calc.py",
        )
        if path.exists()
    )
    assert record["files_generated"] == expected_files_generated
    assert record["format_parse_failures"] == 0
    assert record["wall_clock_seconds"] == pytest.approx(12.5)
    metrics_file = model_dir / "metrics.json"
    assert metrics_file.exists()
    saved = json.loads(metrics_file.read_text(encoding="utf-8"))
    assert saved["revision_cycles"] == 1
    assert saved["test_pass_count"] == 2
    assert saved["test_fail_count"] == 0


### Leaderboard helpers


def test_render_markdown_orders_entries_by_composite_score() -> None:
    entries = [
        {
            "model": "legacy",
            "composite_score": 3.4,
            "metrics": {"test_pass_count": 14},
            "judge": {"scores": {}},
            "revision_cycles": 3,
            "wall_clock_seconds": 380,
            "pipeline_completed": True,
        },
        {
            "model": "glm-4.7-flash:latest",
            "composite_score": 4.6,
            "metrics": {"test_pass_count": 18},
            "judge": {"scores": {}},
            "revision_cycles": 1,
            "wall_clock_seconds": 512,
            "pipeline_completed": True,
        },
    ]
    metadata = {
        "task": "benchmark-calc",
        "date": "2026-04-10",
        "hardware": "RTX 4070 12GB / Ollama",
        "judge": "codex (gpt-5.1-codex)",
    }
    rendered = leaderboard.render_markdown(entries, metadata)
    assert "# Local Model Benchmark Leaderboard" in rendered
    assert metadata["task"] in rendered
    assert metadata["hardware"] in rendered
    assert "| Rank | Model | Completed | Tests Pass | Revisions | Composite | Time |" in rendered
    assert "## Score Breakdown" in rendered
    assert (
        "| Model | Test Coverage | Test Quality | Correctness | Code Quality | Format |" in rendered
    )
    lines = [line for line in rendered.splitlines() if line.strip()]
    idx_glm = next(i for i, line in enumerate(lines) if "glm-4.7-flash:latest" in line)
    idx_legacy = next(i for i, line in enumerate(lines) if "legacy" in line and "Rank" not in line)
    assert idx_glm < idx_legacy
    assert "legacy" in rendered


def test_render_json_returns_sorted_entries_with_metadata() -> None:
    entries = [
        {"model": "low", "composite_score": 2.0},
        {"model": "high", "composite_score": 5.0},
    ]
    metadata = {"task": "benchmark-calc", "judge": "codex"}
    rendered = leaderboard.render_json(entries, metadata)
    parsed = json.loads(rendered)
    assert parsed["metadata"]["task"] == "benchmark-calc"
    assert parsed["entries"][0]["model"] == "high"
    assert parsed["entries"][1]["model"] == "low"


def test_load_results_merges_summary_metrics_and_judges(tmp_path: Path) -> None:
    results_dir = tmp_path / "benchmarks/results"
    results_dir.mkdir(parents=True)
    summary = {
        "task": "benchmark-calc",
        "date": "2026-04-10",
        "hardware": "RTX 4070 12GB / Ollama",
        "judge": "codex (gpt-5.1-codex)",
        "models": [
            {"model": "glm-4.7-flash:latest", "sanitized_tag": "glm-4.7-flash-latest"},
            {"model": "qwen3.5:latest", "sanitized_tag": "qwen3.5-latest"},
        ],
    }
    (results_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    for entry in summary["models"]:
        model_dir = results_dir / entry["sanitized_tag"]
        model_dir.mkdir()
        (model_dir / "metrics.json").write_text(json.dumps({"exit_code": 0}), encoding="utf-8")
        (model_dir / "judge_evaluation.json").write_text(
            json.dumps({"model": entry["model"], "composite_score": 4.2}), encoding="utf-8"
        )

    entries = leaderboard.load_results(results_dir)
    assert len(entries) == len(summary["models"])
    lookup = {entry["model"]: entry for entry in entries}
    for expected in summary["models"]:
        actual = lookup[expected["model"]]
        assert actual["sanitized_tag"] == expected["sanitized_tag"]
        assert actual["metrics"]["exit_code"] == 0
        assert actual["judge"]["model"] == expected["model"]


def test_generate_leaderboard_writes_markdown_and_json_outputs(tmp_path: Path) -> None:
    results_dir = tmp_path / "benchmarks/results"
    results_dir.mkdir(parents=True)
    summary = {
        "task": "benchmark-calc",
        "date": "2026-04-10",
        "hardware": "RTX 4070 12GB / Ollama",
        "judge": "codex (gpt-5.1-codex)",
        "models": [
            {"model": "glm-4.7-flash:latest", "sanitized_tag": "glm-4.7-flash-latest"},
            {"model": "qwen3.5:latest", "sanitized_tag": "qwen3.5-latest"},
        ],
    }
    (results_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    for entry in summary["models"]:
        model_dir = results_dir / entry["sanitized_tag"]
        model_dir.mkdir(parents=True)
        (model_dir / "metrics.json").write_text(
            json.dumps({"exit_code": 0, "files_generated": 3}), encoding="utf-8"
        )
        (model_dir / "judge_evaluation.json").write_text(
            json.dumps({"model": entry["model"], "composite_score": 4.2}), encoding="utf-8"
        )

    output_dir = tmp_path / "benchmarks"
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "leaderboard.md"
    json_path = output_dir / "leaderboard.json"

    leaderboard.generate_leaderboard(results_dir=results_dir, output_path=md_path)

    assert md_path.exists()
    md_content = md_path.read_text(encoding="utf-8")
    assert "# Local Model Benchmark Leaderboard" in md_content
    assert summary["task"] in md_content
    assert summary["hardware"] in md_content
    assert json_path.exists()
    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["metadata"]["task"] == summary["task"]
    models_in_json = {entry["model"] for entry in parsed["entries"]}
    assert models_in_json >= {entry["model"] for entry in summary["models"]}


### CLI wrappers


def test_run_benchmark_cli_parses_models_and_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    invoked: dict[str, object] = {}
    output_dir = tmp_path / "benchmarks/results"
    output_dir_str = str(output_dir)

    def fake_run_benchmark(*args: object, **kwargs: object) -> dict:
        if kwargs:
            invoked["models"] = kwargs["models"]
            invoked["task"] = kwargs["task"]
            invoked["output_dir"] = kwargs["output_dir"]
            invoked["repo_root"] = kwargs["repo_root"]
            invoked["max_revisions"] = kwargs["max_revisions"]
        else:
            (
                invoked["models"],
                invoked["task"],
                invoked["output_dir"],
                invoked["repo_root"],
                invoked["max_revisions"],
            ) = args  # type: ignore[arg-type]
        return {}

    monkeypatch.setattr(runner, "run_benchmark", fake_run_benchmark)

    run_benchmark_script.main(
        [
            "--models",
            "qwen3.5:latest,glm-4.7-flash:latest",
            "--task",
            "custom-task",
            "--output-dir",
            output_dir_str,
            "--max-revisions",
            "2",
        ]
    )

    assert invoked["models"] == ["qwen3.5:latest", "glm-4.7-flash:latest"]
    assert invoked["task"] == "custom-task"
    assert invoked["output_dir"] == output_dir
    assert invoked["max_revisions"] == 2
    assert isinstance(invoked["repo_root"], Path)


def test_run_benchmark_cli_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    invoked: dict[str, object] = {}

    def fake_run_benchmark(*args: object, **kwargs: object) -> dict:
        if kwargs:
            invoked["models"] = kwargs["models"]
            invoked["task"] = kwargs["task"]
            invoked["output_dir"] = kwargs["output_dir"]
            invoked["repo_root"] = kwargs["repo_root"]
            invoked["max_revisions"] = kwargs["max_revisions"]
        else:
            (
                invoked["models"],
                invoked["task"],
                invoked["output_dir"],
                invoked["repo_root"],
                invoked["max_revisions"],
            ) = args  # type: ignore[arg-type]
        return {}

    monkeypatch.setattr(runner, "run_benchmark", fake_run_benchmark)

    run_benchmark_script.main(["--models", "qwen3.5:latest"])

    assert invoked["models"] == ["qwen3.5:latest"]
    assert invoked["task"] == "benchmark-calc"
    assert invoked["max_revisions"] == 4
    default_dir = invoked["repo_root"] / "benchmarks" / "results"
    assert invoked["output_dir"] == default_dir


def test_run_benchmark_cli_requires_models() -> None:
    with pytest.raises(SystemExit):
        run_benchmark_script.main([])


def test_judge_benchmark_cli_runs_single_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results_dir = tmp_path / "benchmarks/results/glm"
    results_dir.mkdir(parents=True)
    calls: list[dict[str, object]] = []

    def fake_run_judge(model_dir: Path, provider: str, spec_path: Path) -> dict:
        calls.append({"model_dir": model_dir, "provider": provider, "spec_path": spec_path})
        return {}

    monkeypatch.setattr(judge, "run_judge", fake_run_judge)

    judge_benchmark_script.main(
        [
            "--results-dir",
            str(results_dir),
            "--provider",
            "codex",
        ]
    )

    assert len(calls) == 1
    assert calls[0]["model_dir"] == results_dir
    assert calls[0]["provider"] == "codex"
    assert calls[0]["spec_path"].name == "benchmark-calc-spec.md"


def test_judge_benchmark_cli_all_iterates_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    base = tmp_path / "benchmarks/results"
    names = ["glm-4.7-flash-latest", "qwen3.5-latest"]
    for name in names:
        (base / name).mkdir(parents=True)
    calls: list[dict[str, object]] = []

    def fake_run_judge(model_dir: Path, provider: str, spec_path: Path) -> dict:
        calls.append({"model_dir": model_dir, "provider": provider, "spec_path": spec_path})
        return {}

    monkeypatch.setattr(judge, "run_judge", fake_run_judge)

    judge_benchmark_script.main(
        [
            "--results-dir",
            str(base),
            "--provider",
            "codex",
            "--all",
        ]
    )

    assert len(calls) == len(names)
    expected_dirs = {base / name for name in names}
    actual_dirs = {call["model_dir"] for call in calls}
    assert actual_dirs == expected_dirs


def test_generate_leaderboard_cli_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Path] = {}

    def fake_generate_leaderboard(*, results_dir: Path, output_path: Path) -> None:
        recorded["results_dir"] = results_dir
        recorded["output_path"] = output_path

    monkeypatch.setattr(leaderboard, "generate_leaderboard", fake_generate_leaderboard)

    generate_leaderboard_script.main([])

    repo_root = Path(__file__).resolve().parents[1]
    expected_results = repo_root / "benchmarks" / "results"
    expected_output = repo_root / "benchmarks" / "leaderboard.md"
    assert recorded["results_dir"] == expected_results
    assert recorded["output_path"] == expected_output


def test_generate_leaderboard_cli_overrides_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results_dir = tmp_path / "custom/results"
    output_path = tmp_path / "custom/leaderboard.md"
    recorded: dict[str, Path] = {}

    def fake_generate_leaderboard(*, results_dir: Path, output_path: Path) -> None:
        recorded["results_dir"] = results_dir
        recorded["output_path"] = output_path

    monkeypatch.setattr(leaderboard, "generate_leaderboard", fake_generate_leaderboard)

    generate_leaderboard_script.main(
        [
            "--results-dir",
            str(results_dir),
            "--output",
            str(output_path),
        ]
    )

    assert recorded["results_dir"] == results_dir
    assert recorded["output_path"] == output_path
