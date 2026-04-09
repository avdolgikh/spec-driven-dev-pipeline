"""Unit tests for provider-agnostic pipeline core helpers."""

import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import spec_driven_dev_pipeline.core as pipeline_core
from spec_driven_dev_pipeline.core import (
    EXIT_FROZEN_TESTS_MODIFIED,
    EXIT_INVALID_REVIEW_OUTPUT,
    EXIT_PROVIDER_EXEC_FAILED,
    EXIT_REVIEWER_MODIFIED_FILES,
    EXIT_STAGE_NO_EFFECT,
    EXIT_STATE_PROVIDER_MISMATCH,
    EXIT_SUCCESS,
    EXIT_TESTS_BROKE_AFTER_REVISION,
    PipelineConfig,
    PipelineError,
    PipelineRunner,
    PromptBuilder,
    hash_paths,
    normalize_review_output,
)
from spec_driven_dev_pipeline.providers.base import ProviderExecution


class DummyProvider:
    """Minimal provider used for unit tests."""

    name = "dummy"

    def run_role(self, *, role, prompt, repo_root, state_dir, schema=None):  # noqa: ANN001
        return ProviderExecution(
            provider=self.name,
            role=role,
            tier="economy",
            model="dummy-model",
            output='{"decision":"approve","summary":"ok","blocking":[]}',
        )


class ConfigurableTransientProvider:
    """Provider that fails a configurable number of times before succeeding."""

    name = "transient"

    def __init__(self, failures: int):
        self.calls: list[str] = []
        self.failures = failures

    def run_role(self, *, role, prompt, repo_root, state_dir, schema=None):  # noqa: ANN001
        self.calls.append(role)
        if len(self.calls) <= self.failures:
            raise PipelineError(
                "FAIL: transient provider execution failed.",
                EXIT_PROVIDER_EXEC_FAILED,
            )
        return ProviderExecution(
            provider=self.name,
            role=role,
            tier="economy",
            model="transient-model",
            output=f"success-attempt-{len(self.calls)}",
        )


def test_review_schema_matches_codex_strict_requirements():
    from spec_driven_dev_pipeline.core import REVIEW_SCHEMA

    assert REVIEW_SCHEMA["additionalProperties"] is False
    assert REVIEW_SCHEMA["required"] == ["decision", "summary", "blocking"]


def test_normalize_review_output_accepts_structured_output():
    raw = json.dumps(
        {
            "structured_output": {
                "decision": "approve",
                "summary": "Looks good",
                "blocking": [],
            }
        }
    )
    decision = normalize_review_output(raw)
    assert decision.decision == "approve"
    assert decision.summary == "Looks good"
    assert decision.blocking == []


def test_normalize_review_output_uses_fallback_for_fenced_json():
    raw = """
    Reviewer notes:
    ```json
    {"decision":"revise","summary":"Needs work","blocking":["missing test"]}
    ```
    """
    decision = normalize_review_output(raw)
    assert decision.decision == "revise"
    assert decision.blocking == ["missing test"]
    assert decision.fallback_used is True


def test_normalize_review_output_rejects_invalid_payload():
    with pytest.raises(PipelineError) as exc_info:
        normalize_review_output("not json at all")
    assert exc_info.value.exit_code == EXIT_INVALID_REVIEW_OUTPUT


def test_hash_paths_is_deterministic(tmp_path: Path):
    root = tmp_path
    (root / "tests").mkdir()
    (root / "tests" / "b.txt").write_text("beta", encoding="utf-8")
    (root / "tests" / "a.txt").write_text("alpha", encoding="utf-8")
    first = hash_paths(root, ["tests"])
    second = hash_paths(root, ["tests"])
    assert first == second


def test_prompt_builder_includes_context(tmp_path: Path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True)
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    spec_path = specs_dir / "demo-task-spec.md"
    spec_path.write_text("# Demo spec\n\nAcceptance criteria here.", encoding="utf-8")
    (prompts_dir / "implementer.md").write_text("Base implementer prompt.", encoding="utf-8")
    builder = PromptBuilder(tmp_path, PipelineConfig(prompts_dir="prompts"))
    prompt = builder.render(
        role="implementer",
        task="demo-task",
        spec_path=spec_path,
        stage_name="Stage 3: Implementation",
        stage_instruction="Implement the code.",
        iteration=1,
        reviewer_feedback=["fix x", "fix y"],
    )
    assert "Base implementer prompt." in prompt
    assert "Task: demo-task" in prompt
    assert "Stage: Stage 3: Implementation" in prompt
    assert "fix x" in prompt
    assert "This pipeline is non-interactive." in prompt
    assert "Implement the code." in prompt
    assert "# Demo spec" in prompt


