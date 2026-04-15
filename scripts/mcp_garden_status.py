#!/usr/bin/env python3
"""mcp_garden_status.py — Garden metadata for the MCP status tool."""

import re
import subprocess
from pathlib import Path

SKIP_FILES = {'GARDEN.md', 'CHECKED.md', 'DISCARDED.md', 'SCHEMA.md',
              'README.md', 'INDEX.md'}
SKIP_DIRS = {'.git', 'submissions', '_augment', '_summaries', '_index', 'labels'}


def parse_garden_md_metadata(garden: Path) -> dict:
    """Read metadata from GARDEN.md via git. Returns dict with defaults on failure."""
    defaults = {'drift': 0, 'threshold': 10, 'last_sweep': 'never',
                'last_staleness_review': 'never', 'name': ''}
    try:
        content = subprocess.run(
            ['git', '-C', str(garden), 'show', 'HEAD:GARDEN.md'],
            capture_output=True, text=True, check=True
        ).stdout
    except subprocess.CalledProcessError:
        return defaults

    def _int(pattern, text, default=0):
        m = re.search(pattern, text)
        return int(m.group(1)) if m else default

    def _str(pattern, text, default='never'):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else default

    return {
        'drift': _int(r'\*\*Entries merged since last sweep:\*\*\s*(\d+)', content),
        'threshold': _int(r'\*\*Drift threshold:\*\*\s*(\d+)', content, default=10),
        'last_sweep': _str(r'\*\*Last full DEDUPE sweep:\*\*\s*(.+)', content),
        'last_staleness_review': _str(r'\*\*Last staleness review:\*\*\s*(.+)', content),
        'name': _str(r'^#\s+(.+)', content, default=''),
    }


def count_entries(garden: Path) -> int:
    """Count committed YAML-frontmatter entry files via git ls-tree."""
    try:
        ls = subprocess.run(
            ['git', '-C', str(garden), 'ls-tree', '-r', '--name-only', 'HEAD'],
            capture_output=True, text=True, check=True
        ).stdout
    except subprocess.CalledProcessError:
        return 0

    count = 0
    for path in ls.splitlines():
        parts = path.split('/')
        if len(parts) < 2:
            continue
        domain_dir = parts[0]
        filename = parts[-1]
        if domain_dir in SKIP_DIRS or filename in SKIP_FILES:
            continue
        if not filename.endswith('.md'):
            continue
        # Check for YAML frontmatter via git show
        try:
            body = subprocess.run(
                ['git', '-C', str(garden), 'show', f'HEAD:{path}'],
                capture_output=True, text=True, check=True
            ).stdout
            if body.startswith('---\n') or body.startswith('---\r\n'):
                count += 1
        except subprocess.CalledProcessError:
            pass
    return count


def get_status(garden: Path) -> dict:
    """Return garden health summary dict."""
    garden = Path(garden).expanduser().resolve()
    if not garden.exists():
        raise FileNotFoundError(f"Garden not found: {garden}")

    meta = parse_garden_md_metadata(garden)
    entry_count = count_entries(garden)
    drift = meta['drift']
    threshold = meta['threshold']

    role = 'unknown'
    try:
        schema = subprocess.run(
            ['git', '-C', str(garden), 'show', 'HEAD:SCHEMA.md'],
            capture_output=True, text=True, check=True
        ).stdout
        m = re.search(r'^role:\s*(\w+)', schema, re.MULTILINE)
        if m:
            role = m.group(1)
    except subprocess.CalledProcessError:
        pass

    return {
        'name': meta['name'],
        'garden_path': str(garden),
        'entry_count': entry_count,
        'drift': drift,
        'threshold': threshold,
        'dedupe_recommended': drift >= threshold,
        'last_sweep': meta['last_sweep'],
        'last_staleness_review': meta['last_staleness_review'],
        'role': role,
    }
