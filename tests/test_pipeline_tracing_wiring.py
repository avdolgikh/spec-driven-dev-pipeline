"""Behavioral tests for tracing wiring in ``PipelineRunner``."""

from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from spec_driven_dev_pipeline.providers.base import ProviderExecution

# !!! UNSKIP-BEFORE-RESUME !!!
# When resuming Slice 3b (`otel-tracing-wiring`), DELETE this `pytestmark` block
# BEFORE relaunching the pipeline. Skipped tests pass vacuously — Stage 4
# validation will green-light an unwired `core.py` otherwise.
# Re-enable recipe: remove the block below, confirm `uv run python -m pytest
# tests/test_pipeline_tracing_wiring.py` is RED (expected: impl pending), then
# launch the pipeline. See AGENTS.md Rule #10 + Known Gaps section.
pytestmark = pytest.mark.skip(
    reason="Slice 3b (otel-tracing-wiring) implementation pending; remove this "
    "skip when core.py tracing wiring lands. See AGENTS.md Known Gaps."
)


CORE_MODULE = "spec_driven_dev_pipeline.core"
TRACING_MODULE = "spec_driven_dev_pipeline.utils.tracing"
OTLP_EXPORTER_MODULES = (
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
)


class RecordingExporter(InMemorySpanExporter):
    """In-memory OTLP exporter that records construction for assertions."""

    instances: list["RecordingExporter"] = []

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.__class__.instances.append(self)


def _span_tree(spans) -> tuple[dict[int, object], dict[int, list[object]]]:
    span_by_id = {span.context.span_id: span for span in spans}
    children_by_parent_id: dict[int, list[object]] = {}
    for span in spans:
        if span.parent is not None:
            children_by_parent_id.setdefault(span.parent.span_id, []).append(span)
    return span_by_id, children_by_parent_id


def _ordered_children(spans, parent_span):
    return sorted(
        [
            span
            for span in spans
            if span.parent is not None and span.parent.span_id == parent_span.context.span_id
        ],
        key=lambda span: span.start_time,
    )


def _namespaced_attributes(span) -> dict[str, object]:
    return {key: value for key, value in span.attributes.items() if "." in key}


def _namespaced_string_values(span) -> list[str]:
    return [str(value) for value in _namespaced_attributes(span).values() if isinstance(value, str)]


def _span_has_namespaced_value(span, expected_value: object) -> bool:
    expected_text = str(expected_value).lower()
    return any(
        str(value).lower() == expected_text for value in _namespaced_attributes(span).values()
    )


def _single_child_span_with_values(spans, parent_span, *expected_values: object):
    matches = [
        span
        for span in spans
        if span.parent is not None
        and span.parent.span_id == parent_span.context.span_id
        and all(
            _span_has_namespaced_value(span, expected_value) for expected_value in expected_values
        )
    ]
    assert len(matches) == 1, (
        f"Expected one child span of {parent_span.name!r} with values {expected_values!r}, found {len(matches)}"
    )
    return matches[0]


def _span_namespace_prefix(span) -> str:
    namespaced_keys = list(_namespaced_attributes(span))
    assert namespaced_keys, f"Expected namespaced attributes on span {span.name!r}"
    prefixes = {key.split(".", 1)[0] for key in namespaced_keys}
    assert len(prefixes) == 1, (
        f"Expected one namespace prefix on {span.name!r}, found {sorted(prefixes)!r}"
    )
    return prefixes.pop()


def _span_iteration_value(span) -> int:
    for key, value in _namespaced_attributes(span).items():
        if "." not in key:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    raise AssertionError(f"Expected an iteration index attribute on span {span.name!r}")


def _pipeline_state_snapshot(root: Path) -> dict[str, str]:
    state_dir = root / ".pipeline-state"
    if not state_dir.exists():
        return {}
    snapshot: dict[str, str] = {}
    for path in sorted(state_dir.rglob("*")):
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return snapshot


def _review_output(decision: str, summary: str, blocking: list[str] | None = None) -> str:
    return json.dumps(
        {
            "decision": decision,
            "summary": summary,
            "blocking": blocking or [],
        }
    )


