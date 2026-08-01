#!/usr/bin/env python3
"""
Recover unpromoted artifacts from attic slot branches to workspace main.

For each attic slot, reads the branch name from .slot, then checks the
original workspace repo for artifacts on that branch that aren't on main.

Usage:
    python3 recover_attic_artifacts.py <family-root> <workspace-repo> [--apply]

Without --apply: dry-run showing what would be recovered.
With --apply: checks out files from branches and commits to main.
"""

import subprocess
import sys
from pathlib import Path


ARTIFACT_DIRS = ["specs", "blog", "adr", "docs/adr", "snapshots"]
EXCLUDE_NAMES = {"INDEX.md", ".DS_Store"}


def run(args, cwd=None):
    r = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def get_branch_from_slot(slot_dir):
    slot_md = slot_dir / ".slot"
    if not slot_md.exists():
        return None
    for line in slot_md.read_text().splitlines():
        if line.startswith("# Slot") and "—" in line:
            return line.split("—", 1)[1].strip()
    return None


def branch_exists(workspace_repo, branch):
    rc, _, _ = run(["git", "-C", str(workspace_repo), "rev-parse", "--verify", branch])
    return rc == 0


def list_branch_artifacts(workspace_repo, branch):
    """List all artifact files on a branch."""
    artifacts = []
    for cat_dir in ARTIFACT_DIRS:
        rc, out, _ = run(
            ["git", "-C", str(workspace_repo), "ls-tree", "-r", "--name-only", branch, "--", f"{cat_dir}/"]
        )
        if rc != 0 or not out:
            continue
        for line in out.splitlines():
            name = Path(line).name
            if name in EXCLUDE_NAMES:
                continue
            if "/attic/" in line:
                continue
            artifacts.append(line)
    return sorted(artifacts)


def file_on_main(workspace_repo, path):
    """Check if file exists on main (working tree or git HEAD)."""
    if (workspace_repo / path).exists():
        return True
    rc, _, _ = run(["git", "-C", str(workspace_repo), "cat-file", "-e", f"main:{path}"])
    return rc == 0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    family_root = Path(sys.argv[1])
    workspace_repo = Path(sys.argv[2])
    apply_mode = "--apply" in sys.argv

    attic = family_root / "worktrees" / "attic"
    if not attic.is_dir():
        print("ERROR: no attic directory found")
        sys.exit(1)

    total_scanned = 0
    total_false_positive = 0
    total_to_recover = 0
    recovery_plan = []

    for slot_dir in sorted(attic.iterdir(), key=lambda x: int(x.name) if x.name.isdigit() else 999):
        if not slot_dir.is_dir() or not slot_dir.name.isdigit():
            continue
        slot_num = slot_dir.name

        branch = get_branch_from_slot(slot_dir)
        if not branch:
            continue

        if not branch_exists(workspace_repo, branch):
            continue

        artifacts = list_branch_artifacts(workspace_repo, branch)
        if not artifacts:
            continue

        slot_missing = []
        slot_already = []

        for rel in artifacts:
            total_scanned += 1
            if file_on_main(workspace_repo, rel):
                total_false_positive += 1
                slot_already.append(rel)
            else:
                total_to_recover += 1
                slot_missing.append(rel)
                recovery_plan.append((branch, rel, slot_num))

        if slot_missing:
            print(f"\nSlot {slot_num} (branch: {branch}): {len(slot_missing)} to recover, {len(slot_already)} already on main")
            for rel in slot_missing:
                print(f"  RECOVER: {rel}")
        elif slot_already:
            print(f"Slot {slot_num}: all {len(slot_already)} already on main")

    print(f"\n{'=' * 60}")
    print(f"Total scanned: {total_scanned}")
    print(f"Already on main (false positives): {total_false_positive}")
    print(f"Need recovery: {total_to_recover}")

    if not apply_mode:
        if total_to_recover > 0:
            print(f"\nDry run. Run with --apply to recover {total_to_recover} artifacts.")
        return

    if total_to_recover == 0:
        print("\nNothing to recover.")
        return

    print(f"\nRecovering {total_to_recover} artifacts to workspace main...")

    original_branch_rc, original_branch, _ = run(
        ["git", "-C", str(workspace_repo), "branch", "--show-current"]
    )
    if original_branch != "main":
        run(["git", "-C", str(workspace_repo), "stash"])
        run(["git", "-C", str(workspace_repo), "checkout", "main"])

    run(["git", "-C", str(workspace_repo), "pull", "--rebase", "origin", "main"])

    recovered = 0
    for branch, rel, slot_num in recovery_plan:
        rc, _, _ = run(
            ["git", "-C", str(workspace_repo), "checkout", branch, "--", rel]
        )
        if rc == 0:
            recovered += 1
        else:
            print(f"  SKIP: {rel} (checkout failed from {branch})")

    if recovered > 0:
        slots_involved = sorted(set(s for _, _, s in recovery_plan))
        msg = f"docs: recover {recovered} artifacts from attic slots {','.join(slots_involved)}"
        run(["git", "-C", str(workspace_repo), "add", "-A"])
        rc, _, stderr = run(["git", "-C", str(workspace_repo), "commit", "-m", msg])
        if rc == 0:
            print(f"COMMITTED: {msg}")
            rc, _, _ = run(["git", "-C", str(workspace_repo), "push"])
            print(f"PUSHED={'yes' if rc == 0 else 'failed'}")
        else:
            print(f"COMMIT_FAILED: {stderr}")

    if original_branch != "main":
        run(["git", "-C", str(workspace_repo), "checkout", original_branch])
        run(["git", "-C", str(workspace_repo), "stash", "pop"])

    print(f"\nRecovered: {recovered}/{total_to_recover}")


if __name__ == "__main__":
    main()
