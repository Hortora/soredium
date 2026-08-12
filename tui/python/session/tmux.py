"""TmuxProvider — persistent background sessions via tmux."""
from __future__ import annotations

import subprocess

from commands.events import IssueContext


class TmuxProvider:
    def __init__(self, cli_command: str = "claude") -> None:
        self._cli_command = cli_command
        self._session_name: str | None = None

    def session_name_for(self, context: IssueContext) -> str:
        repo = context.project_path.rstrip("/").split("/")[-1]
        return f"soredium-{repo}-{context.issue or 'main'}"

    def start(self, context: IssueContext) -> None:
        self._session_name = self.session_name_for(context)
        subprocess.run(
            [
                "tmux", "new-session", "-d",
                "-s", self._session_name,
                "-c", context.project_path,
                self._cli_command,
            ],
            check=False,
        )

    def run(self) -> None:
        if not self._session_name:
            return
        subprocess.run(
            ["tmux", "attach-session", "-t", self._session_name],
        )

    def is_active(self) -> bool:
        if not self._session_name:
            return False
        result = subprocess.run(
            ["tmux", "has-session", "-t", self._session_name],
            capture_output=True,
        )
        return result.returncode == 0

    def stop(self) -> None:
        if not self._session_name:
            return
        subprocess.run(
            ["tmux", "kill-session", "-t", self._session_name],
            capture_output=True,
        )
        self._session_name = None
