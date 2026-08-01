#!/usr/bin/env python3
"""Audit all slots (active + archived) for artifacts lost to gitignore bug #148.

Checks each workspace clone for:
1. .gitignore entries that hide workspace subdirectories
2. Untracked/ignored files in those subdirectories (specs, blog, adr, plans)
3. Artifacts that exist on disk but were never committed

Usage:
    python3 audit_slot_artifacts.py [<family-root> ...]

If no family roots given, scans ~/claude/casehub and ~/claude/hortora.
"""

import subprocess
import sys
from pathlib import Path

ARTIFACT_DIRS = {"specs", "blog", "adr", "plans", "snapshots", "docs"}


def find_workspace_clones(slot_dir: Path) -> list[Path]:
    clones = []
    if not slot_dir.exists():
        return clones
    for sub in slot_dir.iterdir():
        if not sub.is_dir():
            continue
        if not (sub / ".git").exists():
            continue
        if sub.name == "work" or sub.name.startswith("work-"):
            clones.append(sub)
    return clones


def check_gitignore_hides(ws_clone: Path) -> list[str]:
    gitignore = ws_clone / ".gitignore"
    if not gitignore.exists():
        return []
    hidden = []
    for line in gitignore.read_text().splitlines():
        stripped = line.strip().strip("/")
        if not stripped or stripped.startswith("#"):
            continue
        subdir = ws_clone / stripped
        if subdir.is_dir():
            hidden.append(stripped)
    return hidden


def find_lost_artifacts(ws_clone: Path, hidden_dirs: list[str]) -> list[dict]:
    lost = []
    for hidden in hidden_dirs:
        base = ws_clone / hidden
        for artifact_type in ARTIFACT_DIRS:
            artifact_dir = base / artifact_type
            if not artifact_dir.is_dir():
                continue
            for f in artifact_dir.rglob("*.md"):
                if f.name == "INDEX.md":
                    continue
                rel = str(f.relative_to(ws_clone))
                result = subprocess.run(
                    ["git", "-C", str(ws_clone), "ls-files", rel],
                    capture_output=True, text=True,
                )
                if not result.stdout.strip():
                    lost.append({
                        "file": rel,
                        "type": artifact_type,
                        "subdir": hidden,
                        "size": f.stat().st_size,
                    })
    return lost


def parse_slot_md(slot_dir: Path) -> tuple[str, str]:
    slot_md = slot_dir / ".slot"
    branch = ""
    issue = ""
    if slot_md.exists():
        for line in slot_md.read_text().splitlines():
            if line.startswith("# Slot") and "—" in line:
                branch = line.split("—", 1)[1].strip()
            if "#" in line and not line.startswith("#") and not line.startswith("Covers"):
                parts = line.strip().split("#")
                if len(parts) == 2 and parts[1].strip().isdigit():
                    issue = f"#{parts[1].strip()}"
    return branch, issue


def audit_slot(slot_dir: Path, slot_id: str, location: str) -> list[dict]:
    findings = []
    ws_clones = find_workspace_clones(slot_dir)
    branch, issue = parse_slot_md(slot_dir)

    for ws_clone in ws_clones:
        hidden = check_gitignore_hides(ws_clone)
        if not hidden:
            continue
        lost = find_lost_artifacts(ws_clone, hidden)
        for item in lost:
            findings.append({
                "slot": slot_id,
                "location": location,
                "branch": branch,
                "issue": issue,
                "workspace": ws_clone.name,
                **item,
            })
    return findings


def main() -> int:
    if len(sys.argv) > 1:
        family_roots = [Path(p) for p in sys.argv[1:]]
    else:
        family_roots = [
            Path.home() / "claude" / "casehub",
            Path.home() / "claude" / "hortora",
        ]

    all_findings = []

    for family_root in family_roots:
        worktrees = family_root / "worktrees"
        if not worktrees.exists():
            continue
        family_name = family_root.name

        for slot_dir in sorted(worktrees.iterdir()):
            if not slot_dir.is_dir() or not slot_dir.name.isdigit():
                continue
            findings = audit_slot(slot_dir, slot_dir.name, f"{family_name}/active")
            all_findings.extend(findings)

        attic = worktrees / "attic"
        if attic.exists():
            for slot_dir in sorted(attic.iterdir()):
                if not slot_dir.is_dir() or not slot_dir.name.isdigit():
                    continue
                findings = audit_slot(slot_dir, slot_dir.name, f"{family_name}/attic")
                all_findings.extend(findings)

    if not all_findings:
        print("AUDIT_RESULT=clean")
        print("No lost artifacts found across all slots.")
        return 0

    print(f"AUDIT_RESULT=findings")
    print(f"TOTAL_LOST={len(all_findings)}")
    print()

    by_slot: dict[str, dict] = {}
    for f in all_findings:
        key = f"{f['location']}/slot-{f['slot']}"
        if key not in by_slot:
            by_slot[key] = {"branch": f["branch"], "issue": f["issue"], "items": []}
        by_slot[key]["items"].append(f)

    for slot_key, data in sorted(by_slot.items()):
        print(f"--- {slot_key} ({data['branch'] or 'unknown branch'}) {data['issue']} ---")
        for item in data["items"]:
            print(f"  LOST: [{item['type']}] {item['file']} ({item['size']} bytes)")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
