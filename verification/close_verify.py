"""Composed close-time verifier.

Orchestrates which checks to run based on close mode (branch, main, slot)
and formats the output. Replaces verify_slot_close.verify().
"""
from __future__ import annotations

from pathlib import Path

from verification import Finding
from verification.close_checks import (
    check_branch_merged,
    check_branch_stamp,
    check_canonical_sync,
    check_issues_closed,
    check_landed_completeness,
    check_landed_marker,
    check_main_pushed,
    check_no_open_findings,
    check_no_stale_scaffold,
    check_on_main,
    check_artifacts_promoted,
    check_slot_archive_status,
    check_slot_marker,
    resolve_canonical_repos,
)

BLOCKING_CATEGORIES = {
    "landed-incomplete", "branch-not-merged", "stamp-sha-not-on-base",
    "canonical-sync",
}


def _run_branch_checks(
    project: Path, workspace: Path, branch: str, base: str,
    covers: list[int] | None, issue_repo: str, on_main: bool,
) -> list[tuple[str, list[Finding]]]:
    checks: list[tuple[str, list[Finding]]] = []
    if on_main:
        checks.append(("project_pushed", check_main_pushed(project, base)))
        checks.append(("workspace_pushed", check_main_pushed(workspace, base)))
        checks.append(("no_open_findings", check_no_open_findings(workspace)))
        checks.append(("no_stale_scaffold", check_no_stale_scaffold(workspace)))
    else:
        checks.append(("project_merged", check_branch_merged(project, branch, base)))
        checks.append(("project_stamped", check_branch_stamp(project, branch, base)))
        checks.append(("project_pushed", check_main_pushed(project, base)))
        checks.append(("workspace_merged", check_branch_merged(workspace, branch, base)))
        checks.append(("workspace_stamped", check_branch_stamp(workspace, branch, base, verify_sha=False)))
        checks.append(("workspace_pushed", check_main_pushed(workspace, base)))
        checks.append(("project_on_main", check_on_main(project)))
        checks.append(("workspace_on_main", check_on_main(workspace)))
        checks.append(("artifacts_promoted", check_artifacts_promoted(workspace, on_main)))
        checks.append(("no_open_findings", check_no_open_findings(workspace)))
        checks.append(("no_stale_scaffold", check_no_stale_scaffold(workspace)))
    if covers and issue_repo:
        checks.append(("issues_closed", check_issues_closed(issue_repo, covers)))
    return checks


def _run_slot_checks(
    slot_dir: Path, branch: str, base: str,
    covers_repos: set[str] | None,
    canonical_repos: dict[str, str] | None,
) -> list[tuple[str, list[Finding]]]:
    checks: list[tuple[str, list[Finding]]] = []
    checks.append(("landed_marker", check_landed_marker(slot_dir)))
    checks.append(("landed_completeness",
                    check_landed_completeness(slot_dir, repos=covers_repos, branch=branch)))
    checks.append(("phase_a_marker", check_slot_marker(slot_dir, ".phase-a-complete")))
    if canonical_repos:
        for repo_name, orig_path in canonical_repos.items():
            checks.append((
                f"canonical_sync_{repo_name}",
                check_canonical_sync(slot_dir, repo_name, Path(orig_path), branch=branch, base=base),
            ))
            checks.append((
                f"canonical_pushed_{repo_name}",
                check_main_pushed(Path(orig_path), base),
            ))
    slot_num = slot_dir.name
    attic = str(slot_dir.parent / "attic" / slot_num)
    checks.append(("archive_status", check_slot_archive_status(slot_dir, attic)))
    return checks


def _is_blocking(check_name: str, findings: list[Finding]) -> bool:
    if not findings:
        return False
    has_error = any(f.severity == "ERROR" for f in findings)
    if not has_error:
        return False
    if check_name in ("landed_completeness", "project_merged", "project_stamped"):
        return True
    if check_name.startswith("canonical_sync_"):
        return True
    return any(f.category in BLOCKING_CATEGORIES for f in findings)


def verify(
    project: Path, branch: str, workspace: Path,
    base: str = "main", covers: list[int] | None = None,
    issue_repo: str = "",
    slot_dir: Path | None = None,
    canonical_repos: dict[str, str] | None = None,
    on_main: bool = False,
    covers_repos: set[str] | None = None,
) -> bool:
    all_checks = _run_branch_checks(
        project, workspace, branch, base, covers, issue_repo, on_main)
    if slot_dir:
        all_checks.extend(_run_slot_checks(
            slot_dir, branch, base, covers_repos, canonical_repos))

    all_pass = True
    blocking_fail = False
    blocking_details: list[str] = []

    for name, findings in all_checks:
        if not findings:
            print(f"  ✅ {name}: pass")
            continue
        for f in findings:
            is_block = _is_blocking(name, findings)
            icon = "❌" if f.severity == "ERROR" else "⚠️" if f.severity == "WARN" else "ℹ️"
            tag = " [BLOCKING]" if is_block and f.severity == "ERROR" else ""
            print(f"  {icon} {name}: {f.severity.lower()} — {f.message}{tag}")
            if f.severity == "ERROR":
                all_pass = False
                if is_block:
                    blocking_fail = True
                    blocking_details.append(f"{name}: {f.message}")

    if all_pass:
        print("VERIFIED=yes")
    else:
        print("VERIFIED=no")
    if blocking_fail:
        print("BLOCKING_FAIL=yes")
        print(f"BLOCKING_DETAIL={'; '.join(blocking_details)}")

    if all_pass and slot_dir:
        archive_checks = [f for n, fs in all_checks for f in fs
                          if n == "archive_status" and f.severity == "WARN"
                          and "landed but" in f.message]
        if archive_checks:
            print("SUGGEST=archive_slot")

    return all_pass
