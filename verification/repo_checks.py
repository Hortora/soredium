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


def check_plan_in_project(project_path: Path) -> list[Finding]:
    """Detect .plan in a project repo that has a workspace (wksp/ symlink)."""
    findings: list[Finding] = []
    plan = project_path / ".plan"
    if not plan.exists():
        return findings
    wksp = project_path / "wksp"
    if wksp.is_symlink():
        findings.append(Finding(
            "ERROR", "plan-in-project",
            f".plan exists in project repo but wksp/ symlink points to a workspace — .plan should be in the workspace",
        ))
    return findings


def check_workspace_symlink_integrity(repo_path: Path) -> list[Finding]:
    """Verify wksp symlink points to correct workspace and proj points back."""
    findings: list[Finding] = []
    wksp = repo_path / "wksp"
    if not wksp.is_symlink():
        return findings

    try:
        resolved = wksp.resolve()
    except OSError:
        findings.append(Finding("ERROR", "wksp-dangling", "wksp symlink is dangling"))
        return findings

    if not resolved.is_dir():
        findings.append(Finding("ERROR", "wksp-not-dir", f"wksp resolves to non-directory {resolved}"))
        return findings

    proj = resolved / "proj"
    if not proj.is_symlink():
        findings.append(Finding("WARN", "wksp-no-proj", f"workspace at {resolved} has no proj symlink back"))
        return findings

    try:
        proj_target = proj.resolve()
        if proj_target != repo_path.resolve():
            findings.append(Finding(
                "ERROR", "wksp-wrong-target",
                f"workspace proj points to {proj_target}, expected {repo_path.resolve()}",
            ))
    except OSError:
        findings.append(Finding("ERROR", "wksp-proj-dangling", "workspace proj symlink is dangling"))

    # Check workspace branch matches repo branch
    if is_git_repo(repo_path) and is_git_repo(resolved):
        r_repo = git(repo_path, "branch", "--show-current")
        r_ws = git(resolved, "branch", "--show-current")
        if r_repo.returncode == 0 and r_ws.returncode == 0:
            repo_branch = r_repo.stdout.strip()
            ws_branch = r_ws.stdout.strip()
            if repo_branch != "main" and ws_branch != repo_branch and ws_branch != "main":
                findings.append(Finding(
                    "WARN", "ws-branch-mismatch",
                    f"repo on {repo_branch} but workspace on {ws_branch}",
                ))

    return findings


def check_db_state_matches_disk(
    slot_number: int, family_root: str, slot_dir: Path, db_path: Path,
) -> list[Finding]:
    """Verify DB slot state matches disk markers."""
    findings: list[Finding] = []
    if not db_path.exists():
        return findings

    import sqlite3
    try:
        db = sqlite3.connect(str(db_path))
        cur = db.cursor()
        cur.execute(
            "SELECT state FROM slots WHERE slot_number=? AND family_root=?",
            (slot_number, family_root),
        )
        row = cur.fetchone()
        db.close()
    except Exception:
        return findings

    if not row:
        findings.append(Finding("WARN", "db-missing", f"slot {slot_number} not in DB"))
        return findings

    db_state = row[0]
    has_landed = (slot_dir / ".landed").exists()

    if has_landed and db_state == "active":
        findings.append(Finding(
            "ERROR", "db-stale",
            f".landed exists but DB state is '{db_state}' (should be 'landed')",
        ))
    elif not has_landed and db_state in ("landed", "archiving"):
        findings.append(Finding(
            "ERROR", "db-disk-mismatch",
            f"DB state is '{db_state}' but no .landed marker on disk",
        ))

    return findings