class DemoTracingProvider:
    """Provider double that drives deterministic pipeline runs."""

    name = "demo-provider"

    def __init__(
        self,
        *,
        review_outputs: list[str],
        raise_on_role: str | None = None,
    ) -> None:
        self.review_outputs = iter(review_outputs)
        self.raise_on_role = raise_on_role
        self.calls: list[str] = []
        self.executions: list[ProviderExecution] = []

    def run_role(self, *, role, prompt, repo_root, state_dir, schema=None):  # noqa: ANN001
        self.calls.append(role)
        if role == "clarify":
            execution = ProviderExecution(
                provider=self.name,
                role=role,
                tier="economy",
                model="clarify-model",
                output='{"ambiguities":[]}',
            )
            self.executions.append(execution)
            return execution
        if role == "test-writer":
            test_file = Path(repo_root) / "tests" / "test_demo.py"
            test_file.write_text("def test_demo():\n    assert True\n", encoding="utf-8")
            execution = ProviderExecution(
                provider=self.name,
                role=role,
                tier="economy",
                model="test-writer-model",
                output="tests written",
            )
            self.executions.append(execution)
            return execution
        if role == "reviewer":
            execution = ProviderExecution(
                provider=self.name,
                role=role,
                tier="premium",
                model="reviewer-model",
                output=next(self.review_outputs),
            )
            self.executions.append(execution)
            return execution
        if role == "implementer":
            if self.raise_on_role == role:
                raise RuntimeError("boom")
            execution = ProviderExecution(
                provider=self.name,
                role=role,
                tier="economy",
                model="implementer-model",
                output="implemented",
            )
            self.executions.append(execution)
            return execution
        raise AssertionError(f"Unexpected role: {role}")


def _prepare_repo(root: Path) -> None:
    (root / "specs").mkdir(parents=True, exist_ok=True)
    (root / "specs" / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    prompts_dir = root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "clarify.md").write_text("clarify", encoding="utf-8")
    (prompts_dir / "test_writer.md").write_text("test writer", encoding="utf-8")
    (prompts_dir / "implementer.md").write_text("implementer", encoding="utf-8")
    (prompts_dir / "reviewer.md").write_text("reviewer", encoding="utf-8")


def _reset_repo_between_runs(root: Path) -> None:
    state_dir = root / ".pipeline-state"
    if state_dir.exists():
        shutil.rmtree(state_dir)
    test_file = root / "tests" / "test_demo.py"
    if test_file.exists():
        test_file.unlink()


def _load_core_with_tracing_spies(monkeypatch: pytest.MonkeyPatch, *, enable_otel: bool):
    RecordingExporter.instances = []
    captured_provider: dict[str, object | None] = {"value": None}
    original_get_tracer_provider = otel_trace.get_tracer_provider

    def capture_provider(provider):
        captured_provider["value"] = provider

    def get_tracer_provider():
        return captured_provider["value"] or original_get_tracer_provider()

    monkeypatch.setattr(otel_trace, "set_tracer_provider", capture_provider)
    monkeypatch.setattr(otel_trace, "get_tracer_provider", get_tracer_provider)
    monkeypatch.setattr(
        "spec_driven_dev_pipeline.utils.tracing.BatchSpanProcessor", SimpleSpanProcessor
    )

    for module_name in OTLP_EXPORTER_MODULES:
        try:
            exporter_module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        monkeypatch.setattr(exporter_module, "OTLPSpanExporter", RecordingExporter)

    if enable_otel:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid/v1/traces")
    else:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    sys.modules.pop(CORE_MODULE, None)
    sys.modules.pop(TRACING_MODULE, None)
    core = importlib.import_module(CORE_MODULE)
    tracing = importlib.import_module(TRACING_MODULE)
    return core, tracing