def test_prompt_builder_requires_raw_json_for_reviewer(tmp_path: Path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True)
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    spec_path = specs_dir / "demo-task-spec.md"
    spec_path.write_text("# Demo spec", encoding="utf-8")
    (prompts_dir / "reviewer.md").write_text("Base reviewer prompt.", encoding="utf-8")
    builder = PromptBuilder(tmp_path, PipelineConfig(prompts_dir="prompts"))
    prompt = builder.render(
        role="reviewer",
        task="demo-task",
        spec_path=spec_path,
        stage_name="Stage 2: Test Review",
        stage_instruction="Review the tests.",
    )
    assert "Base reviewer prompt." in prompt
    assert "## Required Final Response" in prompt
    assert '"decision":"approve|revise"' in prompt
    assert "Do not ask questions." in prompt


def test_runner_requires_matching_provider_in_state(tmp_path: Path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo", encoding="utf-8")
    state_dir = tmp_path / ".pipeline-state"
    state_dir.mkdir()
    (state_dir / "demo.json").write_text(
        json.dumps(
            {
                "task": "demo",
                "provider": "claude",
                "stage": "SPEC_APPROVED",
                "iteration": 0,
            }
        ),
        encoding="utf-8",
    )
    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())
    with pytest.raises(PipelineError) as exc_info:
        runner._load_state()
    assert exc_info.value.exit_code == EXIT_STATE_PROVIDER_MISMATCH


class RepairingProvider:
    """Provider stub that needs one reviewer output repair pass."""

    name = "dummy"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._outputs = iter(
            [
                ProviderExecution(
                    provider=self.name,
                    role="test-writer",
                    tier="economy",
                    model="dummy-model",
                    output="tests written",
                ),
                ProviderExecution(
                    provider=self.name,
                    role="reviewer",
                    tier="premium",
                    model="dummy-model",
                    output="Please send the review packet first.",
                ),
                ProviderExecution(
                    provider=self.name,
                    role="reviewer",
                    tier="premium",
                    model="dummy-model",
                    output='{"decision":"approve","summary":"tests look good","blocking":[]}',
                ),
                ProviderExecution(
                    provider=self.name,
                    role="implementer",
                    tier="economy",
                    model="dummy-model",
                    output="implemented",
                ),
                ProviderExecution(
                    provider=self.name,
                    role="implementer",
                    tier="economy",
                    model="dummy-model",
                    output="validated",
                ),
                ProviderExecution(
                    provider=self.name,
                    role="reviewer",
                    tier="premium",
                    model="dummy-model",
                    output='{"decision":"approve","summary":"code looks good","blocking":[]}',
                ),
            ]
        )

    def run_role(self, *, role, prompt, repo_root, state_dir, schema=None):  # noqa: ANN001
        self.calls.append((role, prompt))
        if role == "test-writer":
            test_file = Path(repo_root) / "tests" / "test_demo.py"
            existing = test_file.read_text(encoding="utf-8")
            test_file.write_text(existing.rstrip() + "\n# stage 1 update\n", encoding="utf-8")
        return next(self._outputs)


def test_runner_repairs_invalid_reviewer_output_once(tmp_path: Path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "prompts").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text(
        "def test_demo():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo spec", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# repo rules", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "prompts" / "test_writer.md").write_text("test writer", encoding="utf-8")
    (tmp_path / "prompts" / "implementer.md").write_text("implementer", encoding="utf-8")
    (tmp_path / "prompts" / "reviewer.md").write_text("reviewer", encoding="utf-8")
    provider = RepairingProvider()
    runner = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=provider,
        config=PipelineConfig(prompts_dir="prompts"),
    )

    assert runner.run() == 0
    log_text = (tmp_path / ".pipeline-state" / "demo.log").read_text(encoding="utf-8")
    assert "[review] invalid output; attempting one repair pass" in log_text
    assert provider.calls[2][0] == "reviewer"
    assert "## Repair Attempt" in provider.calls[2][1]
    assert "## Artifact Snapshot" in provider.calls[2][1]
    assert "tests/test_demo.py" in provider.calls[2][1]


