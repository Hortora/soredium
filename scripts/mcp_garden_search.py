#!/usr/bin/env python3
"""mcp_garden_search.py — 3-tier knowledge garden retrieval.

All reads via git commands — never filesystem — for consistency with concurrent writes.
"""

import re
import subprocess
from pathlib import Path

GE_ID_RE = re.compile(r'GE-\d{8}-[0-9a-f]{6}|GE-\d{4}')
FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---', re.DOTALL)
TOKEN_RE = re.compile(r'\b[a-zA-Z]{3,}\b')
SKIP_FILES = {'GARDEN.md', 'CHECKED.md', 'DISCARDED.md', 'SCHEMA.md',
              'README.md', 'INDEX.md'}
SKIP_DIRS = {'.git', 'submissions', '_augment', '_summaries', '_index', 'labels'}


def keyword_score(query: str, text: str) -> int:
    """Count unique query tokens (>=3 chars) that appear in text (case-insensitive)."""
    if not query.strip():
        return 0
    q_tokens = set(TOKEN_RE.findall(query.lower()))
    t_tokens = set(TOKEN_RE.findall(text.lower()))
    return len(q_tokens & t_tokens)


def parse_garden_index(garden: Path) -> dict:
    """Read GARDEN.md By Technology section. Returns {tech_heading: [ge_id, ...]}."""
    try:
        content = subprocess.run(
            ['git', '-C', str(garden), 'show', 'HEAD:GARDEN.md'],
            capture_output=True, text=True, check=True
        ).stdout
    except subprocess.CalledProcessError:
        return {}

    m = re.search(r'## By Technology\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
    if not m:
        return {}

    result = {}
    current_tech = None
    for line in m.group(1).splitlines():
        h = re.match(r'^###\s+(.+)', line)
        if h:
            current_tech = h.group(1).strip()
            result[current_tech] = []
            continue
        if current_tech:
            ids = GE_ID_RE.findall(line)
            result[current_tech].extend(ids)

    return result


def fetch_entry_body(garden: Path, domain: str, ge_id: str) -> str | None:
    """Fetch entry body via git cat-file. Returns content or None."""
    try:
        result = subprocess.run(
            ['git', '-C', str(garden), 'cat-file', 'blob',
             f'HEAD:{domain}/{ge_id}.md'],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def _parse_frontmatter(content: str) -> dict:
    content = content.replace('\r\n', '\n')
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}
    result = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            k, _, v = line.partition(':')
            k = k.strip()
            v = v.strip().strip('"\'')
            if v.startswith('[') and v.endswith(']'):
                v = [x.strip().strip('"\'') for x in v[1:-1].split(',') if x.strip()]
            result[k] = v
    return result


def _entry_from_body(body: str, ge_id: str) -> dict:
    fm = _parse_frontmatter(body)
    return {
        'id': fm.get('id', ge_id),
        'title': fm.get('title', ''),
        'domain': fm.get('domain', ''),
        'score': int(fm.get('score', 0)) if str(fm.get('score', '0')).isdigit() else 0,
        'body': body,
        'tags': fm.get('tags', []),
        'submitted': fm.get('submitted', ''),
        'staleness_threshold': int(fm.get('staleness_threshold', 730))
            if str(fm.get('staleness_threshold', '730')).isdigit() else 730,
    }


def tier3_grep(garden: Path, query: str, domain: str = None) -> list:
    """Tier 3: git grep across committed .md files. Returns list of entry dicts."""
    if not query.strip():
        return []
    tokens = TOKEN_RE.findall(query.lower())
    if not tokens:
        return []

    pattern = '|'.join(re.escape(t) for t in tokens)
    # Build pathspec
    if domain:
        pathspecs = [f'{domain}/*.md']
    else:
        pathspecs = ['*.md']

    try:
        result = subprocess.run(
            ['git', '-C', str(garden), 'grep', '-il', '-E', pattern, 'HEAD', '--']
            + pathspecs,
            capture_output=True, text=True
        )
        if not result.stdout.strip():
            return []
    except Exception:
        return []

    entries = []
    seen = set()
    for line in result.stdout.splitlines():
        # Format: HEAD:domain/GE-XXXX.md
        m = re.match(r'HEAD:([^/]+)/(GE-[\w-]+)\.md', line)
        if not m:
            continue
        domain_part = m.group(1)
        ge_id = m.group(2)
        if domain_part in SKIP_DIRS or ge_id in seen:
            continue
        seen.add(ge_id)
        body = fetch_entry_body(garden, domain_part, ge_id)
        if body and FRONTMATTER_RE.match(body.replace('\r\n', '\n')):
            entry = _entry_from_body(body, ge_id)
            entry['relevance'] = keyword_score(query, body)
            entries.append(entry)

    entries.sort(key=lambda e: e.get('relevance', 0), reverse=True)
    return entries


def _list_all_entries(garden: Path) -> list:
    """Get all entry paths from committed state via git ls-tree."""
    try:
        result = subprocess.run(
            ['git', '-C', str(garden), 'ls-tree', '-r', '--name-only', 'HEAD'],
            capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError:
        return []
    entries = []
    for path in result.stdout.splitlines():
        parts = path.split('/')
        if len(parts) != 2:
            continue
        domain_dir, filename = parts
        if domain_dir in SKIP_DIRS or filename in SKIP_FILES:
            continue
        if not filename.endswith('.md'):
            continue
        ge_id = filename[:-3]
        if GE_ID_RE.fullmatch(ge_id):
            entries.append((domain_dir, ge_id))
    return entries


def search_garden(garden: Path, query: str,
                  technology: str = None, domain: str = None) -> list:
    """3-tier search. Returns list of entry dicts sorted by relevance."""
    if not query.strip():
        return []

    results = []

    if technology or domain:
        # Tier 1: get candidate GE-IDs from index
        index = parse_garden_index(garden)
        tech_key = (technology or domain).lower()
        candidate_ids = []
        for tech, ids in index.items():
            if tech_key in tech.lower() or tech.lower() in tech_key:
                candidate_ids.extend(ids)

        # Tier 2: fetch bodies and keyword-score
        # Find domain for each GE-ID via ls-tree
        all_entries = _list_all_entries(garden)
        id_to_domain = {ge_id: d for d, ge_id in all_entries}

        seen = set()
        for ge_id in candidate_ids:
            if ge_id in seen:
                continue
            seen.add(ge_id)
            d = id_to_domain.get(ge_id)
            if not d:
                # Try the explicit domain parameter
                d = domain or (technology.lower() if technology else None)
            if not d:
                continue
            body = fetch_entry_body(garden, d, ge_id)
            if not body:
                continue
            score = keyword_score(query, body)
            if score > 0:
                entry = _entry_from_body(body, ge_id)
                entry['relevance'] = score
                results.append(entry)

        results.sort(key=lambda e: e.get('relevance', 0), reverse=True)

        # Tier 3: fall back to grep if tier 2 found nothing
        if not results:
            results = tier3_grep(garden, query, domain=domain or
                                 (technology.lower() if technology else None))
    else:
        # No filter: tier 3 directly
        results = tier3_grep(garden, query)

    return results