def _load_core_with_noop_tracing(monkeypatch: pytest.MonkeyPatch):
    import spec_driven_dev_pipeline.utils.tracing as tracing_module

    class _NoopSpan:
        def set_attributes(self, *args, **kwargs):  # noqa: ANN001
            return None

        def record_exception(self, *args, **kwargs):  # noqa: ANN001
            return None

        def set_status(self, *args, **kwargs):  # noqa: ANN001
            return None

        def add_event(self, *args, **kwargs):  # noqa: ANN001
            return None

    @contextmanager
    def noop_span(*args, **kwargs):  # noqa: ANN001
        yield _NoopSpan()

    monkeypatch.setattr(tracing_module, "init_tracing", lambda: None)
    monkeypatch.setattr(tracing_module, "shutdown_tracing", lambda: None)
    monkeypatch.setattr(tracing_module, "span", noop_span)
    monkeypatch.setattr(tracing_module, "set_span_attributes", lambda **kwargs: None)
    monkeypatch.setattr(tracing_module, "record_exception", lambda *args, **kwargs: None)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    sys.modules.pop(CORE_MODULE, None)
    core = importlib.import_module(CORE_MODULE)
    return core, tracing_module


def _load_core_without_tracing_spies(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)

    sys.modules.pop(CORE_MODULE, None)
    sys.modules.pop(TRACING_MODULE, None)
    core = importlib.import_module(CORE_MODULE)
    tracing = importlib.import_module(TRACING_MODULE)
    return core, tracing


def _fake_pytest_run(command, **kwargs):  # noqa: ANN001
    return type("CompletedProcess", (), {"returncode": 0, "stdout": "", "stderr": ""})()


