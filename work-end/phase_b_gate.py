#!/usr/bin/env python3
"""
Phase B completion gate for slot-mode work-end.

Reads actual filesystem and GitHub state to verify Phase B is complete.
Replaces the self-certified markdown checklist.

Usage:
    python3 phase_b_gate.py <slot_dir> covers=N,M issue-repo=org/repo

Output:
    GATE=pass           — all checks passed
    GATE=fail MISSING=  — definite failures
    GATE=warn MISSING= REASON= — network errors (can't verify)

Exit codes:
    0  always (gate result is in stdout, not exit code)
    1  bad arguments
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import parse_args


def check_stamps(slot_dir: Path) -> list[str]:
    """Check all repos in slot have stamp commits."""
    missing = []
    for sub in slot_dir.iterdir():
        if not sub.is_dir() or not (sub / ".git").exists():
            continue
        r = subprocess.run(
            ["git", "-C", str(sub), "log", "-1", "--format=%s"],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not r.stdout.strip().startswith("chore: branch closed"):
            missing.append(sub.name)
    return missing


def check_issues(issue_repo: str, covers: list[int]) -> tuple[list[int], bool]:
    """Check all issues in COVERS are CLOSED. Returns (open_issues, unreachable)."""
    open_issues = []
    unreachable = False
    for n in covers:
        try:
            r = subprocess.run(
                ["gh", "issue", "view", str(n), "--repo", issue_repo,
                 "--json", "state", "--jq", ".state"],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0:
                unreachable = True
                open_issues.append(n)
            elif r.stdout.strip() != "CLOSED":
                open_issues.append(n)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            unreachable = True
            open_issues.append(n)
    return open_issues, unreachable


def check_promoted(slot_dir: Path) -> bool:
    """Check .artifacts-promoted stamp exists."""
    for sub in slot_dir.iterdir():
        if sub.is_dir() and (sub / "design" / ".artifacts-promoted").exists():
            return True
    return (slot_dir / "design" / ".artifacts-promoted").exists()


def check_archived(slot_dir: Path) -> bool:
    """Check slot is in the attic."""
    return "attic" in slot_dir.parts


def run_gate(slot_dir: Path, covers: list[int], issue_repo: str) -> dict:
    """Run all checks and return structured result."""
    missing = []
    reason = ""

    stamp_missing = check_stamps(slot_dir)
    if stamp_missing:
        missing.append(f"stamps:{','.join(stamp_missing)}")

    if covers and issue_repo:
        open_issues, unreachable = check_issues(issue_repo, covers)
        if open_issues:
            missing.append(f"issues:{','.join(str(i) for i in open_issues)}")
        if unreachable:
            reason = "github_unreachable"

    if not check_promoted(slot_dir):
        missing.append("promotion")

    if not check_archived(slot_dir):
        missing.append("archive")

    if not missing:
        return {"gate": "pass"}
    elif reason:
        return {"gate": "warn", "missing": ",".join(missing), "reason": reason}
    else:
        return {"gate": "fail", "missing": ",".join(missing)}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    slot_dir = Path(sys.argv[1])
    params = parse_args(sys.argv[2:])
    covers_str = params.get("covers", "")
    issue_repo = params.get("issue-repo", "")
    covers = [int(x) for x in covers_str.split(",") if x.strip()]

    result = run_gate(slot_dir, covers, issue_repo)

    print(f"GATE={result['gate']}")
    if "missing" in result:
        print(f"MISSING={result['missing']}")
    if "reason" in result:
        print(f"REASON={result['reason']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
