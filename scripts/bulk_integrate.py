#!/usr/bin/env python3
"""
bulk_integrate.py — Populate _summaries/, _index/, labels/, and domain INDEX.md
files for all GE-*.md entries in the garden in one pass.

Run this after a bulk import or migration where integrate_entry.py was not
called per-entry. Makes one git commit at the end rather than one per entry.

Usage:
  python3 bulk_integrate.py [garden_root]
  garden_root defaults to $HORTORA_GARDEN or ~/.hortora/garden
"""

import os
import sys
import subprocess
from pathlib import Path

# Pull in helpers from integrate_entry without triggering main()
sys.path.insert(0, str(Path(__file__).parent))
from integrate_entry import parse_entry, generate_summary

SKIP = {'GARDEN.md', 'CHECKED.md', 'DISCARDED.md', 'README.md', 'INDEX.md'}
SKIP_DIRS = {'.git', '.github', 'submissions', '_summaries', '_index', 'labels'}


def init_global_index(garden: Path) -> None:
    gi = garden / '_index' / 'global.md'
    gi.parent.mkdir(exist_ok=True)
    if not gi.exists():
        gi.write_text('# Garden Global Index\n\n| Domain | Index |\n|--------|-------|\n',
                      encoding='utf-8')


def init_domain_index(domain_dir: Path) -> None:
    idx = domain_dir / 'INDEX.md'
    if not idx.exists():
        idx.write_text(f'# {domain_dir.name} Index\n\n| ID | Title | Type | Score |\n|----|----|-------|-------|\n',
                       encoding='utf-8')


def domain_index_has(idx: Path, ge_id: str) -> bool:
    return ge_id in idx.read_text(encoding='utf-8') if idx.exists() else False


def global_index_has(gi: Path, domain: str) -> bool:
    return domain in gi.read_text(encoding='utf-8') if gi.exists() else False


def summary_exists(garden: Path, domain: str, ge_id: str) -> bool:
    return (garden / '_summaries' / domain / f'{ge_id}.md').exists()


def run(garden: Path) -> None:
    init_global_index(garden)

    entries = sorted(
        p for p in garden.rglob('GE-*.md')
        if not any(part in SKIP_DIRS for part in p.parts)
        and p.name not in SKIP
    )

    print(f'Found {len(entries)} entries to process.')
    ok = skipped = errors = 0

    for path in entries:
        fm, _ = parse_entry(path)
        if not fm or not fm.get('id'):
            print(f'  SKIP (no frontmatter): {path.relative_to(garden)}')
            skipped += 1
            continue

        ge_id = fm['id']
        domain = fm.get('domain') or path.parent.name

        # _summaries/<domain>/GE-XXXX.md
        summary_dir = garden / '_summaries' / domain
        summary_dir.mkdir(parents=True, exist_ok=True)
        summary_path = summary_dir / f'{ge_id}.md'
        if not summary_path.exists():
            summary_path.write_text(generate_summary(fm, ge_id), encoding='utf-8')

        # <domain>/INDEX.md
        domain_dir = garden / domain
        init_domain_index(domain_dir)
        idx = domain_dir / 'INDEX.md'
        if not domain_index_has(idx, ge_id):
            with open(idx, 'a', encoding='utf-8') as f:
                f.write(f"| {ge_id} | {fm.get('title', '')} | {fm.get('type', '')} | {fm.get('score', '')}/15 |\n")

        # labels/<tag>.md
        labels_dir = garden / 'labels'
        labels_dir.mkdir(exist_ok=True)
        for tag in fm.get('tags', []):
            tag_file = labels_dir / f'{tag}.md'
            existing = tag_file.read_text(encoding='utf-8') if tag_file.exists() else ''
            if ge_id not in existing:
                with open(tag_file, 'a', encoding='utf-8') as f:
                    f.write(f"- {ge_id}: {fm.get('title', '')}\n")

        # _index/global.md
        gi = garden / '_index' / 'global.md'
        if not global_index_has(gi, domain):
            with open(gi, 'a', encoding='utf-8') as f:
                f.write(f'| {domain} | {domain}/INDEX.md |\n')

        ok += 1

    print(f'\nDone: {ok} integrated, {skipped} skipped, {errors} errors.')

    # Stage and commit
    subprocess.run(['git', '-C', str(garden), 'add',
                    '_summaries/', '_index/', 'labels/'], check=True)
    # Also stage any new INDEX.md files in domain dirs
    subprocess.run(['git', '-C', str(garden), 'add', '--all'], check=True)

    result = subprocess.run(
        ['git', '-C', str(garden), 'diff', '--cached', '--quiet']
    )
    if result.returncode == 0:
        print('Nothing to commit — indexes already up to date.')
        return

    subprocess.run(
        ['git', '-C', str(garden), 'commit',
         '-m', f'index: bulk integrate {ok} entries into _summaries, _index, labels'],
        check=True
    )
    print('Committed.')


if __name__ == '__main__':
    garden = Path(os.environ.get('HORTORA_GARDEN', Path.home() / '.hortora/garden'))
    if len(sys.argv) > 1:
        garden = Path(sys.argv[1])
    garden = garden.expanduser()
    if not garden.is_dir():
        print(f'ERROR: garden not found at {garden}', file=sys.stderr)
        sys.exit(1)
    run(garden)