def _run_and_capture(runner, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    try:
        exit_code = runner.run()
    except Exception as exc:  # noqa: BLE001
        if hasattr(exc, "exit_code"):
            exit_code = exc.exit_code
        else:
            raise
    output = capsys.readouterr().out
    return exit_code, output


def _run_pipeline_case(
    core,
    repo_root: Path,
    provider: DemoTracingProvider,
    capsys: pytest.CaptureFixture[str],
    *,
    max_revisions: int = 1,
) -> tuple[int, str, dict[str, str]]:
    runner = core.PipelineRunner(
        repo_root=repo_root,
        task="demo",
        provider=provider,
        max_revisions=max_revisions,
        config=core.PipelineConfig(prompts_dir="prompts"),
    )
    exit_code, stdout = _run_and_capture(runner, capsys)
    return exit_code, stdout, _pipeline_state_snapshot(repo_root)


def _find_stage_with_direct_leaf(
    spans,
    root_children,
    children_by_parent_id: dict[int, list[object]],
    *,
    provider_name: str,
    model: str,
):
    for stage_span in root_children:
        for child_span in _ordered_children(spans, stage_span):
            if child_span.context.span_id in children_by_parent_id:
                continue
            if _single_child_span_with_values([child_span], stage_span, provider_name, model):
                return stage_span, child_span
    raise AssertionError(f"Expected a stage with a direct provider leaf for model {model!r}")


def _find_review_stage(
    spans,
    root_children,
    children_by_parent_id: dict[int, list[object]],
    *,
    provider_name: str,
    model: str,
    min_iterations: int,
    outcome_fragment: str,
):
    for stage_span in root_children:
        iteration_spans = [
            child
            for child in _ordered_children(spans, stage_span)
            if child.context.span_id in children_by_parent_id
        ]
        if len(iteration_spans) < min_iterations:
            continue

        iteration_leafs: list[object] = []
        valid = True
        for iteration_span in iteration_spans:
            children = _ordered_children(spans, iteration_span)
            if len(children) != 1:
                valid = False
                break
            leaf_span = children[0]
            if not _single_child_span_with_values(
                [leaf_span], iteration_span, provider_name, model
            ):
                valid = False
                break
            iteration_leafs.append(leaf_span)
        if not valid:
            continue
        if not any(
            outcome_fragment in value.lower()
            for value in _namespaced_string_values(iteration_spans[-1])
        ):
            continue
        return stage_span, iteration_spans, iteration_leafs

    raise AssertionError(
        f"Expected a review stage with at least {min_iterations} iterations and outcome {outcome_fragment!r}"
    )


def test_pipeline_run_exports_span_hierarchy_attributes_and_cap_exit_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    core, tracing = _load_core_with_tracing_spies(monkeypatch, enable_otel=True)
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_pytest_run)

    provider = DemoTracingProvider(
        review_outputs=[
            _review_output("approve", "tests are ready"),
            _review_output("revise", "code needs one more pass", ["retry"]),
            _review_output("revise", "still blocked", ["retry again"]),
            _review_output("revise", "still blocked again", ["retry once more"]),
        ]
    )
    _prepare_repo(tmp_path)

    exit_code, _stdout, _artifacts = _run_pipeline_case(
        core, tmp_path, provider, capsys, max_revisions=2
    )
    tracing.shutdown_tracing()

    assert exit_code == core.EXIT_CODE_REVISION_CAP
    assert RecordingExporter.instances

    spans = RecordingExporter.instances[0].get_finished_spans()
    assert spans

    by_id, children_by_parent_id = _span_tree(spans)
    roots = [span for span in spans if span.parent is None]
    assert len(roots) == 1
    root = roots[0]
    assert root.context.span_id in by_id

    root_children = _ordered_children(spans, root)
    assert len(root_children) >= 6
    clarify_model = next(
        execution.model for execution in provider.executions if execution.role == "clarify"
    )
    test_writer_model = next(
        execution.model for execution in provider.executions if execution.role == "test-writer"
    )
    reviewer_model = next(
        execution.model for execution in provider.executions if execution.role == "reviewer"
    )
    implementer_model = next(
        execution.model for execution in provider.executions if execution.role == "implementer"
    )

    clarify_stage, clarify_leaf = _find_stage_with_direct_leaf(
        spans,
        root_children,
        children_by_parent_id,
        provider_name=provider.name,
        model=clarify_model,
    )
    test_generation_stage, test_generation_leaf = _find_stage_with_direct_leaf(
        spans,
        root_children,
        children_by_parent_id,
        provider_name=provider.name,
        model=test_writer_model,
    )
    implementation_stage, implementation_leaf = _find_stage_with_direct_leaf(
        spans,
        root_children,
        children_by_parent_id,
        provider_name=provider.name,
        model=implementer_model,
    )
    test_review_stage, test_review_iterations, test_review_leafs = _find_review_stage(
        spans,
        root_children,
        children_by_parent_id,
        provider_name=provider.name,
        model=reviewer_model,
        min_iterations=1,
        outcome_fragment="approve",
    )
    code_review_stage, code_review_iterations, code_review_leafs = _find_review_stage(
        spans,
        root_children,
        children_by_parent_id,
        provider_name=provider.name,
        model=reviewer_model,
        min_iterations=2,
        outcome_fragment="cap",
    )

    for stage_span in (
        clarify_stage,
        test_generation_stage,
        implementation_stage,
        test_review_stage,
        code_review_stage,
    ):
        assert stage_span.parent is not None
        assert stage_span.parent.span_id == root.context.span_id
        values = {value.lower() for value in _namespaced_string_values(stage_span)}
        assert "demo" in values
        assert any(
            value
            not in {
                "demo",
                provider.name.lower(),
                clarify_model.lower(),
                test_writer_model.lower(),
                reviewer_model.lower(),
                implementer_model.lower(),
                "approve",
                "revise",
                "cap",
                "cap-exit",
                "error",
            }
            for value in values
        )

    for leaf_span, expected_model in (
        (clarify_leaf, clarify_model),
        (test_generation_leaf, test_writer_model),
        (implementation_leaf, implementer_model),
        (test_review_leafs[0], reviewer_model),
        (code_review_leafs[0], reviewer_model),
    ):
        assert leaf_span.parent is not None
        assert leaf_span.context.span_id not in children_by_parent_id
        assert _single_child_span_with_values(
            [leaf_span], leaf_span.parent, provider.name, expected_model
        )

    test_review_iteration = test_review_iterations[0]
    assert _span_iteration_value(test_review_iteration) >= 0
    assert any(
        "approve" in value.lower() for value in _namespaced_string_values(test_review_iteration)
    )
    assert _span_namespace_prefix(test_review_iteration) == _span_namespace_prefix(
        test_review_leafs[0]
    )

    assert len(code_review_iterations) >= 2
    code_review_iteration_values = [_span_iteration_value(span) for span in code_review_iterations]
    assert len(set(code_review_iteration_values)) == len(code_review_iteration_values)
    assert any(
        "revise" in value.lower() for value in _namespaced_string_values(code_review_iterations[0])
    )
    assert any(
        "cap" in value.lower() for value in _namespaced_string_values(code_review_iterations[-1])
    )

    stage_prefix = _span_namespace_prefix(clarify_stage)
    assert _span_namespace_prefix(test_generation_stage) == stage_prefix
    assert _span_namespace_prefix(implementation_stage) == stage_prefix
    assert _span_namespace_prefix(test_review_iteration) == stage_prefix
    assert _span_namespace_prefix(code_review_iterations[-1]) == stage_prefix
    assert _span_namespace_prefix(clarify_leaf) == stage_prefix
    assert _span_namespace_prefix(test_review_leafs[0]) == stage_prefix
    assert _span_namespace_prefix(code_review_leafs[0]) == stage_prefix


