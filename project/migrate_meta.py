#!/usr/bin/env python3
"""
Migrate a .meta file to .plan format, or delete a vestigial .meta
when a .plan already exists alongside it.

Usage:
    python3 migrate_meta.py <workspace-or-design-dir>

The script searches for design/.meta (or .meta at the given path).
If a .plan already exists in the same scope, deletes the .meta.
If no .plan exists, creates one from the .meta content.

Output (KEY=VALUE lines):
    ACTION=migrated|deleted|skipped
    PLAN_PATH=<path>        (when migrated)
    META_PATH=<path>        (always)

Exit codes:
    0  success
    1  no .meta found
"""

import subprocess
import sys
from pathlib import Path


def _parse_meta(meta_path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in meta_path.read_text().splitlines():
        if ': ' in line:
            k, _, v = line.partition(': ')
            meta[k.strip()] = v.strip()
        elif ':' in line:
            k, _, v = line.partition(':')
            meta[k.strip()] = v.strip()
    return meta


def _find_meta(root: Path) -> Path | None:
    if (root / ".meta").exists():
        return root / ".meta"
    if (root / "design" / ".meta").exists():
        return root / "design" / ".meta"
    return None


def _find_plan(root: Path) -> Path | None:
    if (root / ".plan").exists():
        return root / ".plan"
    if (root / "design" / ".plan").exists():
        return root / "design" / ".plan"
    # Check parent (workspace root vs design subdir)
    if root.name == "design" and (root.parent / ".plan").exists():
        return root.parent / ".plan"
    return None


def _git_rm(path: Path) -> bool:
    git_root = path
    while git_root != git_root.parent:
        if (git_root / ".git").exists():
            break
        git_root = git_root.parent
    else:
        return False
    result = subprocess.run(
        ["git", "-C", str(git_root), "rm", "-f", str(path)],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def migrate(root: Path) -> int:
    meta_path = _find_meta(root)
    if not meta_path:
        print("ERROR=no_meta_found")
        return 1

    print(f"META_PATH={meta_path}")

    plan_path = _find_plan(root)
    if plan_path:
        _git_rm(meta_path)
        print(f"ACTION=deleted")
        print(f"PLAN_PATH={plan_path}")
        return 0

    fields = _parse_meta(meta_path)
    if not fields:
        print("ACTION=skipped")
        print("REASON=empty_meta")
        return 0

    branch = fields.get("branch", "unknown")
    issue = fields.get("issue", "")
    covers = fields.get("covers", issue)

    state_lines = []
    for key in ["branch", "state", "project-sha", "date", "issue", "issue-repo",
                 "covers", "design-repo", "design-section-hashes", "flyway-next-v"]:
        if key in fields:
            state_lines.append(f"{key}: {fields[key]}")
        elif key == "covers" and issue:
            state_lines.append(f"covers: {issue}")

    issue_repo = fields.get("issue-repo", "")
    if issue and issue_repo:
        queue_line = f"- [ ] {issue_repo}#{issue} — Issue #{issue} ← active"
    elif issue:
        queue_line = f"- [ ] #{issue} — Issue #{issue} ← active"
    else:
        queue_line = ""

    plan_content = f"# Work Plan — {branch}\n\n## State\n"
    plan_content += "\n".join(state_lines) + "\n"
    if queue_line:
        plan_content += f"\n## Queue\n{queue_line}\n"

    new_plan = meta_path.parent / ".plan"
    new_plan.write_text(plan_content)

    _git_rm(meta_path)

    # Stage the new .plan
    git_root = meta_path.parent
    while git_root != git_root.parent:
        if (git_root / ".git").exists():
            break
        git_root = git_root.parent
    subprocess.run(
        ["git", "-C", str(git_root), "add", str(new_plan)],
        capture_output=True, text=True,
    )

    print(f"ACTION=migrated")
    print(f"PLAN_PATH={new_plan}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: migrate_meta.py <workspace-or-design-dir>")
        sys.exit(1)
    sys.exit(migrate(Path(sys.argv[1])))
