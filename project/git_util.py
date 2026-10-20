"""Canonical git command runner for all pipeline code."""
import subprocess
from pathlib import Path


def git(repo: Path | str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a git command against a repo. Never raises on non-zero exit."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout,
    )


def collect_slot_repos(slot_path: str | Path, project: str | Path,
                       workspace: str | Path) -> list[tuple[str, str]]:
    """Build the full list of git repos in a slot, deduped by resolved path.

    Returns [(repo_path_str, label)] — project and workspace first,
    then any sibling repos found in the slot directory.
    """
    seen = {str(Path(project).resolve()), str(Path(workspace).resolve())}
    repos = [(str(project), "project"), (str(workspace), "workspace")]
    slot = Path(slot_path)
    if not slot.is_dir():
        return repos
    for entry in sorted(slot.iterdir()):
        if not entry.is_dir() or not (entry / ".git").exists():
            continue
        resolved = str(entry.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        repos.append((str(entry), entry.name))
    return repos
