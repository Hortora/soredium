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


def filter_proj_symlinks(findings: list[dict]) -> list[dict]:
    """Remove findings under proj/ — symlink to project repo, not workspace artifacts."""
    return [f for f in findings if not f["file"].startswith("proj/")]


def filter_inherited(findings: list[dict], threshold: int = 3) -> list[dict]:
    """Remove files that appear in threshold+ slots — inherited from main, not lost."""
    from collections import Counter
    counts = Counter(f["file"] for f in findings)
    return [f for f in findings if counts[f["file"]] < threshold]


def filter_already_recovered(findings: list[dict], family_root: Path) -> list[dict]:
    """Remove files that already exist at the workspace main destination.

    Handles multi-repo layout: file paths like 'engine/blog/entry.md' have
    a repo prefix. The actual workspace is found via the wksp symlink at
    family_root/<repo>/wksp. Falls back to family_root/<repo>/work for
    single-repo layouts.
    """
    if not family_root.exists():
        return findings
    result = []
    for f in findings:
        filepath = f["file"]
        parts = filepath.split("/", 1)
        if len(parts) == 2:
            repo_name, rel = parts
            wksp_link = family_root / repo_name / "wksp"
            work_dir = family_root / repo_name / "work"
            if wksp_link.is_symlink():
                ws = wksp_link.resolve()
                if (ws / rel).exists():
                    continue
            elif work_dir.is_dir() and (work_dir / rel).exists():
                continue
        if (family_root / filepath).exists():
            continue
        result.append(f)
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Audit slots for lost artifacts")
    parser.add_argument("family_roots", nargs="*", type=Path,
                        default=[Path.home() / "claude" / "casehub",
                                 Path.home() / "claude" / "hortora"])
    parser.add_argument("--verbose", action="store_true",
                        help="Show filtered-out findings with reason")
    parser.add_argument("--summary", action="store_true",
                        help="Show only counts, not individual files")
    parser.add_argument("--no-filter", action="store_true",
                        help="Skip all false-positive filters (raw output)")
    args = parser.parse_args()

    all_findings = []

    for family_root in args.family_roots:
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

    raw_count = len(all_findings)

    if not args.no_filter:
        pre_proj = len(all_findings)
        all_findings = filter_proj_symlinks(all_findings)
        proj_filtered = pre_proj - len(all_findings)

        pre_inherited = len(all_findings)
        all_findings = filter_inherited(all_findings, threshold=3)
        inherited_filtered = pre_inherited - len(all_findings)

        recovered_filtered = 0
        for family_root in args.family_roots:
            pre = len(all_findings)
            all_findings = filter_already_recovered(all_findings, family_root)
            recovered_filtered += pre - len(all_findings)

        if args.verbose:
            print(f"FILTERED: {proj_filtered} proj/ symlinks, "
                  f"{inherited_filtered} inherited (3+ slots), "
                  f"{recovered_filtered} already recovered")
            print(f"RAW_TOTAL={raw_count}")
            print()

    if not all_findings:
        print("AUDIT_RESULT=clean")
        if raw_count > 0:
            print(f"All {raw_count} raw findings filtered as false positives.")
        else:
            print("No lost artifacts found across all slots.")
        return 0

    print(f"AUDIT_RESULT=findings")
    print(f"TOTAL_LOST={len(all_findings)}")
    print()

    if args.summary:
        by_type: dict[str, int] = {}
        for f in all_findings:
            by_type[f["type"]] = by_type.get(f["type"], 0) + 1
        for t, c in sorted(by_type.items()):
            print(f"  {t}: {c}")
        return 1

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
