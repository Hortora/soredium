#!/usr/bin/env python3
"""Lifecycle corruption detection.

Checks state-vs-environment coherence. Called by ctx.py at session start.
Returns Finding objects — never mutates state, never raises.

Spec: issue-262-lifecycle-corruption-recovery
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import sys
_project_dir = Path(__file__).parent
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

from lifecycle import VALID_STATES
from plan_io import read_plan, read_field, parse_covers, has_uncompleted_items


@dataclass
class Finding:
    scenario: str
    severity: str
    detail: str
    actions: list[str] = field(default_factory=list)


def _git(repo: Path, *args: str, timeout: int = 10) -> tuple[str, int]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo)] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", 1


def check_missing_state(plan_path: Path) -> Optional[Finding]:
    state = read_plan(plan_path)
    if state is None:
        return None
    if not state.fields:
        return None
    if "state" in state.fields:
        return None
    return Finding(
        scenario="S1_MISSING_STATE",
        severity="warning",
        detail="state: field missing from .plan — defaulted to 'active' (legacy migration)",
        actions=["accept_default", "write_scaffolded"],
    )


def check_invalid_state(meta_state: str, plan_path: Path) -> Optional[Finding]:
    if not meta_state or not meta_state.startswith("corrupted:"):
        return None
    raw_value = meta_state[len("corrupted:"):]
    return Finding(
        scenario="S2_INVALID_STATE",
        severity="error",
        detail=f"Unknown state '{raw_value}' in .plan — file may be truncated or hand-edited",
        actions=["write_active", "infer_from_environment", "remove_plan"],
    )


def check_branch_mismatch(
    plan_path: Path, workspace: Path,
    current_branch: str, base_branch: str,
) -> Optional[Finding]:
    if not plan_path.exists():
        return None
    plan_state = read_field(plan_path, "state")
    if plan_state == "drained":
        return None
    plan_branch = read_field(plan_path, "branch")
    if not plan_branch:
        return None
    if plan_branch == current_branch:
        return None
    if plan_branch == base_branch and current_branch == base_branch:
        return None
    actions = ["switch_to_plan_branch", "update_plan_branch", "remove_plan"]
    branch_out, _ = _git(workspace, "branch", "--list", plan_branch)
    if not branch_out.strip():
        actions = ["update_plan_branch", "remove_plan"]
    return Finding(
        scenario="S5_BRANCH_MISMATCH",
        severity="error",
        detail=f".plan says branch '{plan_branch}', git says '{current_branch}'",
        actions=actions,
    )


def check_stale_plan_on_main(
    plan_path: Path, meta_state: str, base_branch: str, on_main: bool,
) -> Optional[Finding]:
    if not on_main or not plan_path.exists():
        return None
    plan_branch = read_field(plan_path, "branch")
    if not plan_branch or plan_branch == base_branch:
        return None
    if meta_state in ("drained", "closing:stamped"):
        return None
    return Finding(
        scenario="S7_STALE_PLAN_ON_MAIN",
        severity="warning",
        detail=f"stale .plan on {base_branch} — references branch '{plan_branch}' with state '{meta_state}'",
        actions=["switch_to_branch", "remove_plan"],
    )


def check_branch_exists(plan_path: Path, project: Path) -> Optional[Finding]:
    if not plan_path.exists():
        return None
    plan_branch = read_field(plan_path, "branch")
    if not plan_branch:
        return None
    local_out, _ = _git(project, "branch", "--list", plan_branch)
    if local_out.strip():
        return None
    remote_out, rc = _git(project, "ls-remote", "--heads", "origin", plan_branch)
    if rc == 0 and remote_out.strip():
        return Finding(
            scenario="S6_BRANCH_NOT_EXIST",
            severity="warning",
            detail=f"branch '{plan_branch}' not local but exists on remote",
            actions=["fetch_and_checkout", "remove_plan"],
        )
    return Finding(
        scenario="S6_BRANCH_NOT_EXIST",
        severity="error",
        detail=f"branch '{plan_branch}' doesn't exist locally or on remote",
        actions=["remove_plan", "recreate_branch"],
    )


def check_closing_postconditions(
    meta_state: str, plan_path: Path,
    project: Path, workspace: Path, base_branch: str,
) -> Optional[Finding]:
    if not meta_state.startswith("closing:"):
        return None
    sub = meta_state.split(":", 1)[1]
    plan_branch = read_field(plan_path, "branch") or ""

    checks: dict[str, tuple[list[str], str]] = {
        "promoted": (
            ["git", "-C", str(workspace), "log", "--oneline", "-1", "--",
             ".artifacts-promoted"],
            "no .artifacts-promoted stamp found",
        ),
        "pushed": (
            ["git", "-C", str(project), "ls-remote", "--heads", "origin", plan_branch],
            f"branch '{plan_branch}' not on remote",
        ),
        "merged": (
            ["git", "-C", str(project), "log", "--oneline",
             f"{base_branch}..{plan_branch}"],
            f"branch '{plan_branch}' has unmerged commits",
        ),
        "stamped": (
            ["git", "-C", str(project), "log", "-1", "--format=%s", plan_branch],
            "last commit is not a closure stamp",
        ),
    }
    if sub not in checks:
        return None
    cmd, failure_detail = checks[sub]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return None
    stdout = result.stdout.strip()

    failed = False
    if sub == "promoted":
        failed = not stdout
    elif sub == "pushed":
        failed = not stdout
    elif sub == "merged":
        non_stamp = [line for line in stdout.splitlines()
                     if not line.split(" ", 1)[-1].startswith("chore: branch closed")]
        failed = bool(non_stamp)
    elif sub == "stamped":
        failed = not stdout.startswith("chore: branch closed")

    if not failed:
        return None

    actions = ["continue_close"]
    if sub in ("review", "verified"):
        actions.append("rollback_to_active")
    return Finding(
        scenario="S4_CLOSING_POSTCONDITION",
        severity="error",
        detail=f"state: {meta_state} but {failure_detail} — ceremony was interrupted",
        actions=actions,
    )


def check_active_all_closed(
    plan_path: Path, meta_state: str, owner_repo: str,
) -> Optional[Finding]:
    if not owner_repo or meta_state != "active":
        return None
    if not plan_path.exists():
        return None
    covers = read_field(plan_path, "covers")
    if not covers:
        return None
    issue_repo = read_field(plan_path, "issue-repo") or owner_repo
    issue_nums = parse_covers(covers)
    all_closed = True
    for num in issue_nums:
        try:
            result = subprocess.run(
                ["gh", "issue", "view", str(num), "--repo", issue_repo,
                 "--json", "state", "--jq", ".state"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0 or result.stdout.strip() != "CLOSED":
                all_closed = False
                break
        except subprocess.TimeoutExpired:
            return None
    if not all_closed:
        return None
    plan_state = read_plan(plan_path)
    if plan_state and has_uncompleted_items(plan_state):
        return None
    total = len(plan_state.queue_items) if plan_state else 0
    return Finding(
        scenario="S3_ACTIVE_ALL_CLOSED",
        severity="warning",
        detail=f"state: active, all covers ({covers}) CLOSED, queue: 0 uncompleted / {total} total items",
        actions=["transition_to_drained", "mark_complete_and_next", "reopen_issues"],
    )


def check_queue_consistency(plan_path: Path, owner_repo: str) -> Optional[Finding]:
    if not owner_repo or not plan_path.exists():
        return None
    plan_state = read_plan(plan_path)
    if plan_state is None or not plan_state.queue_items:
        return None

    issue_repo = plan_state.fields.get("issue-repo", owner_repo)
    covers_raw = plan_state.fields.get("covers", "")
    covers_nums = set(parse_covers(covers_raw))

    inconsistencies: list[str] = []
    for item in plan_state.queue_items:
        try:
            result = subprocess.run(
                ["gh", "issue", "view", str(item.number), "--repo", issue_repo,
                 "--json", "state,title", "--jq", "[.state, .title] | @tsv"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                continue
            parts = result.stdout.strip().split("\t", 1)
            if len(parts) != 2:
                continue
            gh_state, gh_title = parts

            if item.title and gh_title and item.title.lower() not in gh_title.lower() and gh_title.lower() not in item.title.lower():
                if owner_repo != issue_repo:
                    continue

            if not item.completed and gh_state == "CLOSED":
                inconsistencies.append(f"#{item.number} unchecked but CLOSED")
            elif item.completed and gh_state == "OPEN":
                if item.number in covers_nums:
                    continue
                inconsistencies.append(f"#{item.number} checked but OPEN")
        except subprocess.TimeoutExpired:
            return None

    if not inconsistencies:
        return None
    return Finding(
        scenario="S8_QUEUE_INCONSISTENT",
        severity="warning",
        detail=f"queue inconsistency: {len(inconsistencies)} issue(s) differ from GitHub — {', '.join(inconsistencies)}",
        actions=["sync_plan_with_github", "ignore"],
    )


def _is_in_git_repo(path: Path) -> bool:
    candidate = path.resolve()
    while candidate != candidate.parent:
        if (candidate / ".git").exists() or (candidate / ".git").is_file():
            return True
        candidate = candidate.parent
    return False


def check_orphaned_wksp(project: Path) -> Optional[Finding]:
    wksp = project / "wksp"
    if not wksp.is_symlink():
        return None
    if not wksp.exists():
        return Finding(
            scenario="S9_ORPHANED_WKSP",
            severity="error",
            detail="wksp symlink is dangling — target does not exist",
            actions=["repoint_wksp", "remove_wksp"],
        )
    resolved = wksp.resolve()
    if not _is_in_git_repo(resolved):
        return Finding(
            scenario="S9_ORPHANED_WKSP",
            severity="error",
            detail=f"wksp symlink points to {resolved} which is not inside a git repository",
            actions=["repoint_wksp", "remove_wksp"],
        )
    return None


def check_symlink_roundtrip(project: Path, workspace: Path) -> Optional[Finding]:
    """S10: proj/wksp symlinks should round-trip back to the same repos."""
    if project == workspace:
        return None
    proj_link = workspace / "proj"
    wksp_link = project / "wksp"
    if not proj_link.is_symlink() or not wksp_link.is_symlink():
        return None
    if not proj_link.exists() or not wksp_link.exists():
        return None
    proj_resolved = proj_link.resolve()
    wksp_resolved = wksp_link.resolve()
    if proj_resolved != project.resolve():
        return Finding(
            scenario="S10_SYMLINK_CROSSED",
            severity="error",
            detail=f"workspace/proj -> {proj_resolved}, expected {project.resolve()}",
            actions=["repoint_proj", "ignore"],
        )
    if wksp_resolved != workspace.resolve():
        return Finding(
            scenario="S10_SYMLINK_CROSSED",
            severity="error",
            detail=f"project/wksp -> {wksp_resolved}, expected {workspace.resolve()}",
            actions=["repoint_wksp", "ignore"],
        )
    return None


def check_slot_boundary(
    project: Path, workspace: Path, slot_dir: Optional[Path],
) -> Optional[Finding]:
    """S11: In a slot, all resolved paths must be inside the slot boundary."""
    if slot_dir is None:
        return None
    slot_resolved = slot_dir.resolve()
    for label, path in [("project", project), ("workspace", workspace)]:
        try:
            path.resolve().relative_to(slot_resolved)
        except ValueError:
            return Finding(
                scenario="S11_SLOT_ESCAPE",
                severity="error",
                detail=f"{label} path {path.resolve()} is outside slot boundary {slot_resolved}",
                actions=["repoint_symlinks", "ignore"],
            )
    return None


def diagnose(
    plan_path: Optional[Path],
    meta_state: str,
    project: Path,
    workspace: Path,
    base_branch: str = "main",
    current_branch: str = "",
    on_main: bool = False,
    owner_repo: str = "",
    slot_dir: Optional[Path] = None,
) -> list[Finding]:
    findings: list[Finding] = []

    s9 = check_orphaned_wksp(project)
    if s9:
        findings.append(s9)

    s10 = check_symlink_roundtrip(project, workspace)
    if s10:
        findings.append(s10)

    s11 = check_slot_boundary(project, workspace, slot_dir)
    if s11:
        findings.append(s11)

    if plan_path is None or not plan_path.exists():
        return findings
    try:
        s1 = check_missing_state(plan_path)
        if s1:
            findings.append(s1)

        s2 = check_invalid_state(meta_state, plan_path)
        if s2:
            findings.append(s2)
            return findings

        s5 = check_branch_mismatch(plan_path, workspace, current_branch, base_branch)
        if s5:
            findings.append(s5)

        if not s5:
            s6 = check_branch_exists(plan_path, project)
            if s6:
                findings.append(s6)

        s7 = check_stale_plan_on_main(plan_path, meta_state, base_branch, on_main)
        if s7:
            findings.append(s7)

        s4 = check_closing_postconditions(meta_state, plan_path, project, workspace, base_branch)
        if s4:
            findings.append(s4)

        s3 = check_active_all_closed(plan_path, meta_state, owner_repo)
        if s3:
            findings.append(s3)

        s8 = check_queue_consistency(plan_path, owner_repo)
        if s8:
            findings.append(s8)
    except Exception:
        pass

    return findings
