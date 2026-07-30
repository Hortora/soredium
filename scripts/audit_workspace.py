#!/usr/bin/env python3
"""Check workspace repos for unpromoted specs/blogs/ADRs on slot branches."""
import subprocess, re
from pathlib import Path

FAMILY = Path.home() / "claude" / "casehub"
ATTIC = FAMILY / "worktrees" / "attic"
WORKSPACE_REPOS = ["work", "work-casehub", "work-casehub-ras",
                   "work-casehub-iot", "work-casehub-ops",
                   "work-casehub-desiredstate"]

def run(*cmd):
    r = subprocess.run(list(cmd), capture_output=True, text=True)
    return r.returncode, r.stdout.strip()

all_slots = sorted(
    [d for d in ATTIC.iterdir() if d.is_dir() and d.name.isdigit()],
    key=lambda d: int(d.name)
)

for slot_dir in all_slots:
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        continue
    text = slot_file.read_text()
    branch = ""
    issue = ""
    for line in text.splitlines():
        if "branch:" in line and line.strip().startswith("20"):
            branch = line.split("branch:")[1].strip()
        if not issue and "/" in line and "#" in line and not line.startswith("#") and not line.startswith("-"):
            issue = line.strip()
    if not branch:
        continue

    for wksp_name in WORKSPACE_REPOS:
        wksp = FAMILY / wksp_name
        if not wksp.exists() or not (wksp / ".git").exists():
            continue
        rc, _ = run("git", "-C", str(wksp), "rev-parse", "--verify", f"refs/heads/{branch}")
        if rc != 0:
            continue

        # Branch exists in this workspace — check for unpromoted content
        rc, diff_out = run("git", "-C", str(wksp), "log", "--oneline", branch, "--not", "origin/main")
        if not diff_out.strip():
            continue

        # Check for specs, blogs, ADRs, design docs
        rc, files_out = run("git", "-C", str(wksp), "diff", "--name-only", "origin/main...", branch)
        if not files_out.strip():
            continue

        spec_files = [f for f in files_out.splitlines() if any(kw in f.lower() for kw in
                      ["spec", "blog", "adr", "design", "plan", "journal", "arc42"])]
        other_files = [f for f in files_out.splitlines() if f not in spec_files]

        if spec_files or other_files:
            commits = diff_out.strip().splitlines()
            print(f"\n=== Slot {slot_dir.name}: {issue} ===")
            print(f"  Workspace: {wksp_name}, Branch: {branch}")
            print(f"  Unpromoted commits: {len(commits)}")
            for c in commits:
                print(f"    {c}")
            if spec_files:
                print(f"  Spec/blog/design files ({len(spec_files)}):")
                for f in spec_files:
                    print(f"    {f}")
            if other_files:
                print(f"  Other files ({len(other_files)}):")
                for f in other_files[:10]:
                    print(f"    {f}")
                if len(other_files) > 10:
                    print(f"    ... and {len(other_files) - 10} more")