def test_prompt_builder_strips_utf8_bom(tmp_path: Path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True)
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    spec_path = specs_dir / "demo-task-spec.md"
    spec_path.write_bytes("\ufeff# Demo spec".encode("utf-8"))
    (prompts_dir / "reviewer.md").write_bytes("\ufeffBase reviewer prompt.".encode("utf-8"))
    builder = PromptBuilder(tmp_path, PipelineConfig(prompts_dir="prompts"))
    prompt = builder.render(
        role="reviewer",
        task="demo-task",
        spec_path=spec_path,
        stage_name="Stage 2: Test Review",
        stage_instruction="Review the tests.",
    )
    assert "\ufeff" not in prompt
    assert prompt.startswith("Base reviewer prompt.")
    assert "# Demo spec" in prompt


def test_artifact_snapshot_is_capped(tmp_path: Path):
    (tmp_path / "src").mkdir()
    large_text = "x" * 20000
    (tmp_path / "src" / "large.py").write_text(large_text, encoding="utf-8")
    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())
    snapshot = runner._artifact_snapshot(["src"])
    assert len(snapshot) < 3500
    assert "### Workspace Files" in snapshot
    assert "... [truncated]" in snapshot


def test_runner_fails_when_test_generation_requests_more_input_without_writing_tests(
    tmp_path: Path,
):
    (tmp_path / "specs").mkdir()
    (tmp_path / "prompts").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo spec", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# repo rules", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "prompts" / "test_writer.md").write_text("test writer", encoding="utf-8")
    (tmp_path / "prompts" / "implementer.md").write_text("implementer", encoding="utf-8")
    (tmp_path / "prompts" / "reviewer.md").write_text("reviewer", encoding="utf-8")

    class NoopTestWriterProvider:
        name = "dummy"

        def run_role(self, *, role, prompt, repo_root, state_dir, schema=None):  # noqa: ANN001
            return ProviderExecution(
                provider="dummy",
                role=role,
                tier="economy",
                model="dummy-model",
                output=(
                    "Role Acknowledged\n\n"
                    "Please point me to the approved spec or task you want tests written for."
                ),
            )

    runner = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=NoopTestWriterProvider(),
        config=PipelineConfig(prompts_dir="prompts"),
    )

    with pytest.raises(PipelineError) as exc_info:
        runner.run()
    assert exc_info.value.exit_code == EXIT_STAGE_NO_EFFECT
    assert "did not modify tests/" in str(exc_info.value)


def test_tests_stage_effect_fails_when_no_task_specific_changes(tmp_path: Path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_existing.py").write_text(
        "def test_existing():\n    assert True\n", encoding="utf-8"
    )

    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())
    before_hash = runner._tests_hash()
    execution = ProviderExecution(
        provider="dummy",
        role="test-writer",
        tier="economy",
        model="dummy-model",
        output="Tests still pending.",
    )

    with pytest.raises(PipelineError) as exc_info:
        runner._ensure_tests_stage_effect(
            before_hash=before_hash,
            execution=execution,
            stage_label="Stage 1: Test Generation",
            allow_existing=True,
        )
    assert exc_info.value.exit_code == EXIT_STAGE_NO_EFFECT
    assert "did not modify tests/" in str(exc_info.value)


def test_tests_stage_effect_fails_when_task_specific_file_unchanged(tmp_path: Path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())
    before_hash = runner._tests_hash()
    execution = ProviderExecution(
        provider="dummy",
        role="test-writer",
        tier="economy",
        model="dummy-model",
        output="Tests already exist.",
    )

    with pytest.raises(PipelineError) as exc_info:
        runner._ensure_tests_stage_effect(
            before_hash=before_hash,
            execution=execution,
            stage_label="Stage 1: Test Generation",
            allow_existing=True,
        )
    assert exc_info.value.exit_code == EXIT_STAGE_NO_EFFECT
    message = str(exc_info.value)
    assert "with files for task 'demo'" in message
    assert "Existing task-specific test files were not modified" in message


