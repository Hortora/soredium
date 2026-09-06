"""Repo-level verification checks.

Pure functions that inspect a single repo's state and return findings.
No side effects, no fixes.
"""
from __future__ import annotations

import re
from pathlib import Path

from verification import Finding, git, is_git_repo, read_file_safe

MECHANICAL_PREFIXES = (
    "Merge ", "chore: branch closed", "chore(work-end):", "docs(work-end):",
    "chore: bootstrap", "chore: add .workspace",
    "docs: spec revised", "docs: session handover", "docs: sync ARC42",
)


def check_fork_divergence(repo_path: Path) -> list[Finding]:
    """Detect fork vs upstream divergence on main."""
    findings: list[Finding] = []
    if not repo_path.exists() or not is_git_repo(repo_path):
        return findings

    r_upstream = git(repo_path, "remote", "get-url", "upstream")
    if r_upstream.returncode != 0 or not r_upstream.stdout.strip():
        return findings

    r_fork_local = git(repo_path, "log", "--oneline", "upstream/main..main")
    r_upstream_ahead = git(repo_path, "log", "--oneline", "main..upstream/main")
    fork_local = len(r_fork_local.stdout.strip().splitlines()) if r_fork_local.returncode == 0 and r_fork_local.stdout.strip() else 0
    upstream_ahead = len(r_upstream_ahead.stdout.strip().splitlines()) if r_upstream_ahead.returncode == 0 and r_upstream_ahead.stdout.strip() else 0

    if fork_local > 0 and upstream_ahead > 0:
        findings.append(Finding(
            "ERROR", "fork-upstream-diverged",
            f"fork has {fork_local} local commits, upstream has {upstream_ahead} ahead — needs merge",
        ))
    elif fork_local > 5:
        findings.append(Finding(
            "WARN", "fork-local-accumulation",
            f"{fork_local} fork-local commits on main not upstreamed",
        ))
    return findings


def check_unpushed_main(repo_path: Path) -> list[Finding]:
    """Detect unpushed commits on main, behind-origin, and dirty working tree."""
    findings: list[Finding] = []
    if not repo_path.exists() or not is_git_repo(repo_path):
        return findings

    branch = git(repo_path, "branch", "--show-current").stdout.strip()
    if branch != "main":
        return findings

    r = git(repo_path, "log", "--oneline", "origin/main..main")
    if r.returncode == 0 and r.stdout.strip():
        count = len(r.stdout.strip().splitlines())
        findings.append(Finding(
            "ERROR", "unpushed-main",
            f"{count} unpushed commits on main",
        ))

    r_behind = git(repo_path, "log", "--oneline", "main..origin/main")
    if r_behind.returncode == 0 and r_behind.stdout.strip():
        behind_count = len(r_behind.stdout.strip().splitlines())
        r_ahead = git(repo_path, "log", "--oneline", "origin/main..main")
        ahead_count = len(r_ahead.stdout.strip().splitlines()) if r_ahead.returncode == 0 and r_ahead.stdout.strip() else 0
        if ahead_count > 0:
            findings.append(Finding(
                "ERROR", "fork-diverged",
                f"main diverged from origin — {ahead_count} ahead, {behind_count} behind",
            ))
        else:
            findings.append(Finding(
                "WARN", "behind-origin",
                f"main is {behind_count} commits behind origin/main",
            ))

    r_dirty = git(repo_path, "status", "--short")
    if r_dirty.returncode == 0 and r_dirty.stdout.strip():
        count = len(r_dirty.stdout.strip().splitlines())
        findings.append(Finding(
            "WARN", "dirty-main",
            f"{count} dirty files on main",
        ))
    return findings


def check_conflict_markers_on_remote(
    repo_path: Path, remote: str = "origin",
) -> list[Finding]:
    """Detect committed conflict markers on a remote branch."""
    findings: list[Finding] = []
    if not repo_path.exists() or not is_git_repo(repo_path):
        return findings
    r = git(
        repo_path, "grep", "-l", "<<<<<<<",
        f"{remote}/main", "--",
        "*.java", "*.ts", "*.tsx", "*.json",
    )
    if r.returncode == 0 and r.stdout.strip():
        files = r.stdout.strip().splitlines()
        findings.append(Finding(
            "ERROR", f"{remote}-conflict-markers",
            f"{len(files)} files on {remote}/main have unresolved merge conflict markers",
        ))
    return findings


def check_workspace_wipe(workspace_path: Path) -> list[Finding]:
    """Detect bulk-deleted files in a workspace (possible wipe)."""
    findings: list[Finding] = []
    if not workspace_path.exists() or not is_git_repo(workspace_path):
        return findings
    r = git(workspace_path, "status", "--short")
    if r.returncode != 0 or not r.stdout.strip():
        return findings
    deleted = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("D ")]
    if len(deleted) > 10:
        findings.append(Finding(
            "ERROR", "workspace-wipe",
            f"workspace has {len(deleted)} deleted files — possible wipe",
        ))
    return findings


def check_stuck_close_state(plan_path: Path) -> list[Finding]:
    """Detect .plan files stuck in a closing:* state."""
    findings: list[Finding] = []
    content = read_file_safe(plan_path)
    if content is None:
        return findings
    for line in content.splitlines():
        if line.startswith("state:") and "closing:" in line:
            state = line.split(":", 1)[1].strip()
            findings.append(Finding(
                "ERROR", "stuck-close",
                f".plan state is {state}",
            ))
            break
    return findings


def check_duplicate_commits(
    repo_path: Path, limit: int = 200,
) -> list[Finding]:
    """Detect duplicate commit messages on main (same message, different SHA)."""
    findings: list[Finding] = []
    if not repo_path.exists() or not is_git_repo(repo_path):
        return findings
    r = git(repo_path, "log", "--oneline", "--format=%H %s", "main", f"-{limit}")
    if r.returncode != 0 or not r.stdout.strip():
        return findings
    seen: dict[str, str] = {}
    for line in r.stdout.strip().splitlines():
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        sha, msg = parts[0], parts[1]
        if any(msg.startswith(p) for p in MECHANICAL_PREFIXES):
            continue
        if msg in seen:
            findings.append(Finding(
                "ERROR", "duplicate-commit",
                f"duplicate on main — '{msg[:60]}' at {seen[msg][:8]} and {sha[:8]}",
            ))
        else:
            seen[msg] = sha
    return findings
