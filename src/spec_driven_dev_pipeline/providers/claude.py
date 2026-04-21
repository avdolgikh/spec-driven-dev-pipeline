"""Claude Code provider adapter."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from spec_driven_dev_pipeline.core import EXIT_PROVIDER_EXEC_FAILED, PipelineError
from spec_driven_dev_pipeline.providers.base import ProviderExecution
from spec_driven_dev_pipeline.utils import executables as _executables


@dataclass(frozen=True)
class RoleConfig:
    tier: str
    model: str


class ClaudeProvider:
    """Runs pipeline roles through the Claude CLI."""

    name = "claude"
    _permission_mode = "bypassPermissions"

    def __init__(self) -> None:
        economy_model = os.getenv("CLAUDE_MODEL_ECONOMY", "sonnet")
        self.role_configs = {
            "clarify": RoleConfig(
                tier="economy",
                model=os.getenv("CLAUDE_MODEL_CLARIFY", economy_model),
            ),
            "test-writer": RoleConfig(
                tier="economy",
                model=economy_model,
            ),
            "implementer": RoleConfig(
                tier="economy",
                model=economy_model,
            ),
            "reviewer": RoleConfig(
                tier="premium",
                model=os.getenv("CLAUDE_MODEL_PREMIUM", "opus"),
            ),
        }
        self.executable: str | Path | None = None

    def _command(
        self,
        *,
        role: str,
        prompt: str,
        schema: dict[str, Any] | None,
        executable: str = "claude",
    ) -> list[str]:
        config = self.role_configs[role]
        command = [
            executable,
            "-p",
            prompt,
            "--model",
            config.model,
            "--permission-mode",
            self._permission_mode,
        ]
        if schema is not None:
            command.extend(
                [
                    "--output-format",
                    "json",
                    "--json-schema",
                    json.dumps(schema, separators=(",", ":")),
                ]
            )
        return command

    def run_role(
        self,
        *,
        role: str,
        prompt: str,
        repo_root: Path,
        state_dir: Path,
        schema: dict[str, Any] | None = None,
    ) -> ProviderExecution:
        resolved_executable = _executables.resolve_executable(self.name, override=self.executable)
        config = self.role_configs[role]
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        result = subprocess.run(
            self._command(
                role=role,
                prompt=prompt,
                schema=schema,
                executable=resolved_executable,
            ),
            cwd=repo_root,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        output = result.stdout.strip()
        if result.stderr.strip():
            output = f"{output}\n{result.stderr.strip()}".strip()
        if result.returncode != 0:
            raise PipelineError(
                f"FAIL: Claude provider execution failed for role {role} (exit {result.returncode}).",
                EXIT_PROVIDER_EXEC_FAILED,
            )
        return ProviderExecution(
            provider=self.name,
            role=role,
            tier=config.tier,
            model=config.model,
            output=output,
        )