def test_tests_stage_effect_fails_when_unrelated_test_files_change(tmp_path: Path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())
    before_hash = runner._tests_hash()
    (tests_dir / "test_unrelated.py").write_text(
        "def test_unrelated():\n    assert True\n", encoding="utf-8"
    )
    execution = ProviderExecution(
        provider="dummy",
        role="test-writer",
        tier="economy",
        model="dummy-model",
        output="Added unrelated file.",
    )

    with pytest.raises(PipelineError) as exc_info:
        runner._ensure_tests_stage_effect(
            before_hash=before_hash,
            execution=execution,
            stage_label="Stage 1: Test Generation",
            allow_existing=True,
        )
    assert exc_info.value.exit_code == EXIT_STAGE_NO_EFFECT
    assert "did not modify tests/" in str(exc_info.value)


def test_tests_stage_effect_allows_task_specific_test_change(tmp_path: Path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_demo.py"
    test_file.write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())
    before_hash = runner._tests_hash()
    test_file.write_text("def test_demo():\n    assert False\n", encoding="utf-8")
    execution = ProviderExecution(
        provider="dummy",
        role="test-writer",
        tier="economy",
        model="dummy-model",
        output="Updated demo test.",
    )

    runner._ensure_tests_stage_effect(
        before_hash=before_hash,
        execution=execution,
        stage_label="Stage 1: Test Generation",
        allow_existing=True,
    )


def test_tests_stage_effect_allows_new_task_specific_test_file(tmp_path: Path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())
    before_hash = runner._tests_hash()
    new_test_file = tests_dir / "test_demo.py"
    new_test_file.write_text("def test_demo():\n    assert True\n", encoding="utf-8")
    execution = ProviderExecution(
        provider="dummy",
        role="test-writer",
        tier="economy",
        model="dummy-model",
        output="Created demo test.",
    )

    runner._ensure_tests_stage_effect(
        before_hash=before_hash,
        execution=execution,
        stage_label="Stage 1: Test Generation",
        allow_existing=True,
    )


def test_review_requests_missing_inputs_detects_placeholder_feedback():
    from spec_driven_dev_pipeline.core import ReviewDecision, _review_requests_missing_inputs

    decision = ReviewDecision(
        decision="revise",
        summary="I do not have the review packet yet.",
        blocking=["Missing review inputs: spec and files under review."],
    )
    assert _review_requests_missing_inputs(decision) is True


def test_runner_includes_artifact_snapshot_in_initial_review_prompt(tmp_path: Path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "prompts").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text(
        "def test_demo():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo spec", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# repo rules", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "prompts" / "reviewer.md").write_text("reviewer", encoding="utf-8")

    class SingleReviewProvider:
        name = "dummy"

        def __init__(self) -> None:
            self.prompt = ""

        def run_role(self, *, role, prompt, repo_root, state_dir, schema=None):  # noqa: ANN001
            self.prompt = prompt
            return ProviderExecution(
                provider="dummy",
                role="reviewer",
                tier="premium",
                model="dummy-model",
                output='{"decision":"approve","summary":"ok","blocking":[]}',
            )

    provider = SingleReviewProvider()
    runner = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=provider,
        config=PipelineConfig(prompts_dir="prompts"),
    )
    decision = runner._run_review_role(
        prompt="Base review prompt",
        stage_label="Stage 2: Test Review",
        before_hash=runner._repo_hash(),
    )
    assert decision.decision == "approve"
    assert "## Artifact Snapshot" in provider.prompt
    assert "tests/test_demo.py" in provider.prompt


def test_enforce_test_freeze_detects_modified_tests(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_demo.py"
    test_file.write_text("def test_demo():\n    assert True\n", encoding="utf-8")
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    (specs_dir / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")

    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())
    frozen_hash = runner._tests_hash()
    test_file.write_text("def test_demo():\n    assert False\n", encoding="utf-8")

    with pytest.raises(PipelineError) as exc_info:
        runner._enforce_test_freeze(frozen_hash)
    assert exc_info.value.exit_code == EXIT_FROZEN_TESTS_MODIFIED


def test_enforce_reviewer_immutability_detects_repo_changes(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# repo rules", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "placeholder.py").write_text("print('hi')\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    spec_path = specs_dir / "demo-spec.md"
    spec_path.write_text("# demo spec\n", encoding="utf-8")

    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())
    before_hash = runner._repo_hash()
    spec_path.write_text("# demo spec updated\n", encoding="utf-8")

    with pytest.raises(PipelineError) as exc_info:
        runner._enforce_reviewer_immutability(before_hash, "Stage 5: Code Review")
    assert exc_info.value.exit_code == EXIT_REVIEWER_MODIFIED_FILES


def test_run_pytest_gate_invokes_uv_run_python_module(tmp_path: Path, monkeypatch):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# repo rules", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text(
        "def test_demo():\n    assert True\n", encoding="utf-8"
    )

    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):  # noqa: ANN001
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", fake_run)
    runner._run_pytest_gate("Gate: pytest after code revision")

    assert captured["command"] == ["uv", "run", "python", "-m", "pytest"]
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["check"] is False


