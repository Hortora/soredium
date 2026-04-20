#!/usr/bin/env python3
"""
migrate_legacy_entries.py

Migrates legacy multi-entry garden files to individual YAML-frontmatter files.

For each multi-entry .md file in the garden containing **ID:** GE-NNNN entries:
  1. Parse entries by ## heading
  2. Write each to <domain>/GE-NNNN.md with YAML frontmatter
  3. Update GARDEN.md links to point to new individual files
  4. Rewrite source files (keeping unindexed entries) or delete if fully migrated
  5. Validate and commit

Usage:
  python3 migrate_legacy_entries.py             # migrate all
  python3 migrate_legacy_entries.py --dry-run   # preview only
  python3 migrate_legacy_entries.py --domain tools
  python3 migrate_legacy_entries.py --issue 42  # add Refs #42 to commit
"""

import argparse
import datetime
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKIP_FILES = {"GARDEN.md", "CHECKED.md", "DISCARDED.md", "README.md",
              "SKILL-SPEC.md", "INDEX.md"}
SKIP_DIRS  = {"submissions", "_summaries", "_index", "labels",
              ".git", ".github", "scripts"}

# 4-digit sequential legacy IDs only (GE-0001 … GE-0999)
LEGACY_ID_RE     = re.compile(r'^\*\*ID:\*\*\s+(GE-\d{4})\s*$', re.MULTILINE)
# Split file content into entry chunks at every ## heading
ENTRY_SPLIT_RE   = re.compile(r'(?=^## )', re.MULTILINE)

# Field extractors
TITLE_RE         = re.compile(r'^## (.+)', re.MULTILINE)
STACK_RE         = re.compile(r'^\*\*Stack:\*\*\s*(.+)', re.MULTILINE)
LABELS_RE        = re.compile(r'^\*\*Labels:\*\*\s*(.+)', re.MULTILINE)
TAG_RE           = re.compile(r'`#([^`]+)`')
SCORE_RE         = re.compile(r'\*Score:\s*(\d+)/15')

# Type-inference markers (checked in order — first match wins)
GOTCHA_MARKERS      = re.compile(
    r'^\*\*Symptom:\*\*|^### Root cause|^### What was tried', re.MULTILINE)
TECHNIQUE_MARKERS   = re.compile(
    r'^\*\*What it achieves:\*\*|^### The technique', re.MULTILINE)
UNDOCUMENTED_MARKERS = re.compile(
    r'^\*\*What it is:\*\*|^### How to use it', re.MULTILINE)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Entry:
    ge_id:   str
    title:   str
    stack:   str
    tags:    list
    score:   int
    type:    str
    body:    str          # original markdown (## heading onward, trailing --- stripped)
    domain:  str
    submitted: str


@dataclass
class MigrationStats:
    migrated:        int = 0
    skipped_exists:  int = 0
    files_deleted:   int = 0
    files_updated:   int = 0
    garden_links:    int = 0
    errors:          list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git(garden: Path, *args) -> str:
    result = subprocess.run(
        ["git", "-C", str(garden)] + list(args),
        capture_output=True, text=True
    )
    return result.stdout.strip()


def get_submitted_date(garden: Path, rel_path: str) -> str:
    """Oldest commit date for this file (git log newest-first → take last line)."""
    out = git(garden, "log", "--follow", "--format=%ad", "--date=short", "--", rel_path)
    if not out:
        return datetime.date.today().isoformat()
    dates = [d for d in out.split("\n") if d.strip()]
    return dates[-1] if dates else datetime.date.today().isoformat()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def infer_type(body: str) -> str:
    if GOTCHA_MARKERS.search(body):
        return "gotcha"
    if TECHNIQUE_MARKERS.search(body):
        return "technique"
    if UNDOCUMENTED_MARKERS.search(body):
        return "undocumented"
    return "gotcha"


def parse_tags(body: str) -> list:
    m = LABELS_RE.search(body)
    if not m:
        return []
    return TAG_RE.findall(m.group(1))


def parse_score(body: str) -> int:
    m = SCORE_RE.search(body)
    return max(int(m.group(1)), 8) if m else 8


