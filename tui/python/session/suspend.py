"""SuspendingProvider — inline suspend/resume sessions."""
from __future__ import annotations

import subprocess

from commands.events import IssueContext


class SuspendingProvider:
    def __init__(self, cli_command: str = "claude") -> None:
        self._cli_command = cli_command
        self._context: IssueContext | None = None

    def start(self, context: IssueContext) -> None:
        self._context = context

    def run(self) -> None:
        if not self._context:
            return
        subprocess.run(
            [self._cli_command],
            cwd=self._context.project_path,
        )

    def is_active(self) -> bool:
        return False

    def stop(self) -> None:
        self._context = None
