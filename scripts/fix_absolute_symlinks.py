#!/usr/bin/env python3
"""
Fix absolute wksp/proj/CLAUDE.md symlinks to relative across all repos.

Scans project and workspace repos under ~/claude/ for absolute symlinks
named 'wksp', 'proj', or 'CLAUDE.md' and replaces them with relative
equivalents that resolve to the same target.

Usage:
    python3 scripts/fix_absolute_symlinks.py              # dry-run
    python3 scripts/fix_absolute_symlinks.py --apply       # apply fixes
"""

import os
import sys
from pathlib import Path


SYMLINK_NAMES = {"wksp", "proj", "CLAUDE.md"}
SKIP_DIRS = {"slots", "worktrees", "attic", ".m2", "node_modules", "target",
             ".git", "__pycache__", ".idea", ".gradle", "build", "dist"}


def scan_dir(base: Path, label: str) -> list[tuple[Path, str, str]]:
    """Return list of (symlink_path, current_target, proposed_relative)."""
    findings: list[tuple[Path, str, str]] = []
    if not base.is_dir():
        return findings
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name in SKIP_DIRS or child.name.startswith("."):
            continue
        for name in SYMLINK_NAMES:
            p = child / name
            if not p.is_symlink():
                continue
            target = os.readlink(p)
            if not target.startswith("/"):
                continue
            resolved = p.resolve()
            if not resolved.exists():
                findings.append((p, target, f"DANGLING -> {target}"))
                continue
            rel = os.path.relpath(resolved, p.parent)
            findings.append((p, target, rel))
    return findings


def main() -> int:
    apply = "--apply" in sys.argv
    home = Path.home()
    claude_dir = home / "claude"

    all_findings: list[tuple[Path, str, str]] = []

    for family_name in sorted((claude_dir).iterdir()):
        if not family_name.is_dir() or family_name.name in ("public", "private", ".claude"):
            continue
        all_findings.extend(scan_dir(family_name, family_name.name))

    for privacy in ("public", "private"):
        priv_dir = claude_dir / privacy
        if not priv_dir.is_dir():
            continue
        for family in sorted(priv_dir.iterdir()):
            if not family.is_dir():
                continue
            if (family / ".git").exists():
                all_findings.extend(scan_dir(family.parent, f"{privacy}/{family.parent.name}"))
            else:
                all_findings.extend(scan_dir(family, f"{privacy}/{family.name}"))

    standalone = [claude_dir / "cccli", claude_dir / "quarkus-langchain4j"]
    for proj in standalone:
        if proj.is_dir():
            for name in SYMLINK_NAMES:
                p = proj / name
                if p.is_symlink():
                    target = os.readlink(p)
                    if target.startswith("/"):
                        resolved = p.resolve()
                        rel = os.path.relpath(resolved, p.parent) if resolved.exists() else f"DANGLING -> {target}"
                        all_findings.append((p, target, rel))

    seen = set()
    unique: list[tuple[Path, str, str]] = []
    for f in all_findings:
        key = str(f[0])
        if key not in seen:
            seen.add(key)
            unique.append(f)

    if not unique:
        print("No absolute symlinks found.")
        return 0

    fixed = 0
    skipped = 0
    for symlink, old_target, new_target in unique:
        if "DANGLING" in new_target:
            print(f"SKIP  {symlink}  (dangling: {old_target})")
            skipped += 1
            continue

        if apply:
            symlink.unlink()
            symlink.symlink_to(new_target)
            print(f"FIXED {symlink}  {old_target} -> {new_target}")
            fixed += 1
        else:
            print(f"WOULD {symlink}  {old_target} -> {new_target}")
            fixed += 1

    mode = "applied" if apply else "dry-run"
    print(f"\n{mode}: {fixed} fixed, {skipped} skipped (dangling)")
    if not apply and fixed > 0:
        print("Run with --apply to fix.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