def test_run_pytest_gate_fails_on_nonzero_exit(tmp_path: Path, monkeypatch):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# repo rules", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    runner = PipelineRunner(repo_root=tmp_path, task="demo", provider=DummyProvider())

    def fake_run(command, **kwargs):  # noqa: ANN001
        return SimpleNamespace(returncode=1, stdout="fail", stderr="broken")

    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", fake_run)

    with pytest.raises(PipelineError) as exc_info:
        runner._run_pytest_gate("Gate: pytest after code revision")
    assert exc_info.value.exit_code == EXIT_TESTS_BROKE_AFTER_REVISION


def _runner_for_retry_tests(tmp_path: Path, provider):
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    (specs_dir / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")
    return PipelineRunner(repo_root=tmp_path, task="demo", provider=provider)


def _patch_sleep_if_available(monkeypatch):
    time_module = getattr(pipeline_core, "time", None)
    if time_module:
        monkeypatch.setattr(time_module, "sleep", lambda *_: None)


def test_run_role_retries_once_on_transient_provider_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    provider = ConfigurableTransientProvider(failures=1)
    runner = _runner_for_retry_tests(tmp_path, provider)
    _patch_sleep_if_available(monkeypatch)

    execution = runner._run_role(
        role="test-writer",
        prompt="Write tests",
        stage_label="Stage 1: Test Generation",
    )

    assert execution.output == "success-attempt-2"
    assert provider.calls == ["test-writer", "test-writer"]
    log_text = (tmp_path / ".pipeline-state" / "demo.log").read_text(encoding="utf-8")
    assert "retry" in log_text.lower()


def test_run_role_respects_configured_retry_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    provider = ConfigurableTransientProvider(failures=2)
    runner = _runner_for_retry_tests(tmp_path, provider)
    runner.config.provider_retry_attempts = 2
    _patch_sleep_if_available(monkeypatch)

    execution = runner._run_role(
        role="test-writer",
        prompt="Write tests",
        stage_label="Stage 1: Test Generation",
    )

    assert execution.output == "success-attempt-3"
    assert len(provider.calls) == 3
    log_text = (tmp_path / ".pipeline-state" / "demo.log").read_text(encoding="utf-8")
    assert "retry" in log_text.lower()


def test_run_role_propagates_after_retry_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider = ConfigurableTransientProvider(failures=3)
    runner = _runner_for_retry_tests(tmp_path, provider)
    _patch_sleep_if_available(monkeypatch)

    with pytest.raises(PipelineError) as exc_info:
        runner._run_role(
            role="test-writer",
            prompt="Write tests",
            stage_label="Stage 1: Test Generation",
        )

    assert exc_info.value.exit_code == EXIT_PROVIDER_EXEC_FAILED
    assert len(provider.calls) == 2
    log_text = (tmp_path / ".pipeline-state" / "demo.log").read_text(encoding="utf-8")
    assert "retry" in log_text.lower()


def _runner_with_code_reviewed_state(
    tmp_path: Path,
    provider=None,
    spec_text: str | None = None,
):
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    (specs_dir / "demo-spec.md").write_text(spec_text or "# demo spec\n", encoding="utf-8")
    state_dir = tmp_path / ".pipeline-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "demo.json"
    state_path.write_text(
        json.dumps(
            {
                "task": "demo",
                "provider": provider.name if provider else "dummy",
                "stage": "CODE_REVIEWED",
                "iteration": 0,
            }
        ),
        encoding="utf-8",
    )
    return PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=provider or DummyProvider(),
    )


