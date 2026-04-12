#!/usr/bin/env python3
"""integrate_entry.py — Update all garden indexes after a PR is merged."""

import sys
import json
import subprocess
from pathlib import Path

try:
    import yaml
except ImportError:
    print(json.dumps({'error': 'PyYAML not installed: pip install pyyaml'}))
    sys.exit(1)


def parse_entry(path: Path) -> tuple:
    content = path.read_text(encoding='utf-8')
    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}, content.strip()  # no YAML frontmatter — legacy markdown-style entry
    return yaml.safe_load(parts[1]) or {}, parts[2].strip()


def generate_summary(fm: dict, ge_id: str) -> str:
    title = fm.get('title', '')
    entry_type = fm.get('type', '')
    score = fm.get('score', '')
    tags = ', '.join(fm.get('tags', [])[:3])
    return f"{ge_id}: [{entry_type}, {score}/15] {title} | {tags}\n"


def update_summaries(domain: str, ge_id: str, fm: dict, garden: Path):
    out = garden / '_summaries' / domain
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{ge_id}.md").write_text(generate_summary(fm, ge_id), encoding='utf-8')


def update_domain_index(domain: str, ge_id: str, fm: dict, garden: Path):
    index = garden / domain / 'INDEX.md'
    with open(index, 'a', encoding='utf-8') as f:
        f.write(f"| {ge_id} | {fm.get('title', '')} | {fm.get('type', '')} | {fm.get('score', '')}/15 |\n")


def update_labels(fm: dict, ge_id: str, garden: Path):
    labels = garden / 'labels'
    labels.mkdir(exist_ok=True)
    for tag in fm.get('tags', []):
        with open(labels / f"{tag}.md", 'a', encoding='utf-8') as f:
            f.write(f"- {ge_id}: {fm.get('title', '')}\n")


def update_global_index(domain: str, garden: Path):
    global_index = garden / '_index' / 'global.md'
    content = global_index.read_text(encoding='utf-8') if global_index.exists() else ''
    if domain not in content:
        with open(global_index, 'a', encoding='utf-8') as f:
            f.write(f"| {domain} | {domain}/INDEX.md |\n")


def run_validate(garden: Path):
    script = Path(__file__).parent / 'validate_garden.py'
    subprocess.run(
        ['python3', str(script), '--structural', str(garden)],
        check=True
    )


def git_commit(garden: Path, ge_id: str):
    subprocess.run(['git', '-C', str(garden), 'add', '_summaries/', '_index/', 'labels/'], check=True)
    subprocess.run(['git', '-C', str(garden), 'add', '--update'], check=True)
    subprocess.run(
        ['git', '-C', str(garden), 'commit', '-m', f'index: integrate {ge_id}'],
        check=True
    )


def integrate(entry_path: str, garden_root: str = None) -> dict:
    path = Path(entry_path)
    garden = Path(garden_root) if garden_root else path.parent.parent
    fm, _ = parse_entry(path)
    domain = fm.get('domain', '')
    ge_id = fm.get('id') or path.stem  # frontmatter id wins; filename stem is fallback only

    update_summaries(domain, ge_id, fm, garden)
    update_domain_index(domain, ge_id, fm, garden)
    update_labels(fm, ge_id, garden)
    update_global_index(domain, garden)

    run_validate(garden)
    git_commit(garden, ge_id)

    return {'status': 'ok', 'ge_id': ge_id, 'domain': domain}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: integrate_entry.py <entry_file> [garden_root]'}))
        sys.exit(1)
    result = integrate(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else None,
    )
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