def parse_entries(content: str, domain: str, submitted: str) -> tuple:
    """
    Returns (header_text, [Entry, ...], [str, ...])
    where the last list contains raw body text for unindexed entries (no GE-ID).
    """
    chunks = ENTRY_SPLIT_RE.split(content)
    header = chunks[0]          # preamble before first ## heading
    entries = []
    unindexed = []              # chunks with no legacy ID

    for chunk in chunks[1:]:
        body = chunk.strip()
        # Strip trailing --- separator (some files have them, some don't)
        body = re.sub(r'\n+---\s*$', '', body).strip()
        if not body:
            continue

        id_match = LEGACY_ID_RE.search(body)
        if not id_match:
            unindexed.append(body)
            continue

        ge_id = id_match.group(1)

        title_m = TITLE_RE.search(body)
        title   = title_m.group(1).strip() if title_m else ge_id

        stack_m = STACK_RE.search(body)
        stack   = stack_m.group(1).strip() if stack_m else ""

        entries.append(Entry(
            ge_id=ge_id,
            title=title,
            stack=stack,
            tags=parse_tags(body),
            score=parse_score(body),
            type=infer_type(body),
            body=body,
            domain=domain,
            submitted=submitted,
        ))

    return header, entries, unindexed


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def format_tags(tags: list) -> str:
    if not tags:
        return "[]"
    return "[" + ", ".join(tags) + "]"


def format_file(entry: Entry) -> str:
    title_escaped = entry.title.replace('"', '\\"')
    stack_escaped = entry.stack.replace('"', '\\"') if '"' in entry.stack else entry.stack
    frontmatter = (
        "---\n"
        f"id: {entry.ge_id}\n"
        f'title: "{title_escaped}"\n'
        f"type: {entry.type}\n"
        f"domain: {entry.domain}\n"
        f'stack: "{stack_escaped}"\n'
        f"tags: {format_tags(entry.tags)}\n"
        f"score: {entry.score}\n"
        "verified: true\n"
        "staleness_threshold: 730\n"
        f"submitted: {entry.submitted}\n"
        "---\n"
        "\n"
    )
    return frontmatter + entry.body + "\n"


# ---------------------------------------------------------------------------
# GARDEN.md update
# ---------------------------------------------------------------------------

def update_garden_links(content: str, ge_id: str, old_rel: str, new_rel: str) -> tuple:
    """Replace all occurrences of (old_rel) in lines starting with `- GE-NNNN`."""
    pattern = re.compile(
        r'^(- ' + re.escape(ge_id) + r' .+?\()' + re.escape(old_rel) + r'(\))',
        re.MULTILINE
    )
    new_content, count = pattern.subn(r'\g<1>' + new_rel + r'\2', content)
    return new_content, count


# ---------------------------------------------------------------------------
# File cleanup
# ---------------------------------------------------------------------------

