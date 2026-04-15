#!/usr/bin/env python3
"""
dedupe_scanner.py — Jaccard similarity pre-scorer for harvest DEDUPE.

Scans garden domain directories for YAML-frontmatter entries, computes
Jaccard similarity for all unchecked within-domain pairs, and returns
pairs sorted highest-first. Owns CHECKED.md state via --record.

Usage:
  dedupe_scanner.py [garden_root]
  dedupe_scanner.py [garden_root] --domain quarkus
  dedupe_scanner.py [garden_root] --top 20
  dedupe_scanner.py [garden_root] --json
  dedupe_scanner.py [garden_root] --record "GE-X x GE-Y" distinct "note"
"""

import re
import sys
import json
import os
from datetime import date
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from garden_db import (
    load_checked_pairs as _db_load_checked_pairs,
    record_pair as _db_record_pair,
    init_db as _db_init,
)

SKIP_FILES = {'GARDEN.md', 'CHECKED.md', 'DISCARDED.md', 'INDEX.md', 'README.md'}
SKIP_DIRS  = {'.git', '_summaries', '_index', 'labels', 'submissions', 'scripts'}
TOKEN_RE   = re.compile(r'\b[a-z]{3,}\b')


def tokenize(text: str) -> set:
    """Extract 3+ char lowercase word tokens from text."""
    return set(TOKEN_RE.findall(text.lower()))


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity: |A∩B| / |A∪B|. Returns 0.0 if both empty."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def parse_tags(tags_str: str) -> list:
    """Parse comma-separated tag list from frontmatter value string."""
    return [t.strip().strip('"\'') for t in tags_str.split(',') if t.strip()]


def canonical_pair(id_a: str, id_b: str) -> str:
    """Return canonical 'lower × higher' pair string (lexicographic)."""
    lo, hi = (id_a, id_b) if id_a <= id_b else (id_b, id_a)
    return f"{lo} × {hi}"


def load_checked_pairs(garden: Path) -> set:
    """Return set of canonical pair strings already in garden.db."""
    if not (garden / 'garden.db').exists():
        _db_init(garden)
    return _db_load_checked_pairs(garden)


def record_pair(garden: Path, pair: str, result: str, note: str = '') -> None:
    """Record pair comparison result to garden.db. Idempotent."""
    valid = {'distinct', 'related', 'duplicate-discarded'}
    if result not in valid:
        print(f"ERROR: result must be one of {valid}", file=sys.stderr)
        sys.exit(1)
    if not (garden / 'garden.db').exists():
        _db_init(garden)
    _db_record_pair(garden, pair, result, note)


def load_entries(garden: Path, domain_filter: str = None) -> dict:
    """
    Scan domain directories for entries with YAML frontmatter.
    Returns {domain: [{'id': str, 'title': str, 'tags': list, 'path': Path}]}
    """
    entries_by_domain: dict = {}
    for path in garden.rglob('*.md'):
        if path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(garden).parts):
            continue
        content = path.read_text(encoding='utf-8').replace('\r\n', '\n')
        fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if not fm_match:
            continue
        fm = fm_match.group(1)
        id_m = re.search(r'^id:\s*(.+)$', fm, re.MULTILINE)
        if not id_m:
            continue
        ge_id = id_m.group(1).strip()
        title_m = re.search(r'^title:\s*"?(.+?)"?\s*$', fm, re.MULTILINE)
        title = title_m.group(1).strip().strip('"') if title_m else ''
        tags_m = re.search(r'^tags:\s*\[(.+)\]', fm, re.MULTILINE)
        tags = parse_tags(tags_m.group(1)) if tags_m else []
        domain_m = re.search(r'^domain:\s*(.+)$', fm, re.MULTILINE)
        domain = domain_m.group(1).strip() if domain_m else path.parent.name
        if domain_filter and domain != domain_filter:
            continue
        entries_by_domain.setdefault(domain, []).append({
            'id': ge_id, 'title': title, 'tags': tags, 'path': path,
        })
    return entries_by_domain


def compute_pairs(entries_by_domain: dict, checked_pairs: set,
                  top: int = None) -> list:
    """Generate all unchecked within-domain pairs with Jaccard scores, sorted desc."""
    results = []
    for domain, entries in entries_by_domain.items():
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]
                pair_key = canonical_pair(a['id'], b['id'])
                if pair_key in checked_pairs:
                    continue
                tokens_a = tokenize(a['title'] + ' ' + ' '.join(a['tags']))
                tokens_b = tokenize(b['title'] + ' ' + ' '.join(b['tags']))
                score = jaccard(tokens_a, tokens_b)
                results.append({
                    'pair': pair_key, 'id_a': a['id'], 'id_b': b['id'],
                    'title_a': a['title'], 'title_b': b['title'],
                    'domain': domain, 'score': round(score, 4),
                })
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top] if top is not None else results


def format_text(pairs: list) -> str:
    """Format pairs as human-readable text grouped by domain."""
    if not pairs:
        return "No unchecked pairs found."
    by_domain: dict = {}
    for p in pairs:
        by_domain.setdefault(p['domain'], []).append(p)
    lines = []
    for domain in sorted(by_domain):
        domain_pairs = by_domain[domain]
        lines.append(f"\nDOMAIN: {domain}  ({len(domain_pairs)} unchecked pairs)")
        for p in domain_pairs:
            ta = p['title_a'][:40]
            tb = p['title_b'][:40]
            lines.append(f"  {p['score']:.2f}  {p['pair']}  [{ta} / {tb}]")
    return '\n'.join(lines)


def _default_garden() -> Path:
    env = os.environ.get('HORTORA_GARDEN')
    return Path(env).expanduser().resolve() if env else \
           (Path.home() / '.hortora' / 'garden').resolve()


def main():
    args = sys.argv[1:]
    non_flags = [a for a in args if not a.startswith('--')]
    garden = Path(non_flags[0]).expanduser().resolve() if non_flags else _default_garden()

    if '--record' in args:
        idx = args.index('--record')
        if idx + 2 >= len(args):
            print('ERROR: --record requires <pair> <result> [note]', file=sys.stderr)
            sys.exit(1)
        record_pair(garden, args[idx + 1], args[idx + 2],
                    args[idx + 3] if idx + 3 < len(args) else '')
        sys.exit(0)

    domain_filter = None
    if '--domain' in args:
        i = args.index('--domain')
        domain_filter = args[i + 1] if i + 1 < len(args) else None

    top = None
    if '--top' in args:
        i = args.index('--top')
        try:
            top = int(args[i + 1])
        except (IndexError, ValueError):
            print('ERROR: --top requires an integer', file=sys.stderr)
            sys.exit(1)

    use_json = '--json' in args

    entries_by_domain = load_entries(garden, domain_filter)
    checked_pairs = load_checked_pairs(garden)
    pairs = compute_pairs(entries_by_domain, checked_pairs, top)

    if use_json:
        print(json.dumps(pairs, indent=2))
    else:
        print(format_text(pairs))
    sys.exit(0)


if __name__ == '__main__':
    main()
