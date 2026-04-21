"""Tests for portable executable discovery."""

from __future__ import annotations

import io
import importlib
import os
from pathlib import Path
import tokenize
from types import SimpleNamespace

import pytest

from spec_driven_dev_pipeline.core import (
    EXIT_PROVIDER_EXEC_FAILED,
)


PROVIDERS_DIR = Path("src/spec_driven_dev_pipeline/providers")

FORBIDDEN_PATH_FRAGMENTS = ("APPDATA", "\\npm\\", ".cmd")
RESOLVER_BACKED_PROVIDERS = [
    ("spec_driven_dev_pipeline.providers.claude", "ClaudeProvider", "claude"),
    ("spec_driven_dev_pipeline.providers.codex", "CodexProvider", "codex"),
    ("spec_driven_dev_pipeline.providers.gemini", "GeminiProvider", "gemini"),
    ("spec_driven_dev_pipeline.providers.opencode", "OpenCodeProvider", "opencode"),
]


def _executables_module():
    return importlib.import_module("spec_driven_dev_pipeline.utils.executables")


def _reloaded_provider_class(module_name: str, class_name: str):
    module = importlib.import_module(module_name)
    reloaded = importlib.reload(module)
    return getattr(reloaded, class_name), reloaded


def _contains_forbidden_fragment_outside_comments(source: str, fragment: str) -> bool:
    reader = io.StringIO(source).readline
    for token in tokenize.generate_tokens(reader):
        if token.type == tokenize.COMMENT:
            continue
        if fragment in token.string:
            return True
    return False


def test_source_scan_ignores_comment_only_fragments():
    source = """\
def build_command():
    return "portable"  # APPDATA \\npm\\ .cmd should be ignored here
"""

    for fragment in FORBIDDEN_PATH_FRAGMENTS:
        assert _contains_forbidden_fragment_outside_comments(source, fragment) is False


def test_provider_sources_do_not_contain_windows_path_fragments_outside_comments():
    repo_root = Path(__file__).resolve().parents[1]
    offending: dict[str, list[str]] = {}

    for relative_path in sorted(PROVIDERS_DIR.rglob("*.py")):
        text = (repo_root / relative_path).read_text(encoding="utf-8")
        matches = [
            fragment
            for fragment in FORBIDDEN_PATH_FRAGMENTS
            if _contains_forbidden_fragment_outside_comments(text, fragment)
        ]
        if matches:
            offending[relative_path.as_posix()] = matches

    assert not offending, f"found hardcoded Windows executable fragments: {offending}"


def test_resolver_returns_explicit_override_without_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    executables = _executables_module()
    override = tmp_path / "bin" / "codex"
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text("echo placeholder\n", encoding="utf-8")

    looked_up: list[object] = []

    def fake_which(*args, **kwargs):  # noqa: ANN001
        looked_up.append((args, kwargs))
        raise AssertionError("shutil.which should not be called when an override path is supplied")

    monkeypatch.setattr(executables.shutil, "which", fake_which)

    resolved = executables.resolve_executable("codex", str(override))

    assert Path(resolved) == override.resolve()
    assert Path(resolved).is_absolute()
    assert looked_up == []


def test_resolver_reports_missing_tool_and_search_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    executables = _executables_module()
    searched_dirs = [tmp_path / "bin-a", tmp_path / "bin-b"]
    for directory in searched_dirs:
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PATH", os.pathsep.join(str(directory) for directory in searched_dirs))
    monkeypatch.setattr(executables.shutil, "which", lambda *args, **kwargs: None)

    with pytest.raises(Exception) as exc_info:
        executables.resolve_executable("gemini")

    message = str(exc_info.value)
    assert "gemini" in message
    assert "PATH" in message.upper()
    assert "install" in message.lower()
    for directory in searched_dirs:
        assert str(directory) in message


def test_resolver_returns_absolute_path_from_path_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    executables = _executables_module()
    executable = tmp_path / "bin" / "codex"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("echo placeholder\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    looked_up: list[str] = []

    monkeypatch.setattr(
        executables.shutil,
        "which",
        lambda logical_tool_name, *args, **kwargs: (
            looked_up.append(logical_tool_name) or str(Path("bin") / logical_tool_name)
        ),
    )

    resolved = executables.resolve_executable("codex")

    assert Path(resolved) == executable.resolve()
    assert Path(resolved).is_absolute()
    assert looked_up == ["codex"]


def test_resolver_rejects_invalid_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    executables = _executables_module()
    override = tmp_path / "missing" / "codex"

    def fake_which(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("shutil.which should not be called when an override is supplied")

    monkeypatch.setattr(executables.shutil, "which", fake_which)

    with pytest.raises(Exception) as exc_info:
        executables.resolve_executable("codex", str(override))

    message = str(exc_info.value)
    assert "codex" in message
    assert str(override) in message or str(override.resolve()) in message


@pytest.mark.parametrize(
    "provider_module_name, provider_class_name, tool_name", RESOLVER_BACKED_PROVIDERS
)
def test_provider_uses_shared_executable_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_module_name: str,
    provider_class_name: str,
    tool_name: str,
):
    executables = _executables_module()
    resolved_executable = tmp_path / "bin" / tool_name
    resolved_executable.parent.mkdir(parents=True, exist_ok=True)
    resolved_executable.write_text("echo resolved\n", encoding="utf-8")

    resolver_calls: list[str] = []

    def fake_resolve(logical_tool_name, override=None):  # noqa: ANN001
        resolver_calls.append(f"{logical_tool_name}:{override!r}")
        return str(resolved_executable.resolve())

    monkeypatch.setattr(executables, "resolve_executable", fake_resolve)
    provider_cls, provider_module = _reloaded_provider_class(
        provider_module_name, provider_class_name
    )

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):  # noqa: ANN001
        captured["command"] = command
        captured["kwargs"] = kwargs
        output_path = (
            Path(command[command.index("--output-last-message") + 1])
            if "--output-last-message" in command
            else None
        )
        if output_path is not None:
            output_path.write_text("resolved output\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="resolved output\n", stderr="")

    monkeypatch.setattr(provider_module.subprocess, "run", fake_run)

    provider = provider_cls()
    state_dir = tmp_path / ".pipeline-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    result = provider.run_role(
        role="implementer",
        prompt="Implement code",
        repo_root=tmp_path,
        state_dir=state_dir,
    )

    assert resolver_calls == [f"{tool_name}:None"]
    assert captured["command"][0] == str(resolved_executable.resolve())
    assert Path(captured["command"][0]).is_absolute()
    assert result.output == "resolved output"


