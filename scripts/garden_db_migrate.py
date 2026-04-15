#!/usr/bin/env python3
"""garden_db_migrate.py — One-time migration from CHECKED.md / DISCARDED.md to garden.db.

Usage:
  garden_db_migrate.py <garden_path> [--dry-run]

--dry-run: print what would be migrated without writing anything.
After migration: CHECKED.md → CHECKED.md.bak, DISCARDED.md → DISCARDED.md.bak
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from garden_db import init_db, record_pair, record_discarded, VALID_RESULTS

_GE_ID = r'GE-[\w-]+'
_PAIR_RE = re.compile(
    rf'\|\s*({_GE_ID})\s*[×x]\s*({_GE_ID})\s*\|\s*([\w-]+)\s*\|[^|]*\|([^|]*)\|'
)
_DISCARDED_RE = re.compile(
    rf'\|\s*({_GE_ID})\s*\|\s*({_GE_ID})\s*\|[^|]*\|([^|]*)\|'
)


def migrate_checked_md(garden: Path, dry_run: bool = False) -> int:
    """Read CHECKED.md rows into garden.db. Returns count of valid rows processed."""
    src = Path(garden) / 'CHECKED.md'
    if not src.exists():
        return 0
    count = 0
    for line in src.read_text(encoding='utf-8').splitlines():
        m = _PAIR_RE.search(line)
        if not m:
            continue
        id_a, id_b = m.group(1), m.group(2)
        result = m.group(3).strip()
        notes = m.group(4).strip()
        if result not in VALID_RESULTS:
            continue
        pair = f"{min(id_a, id_b)} × {max(id_a, id_b)}"
        if not dry_run:
            record_pair(garden, pair, result, notes)
        count += 1
    return count


def migrate_discarded_md(garden: Path, dry_run: bool = False) -> int:
    """Read DISCARDED.md rows into garden.db. Returns count of valid rows processed."""
    src = Path(garden) / 'DISCARDED.md'
    if not src.exists():
        return 0
    count = 0
    for line in src.read_text(encoding='utf-8').splitlines():
        m = _DISCARDED_RE.search(line)
        if not m:
            continue
        ge_id, conflicts_with, reason = m.group(1), m.group(2), m.group(3).strip()
        if ge_id in ('Discarded', 'GE-ID'):
            continue
        if not dry_run:
            record_discarded(garden, ge_id, conflicts_with, reason)
        count += 1
    return count


def run_migration(garden: Path, dry_run: bool = False) -> dict:
    """Full migration: init db, import source files, rename to .bak."""
    garden = Path(garden)
    if not garden.exists():
        raise FileNotFoundError(f"Garden not found: {garden}")
    if not dry_run:
        init_db(garden)
    checked = migrate_checked_md(garden, dry_run)
    discarded = migrate_discarded_md(garden, dry_run)
    if not dry_run:
        for fname in ('CHECKED.md', 'DISCARDED.md'):
            src = garden / fname
            if src.exists():
                src.rename(garden / f'{fname}.bak')
    return {'checked': checked, 'discarded': discarded}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('garden_path', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    try:
        result = run_migration(args.garden_path, dry_run=args.dry_run)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    prefix = '[DRY RUN] ' if args.dry_run else ''
    print(f"{prefix}Migrated {result['checked']} checked pairs, "
          f"{result['discarded']} discarded entries")
    if args.dry_run:
        print("Run without --dry-run to write to garden.db and rename source files.")


if __name__ == '__main__':
    main()
