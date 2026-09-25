"""Step-level postcondition checks for work-end pipeline idempotency.

Each function checks whether a specific step's side effect has already
been achieved. Used by the orchestrator engine in the check-execute-verify
pattern: check before executing (skip if met), verify after executing
(fail if not met).

All functions: (ctx) -> bool. Pure checks, no side effects.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _git(repo_path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True, text=True, timeout=10,
    )


def rebase_postcondition(ctx) -> bool:
    project = getattr(ctx, "current_repo_project", None) or ctx.project
    result = _git(project, "merge-base", "--is-ancestor",
                  ctx.base_branch, ctx.branch)
    return result.returncode == 0


def push_postcondition(ctx) -> bool:
    project = getattr(ctx, "current_repo_project", None) or ctx.project
    repo_name = project.name
    sha = ctx.landed_shas.get(repo_name, "")
    if not sha:
        return False
    result = _git(project, "merge-base", "--is-ancestor",
                  sha, f"origin/{ctx.base_branch}")
    return result.returncode == 0


def stamp_postcondition(ctx) -> bool:
    project = getattr(ctx, "current_repo_project", None) or ctx.project
    tip = _git(project, "log", "-1", "--format=%s", ctx.branch)
    if tip.returncode != 0:
        return False
    if not tip.stdout.strip().startswith("chore: branch closed"):
        return False
    sha_match = re.search(r"landed as ([0-9a-f]+)", tip.stdout.strip())
    if not sha_match:
        return True
    sha = sha_match.group(1)
    check = _git(project, "merge-base", "--is-ancestor", sha, ctx.base_branch)
    return check.returncode == 0


def promote_postcondition(ctx) -> bool:
    ws = getattr(ctx, "current_repo_workspace", None) or ctx.workspace
    return (ws / ".artifacts-promoted").exists()


def archive_move_postcondition(ctx) -> bool:
    if not ctx.slot_path or not ctx.family_root:
        return False
    attic = ctx.family_root / "attic" / ctx.slot_num
    return attic.is_dir() and not ctx.slot_path.is_dir()


def landed_marker_postcondition(ctx) -> bool:
    if not ctx.slot_path:
        return False
    landed = ctx.slot_path / ".landed"
    if not landed.exists():
        return False
    content = landed.read_text()
    if "landed_shas=" not in content:
        return False
    for line in content.splitlines():
        if line.startswith("landed_shas="):
            shas = line.split("=", 1)[1]
            if not shas.strip():
                return False
            pairs = [p for p in shas.split(",") if ":" in p]
            return len(pairs) > 0 and all(
                p.split(":", 1)[1].strip() for p in pairs
            )
    return False


def checkout_main_postcondition(ctx) -> bool:
    for repo in [ctx.project, ctx.workspace]:
        result = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if result.returncode != 0 or result.stdout.strip() != "main":
            return False
    return True


def write_marker_postcondition(ctx) -> bool:
    if not ctx.slot_path:
        return False
    return (ctx.slot_path / ".phase-a-complete").exists()


def issues_closed_postcondition(ctx) -> bool:
    if not ctx.covers or not ctx.issue_repo:
        return True
    import sys
    _project_dir = str(Path(__file__).resolve().parent.parent / "project")
    if _project_dir not in sys.path:
        sys.path.insert(0, _project_dir)
    from plan_io import parse_covers
    for issue_num in parse_covers(ctx.covers):
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_num), "--repo", ctx.issue_repo,
             "--json", "state", "--jq", ".state"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or result.stdout.strip() != "CLOSED":
            return False
    return True


def cleanup_scaffold_postcondition(ctx) -> bool:
    ws = ctx.workspace
    scaffold = ["JOURNAL.md", ".execute-progress", ".land-ledger.jsonl",
                ".artifacts-promoted"]
    return not any((ws / f).exists() for f in scaffold)
