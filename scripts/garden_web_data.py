#!/usr/bin/env python3
"""garden_web_data.py — Build JSON data from a knowledge garden for the web app.

Usage:
  garden_web_data.py [garden_path]   # outputs JSON to stdout
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---', re.DOTALL)
GE_ID_RE = re.compile(r'\bGE-\d{8}-[0-9a-f]{6}\b|\bGE-\d{4}\b')
SKIP_FILES = {'INDEX.md', 'README.md', 'GARDEN.md', 'CHECKED.md',
              'DISCARDED.md', 'SCHEMA.md'}
SKIP_DIRS = {'.git', 'submissions', '_augment', '_summaries',
             '_index', 'labels', 'scripts'}


def parse_entry_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter fields from an entry file."""
    if not content:
        return {}
    content = content.replace('\r\n', '\n')
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}
    result = {}
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or ':' not in line:
            i += 1
            continue
        key, _, rest = line.partition(':')
        key = key.strip()
        rest = rest.strip()
        if not rest:
            i += 1
            continue
        if rest.startswith('[') and rest.endswith(']'):
            result[key] = [v.strip().strip('"\'') for v in rest[1:-1].split(',') if v.strip()]
        else:
            val = rest.strip('"\'')
            if key in ('score', 'staleness_threshold') and val.isdigit():
                result[key] = int(val)
            else:
                result[key] = val
        i += 1
    return result


def parse_domain_index(content: str) -> list:
    """Parse a domain INDEX.md table. Returns list of {id, title} dicts."""
    entries = []
    for line in content.splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if not cells or all(c.startswith('-') for c in cells):
            continue
        ge_id = None
        title = None
        for cell in cells:
            ids = GE_ID_RE.findall(cell)
            if ids and ids[0] != 'GE-ID':
                ge_id = ids[0]
            elif ge_id and not title and cell and not cell.startswith('GE-'):
                title = cell
        if ge_id and ge_id != 'GE-ID':
            entries.append({'id': ge_id, 'title': title or ''})
    return entries


def get_domain_entries(garden: Path, domain: str) -> list:
    """Read all YAML-frontmatter entries from a domain directory."""
    domain_dir = garden / domain
    if not domain_dir.is_dir():
        return []
    entries = []
    for path in sorted(domain_dir.glob('*.md')):
        if path.name in SKIP_FILES or not GE_ID_RE.search(path.stem):
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except OSError:
            continue
        fm = parse_entry_frontmatter(content)
        if not fm.get('id'):
            continue
        entries.append({
            'id': fm.get('id', path.stem),
            'title': fm.get('title', ''),
            'type': fm.get('type', ''),
            'domain': fm.get('domain', domain),
            'stack': fm.get('stack', ''),
            'tags': fm.get('tags', []),
            'score': fm.get('score', 0),
            'submitted': fm.get('submitted', ''),
            'staleness_threshold': fm.get('staleness_threshold', 730),
            'verified_on': fm.get('verified_on', ''),
        })
    return entries


def build_garden_data(garden: Path) -> dict:
    """Build complete garden data dict for JSON output."""
    garden = Path(garden).expanduser().resolve()
    if not garden.exists():
        raise FileNotFoundError(f"Garden not found: {garden}")
    domains = []
    total = 0
    for d in sorted(garden.iterdir()):
        if not d.is_dir() or d.name in SKIP_DIRS or d.name.startswith('.'):
            continue
        entries = get_domain_entries(garden, d.name)
        if entries:
            domains.append({'name': d.name, 'entry_count': len(entries), 'entries': entries})
            total += len(entries)
    return {
        'domains': domains,
        'total_entries': total,
        'generated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def main():
    default = Path(
        os.environ.get('HORTORA_GARDEN', str(Path.home() / '.hortora' / 'garden'))
    ).expanduser().resolve()
    garden = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else default
    try:
        data = build_garden_data(garden)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(data, indent=2))


if __name__ == '__main__':
    main()