def test_final_pytest_gate_runs_after_code_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runner = _runner_with_code_reviewed_state(tmp_path)
    called: list[str] = []

    def fake_gate(self, label: str) -> None:  # noqa: ANN401
        called.append(label)

    monkeypatch.setattr(PipelineRunner, "_run_pytest_gate", fake_gate)

    assert runner.run() == EXIT_SUCCESS
    assert called, "Expected the final pytest gate to run"
    assert "pytest" in called[0].lower()
    state = json.loads((tmp_path / ".pipeline-state" / "demo.json").read_text(encoding="utf-8"))
    assert state["stage"] == "VERIFIED"


def test_final_pytest_gate_runs_after_code_review_with_artifact_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    artifact_spec = """# demo spec

## Artifact Pipeline

### Training
command: echo training
required_files: []
metrics_file: ""
metrics_checks: []

### Evaluation
command: echo evaluation
required_files: []
metrics_file: ""
metrics_checks: []

### Acceptance
summary_file: acceptance.txt
all_checks_must_pass: true
min_checks_pass: 0
"""
    runner = _runner_with_code_reviewed_state(tmp_path, spec_text=artifact_spec)
    called: list[str] = []
    artifact_calls: list[str] = []

    def fake_gate(self, label: str) -> None:  # noqa: ANN401
        called.append(label)

    def fake_artifact_stage(self, *, config, stage_label, error_exit_code):  # noqa: ANN401
        artifact_calls.append(stage_label)
        return []

    monkeypatch.setattr(PipelineRunner, "_run_pytest_gate", fake_gate)
    monkeypatch.setattr(PipelineRunner, "_run_artifact_stage", fake_artifact_stage)

    assert runner.run() == EXIT_SUCCESS
    assert called, "Expected the final pytest gate to run before artifacts"
    assert any("pytest" in label.lower() for label in called)
    assert artifact_calls == ["Stage 6: Produce Artifacts", "Stage 7: Validate Artifacts"]
    state = json.loads((tmp_path / ".pipeline-state" / "demo.json").read_text(encoding="utf-8"))
    assert state["stage"] == "VERIFIED"


def test_final_pytest_gate_failure_prevents_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    exit_code = getattr(pipeline_core, "EXIT_FINAL_TESTS_FAILED", None)
    assert isinstance(exit_code, int)
    runner = _runner_with_code_reviewed_state(tmp_path)

    def fake_gate(self, label: str) -> None:  # noqa: ANN401
        raise PipelineError("final tests failed", exit_code)

    monkeypatch.setattr(PipelineRunner, "_run_pytest_gate", fake_gate)

    with pytest.raises(PipelineError) as exc_info:
        runner.run()
    assert exc_info.value.exit_code == exit_code
    state = json.loads((tmp_path / ".pipeline-state" / "demo.json").read_text(encoding="utf-8"))
    assert state["stage"] == "CODE_REVIEWED"


def test_pipeline_run_raises_final_tests_failed_when_pytest_gate_command_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    exit_code = getattr(pipeline_core, "EXIT_FINAL_TESTS_FAILED", None)
    assert isinstance(exit_code, int)
    runner = _runner_with_code_reviewed_state(tmp_path)

    def fake_run(command, **kwargs):  # noqa: ANN001
        return SimpleNamespace(returncode=1, stdout="fail", stderr="broken")

    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", fake_run)

    with pytest.raises(PipelineError) as exc_info:
        runner.run()
    assert exc_info.value.exit_code == exit_code
    state = json.loads((tmp_path / ".pipeline-state" / "demo.json").read_text(encoding="utf-8"))
    assert state["stage"] == "CODE_REVIEWED"


def test_pipeline_logger_replaces_unencodable_console_output(tmp_path: Path, monkeypatch):
    from spec_driven_dev_pipeline.core import PipelineLogger

    class FakeStdout:
        def __init__(self) -> None:
            self.buffer = io.BytesIO()
            self.encoding = "cp1252"

    fake_stdout = FakeStdout()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    logger = PipelineLogger(tmp_path / "pipeline.log")
    logger.log("unicode \u2192 output")

    assert fake_stdout.buffer.getvalue().decode("cp1252") == "unicode ? output\n"
    assert (tmp_path / "pipeline.log").read_text(encoding="utf-8") == "unicode \u2192 output\n"
