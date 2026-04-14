#!/usr/bin/env python3
"""
contributors.py — Generate CONTRIBUTORS.md from garden entries.

Reads all YAML-frontmatter garden entries, computes effective scores
per author (base score + bonus from BONUS_RULES), and generates a
ranked contributor table in CONTRIBUTORS.md.

Usage:
  contributors.py [garden_root]          # generate CONTRIBUTORS.md
  contributors.py [garden_root] --json   # machine-readable output
"""

import sys
import json
import os
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from validate_pr import BONUS_RULES, compute_bonus, bonus_points, parse_entry

SKIP_FILES = {
    'GARDEN.md', 'CHECKED.md', 'DISCARDED.md', 'INDEX.md',
    'README.md', 'CONTRIBUTORS.md',
}
SKIP_DIRS = {'.git', '_summaries', '_index', 'labels', 'submissions', 'scripts'}


def git_blame_author(garden: Path, entry_path: Path) -> str:
    """Return committer email from git log for this entry file. Returns 'unknown' on failure."""
    try:
        rel = str(entry_path.relative_to(garden))
        result = subprocess.run(
            ['git', '-C', str(garden), 'log', '--follow', '--format=%ae', '--', rel],
            capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().splitlines()
        return lines[-1].strip() if lines else 'unknown'
    except Exception:
        return 'unknown'


def load_garden_entries(garden: Path) -> list:
    """Load all YAML-frontmatter entries. Returns list of entry dicts."""
    entries = []
    for path in garden.rglob('*.md'):
        if path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(garden).parts):
            continue
        try:
            fm, body, _ = parse_entry(path)
        except Exception:
            continue
        if 'score' not in fm or 'title' not in fm:
            continue

        author = fm.get('author') or git_blame_author(garden, path) or 'unknown'
        base_score = int(fm.get('score', 0))
        bonus_results = compute_bonus(fm, body)
        bonus = bonus_points(bonus_results)

        entries.append({
            'ge_id': fm.get('id', path.stem),
            'title': fm.get('title', ''),
            'author': author,
            'base_score': base_score,
            'bonus': bonus,
            'effective_score': base_score + bonus,
            'path': str(path.relative_to(garden)),
        })
    return entries


def compute_contributors(entries: list) -> list:
    """Aggregate entries by author. Returns list sorted by avg_score descending."""
    by_author: dict = defaultdict(list)
    for e in entries:
        by_author[e['author']].append(e)

    contributors = []
    for author, author_entries in by_author.items():
        best = max(author_entries, key=lambda e: e['effective_score'])
        n = len(author_entries)
        avg_score = round(sum(e['effective_score'] for e in author_entries) / n, 1)
        avg_bonus = round(sum(e['bonus'] for e in author_entries) / n, 1)
        contributors.append({
            'author': author,
            'entries': n,
            'avg_score': avg_score,
            'avg_bonus': avg_bonus,
            'best_entry': best,
        })

    contributors.sort(key=lambda c: (-c['avg_score'], -c['entries']))
    return contributors


def format_contributors_md(contributors: list) -> str:
    """Generate CONTRIBUTORS.md content."""
    today = date.today().isoformat()
    lines = [
        '# Garden Contributors',
        '',
        f'Ranked by average effective score. Updated: {today}.',
        '',
        '| Rank | Author | Entries | Avg Score | Avg Bonus | Best Entry |',
        '|------|--------|---------|-----------|-----------|------------|',
    ]
    for i, c in enumerate(contributors, 1):
        best = c['best_entry']
        title_short = best['title'][:50]
        best_link = f"[{title_short}]({best['path']})"
        lines.append(
            f"| {i} | {c['author']} | {c['entries']} | {c['avg_score']} | "
            f"+{c['avg_bonus']} | {best_link} |"
        )
    lines += [
        '',
        '_Avg Bonus reflects how consistently contributors document constraints, '
        'alternatives considered, and invalidation triggers._',
        '',
    ]
    return '\n'.join(lines)


def _default_garden() -> Path:
    env = os.environ.get('HORTORA_GARDEN')
    return Path(env).expanduser().resolve() if env else \
           (Path.home() / '.hortora' / 'garden').resolve()


def main():
    args = sys.argv[1:]
    non_flags = [a for a in args if not a.startswith('--')]
    garden = Path(non_flags[0]).expanduser().resolve() if non_flags else _default_garden()
    use_json = '--json' in args

    entries = load_garden_entries(garden)
    contributors = compute_contributors(entries)

    if use_json:
        print(json.dumps(contributors, indent=2, default=str))
    else:
        md = format_contributors_md(contributors)
        out = garden / 'CONTRIBUTORS.md'
        out.write_text(md, encoding='utf-8')
        print(f"Written: {out}")
        print(f"{len(contributors)} contributor(s), {len(entries)} entries")
    sys.exit(0)


if __name__ == '__main__':
    main()
