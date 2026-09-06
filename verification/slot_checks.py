"""Slot-level verification checks.

Pure functions that inspect a single slot's state and return findings.
No side effects, no fixes.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from verification import Finding, git, is_git_repo, read_file_safe, readlink_safe


def check_absolute_symlinks(clone_path: Path, slot_dir: Path) -> list[Finding]:
    """Flag top-level symlinks in a clone that resolve outside the slot boundary."""
    findings: list[Finding] = []
    slot_abs = str(slot_dir.resolve())
    for sym in sorted(clone_path.iterdir()):
        if not sym.is_symlink():
            continue
        target = readlink_safe(sym)
        if target is None:
            continue
        if not (target.startswith("/Users/") or target.startswith("/home/")):
            continue
        resolved = str(sym.resolve()) if sym.exists() else target
        if not resolved.startswith(slot_abs):
            findings.append(Finding(
                "ERROR", "slot-absolute-symlink",
                f"{clone_path.name}: {sym.name} -> {target} (outside slot)",
            ))
    return findings


def check_claude_md_paths(claude_md: Path, boundary: Path) -> list[Finding]:
    """Flag absolute paths in CLAUDE.md that break slot isolation."""
    findings: list[Finding] = []
    if not claude_md.exists() and not claude_md.is_symlink():
        return findings

    if claude_md.is_symlink():
        target = readlink_safe(claude_md)
        if target and (target.startswith("/Users/") or target.startswith("/home/")):
            findings.append(Finding(
                "ERROR", "claude-md-absolute-symlink",
                f"CLAUDE.md symlink uses absolute path -> {target}",
            ))

    content = read_file_safe(claude_md)
    if content is None:
        return findings

    boundary_abs = str(boundary.resolve())
    abs_refs = re.findall(r'/Users/\S+', content)
    outside = [r for r in abs_refs if not r.startswith(boundary_abs)]
    if outside:
        findings.append(Finding(
            "ERROR", "claude-md-absolute-paths",
            f"CLAUDE.md has {len(outside)} absolute path(s) outside boundary",
        ))
    return findings


def check_workspace_content_in_project(claude_md: Path) -> list[Finding]:
    """Flag project CLAUDE.md files that contain workspace-style headers."""
    findings: list[Finding] = []
    if not claude_md.exists():
        return findings
    content = read_file_safe(claude_md)
    if content is None:
        return findings
    first_line = content.strip().splitlines()[0] if content.strip() else ""
    if "Workspace" in first_line and first_line.startswith("#"):
        findings.append(Finding(
            "ERROR", "project-has-workspace-content",
            f"CLAUDE.md starts with '{first_line[:60]}' — workspace content in project repo",
        ))
    return findings


def verify_stamp_sha(repo_path: Path, branch: str) -> list[Finding]:
    """Verify that a stamp's landing SHA actually exists in the repo."""
    findings: list[Finding] = []
    r = git(repo_path, "log", "-1", "--format=%s", branch)
    if r.returncode != 0:
        return findings
    tip = r.stdout.strip()
    if "landed as " not in tip:
        return findings
    stamp_sha = tip.split("landed as ")[1].split(" ")[0]
    r_cat = git(repo_path, "cat-file", "-t", stamp_sha)
    if r_cat.returncode != 0:
        findings.append(Finding(
            "ERROR", "invalid-stamp-sha",
            f"stamp references SHA {stamp_sha[:12]} which doesn't exist",
        ))
    return findings


def verify_landed_content(
    clone_path: Path, original_path: Path, branch: str,
) -> list[Finding]:
    """Verify branch content actually landed on the original repo's main."""
    findings: list[Finding] = []
    if not original_path.exists() or not is_git_repo(original_path):
        return findings

    r_sha = git(clone_path, "rev-parse", branch)
    if r_sha.returncode != 0:
        return findings
    branch_sha = r_sha.stdout.strip()

    git(original_path, "fetch", str(clone_path), branch_sha, "--quiet")
    r_diff = git(
        original_path, "diff", f"main..{branch_sha}",
        "--", "*.java", "*.ts", "*.py",
    )
    if r_diff.returncode == 0 and r_diff.stdout.strip():
        diff_lines = len(r_diff.stdout.strip().splitlines())
        findings.append(Finding(
            "ERROR", "landed-content-not-merged",
            f"branch has {diff_lines} lines of unmerged source vs original main",
        ))
    return findings


def check_workspace_clone_is_git_repo(wsp_path: Path) -> list[Finding]:
    """Verify a workspace clone directory is a real git repo."""
    findings: list[Finding] = []
    if not wsp_path.exists():
        findings.append(Finding(
            "ERROR", "broken-wsp-clone",
            f"{wsp_path.name}: workspace clone directory does not exist",
        ))
        return findings
    if not is_git_repo(wsp_path):
        findings.append(Finding(
            "ERROR", "broken-wsp-clone",
            f"{wsp_path.name}: NOT a git repo — clone failed silently",
        ))
    return findings


def check_plan_branch_matches_slot(plan_path: Path, slot_branch: str) -> list[Finding]:
    """Verify .plan branch field matches the slot's branch."""
    findings: list[Finding] = []
    content = read_file_safe(plan_path)
    if content is None:
        return findings
    for line in content.splitlines():
        if line.startswith("branch:"):
            plan_branch = line.split(":", 1)[1].strip()
            if slot_branch and plan_branch != slot_branch:
                findings.append(Finding(
                    "ERROR", "stale-plan",
                    f".plan is for {plan_branch}, slot is {slot_branch}",
                ))
            break
    return findings


def check_duplicate_plan_items(plan_path: Path) -> list[Finding]:
    """Detect issues that appear both checked and unchecked in a .plan queue."""
    findings: list[Finding] = []
    content = read_file_safe(plan_path)
    if content is None:
        return findings
    checked: set[str] = set()
    unchecked: set[str] = set()
    for line in content.splitlines():
        m = re.search(r'#(\d+)', line)
        if not m:
            continue
        num = m.group(1)
        if '- [x]' in line:
            checked.add(num)
        elif '- [ ]' in line:
            unchecked.add(num)
    dupes = checked & unchecked
    if dupes:
        findings.append(Finding(
            "ERROR", "plan-circular-dupes",
            f".plan has circular duplicates — issues {', '.join('#'+d for d in sorted(dupes))} appear both checked and unchecked",
        ))
    return findings
