#!/usr/bin/env python3
"""init_garden.py — Initialize a new Hortora knowledge garden.

Creates GARDEN.md, SCHEMA.md, CHECKED.md, DISCARDED.md, domain directories
with INDEX.md, and .github/workflows/validate_pr.yml.

Usage:
  init_garden.py <garden_path> --name NAME --description DESC \\
    --role canonical|child|peer --ge-prefix PREFIX \\
    --domains DOMAIN [DOMAIN ...] \\
    [--upstream URL [URL ...]]
"""

import argparse
import sys
from datetime import date
from pathlib import Path

TODAY = date.today().isoformat()


def create_garden_md(root: Path, name: str, ge_prefix: str) -> None:
    path = root / 'GARDEN.md'
    if path.exists():
        return
    path.write_text(
        f'# {name}\n\n'
        f'**Last assigned ID:** GE-0000\n'
        f'**Last full DEDUPE sweep:** {TODAY}\n'
        f'Entries merged since last sweep: 0\n'
        f'**Drift threshold:** 10\n'
        f'**Last staleness review:** never\n'
        f'\n## By Technology\n\n---\n\n'
        f'## By Symptom / Type\n\n---\n\n'
        f'## By Label\n\n---\n',
        encoding='utf-8',
    )


def create_schema_md(root: Path, name: str, description: str, role: str,
                     ge_prefix: str, domains: list, upstream: list = None) -> None:
    path = root / 'SCHEMA.md'
    if path.exists():
        return
    lines = [
        '---',
        f'name: {name}',
        f'description: "{description}"',
        f'role: {role}',
        f'ge_prefix: {ge_prefix}',
        'schema_version: "1.0"',
        f'domains: [{", ".join(domains)}]',
    ]
    if upstream:
        lines.append('upstream:')
        for url in upstream:
            lines.append(f'  - {url}')
    lines.extend(['---', ''])
    path.write_text('\n'.join(lines), encoding='utf-8')


def create_checked_md(root: Path) -> None:
    path = root / 'CHECKED.md'
    if path.exists():
        return
    path.write_text(
        '# Garden Duplicate Check Log\n\n'
        '| Pair | Result | Date | Notes |\n'
        '|------|--------|------|-------|\n',
        encoding='utf-8',
    )


def create_discarded_md(root: Path) -> None:
    path = root / 'DISCARDED.md'
    if path.exists():
        return
    path.write_text(
        '# Discarded Submissions\n\n'
        '| Discarded | Conflicts With | Date | Reason |\n'
        '|-----------|----------------|------|--------|\n',
        encoding='utf-8',
    )


def create_domain(root: Path, domain: str) -> None:
    domain_dir = root / domain
    domain_dir.mkdir(parents=True, exist_ok=True)
    index = domain_dir / 'INDEX.md'
    if index.exists():
        return
    index.write_text(
        f'# {domain.capitalize()} Index\n\n'
        '| GE-ID | Title | Type | Score | Submitted |\n'
        '|-------|-------|------|-------|-----------|\n',
        encoding='utf-8',
    )


def create_ci_workflow(root: Path) -> None:
    workflows_dir = root / '.github' / 'workflows'
    workflows_dir.mkdir(parents=True, exist_ok=True)
    workflow = workflows_dir / 'validate_pr.yml'
    if workflow.exists():
        return
    workflow.write_text(
        'name: Validate Garden Entry PR\n'
        '\n'
        'on:\n'
        '  pull_request:\n'
        '    branches: [main]\n'
        '\n'
        'jobs:\n'
        '  validate:\n'
        '    runs-on: ubuntu-latest\n'
        '    steps:\n'
        '      - uses: actions/checkout@v4\n'
        '        with:\n'
        '          fetch-depth: 0\n'
        '\n'
        '      - name: Set up Python\n'
        '        uses: actions/setup-python@v5\n'
        '        with:\n'
        '          python-version: "3.11"\n'
        '\n'
        '      - name: Validate PR\n'
        '        run: |\n'
        '          curl -sSL https://raw.githubusercontent.com/Hortora/soredium/main/scripts/validate_pr.py \\\n'
        '            -o validate_pr.py\n'
        '          python3 validate_pr.py\n',
        encoding='utf-8',
    )


def create_augment_dir(root: Path) -> None:
    """Create _augment/ directory with README.md for child gardens."""
    augment_dir = root / '_augment'
    augment_dir.mkdir(exist_ok=True)
    readme = augment_dir / 'README.md'
    if readme.exists():
        return
    readme.write_text(
        '# _augment/\n\n'
        'Private annotations on parent garden entries.\n\n'
        'Each file augments a single parent entry without modifying it.\n\n'
        '## Format\n\n'
        '```yaml\n'
        '---\n'
        'target: GE-20260414-aabbcc\n'
        'target_garden: jvm-garden\n'
        'augment_type: context   # context | correction | update\n'
        'submitted: YYYY-MM-DD\n'
        '---\n\n'
        '## Private context for GE-20260414-aabbcc\n\n'
        '[Your private notes here]\n'
        '```\n',
        encoding='utf-8',
    )


def init_garden(root: Path, name: str, description: str, role: str,
                ge_prefix: str, domains: list, upstream: list = None) -> list:
    """Initialize a garden. Idempotent — skips files that already exist.
    Returns list of created file paths relative to root."""
    root.mkdir(parents=True, exist_ok=True)
    created = []

    for fn, args, kwargs in [
        (create_garden_md,    [root, name, ge_prefix], {}),
        (create_schema_md,    [root, name, description, role, ge_prefix, domains],
                              {'upstream': upstream}),
        (create_checked_md,   [root], {}),
        (create_discarded_md, [root], {}),
        (create_ci_workflow,  [root], {}),
    ]:
        before = set(root.rglob('*'))
        fn(*args, **kwargs)
        after = set(root.rglob('*'))
        created.extend(str(p.relative_to(root)) for p in sorted(after - before))

    for domain in domains:
        before = set(root.rglob('*'))
        create_domain(root, domain)
        after = set(root.rglob('*'))
        created.extend(str(p.relative_to(root)) for p in sorted(after - before))

    if role == 'child':
        before = set(root.rglob('*'))
        create_augment_dir(root)
        after = set(root.rglob('*'))
        created.extend(str(p.relative_to(root)) for p in sorted(after - before))

    return created


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('garden_path')
    parser.add_argument('--name', required=True)
    parser.add_argument('--description', required=True)
    parser.add_argument('--role', required=True, choices=['canonical', 'child', 'peer'])
    parser.add_argument('--ge-prefix', required=True, dest='ge_prefix')
    parser.add_argument('--domains', required=True, nargs='+')
    parser.add_argument('--upstream', nargs='+', default=None)

    args = parser.parse_args()
    root = Path(args.garden_path).expanduser().resolve()

    created = init_garden(
        root=root, name=args.name, description=args.description,
        role=args.role, ge_prefix=args.ge_prefix,
        domains=args.domains, upstream=args.upstream,
    )

    if created:
        print(f"Initialized garden at {root}:")
        for f in created:
            print(f"  Created: {f}")
    else:
        print(f"Garden already exists at {root} — nothing created.")

    print(f"\nNext: cd {root} && git init && git add . && git commit -m 'init: {args.name}'")
    sys.exit(0)


if __name__ == '__main__':
    main()
