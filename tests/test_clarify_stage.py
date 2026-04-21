"""Behavioral tests for the clarify stage."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import run_pipeline
from scripts.run_pipeline import load_config
from spec_driven_dev_pipeline.core import (
    EXIT_SUCCESS,
    PipelineConfig,
    PipelineError,
    PipelineRunner,
)
from spec_driven_dev_pipeline.providers.base import ProviderExecution


KNOWN_BAD_SPEC = """\
# Demo Spec

## Goal

Build an orchestrator.

## Requirements

- The spec names an `Orchestrator` class.
- The constructor shape is intentionally unspecified.
- The public entry method is intentionally unspecified.
"""

SMOKE_TEST_SPEC_TEXT = (
    Path(__file__).resolve().parents[1] / "specs" / "smoke-test-spec.md"
).read_text(encoding="utf-8")


def _write_repo(tmp_path: Path, spec_text: str = KNOWN_BAD_SPEC) -> None:
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    (specs_dir / "demo-spec.md").write_text(spec_text, encoding="utf-8")

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "clarify.md").write_text("clarify dedicated template marker", encoding="utf-8")
    (prompts_dir / "test_writer.md").write_text("test writer base prompt", encoding="utf-8")
    (prompts_dir / "implementer.md").write_text("implementer base prompt", encoding="utf-8")
    (prompts_dir / "reviewer.md").write_text("reviewer base prompt", encoding="utf-8")

    (tmp_path / "AGENTS.md").write_text("# repo rules", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.0.0'\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "scripts").mkdir(exist_ok=True)


def _clarify_config(mode: str, cap: int | None = 2) -> PipelineConfig:
    config: Any = PipelineConfig(prompts_dir="prompts")
    setattr(config, "clarify_mode", mode)
    if cap is not None:
        setattr(config, "clarify_max_ambiguities", cap)
    return config


def _fake_run(command, **kwargs):  # noqa: ANN001
    return SimpleNamespace(returncode=0, stdout="", stderr="")


def _clarify_payload(num_items: int = 5) -> dict[str, Any]:
    items = [
        {
            "source": "## Requirements",
            "decision": "constructor shape for Orchestrator",
            "answers": [
                "__init__(repo_root)",
                "__init__(config)",
                "factory method",
            ],
        },
        {
            "source": "## Requirements",
            "decision": "entry method name",
            "answers": ["run", "execute", "start"],
        },
    ]
    for index in range(2, num_items):
        items.append(
            {
                "source": "## Requirements",
                "decision": f"additional ambiguity {index + 1}",
                "answers": ["option A", "option B", "option C"],
            }
        )
    return {"ambiguities": items}


class ClarifyHarnessProvider:
    """Provider stub that records prompts and produces deterministic outputs."""

    name = "dummy"

    def __init__(
        self,
        clarify_payload: dict[str, Any],
        *,
        blocked_roles: set[str] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.prompts: dict[str, list[str]] = {
            "clarify": [],
            "test-writer": [],
            "implementer": [],
            "reviewer": [],
        }
        self._clarify_payload = clarify_payload
        self._blocked_roles = blocked_roles or set()
        self._test_writer_runs = 0

    def run_role(self, *, role, prompt, repo_root, state_dir, schema=None):  # noqa: ANN001
        if role in self._blocked_roles:
            raise AssertionError(f"unexpected role: {role}")
        self.calls.append(role)
        self.prompts.setdefault(role, []).append(prompt)

        if role == "clarify":
            assert prompt.startswith("clarify dedicated template marker")
            assert "test writer base prompt" not in prompt
            assert "reviewer base prompt" not in prompt
            assert "Orchestrator" in prompt
            assert "constructor" in prompt.lower()
            assert "entry method" in prompt.lower()
            return ProviderExecution(
                provider=self.name,
                role=role,
                tier="economy",
                model="dummy-model",
                output=json.dumps(self._clarify_payload),
            )

        if role == "test-writer":
            self._test_writer_runs += 1
            test_file = Path(repo_root) / "tests" / "test_demo.py"
            constructor_answer = "__init__(repo_root, config)"
            entry_answer = "run()"
            if constructor_answer in prompt and entry_answer in prompt:
                test_file.write_text(
                    "def test_demo_honors_answered_clarification():\n"
                    f"    assert {constructor_answer!r} in {constructor_answer!r}\n"
                    f"    assert {entry_answer!r} in {entry_answer!r}\n",
                    encoding="utf-8",
                )
            else:
                test_file.write_text(
                    f"def test_demo():\n    assert True  # run {self._test_writer_runs}\n",
                    encoding="utf-8",
                )
            return ProviderExecution(
                provider=self.name,
                role=role,
                tier="economy",
                model="dummy-model",
                output="tests written",
            )

        if role == "implementer":
            return ProviderExecution(
                provider=self.name,
                role=role,
                tier="economy",
                model="dummy-model",
                output="implemented",
            )

        if role == "reviewer":
            return ProviderExecution(
                provider=self.name,
                role=role,
                tier="premium",
                model="dummy-model",
                output='{"decision":"approve","summary":"ok","blocking":[]}',
            )

        raise AssertionError(f"unexpected role: {role}")


def _clarify_artifact(state_dir: Path) -> tuple[Path, dict[str, Any]]:
    for path in sorted(state_dir.rglob("*.json")):
        if path.name == "demo.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "ambiguities" in payload:
            return path, payload
    raise AssertionError("clarify artifact was not written")


def test_load_config_preserves_clarify_mode_keys(tmp_path: Path):
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text(
        'clarify_mode = "blocking"\nclarify_max_ambiguities = 3\n',
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert getattr(config, "clarify_mode", None) == "blocking"
    assert getattr(config, "clarify_max_ambiguities", None) == 3


def test_parse_args_accepts_clarify_mode_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline.py",
            "demo",
            "--provider",
            "codex",
            "--clarify-mode",
            "blocking",
        ],
    )

    args = run_pipeline.parse_args()

    assert args.clarify_mode == "blocking"


def test_main_uses_default_clarify_mode_without_cli_or_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, Any] = {}

    class DummyCLIProvider:
        name = "dummy"

        def __init__(self) -> None:
            self.initialized = True

    def fake_run_from_cli(**kwargs):  # noqa: ANN001
        captured["config"] = kwargs["config"]
        return EXIT_SUCCESS

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline.py",
            "demo",
            "--provider",
            "codex",
            "--repo-root",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(run_pipeline, "run_from_cli", fake_run_from_cli)
    monkeypatch.setattr(run_pipeline, "CodexProvider", DummyCLIProvider)

    result = run_pipeline.main()

    assert result == EXIT_SUCCESS
    assert getattr(captured["config"], "clarify_mode", None) == "advisory"


def test_main_uses_config_clarify_mode_without_cli_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, Any] = {}

    class DummyCLIProvider:
        name = "dummy"

        def __init__(self) -> None:
            self.initialized = True

    def fake_run_from_cli(**kwargs):  # noqa: ANN001
        captured["config"] = kwargs["config"]
        return EXIT_SUCCESS

    config_path = tmp_path / "pipeline.toml"
    config_path.write_text(
        'clarify_mode = "blocking"\nclarify_max_ambiguities = 3\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline.py",
            "demo",
            "--provider",
            "codex",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(run_pipeline, "run_from_cli", fake_run_from_cli)
    monkeypatch.setattr(run_pipeline, "CodexProvider", DummyCLIProvider)

    result = run_pipeline.main()

    assert result == EXIT_SUCCESS
    assert getattr(captured["config"], "clarify_mode", None) == "blocking"
    assert getattr(captured["config"], "clarify_max_ambiguities", None) == 3


def test_off_mode_keeps_existing_pipeline_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_repo(tmp_path, spec_text=SMOKE_TEST_SPEC_TEXT)
    provider = ClarifyHarnessProvider(_clarify_payload())
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_run)
    config = _clarify_config("off")

    result = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=provider,
        config=config,
    ).run()

    assert result == EXIT_SUCCESS
    assert provider.calls == ["test-writer", "reviewer", "implementer", "implementer", "reviewer"]
    assert provider.prompts["clarify"] == []
    assert "## Clarifications" not in provider.prompts["test-writer"][-1]
    assert "## Clarifications" not in provider.prompts["reviewer"][-1]
    state_dir = tmp_path / ".pipeline-state"
    assert not any(
        "clarify" in path.name.lower() for path in state_dir.rglob("*") if path.is_file()
    )
    assert not any(
        "ambiguities" in json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / ".pipeline-state").rglob("*.json")
        if path.name != "demo.json"
    )


def test_advisory_mode_writes_capped_artifact_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_repo(tmp_path)
    provider = ClarifyHarnessProvider(_clarify_payload(num_items=5))
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_run)
    config = _clarify_config("advisory", cap=2)

    result = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=provider,
        config=config,
    ).run()

    assert result == EXIT_SUCCESS
    assert provider.calls[0] == "clarify"
    assert provider.calls[1] == "test-writer"
    artifact_path, payload = _clarify_artifact(tmp_path / ".pipeline-state")
    assert len(payload["ambiguities"]) == 2
    assert [item["decision"] for item in payload["ambiguities"][:2]] == [
        "constructor shape for Orchestrator",
        "entry method name",
    ]
    for ambiguity in payload["ambiguities"]:
        assert ambiguity["source"] == "## Requirements"
        assert ambiguity["decision"]
        assert 2 <= len(ambiguity["answers"]) <= 4
    assert artifact_path.name != "demo.json"
    assert "## Clarifications" not in provider.prompts["test-writer"][-1]
    assert "## Clarifications" not in provider.prompts["reviewer"][-1]


def test_advisory_mode_uses_default_clarify_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_repo(tmp_path)
    provider = ClarifyHarnessProvider(_clarify_payload(num_items=5))
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_run)
    config = _clarify_config("advisory", cap=None)

    result = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=provider,
        config=config,
    ).run()

    assert result == EXIT_SUCCESS
    _, payload = _clarify_artifact(tmp_path / ".pipeline-state")
    assert len(payload["ambiguities"]) == 2


def test_advisory_mode_keeps_shorter_clarify_payload_unpadded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_repo(tmp_path)
    provider = ClarifyHarnessProvider(_clarify_payload(num_items=2))
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_run)
    config = _clarify_config("advisory", cap=4)

    result = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=provider,
        config=config,
    ).run()

    assert result == EXIT_SUCCESS
    _, payload = _clarify_artifact(tmp_path / ".pipeline-state")
    assert len(payload["ambiguities"]) == 2


def test_blocking_mode_stops_before_test_writer_without_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_repo(tmp_path)
    provider = ClarifyHarnessProvider(_clarify_payload())
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_run)
    config = _clarify_config("blocking")

    runner = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=provider,
        config=config,
    )

    with pytest.raises(PipelineError):
        runner.run()

    artifact_path, payload = _clarify_artifact(tmp_path / ".pipeline-state")
    assert artifact_path.exists()
    assert len(payload["ambiguities"]) == 2
    assert provider.calls == ["clarify"]
    assert "test-writer" not in provider.calls
    assert "reviewer" not in provider.calls


def test_cli_clarify_mode_overrides_config_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class DummyCLIProvider:
        name = "dummy"

        def __init__(self) -> None:
            self.initialized = True

    def fake_run_from_cli(**kwargs):  # noqa: ANN001
        captured["config"] = kwargs["config"]
        return EXIT_SUCCESS

    config_path = tmp_path / "pipeline.toml"
    config_path.write_text(
        'clarify_mode = "advisory"\nclarify_max_ambiguities = 3\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline.py",
            "demo",
            "--provider",
            "codex",
            "--config",
            str(config_path),
            "--repo-root",
            str(tmp_path),
            "--max-revisions",
            "4",
            "--clarify-mode",
            "blocking",
        ],
    )
    monkeypatch.setattr(run_pipeline, "run_from_cli", fake_run_from_cli)
    monkeypatch.setattr(run_pipeline, "CodexProvider", DummyCLIProvider)

    result = run_pipeline.main()

    assert result == EXIT_SUCCESS
    assert getattr(captured["config"], "clarify_mode", None) == "blocking"
    assert getattr(captured["config"], "clarify_max_ambiguities", None) == 3


def test_answered_artifact_is_reused_and_injected_into_downstream_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    unanswered_root = tmp_path / "unanswered"
    answered_root = tmp_path / "answered"
    _write_repo(unanswered_root)
    _write_repo(answered_root)
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_run)
    unanswered_config = _clarify_config("advisory", cap=2)
    answered_config = _clarify_config("advisory", cap=2)

    unanswered_provider = ClarifyHarnessProvider(_clarify_payload(num_items=3))
    unanswered_runner = PipelineRunner(
        repo_root=unanswered_root,
        task="demo",
        provider=unanswered_provider,
        config=unanswered_config,
    )

    assert unanswered_runner.run() == EXIT_SUCCESS
    unanswered_test = (unanswered_root / "tests" / "test_demo.py").read_text(encoding="utf-8")

    artifact_path, _ = _clarify_artifact(unanswered_root / ".pipeline-state")
    answered_artifact_path = (
        answered_root
        / ".pipeline-state"
        / artifact_path.relative_to(unanswered_root / ".pipeline-state")
    )
    answered_artifact_path.parent.mkdir(parents=True, exist_ok=True)
    answered_payload = _clarify_payload(num_items=3)
    answered_payload["answers"] = {
        "constructor shape for Orchestrator": "__init__(repo_root, config)",
        "entry method name": "run()",
    }
    answered_artifact_path.write_text(json.dumps(answered_payload, indent=2), encoding="utf-8")

    answered_provider = ClarifyHarnessProvider(_clarify_payload(num_items=3))
    answered_runner = PipelineRunner(
        repo_root=answered_root,
        task="demo",
        provider=answered_provider,
        config=answered_config,
    )

    assert answered_runner.run() == EXIT_SUCCESS
    answered_test = (answered_root / "tests" / "test_demo.py").read_text(encoding="utf-8")

    assert unanswered_provider.calls[0] == "clarify"
    assert "clarify" not in answered_provider.calls
    assert "## Clarifications" in answered_provider.prompts["test-writer"][-1]
    assert "__init__(repo_root, config)" in answered_provider.prompts["test-writer"][-1]
    assert "run()" in answered_provider.prompts["test-writer"][-1]

    assert unanswered_test != answered_test
    assert "def test_demo()" in unanswered_test
    assert "run()" not in unanswered_test
    assert "def test_demo_honors_answered_clarification()" in answered_test
    assert "__init__(repo_root, config)" in answered_test
    assert "run()" in answered_test
    assert answered_provider.prompts["reviewer"]
    for reviewer_prompt in answered_provider.prompts["reviewer"]:
        assert "## Clarifications" in reviewer_prompt
        assert "__init__(repo_root, config)" in reviewer_prompt
        assert "run()" in reviewer_prompt


def test_blocking_mode_resumes_with_answered_artifact_in_same_state_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_repo(tmp_path)
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_run)
    blocking_config = _clarify_config("blocking", cap=2)

    seed_provider = ClarifyHarnessProvider(_clarify_payload(num_items=3))
    seed_runner = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=seed_provider,
        config=blocking_config,
    )

    with pytest.raises(PipelineError):
        seed_runner.run()

    assert seed_provider.calls == ["clarify"]
    artifact_path, _ = _clarify_artifact(tmp_path / ".pipeline-state")
    answered_payload = _clarify_payload(num_items=3)
    answered_payload["answers"] = {
        "constructor shape for Orchestrator": "__init__(repo_root, config)",
        "entry method name": "run()",
    }
    artifact_path.write_text(json.dumps(answered_payload, indent=2), encoding="utf-8")

    blocking_provider = ClarifyHarnessProvider(
        _clarify_payload(num_items=3),
        blocked_roles={"clarify"},
    )
    blocking_runner = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=blocking_provider,
        config=blocking_config,
    )

    assert blocking_runner.run() == EXIT_SUCCESS

    blocking_test = (tmp_path / "tests" / "test_demo.py").read_text(encoding="utf-8")
    assert blocking_provider.calls[0] == "test-writer"
    assert "clarify" not in blocking_provider.calls
    assert "## Clarifications" in blocking_provider.prompts["test-writer"][0]
    assert "__init__(repo_root, config)" in blocking_provider.prompts["test-writer"][0]
    assert "run()" in blocking_provider.prompts["test-writer"][0]
    assert "def test_demo_honors_answered_clarification()" in blocking_test


def test_answered_artifact_is_scoped_to_task_slice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_repo(tmp_path)
    (tmp_path / "specs" / "alt-spec.md").write_text(KNOWN_BAD_SPEC, encoding="utf-8")
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_run)

    demo_config = _clarify_config("advisory", cap=2)
    demo_provider = ClarifyHarnessProvider(_clarify_payload(num_items=3))
    demo_runner = PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=demo_provider,
        config=demo_config,
    )

    assert demo_runner.run() == EXIT_SUCCESS
    demo_artifact_path, _ = _clarify_artifact(tmp_path / ".pipeline-state")
    answered_payload = json.loads(demo_artifact_path.read_text(encoding="utf-8"))
    answered_payload["answers"] = {
        "constructor shape for Orchestrator": "__init__(repo_root, config)",
        "entry method name": "run()",
    }
    demo_artifact_path.write_text(json.dumps(answered_payload, indent=2), encoding="utf-8")

    alt_provider = ClarifyHarnessProvider(_clarify_payload(num_items=3))
    alt_runner = PipelineRunner(
        repo_root=tmp_path,
        task="alt",
        provider=alt_provider,
        config=demo_config,
    )

    assert alt_runner.run() == EXIT_SUCCESS
    assert alt_provider.calls[0] == "clarify"
    assert "## Clarifications" not in alt_provider.prompts["test-writer"][-1]
    assert (tmp_path / ".pipeline-state" / "demo.json").exists()
    assert (tmp_path / ".pipeline-state" / "alt.json").exists()
