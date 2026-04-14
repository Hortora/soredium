#!/usr/bin/env python3
"""garden_config.py — Reads ~/.claude/garden-config.toml and resolves garden routing.

Usage:
  garden_config.py status [--config PATH]

Exit codes: 0 = ok, 1 = error
"""

import argparse
import re
import sys
import tomllib
from pathlib import Path

DEFAULT_CONFIG = Path.home() / '.claude' / 'garden-config.toml'
FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---', re.DOTALL)


def load_config(path: Path) -> list:
    """Load garden-config.toml. Returns list of {name, path} dicts."""
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, 'rb') as f:
        data = tomllib.load(f)
    return data.get('gardens', [])


def validate_config(gardens: list) -> tuple:
    """Validate garden list. Returns (errors, warnings)."""
    errors = []
    warnings = []
    seen_names = set()
    for i, g in enumerate(gardens):
        prefix = f"Garden {i+1}"
        if not g.get('name'):
            errors.append(f"{prefix}: 'name' is required")
        if not g.get('path'):
            errors.append(f"{prefix}: 'path' is required")
        name = g.get('name', '')
        if name and name in seen_names:
            errors.append(f"Duplicate garden name: {name!r}")
        if name:
            seen_names.add(name)
    return errors, warnings


def resolve_paths(gardens: list) -> list:
    """Return new list with ~ expanded in path fields."""
    return [
        {**g, 'path': str(Path(g['path']).expanduser())}
        for g in gardens
    ]


def _read_schema(garden_path) -> dict | None:
    """Read and parse SCHEMA.md frontmatter from a garden directory."""
    schema_path = Path(garden_path) / 'SCHEMA.md'
    if not schema_path.exists():
        return None
    content = schema_path.read_text(encoding='utf-8').replace('\r\n', '\n')
    m = FRONTMATTER_RE.match(content)
    if not m:
        return None
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
            items = []
            i += 1
            while i < len(lines) and re.match(r'^\s+-\s+', lines[i]):
                items.append(re.sub(r'^\s+-\s+', '', lines[i]).strip().strip('"\''))
                i += 1
            if items:
                result[key] = items
            continue
        elif rest.startswith('[') and rest.endswith(']'):
            result[key] = [v.strip().strip('"\'') for v in rest[1:-1].split(',') if v.strip()]
        else:
            result[key] = rest.strip('"\'')
        i += 1
    return result


def find_garden_for_domain(gardens: list, domain: str,
                            return_warnings: bool = False):
    """Find the garden that owns the given domain.

    Reads SCHEMA.md from each configured garden to find domain membership.
    Returns garden dict or None. With return_warnings=True returns (result, warnings).
    """
    matches = []
    for g in gardens:
        schema = _read_schema(g.get('path', ''))
        if schema is None:
            continue
        if domain in schema.get('domains', []):
            matches.append(g)

    warnings = []
    if len(matches) > 1:
        names = [m['name'] for m in matches]
        warnings.append(
            f"Domain {domain!r} claimed by multiple gardens: {', '.join(names)} — using first"
        )

    result = matches[0] if matches else None
    if return_warnings:
        return result, warnings
    return result


def get_upstream_chain(gardens: list, garden_path: Path) -> list:
    """Return ordered list of upstream garden Paths [immediate_parent, ..., canonical].

    Reads target garden's SCHEMA.md upstream URLs, maps to local paths via
    garden name (URL last segment match). Recursively walks the chain.
    Returns [] for canonical/peer gardens or when no upstream config found.
    """
    schema = _read_schema(garden_path)
    if schema is None or schema.get('role') != 'child':
        return []

    upstream_urls = schema.get('upstream', [])
    if not upstream_urls:
        return []

    name_to_path = {g['name']: Path(g['path']) for g in gardens}
    chain = []

    for url in upstream_urls:
        name = url.rstrip('/').split('/')[-1].removesuffix('.git')
        parent_path = name_to_path.get(name)
        if parent_path is None:
            continue
        chain.append(parent_path)
        chain.extend(get_upstream_chain(gardens, parent_path))

    return chain


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['status'])
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    try:
        gardens = load_config(args.config)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    errors, _ = validate_config(gardens)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        sys.exit(1)

    gardens = resolve_paths(gardens)

    if args.command == 'status':
        if not gardens:
            print("No gardens configured.")
            sys.exit(0)
        print(f"Configured gardens ({len(gardens)}):")
        for g in gardens:
            schema = _read_schema(g['path'])
            role = schema.get('role', 'unknown') if schema else 'no SCHEMA.md'
            domains = schema.get('domains', []) if schema else []
            print(f"  {g['name']}")
            print(f"    path:    {g['path']}")
            print(f"    role:    {role}")
            print(f"    domains: {', '.join(domains) if domains else '(none)'}")
        sys.exit(0)


if __name__ == '__main__':
    main()
