#!/usr/bin/env python3
"""augment_entry.py — Create and manage private augmentations of parent garden entries.

Usage:
  augment_entry.py create GE-XXXX --garden GARDEN --type TYPE --content TEXT [--augment-dir DIR]
  augment_entry.py list [--augment-dir DIR]
  augment_entry.py validate PATH

augment_type: context | correction | update
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

VALID_TYPES = {'context', 'correction', 'update'}
FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---', re.DOTALL)
TODAY = date.today().isoformat()


def create_augmentation(augment_dir: Path, target_id: str, target_garden: str,
                        augment_type: str, content: str) -> Path:
    """Write an augmentation file. Returns the created path."""
    path = augment_dir / f'{target_id}.md'
    path.write_text(
        f'---\n'
        f'target: {target_id}\n'
        f'target_garden: {target_garden}\n'
        f'augment_type: {augment_type}\n'
        f'submitted: {TODAY}\n'
        f'---\n\n'
        f'## Private context for {target_id}\n\n'
        f'{content}\n',
        encoding='utf-8',
    )
    return path


def _parse_frontmatter(content: str) -> dict | None:
    content = content.replace('\r\n', '\n')
    m = FRONTMATTER_RE.match(content)
    if not m:
        return None
    result = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            key, _, val = line.partition(':')
            result[key.strip()] = val.strip().strip('"\'')
    return result


def list_augmentations(augment_dir: Path) -> list:
    """Return list of dicts for all augmentation files in augment_dir."""
    results = []
    for p in sorted(augment_dir.glob('*.md')):
        if p.name == 'README.md':
            continue
        fm = _parse_frontmatter(p.read_text(encoding='utf-8'))
        if fm is None:
            continue
        results.append({
            'target': fm.get('target', ''),
            'target_garden': fm.get('target_garden', ''),
            'augment_type': fm.get('augment_type', ''),
            'submitted': fm.get('submitted', ''),
            'path': p,
        })
    return results


def validate_augmentation(path: Path) -> tuple:
    """Validate an augmentation file. Returns (errors, warnings)."""
    errors = []
    warnings = []
    content = path.read_text(encoding='utf-8')
    fm = _parse_frontmatter(content)
    if fm is None:
        errors.append("No YAML frontmatter found")
        return errors, warnings
    if not fm.get('target'):
        errors.append("'target' is required (the parent entry GE-ID)")
    if not fm.get('target_garden'):
        errors.append("'target_garden' is required (name of the parent garden)")
    aug_type = fm.get('augment_type', '')
    if not aug_type:
        errors.append("'augment_type' is required")
    elif aug_type not in VALID_TYPES:
        errors.append(
            f"'augment_type' is {aug_type!r} — must be one of: {', '.join(sorted(VALID_TYPES))}"
        )
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    create_p = sub.add_parser('create')
    create_p.add_argument('target_id')
    create_p.add_argument('--garden', required=True, dest='target_garden')
    create_p.add_argument('--type', required=True, dest='augment_type',
                          choices=sorted(VALID_TYPES))
    create_p.add_argument('--content', required=True)
    create_p.add_argument('--augment-dir', type=Path, default=Path('_augment'))

    list_p = sub.add_parser('list')
    list_p.add_argument('--augment-dir', type=Path, default=Path('_augment'))

    validate_p = sub.add_parser('validate')
    validate_p.add_argument('path', type=Path)

    args = parser.parse_args()

    if args.command == 'create':
        path = create_augmentation(
            args.augment_dir, args.target_id,
            args.target_garden, args.augment_type, args.content
        )
        print(f"Created: {path}")
        sys.exit(0)

    elif args.command == 'list':
        augmentations = list_augmentations(args.augment_dir)
        if not augmentations:
            print(f"0 augmentations in {args.augment_dir}")
        else:
            print(f"{len(augmentations)} augmentation(s):")
            for a in augmentations:
                print(f"  {a['target']} ({a['augment_type']}) <- {a['target_garden']}")
        sys.exit(0)

    elif args.command == 'validate':
        errors, warnings = validate_augmentation(args.path)
        for w in warnings:
            print(f"WARNING: {w}")
        if errors:
            for e in errors:
                print(f"ERROR: {e}")
            sys.exit(1)
        print(f"valid: {args.path.name} is valid")
        sys.exit(0)


if __name__ == '__main__':
    main()