def rebuild_source_file(header: str, unindexed: list) -> str:
    """Reconstruct a multi-entry file keeping only unindexed entries."""
    parts = [header.rstrip()]
    for body in unindexed:
        parts.append("\n\n---\n\n" + body)
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_legacy_files(garden: Path, domain_filter: str | None) -> list:
    """Find all multi-entry .md files that contain at least one legacy GE-ID."""
    found = []
    for path in sorted(garden.rglob("*.md")):
        # Skip special files
        if path.name in SKIP_FILES:
            continue
        # Skip special dirs
        rel_parts = path.relative_to(garden).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        # Skip already-migrated individual files (GE-NNNN.md or GE-YYYYMMDD-*.md)
        if re.match(r'^GE-', path.name):
            continue
        # Domain filter
        if domain_filter and (len(rel_parts) < 1 or rel_parts[0] != domain_filter):
            continue
        # Only files with at least one legacy ID
        content = path.read_text(encoding="utf-8")
        if LEGACY_ID_RE.search(content):
            found.append(path)
    return found


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args):
    garden = Path(args.garden).expanduser()
    dry_run = args.dry_run
    verbose = args.verbose

    if not garden.is_dir():
        print(f"ERROR: garden not found at {garden}", file=sys.stderr)
        sys.exit(1)

    files = discover_legacy_files(garden, args.domain)
    if not files:
        print("No legacy multi-entry files found.")
        return

    print(f"Found {len(files)} file(s) with legacy entries.")

    stats = MigrationStats()
    # migration_map: ge_id → (old_rel, new_rel)
    migration_map: dict = {}

    for src_path in files:
        rel_path   = str(src_path.relative_to(garden))
        domain     = src_path.parent.name
        submitted  = get_submitted_date(garden, rel_path)
        content    = src_path.read_text(encoding="utf-8")

        header, entries, unindexed = parse_entries(content, domain, submitted)

        if verbose:
            print(f"\n{rel_path}: {len(entries)} legacy entries, "
                  f"{len(unindexed)} unindexed")

        for entry in entries:
            out_path = garden / domain / f"{entry.ge_id}.md"
            new_rel  = f"{domain}/{entry.ge_id}.md"

            if out_path.exists():
                if verbose:
                    print(f"  SKIP {entry.ge_id} (already exists)")
                stats.skipped_exists += 1
                continue

            file_content = format_file(entry)

            if dry_run:
                print(f"  [DRY] write {new_rel}  ({entry.type}, score={entry.score})")
            else:
                out_path.write_text(file_content, encoding="utf-8")
                if verbose:
                    print(f"  WRITE {new_rel}")

            stats.migrated += 1
            migration_map[entry.ge_id] = (rel_path, new_rel)

        # Rewrite or delete source file
        if not dry_run:
            if unindexed:
                src_path.write_text(rebuild_source_file(header, unindexed), encoding="utf-8")
                stats.files_updated += 1
                if verbose:
                    print(f"  UPDATE {rel_path} ({len(unindexed)} unindexed entries kept)")
            else:
                src_path.unlink()
                stats.files_deleted += 1
                if verbose:
                    print(f"  DELETE {rel_path}")
        else:
            action = "update" if unindexed else "delete"
            print(f"  [DRY] {action} {rel_path}")

    # Update GARDEN.md
    garden_md_path = garden / "GARDEN.md"
    garden_content = garden_md_path.read_text(encoding="utf-8")
    total_links = 0

    for ge_id, (old_rel, new_rel) in migration_map.items():
        garden_content, count = update_garden_links(garden_content, ge_id, old_rel, new_rel)
        total_links += count

    stats.garden_links = total_links

    if dry_run:
        print(f"\n[DRY] GARDEN.md: {total_links} link(s) would be updated")
    else:
        garden_md_path.write_text(garden_content, encoding="utf-8")

    # Summary
    print(f"\n{'DRY RUN ' if dry_run else ''}Summary:")
    print(f"  Migrated:        {stats.migrated}")
    print(f"  Skipped (exist): {stats.skipped_exists}")
    print(f"  Files deleted:   {stats.files_deleted}")
    print(f"  Files updated:   {stats.files_updated}")
    print(f"  GARDEN.md links: {stats.garden_links}")

    if dry_run or stats.migrated == 0:
        return

    # Validate
    print("\nRunning validator...")
    val = subprocess.run(
        [sys.executable,
         str(Path(__file__).parent / "validate_garden.py"),
         str(garden)],
        capture_output=True, text=True
    )
    print(val.stdout)
    if val.returncode == 1:
        print("VALIDATION ERRORS — aborting commit. Fix issues before re-running.",
              file=sys.stderr)
        print(val.stderr, file=sys.stderr)
        sys.exit(1)

    # Commit
    # Stage new files
    new_files = [str((garden / nr).relative_to(garden)) for _, (_, nr) in migration_map.items()]
    for f in new_files:
        git(garden, "add", f)

    # Stage modified/deleted source files and GARDEN.md
    git(garden, "add", "-u")
    git(garden, "add", "GARDEN.md")

    issue_footer = f"\nRefs #{args.issue}" if args.issue else ""
    commit_msg = (
        f"feat(migrate): extract {stats.migrated} legacy entries to individual files\n"
        f"\n"
        f"{stats.migrated} entries migrated across "
        f"{stats.files_deleted + stats.files_updated} file(s).\n"
        f"Files deleted: {stats.files_deleted}  "
        f"(fully migrated, no unindexed residuals)\n"
        f"Files updated: {stats.files_updated}  "
        f"(unindexed entries retained)\n"
        f"GARDEN.md: {stats.garden_links} link(s) updated"
        f"{issue_footer}"
    )

    result = subprocess.run(
        ["git", "-C", str(garden), "commit", "-m", commit_msg],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Commit failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"\nCommitted: {git(garden, 'log', '--oneline', '-1')}")
    if not args.issue:
        print("NOTE: no --issue flag provided — commit has no issue reference.")


def main():
    default_garden = os.environ.get("HORTORA_GARDEN", str(Path.home() / ".hortora/garden"))

    p = argparse.ArgumentParser(description="Migrate legacy garden entries to individual files")
    p.add_argument("--dry-run",  action="store_true", help="Preview only, no writes")
    p.add_argument("--domain",   help="Migrate only this domain directory (e.g. tools)")
    p.add_argument("--verbose",  action="store_true", help="Verbose per-file output")
    p.add_argument("--garden",   default=default_garden, help="Garden root path")
    p.add_argument("--issue",    type=int, help="GitHub issue number to reference in commit")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
