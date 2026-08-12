"""Repo/slot discovery — scans configured paths for soredium-managed projects."""
from __future__ import annotations

import subprocess
from pathlib import Path

from commands.events import RepoSlotInfo, HomeReady


def discover_repos(scan_paths: list[str]) -> HomeReady:
    """Scan directories for repos and slots, resolve context for each."""
    repos: list[RepoSlotInfo] = []
    for scan_path in scan_paths:
        root = Path(scan_path).expanduser()
        if not root.is_dir():
            continue
        for candidate in _find_repos(root):
            info = _resolve_repo_info(candidate)
            if info:
                repos.append(info)
        for slot_dir in _find_slots(root):
            for info in _resolve_slot_info(slot_dir):
                repos.append(info)
    return HomeReady(repos=repos)


def _find_repos(root: Path) -> list[Path]:
    """Find directories containing .git and CLAUDE.md (up to 2 levels deep)."""
    results: list[Path] = []
    try:
        for d in root.iterdir():
            if not d.is_dir() or d.name.startswith("."):
                continue
            if (d / ".git").exists() and (d / "CLAUDE.md").exists():
                results.append(d)
            else:
                try:
                    for sub in d.iterdir():
                        if sub.is_dir() and not sub.name.startswith("."):
                            if (sub / ".git").exists() and (sub / "CLAUDE.md").exists():
                                results.append(sub)
                except PermissionError:
                    pass
    except PermissionError:
        pass
    return results


def _find_slots(root: Path) -> list[Path]:
    """Find slot directories (contain .slot marker) under root/slots/."""
    results: list[Path] = []
    slots_dir = root / "slots"
    if not slots_dir.is_dir():
        return results
    try:
        for d in slots_dir.iterdir():
            if d.is_dir() and (d / ".slot").exists():
                results.append(d)
    except PermissionError:
        pass
    return results


def _resolve_repo_info(repo_path: Path) -> RepoSlotInfo | None:
    """Resolve context for a single repo."""
    try:
        branch = subprocess.run(
            ["git", "-C", str(repo_path), "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip() or "main"

        repo_name = f"{repo_path.parent.name}/{repo_path.name}"
        state = "idle" if branch in ("main", "master") else "active"

        return RepoSlotInfo(
            repo=repo_name,
            slot=None,
            branch=branch,
            state=state,
            issue=_extract_issue(branch),
            plan_position=None,
            tmux_session=_check_tmux_session(repo_name, None),
            project_path=str(repo_path),
            workspace_path=None,
        )
    except Exception:
        return None


def _resolve_slot_info(slot_path: Path) -> list[RepoSlotInfo]:
    """Resolve context for all git repos in a slot directory."""
    results: list[RepoSlotInfo] = []
    try:
        for child in slot_path.iterdir():
            if not child.is_dir() or not (child / ".git").exists():
                continue

            branch = subprocess.run(
                ["git", "-C", str(child), "branch", "--show-current"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip() or "main"

            slot_name = f"slot/{slot_path.name}"
            state = "idle" if branch in ("main", "master") else "active"

            results.append(RepoSlotInfo(
                repo=child.name,
                slot=slot_name,
                branch=branch,
                state=state,
                issue=_extract_issue(branch),
                plan_position=None,
                tmux_session=_check_tmux_session(child.name, slot_name),
                project_path=str(child),
                workspace_path=None,
            ))
    except Exception:
        pass
    return results


def _extract_issue(branch: str) -> int | None:
    """Extract issue number from branch name like 'issue-42-fix'."""
    if branch.startswith("issue-"):
        parts = branch.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
    return None


def _check_tmux_session(repo: str, slot: str | None) -> str | None:
    """Check if a tmux session exists for this repo/slot."""
    name = f"soredium-{repo.replace('/', '-')}"
    if slot:
        name += f"-{slot.replace('/', '-')}"
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", name],
            capture_output=True, timeout=2,
        )
        return name if result.returncode == 0 else None
    except Exception:
        return None