@pytest.mark.parametrize(
    "provider_module_name, provider_class_name, tool_name", RESOLVER_BACKED_PROVIDERS
)
def test_provider_forwards_configured_executable_override_to_shared_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_module_name: str,
    provider_class_name: str,
    tool_name: str,
):
    executables = _executables_module()
    resolved_executable = tmp_path / "bin" / tool_name
    resolved_executable.parent.mkdir(parents=True, exist_ok=True)
    resolved_executable.write_text("echo resolved\n", encoding="utf-8")
    override_executable = tmp_path / "custom" / tool_name
    override_executable.parent.mkdir(parents=True, exist_ok=True)
    override_executable.write_text("echo override\n", encoding="utf-8")

    resolver_calls: list[tuple[str, Path | None]] = []

    def fake_resolve(logical_tool_name, override=None):  # noqa: ANN001
        resolver_calls.append((logical_tool_name, Path(override) if override is not None else None))
        return str(resolved_executable.resolve())

    monkeypatch.setattr(executables, "resolve_executable", fake_resolve)
    provider_cls, provider_module = _reloaded_provider_class(
        provider_module_name, provider_class_name
    )

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):  # noqa: ANN001
        captured["command"] = command
        captured["kwargs"] = kwargs
        output_path = (
            Path(command[command.index("--output-last-message") + 1])
            if "--output-last-message" in command
            else None
        )
        if output_path is not None:
            output_path.write_text("resolved output\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="resolved output\n", stderr="")

    monkeypatch.setattr(provider_module.subprocess, "run", fake_run)

    provider = provider_cls()
    provider.executable = override_executable
    state_dir = tmp_path / ".pipeline-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    result = provider.run_role(
        role="implementer",
        prompt="Implement code",
        repo_root=tmp_path,
        state_dir=state_dir,
    )

    assert resolver_calls == [(tool_name, override_executable)]
    assert captured["command"][0] == str(resolved_executable.resolve())
    assert Path(captured["command"][0]).is_absolute()
    assert result.output == "resolved output"


@pytest.mark.parametrize(
    "provider_module_name, provider_class_name, tool_name", RESOLVER_BACKED_PROVIDERS
)
def test_pipeline_fails_before_stage_one_when_provider_cli_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_module_name: str,
    provider_class_name: str,
    tool_name: str,
):
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    (specs_dir / "demo-spec.md").write_text("# demo spec\n", encoding="utf-8")

    searched_dirs = [tmp_path / "bin-a", tmp_path / "bin-b"]
    for directory in searched_dirs:
        directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PATH", os.pathsep.join(str(directory) for directory in searched_dirs))

    executables = _executables_module()
    monkeypatch.setattr(executables.shutil, "which", lambda *args, **kwargs: None)
    _, provider_module = _reloaded_provider_class(provider_module_name, provider_class_name)

    def fake_run(*args, **kwargs):  # noqa: ANN001
        raise AssertionError(
            "subprocess.run should not be reached when executable lookup fails before Stage 1"
        )

    monkeypatch.setattr(provider_module.subprocess, "run", fake_run)

    log_path = tmp_path / ".pipeline-state" / "demo.log"

    run_pipeline = importlib.import_module("scripts.run_pipeline")
    run_pipeline = importlib.reload(run_pipeline)
    monkeypatch.setattr(
        run_pipeline,
        "parse_args",
        lambda: SimpleNamespace(
            task="demo",
            provider=tool_name,
            config=None,
            repo_root=tmp_path,
            max_revisions=4,
        ),
    )

    exit_code = run_pipeline.main()
    assert exit_code == EXIT_PROVIDER_EXEC_FAILED

    message = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert tool_name in message.lower()
    assert "path" in message.lower()
    assert "install" in message.lower()
    for directory in searched_dirs:
        assert str(directory) in message

    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8")
        assert "Stage 1: Test Generation" not in log_text