def test_stage_error_is_recorded_on_stage_and_root_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    core, tracing = _load_core_with_tracing_spies(monkeypatch, enable_otel=True)
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_pytest_run)

    provider = DemoTracingProvider(
        review_outputs=[_review_output("approve", "tests are ready")],
        raise_on_role="implementer",
    )
    _prepare_repo(tmp_path)
    runner = core.PipelineRunner(
        repo_root=tmp_path,
        task="demo",
        provider=provider,
        config=core.PipelineConfig(prompts_dir="prompts"),
    )

    with pytest.raises(RuntimeError, match="boom"):
        runner.run()
    capsys.readouterr()
    tracing.shutdown_tracing()

    assert RecordingExporter.instances
    spans = RecordingExporter.instances[0].get_finished_spans()
    assert spans

    roots = [span for span in spans if span.parent is None]
    assert len(roots) == 1
    root = roots[0]
    assert root.status.status_code == StatusCode.ERROR
    assert "boom" in str(getattr(root.status, "description", ""))

    root_children = _ordered_children(spans, root)
    error_stages = [span for span in root_children if span.status.status_code == StatusCode.ERROR]
    assert len(error_stages) == 1
    error_stage = error_stages[0]
    assert error_stage.parent is not None
    assert error_stage.parent.span_id == root.context.span_id
    error_events = [event for event in error_stage.events if event.name == "exception"]
    assert error_events
    event = error_events[0]
    assert event.attributes["exception.type"] == "RuntimeError"
    assert event.attributes["exception.message"] == "boom"
    assert "boom" in str(getattr(error_stage.status, "description", ""))


def test_unconfigured_runs_match_stdout_and_do_not_create_exporters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    RecordingExporter.instances = []
    baseline_core, baseline_tracing = _load_core_with_noop_tracing(monkeypatch)
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_pytest_run)

    baseline_provider = DemoTracingProvider(
        review_outputs=[
            _review_output("approve", "tests are ready"),
            _review_output("revise", "code needs one more pass", ["retry"]),
            _review_output("revise", "still blocked", ["retry again"]),
            _review_output("revise", "still blocked again", ["retry once more"]),
        ]
    )
    repo_root = tmp_path / "repo"
    _prepare_repo(repo_root)
    baseline_exit, baseline_stdout, baseline_artifacts = _run_pipeline_case(
        baseline_core, repo_root, baseline_provider, capsys, max_revisions=2
    )
    baseline_tracing.shutdown_tracing()

    _reset_repo_between_runs(repo_root)
    _prepare_repo(repo_root)

    comparison_core, comparison_tracing = _load_core_without_tracing_spies(monkeypatch)
    monkeypatch.setattr("spec_driven_dev_pipeline.core.subprocess.run", _fake_pytest_run)

    comparison_provider = DemoTracingProvider(
        review_outputs=[
            _review_output("approve", "tests are ready"),
            _review_output("revise", "code needs one more pass", ["retry"]),
            _review_output("revise", "still blocked", ["retry again"]),
            _review_output("revise", "still blocked again", ["retry once more"]),
        ]
    )
    comparison_exit, comparison_stdout, comparison_artifacts = _run_pipeline_case(
        comparison_core, repo_root, comparison_provider, capsys, max_revisions=2
    )
    comparison_tracing.shutdown_tracing()

    assert baseline_exit == comparison_exit == baseline_core.EXIT_CODE_REVISION_CAP
    assert baseline_stdout == comparison_stdout
    assert baseline_artifacts == comparison_artifacts
    assert RecordingExporter.instances == []
