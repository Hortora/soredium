#!/usr/bin/env python3
"""Lifecycle corruption detection.

Checks state-vs-environment coherence. Called by ctx.py at session start.
Returns Finding objects — never mutates state, never raises.

Spec: issue-262-lifecycle-corruption-recovery
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import sys
_project_dir = Path(__file__).parent
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

from lifecycle import VALID_STATES


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


def _read_plan_field(plan_path: Path, field_name: str) -> Optional[str]:
    if not plan_path.exists():
        return None
    in_state = False
    has_sections = False
    for line in plan_path.read_text().splitlines():
        if line.strip() == "## State":
            in_state = True
            has_sections = True
            continue
        if line.startswith("## "):
            in_state = False
            continue
        should_check = in_state if has_sections else True
        if should_check and line.startswith(f"{field_name}:"):
            return line.split(":", 1)[1].strip()
    return None


def check_missing_state(plan_path: Path) -> Optional[Finding]:
    if not plan_path.exists():
        return None
    in_state = False
    has_sections = False
    for line in plan_path.read_text().splitlines():
        if line.strip() == "## State":
            in_state = True
            has_sections = True
            continue
        if line.startswith("## "):
            in_state = False
            continue
        should_check = in_state if has_sections else True
        if should_check and line.startswith("state:"):
            return None
    if not has_sections:
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
    plan_branch = _read_plan_field(plan_path, "branch")
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
    plan_branch = _read_plan_field(plan_path, "branch")
    if not plan_branch or plan_branch == base_branch:
        return None
    if meta_state == "drained":
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
    plan_branch = _read_plan_field(plan_path, "branch")
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
    plan_branch = _read_plan_field(plan_path, "branch") or ""

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
    covers = _read_plan_field(plan_path, "covers")
    if not covers:
        return None
    issue_repo = _read_plan_field(plan_path, "issue-repo") or owner_repo
    issue_nums = [n.strip() for n in covers.split(",") if n.strip()]
    all_closed = True
    for num in issue_nums:
        try:
            result = subprocess.run(
                ["gh", "issue", "view", num, "--repo", issue_repo,
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
    return Finding(
        scenario="S3_ACTIVE_ALL_CLOSED",
        severity="warning",
        detail=f"state: active but all issues in covers ({covers}) are CLOSED on GitHub",
        actions=["transition_to_drained", "mark_complete_and_next", "reopen_issues"],
    )


def check_queue_consistency(plan_path: Path, owner_repo: str) -> Optional[Finding]:
    if not owner_repo or not plan_path.exists():
        return None
    content = plan_path.read_text()
    in_queue = False
    issues: list[tuple[int, bool, str]] = []
    for line in content.splitlines():
        if line.strip() == "## Queue":
            in_queue = True
            continue
        if line.startswith("## "):
            in_queue = False
            continue
        if not in_queue:
            continue
        m = re.match(r'\s*- \[([ x])\] #(\d+)\s*—\s*(.+?)(?:\s*←.*)?$', line)
        if m:
            completed = m.group(1) == "x"
            issue_num = int(m.group(2))
            title = m.group(3).strip()
            issues.append((issue_num, completed, title))

    if not issues:
        return None

    issue_repo = _read_plan_field(plan_path, "issue-repo") or owner_repo

    covers_raw = _read_plan_field(plan_path, "covers") or ""
    covers_nums = set()
    for c in covers_raw.split(","):
        c = c.strip()
        if c.isdigit():
            covers_nums.add(int(c))

    inconsistencies: list[str] = []
    for num, completed, plan_title in issues:
        try:
            result = subprocess.run(
                ["gh", "issue", "view", str(num), "--repo", issue_repo,
                 "--json", "state,title", "--jq", "[.state, .title] | @tsv"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                continue
            parts = result.stdout.strip().split("\t", 1)
            if len(parts) != 2:
                continue
            gh_state, gh_title = parts

            if plan_title and gh_title and plan_title.lower() not in gh_title.lower() and gh_title.lower() not in plan_title.lower():
                if owner_repo != issue_repo:
                    continue

            if not completed and gh_state == "CLOSED":
                inconsistencies.append(f"#{num} unchecked but CLOSED")
            elif completed and gh_state == "OPEN":
                if num in covers_nums:
                    continue
                inconsistencies.append(f"#{num} checked but OPEN")
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


def diagnose(
    plan_path: Optional[Path],
    meta_state: str,
    project: Path,
    workspace: Path,
    base_branch: str = "main",
    current_branch: str = "",
    on_main: bool = False,
    owner_repo: str = "",
) -> list[Finding]:
    if plan_path is None or not plan_path.exists():
        return []
    findings: list[Finding] = []
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
