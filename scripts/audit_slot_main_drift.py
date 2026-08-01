#!/usr/bin/env python3
"""
Audit attic slot workspace clones for artifacts promoted to the slot's
local main but never pushed to origin/main.

This catches the case where artifact_promote.py ran successfully inside
the slot clone (checkout main, cherry-pick, commit) but the push to
origin failed silently.
"""

import subprocess
import sys
from pathlib import Path

EXCLUDE = {"INDEX.md", ".DS_Store"}
ARTIFACT_DIRS = ["blog/", "specs/", "adr/", "docs/adr/", "snapshots/"]


def run(args, cwd=None):
    r = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def is_clone(path):
    return (path / ".git").is_dir()


def is_worktree(path):
    git = path / ".git"
    return git.is_file()


def check_workspace(ws_path, slot_num):
    """Check if the workspace clone's main has artifacts not on origin/main."""
    if not is_clone(ws_path):
        if is_worktree(ws_path):
            return None, "worktree (broken ref, skip)"
        return None, "no .git"

    # Fetch origin to get current state
    rc, _, _ = run(["git", "-C", str(ws_path), "fetch", "origin", "main"], cwd=str(ws_path))
    if rc != 0:
        return None, "fetch failed"

    # Check current branch
    rc, branch, _ = run(["git", "-C", str(ws_path), "branch", "--show-current"])

    # Compare local main with origin/main
    missing = []
    for art_dir in ARTIFACT_DIRS:
        rc, diff, _ = run([
            "git", "-C", str(ws_path), "diff",
            "--name-only", "origin/main..main", "--", art_dir
        ])
        if rc != 0 or not diff:
            continue
        for line in diff.splitlines():
            name = Path(line).name
            if name in EXCLUDE:
                continue
            if "/attic/" in line:
                continue
            missing.append(line)

    # Also check the feature branch for unpromoted artifacts
    slot_branch_rc, slot_branch, _ = run([
        "git", "-C", str(ws_path), "log", "--all", "--oneline", "-1",
        "--format=%D"
    ])

    return missing, None


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 audit_slot_main_drift.py <family-root> [--recover <workspace-origin>]")
        sys.exit(1)

    family_root = Path(sys.argv[1])
    recover_mode = "--recover" in sys.argv
    recover_target = None
    if recover_mode:
        idx = sys.argv.index("--recover")
        if idx + 1 < len(sys.argv):
            recover_target = Path(sys.argv[idx + 1])

    attic = family_root / "worktrees" / "attic"
    if not attic.is_dir():
        print("No attic found")
        return

    total_missing = 0
    all_recoveries = []

    for slot_dir in sorted(attic.iterdir(), key=lambda x: int(x.name) if x.name.isdigit() else 999):
        if not slot_dir.is_dir() or not slot_dir.name.isdigit():
            continue
        slot_num = slot_dir.name

        for ws in sorted(slot_dir.iterdir()):
            if not ws.is_dir():
                continue
            if not ws.name.startswith("work"):
                continue
            if not (ws / ".git").exists():
                continue

            missing, err = check_workspace(ws, slot_num)
            if err:
                continue
            if not missing:
                continue

            origin_rc, origin, _ = run(["git", "-C", str(ws), "remote", "get-url", "origin"])
            print(f"\nSlot {slot_num}/{ws.name} → {origin}")
            print(f"  {len(missing)} artifacts on local main but NOT on origin/main:")
            for m in missing:
                print(f"    {m}")
                all_recoveries.append((ws, m, origin))
            total_missing += len(missing)

    print(f"\n{'=' * 60}")
    print(f"Total stranded on slot mains: {total_missing}")

    if not recover_mode or not all_recoveries:
        if total_missing > 0:
            print("Run with --recover <workspace-origin-path> to push them.")
        return

    # Group by origin
    by_origin = {}
    for ws, path, origin in all_recoveries:
        by_origin.setdefault(origin, []).append((ws, path))

    for origin, items in by_origin.items():
        origin_path = Path(origin)
        if not origin_path.is_dir():
            print(f"SKIP: origin {origin} not a local path")
            continue

        # Check out each file from the slot workspace clone's main into the origin
        run(["git", "-C", str(origin_path), "checkout", "main"])
        run(["git", "-C", str(origin_path), "pull", "--rebase", "origin", "main"])

        recovered = 0
        for ws, rel_path in items:
            # Get file content from slot workspace main
            rc, content, _ = run(["git", "-C", str(ws), "show", f"main:{rel_path}"])
            if rc != 0:
                print(f"  SKIP: {rel_path} (git show failed)")
                continue
            dest = origin_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
            run(["git", "-C", str(origin_path), "add", rel_path])
            recovered += 1

        if recovered > 0:
            msg = f"docs: recover {recovered} artifacts from slot workspace mains"
            rc, _, _ = run(["git", "-C", str(origin_path), "commit", "-m", msg])
            if rc == 0:
                print(f"COMMITTED to {origin}: {msg}")
                rc, _, _ = run(["git", "-C", str(origin_path), "push"])
                print(f"PUSHED={'yes' if rc == 0 else 'failed'}")
            else:
                print(f"COMMIT FAILED at {origin}")


if __name__ == "__main__":
    main()
