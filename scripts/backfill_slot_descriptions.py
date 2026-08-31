#!/usr/bin/env python3
"""
backfill_slot_descriptions.py — Add ## Description to existing .slot files.

Reads the primary issue body from GitHub and extracts the first meaningful
paragraph as the description. Applies to all active and archived slots.

Usage:
    python3 scripts/backfill_slot_descriptions.py <family_root> [--dry-run]

Output: KEY=VALUE lines per slot.
"""

import subprocess
import sys
from pathlib import Path


def _gh_issue_body(repo: str, issue_num: str) -> str:
    try:
        result = subprocess.run(
            ["gh", "issue", "view", issue_num, "--repo", repo,
             "--json", "body", "--jq", ".body"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def _extract_description(body: str) -> str:
    if not body:
        return ""
    lines = body.splitlines()
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
        elif stripped.startswith("#") or stripped.startswith("|") or stripped.startswith("```"):
            if current:
                paragraphs.append(" ".join(current))
                current = []
        else:
            current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))

    for p in paragraphs:
        if len(p) > 20 and not p.startswith("- ["):
            return p[:500]
    return ""


def backfill_slot(slot_dir: Path, dry_run: bool = False) -> dict[str, str]:
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        return {"status": "skipped", "reason": "no .slot file"}

    content = slot_file.read_text()
    if "## Description" in content:
        return {"status": "skipped", "reason": "already has description"}

    issue_repo = ""
    issue_num = ""
    for line in content.splitlines():
        if "#" in line and not line.startswith("#") and not line.startswith("Covers:"):
            parts = line.strip().split("#")
            if len(parts) == 2:
                issue_repo = parts[0]
                issue_num = parts[1]
                break

    if not issue_repo or not issue_num:
        return {"status": "skipped", "reason": "no issue ref found"}

    body = _gh_issue_body(issue_repo, issue_num)
    description = _extract_description(body)

    if not description:
        return {"status": "skipped", "reason": "no description extracted from issue body"}

    if dry_run:
        return {"status": "would_update", "description": description[:80]}

    lines = content.splitlines()
    insert_idx = None
    for i, line in enumerate(lines):
        if line.startswith("## What to do"):
            insert_idx = i
            break

    if insert_idx is None:
        for i, line in enumerate(lines):
            if line.startswith("## Repos"):
                insert_idx = i
                break

    if insert_idx is not None:
        lines.insert(insert_idx, f"## Description\n{description}\n")
        slot_file.write_text("\n".join(lines) + "\n")
        return {"status": "updated", "description": description[:80]}

    return {"status": "skipped", "reason": "no insertion point found"}


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    family_root = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv

    slots_dir = family_root / "slots"
    if not slots_dir.is_dir():
        print("ERROR=no_slots_dir")
        sys.exit(1)

    updated = 0
    skipped = 0
    errors = 0

    for scan_dir in [slots_dir, slots_dir / "attic"]:
        if not scan_dir.is_dir():
            continue
        for entry in sorted(scan_dir.iterdir()):
            if not entry.is_dir() or not entry.name.isdigit():
                continue
            result = backfill_slot(entry, dry_run=dry_run)
            status = result["status"]
            slot_num = entry.name
            location = "attic" if "attic" in str(entry) else "active"

            if status == "updated" or status == "would_update":
                print(f"{'WOULD_UPDATE' if dry_run else 'UPDATED'}={slot_num} location={location} desc={result.get('description', '')}")
                updated += 1
            elif status == "skipped":
                reason = result.get("reason", "")
                if reason != "already has description":
                    print(f"SKIPPED={slot_num} location={location} reason={reason}")
                skipped += 1
            else:
                errors += 1

    print(f"TOTAL_UPDATED={updated}")
    print(f"TOTAL_SKIPPED={skipped}")
    print(f"DRY_RUN={'yes' if dry_run else 'no'}")


if __name__ == "__main__":
    main()
