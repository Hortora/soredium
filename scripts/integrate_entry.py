#!/usr/bin/env python3
"""integrate_entry.py — Update all garden indexes after a PR is merged."""

import re
import json
import subprocess
from pathlib import Path

try:
    import yaml
except ImportError:
    print(json.dumps({'error': 'PyYAML not installed: pip install pyyaml'}))
    exit(1)


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


def upsert_entry_index(garden: Path, entry_path: Path, domain: str) -> None:
    """Upsert entry metadata into entries_index. Errors are swallowed — never block integration."""
    import re as _re
    _FM_RE = _re.compile(r'^---\n(.*?)\n---', _re.DOTALL)
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from garden_db import upsert_entry, init_db
        db_path = Path(garden) / 'garden.db'
        if not db_path.exists():
            init_db(Path(garden))
        content = Path(entry_path).read_text(encoding='utf-8').replace('\r\n', '\n')
        m = _FM_RE.match(content)
        if not m:
            return
        fm = m.group(1)

        def _get(key, default=''):
            mm = _re.search(rf'^{key}:\s*(.+)$', fm, _re.MULTILINE)
            return mm.group(1).strip().strip('"\'') if mm else default

        tags_raw = _get('tags', '[]')
        tags = [t.strip().strip('"\'') for t in tags_raw.strip('[]').split(',') if t.strip()]
        score_s = _get('score', '0')
        thresh_s = _get('staleness_threshold', '730')
        ge_id = _get('id') or Path(entry_path).stem

        upsert_entry(Path(garden), {
            'ge_id': ge_id,
            'title': _get('title'),
            'domain': _get('domain', domain),
            'type': _get('type', 'gotcha'),
            'score': int(score_s) if score_s.isdigit() else 0,
            'submitted': _get('submitted'),
            'staleness_threshold': int(thresh_s) if thresh_s.isdigit() else 730,
            'tags': tags,
            'verified_on': _get('verified_on'),
            'last_reviewed': _get('last_reviewed'),
            'file_path': f"{domain}/{Path(entry_path).name}",
        })
    except Exception:
        pass  # index failure never blocks integration


def update_garden_by_technology(domain: str, ge_id: str, fm: dict, garden: Path):
    """Add entry to the By Technology section of GARDEN.md."""
    garden_md = garden / 'GARDEN.md'
    if not garden_md.exists():
        return
    content = garden_md.read_text(encoding='utf-8')

    by_tech = re.search(r'^## By Technology\n', content, re.MULTILINE)
    if not by_tech:
        return

    title = fm.get('title', '')
    entry_line = f"- {ge_id} [{title}]({domain}/{ge_id}.md)\n"
    domain_header = f"### {domain}/\n"

    by_tech_body_start = by_tech.end()
    next_h2 = re.search(r'^## ', content[by_tech_body_start:], re.MULTILINE)
    by_tech_body_end = by_tech_body_start + (next_h2.start() if next_h2 else len(content) - by_tech_body_start)
    by_tech_body = content[by_tech_body_start:by_tech_body_end]

    if domain_header in by_tech_body:
        domain_pos = by_tech_body.index(domain_header)
        after_header = domain_pos + len(domain_header)
        next_domain = re.search(r'^### ', by_tech_body[after_header:], re.MULTILINE)
        if next_domain:
            insert_in_body = after_header + next_domain.start()
        else:
            sep = re.search(r'\n\n---\n', by_tech_body[after_header:])
            if sep:
                insert_in_body = after_header + sep.start() + 1
            else:
                insert_in_body = len(by_tech_body)
    else:
        sep = re.search(r'\n\n---\n', by_tech_body)
        insert_in_body = sep.start() + 1 if sep else len(by_tech_body)
        entry_line = domain_header + entry_line

    garden_md.write_text(content[:by_tech_body_start + insert_in_body] + entry_line + content[by_tech_body_start + insert_in_body:])


def increment_drift_counter(garden: Path):
    """Increment 'Entries merged since last sweep' in GARDEN.md by 1."""
    garden_md = garden / 'GARDEN.md'
    if not garden_md.exists():
        return
    content = garden_md.read_text(encoding='utf-8')
    def _inc(m):
        return f'**Entries merged since last sweep:** {int(m.group(1)) + 1}'
    new_content = re.sub(
        r'\*\*Entries merged since last sweep:\*\*\s*(\d+)',
        _inc,
        content
    )
    if new_content != content:
        garden_md.write_text(new_content, encoding='utf-8')


def run_validate(garden: Path):
    script = Path(__file__).parent / 'validate_garden.py'
    subprocess.run(
        ['python3', str(script), '--structural', str(garden)],
        check=True
    )


def git_commit(garden: Path, ge_id: str):
    subprocess.run(['git', '-C', str(garden), 'add', '_summaries/', '_index/', 'labels/', 'GARDEN.md'], check=True)
    subprocess.run(['git', '-C', str(garden), 'add', '--update'], check=True)
    subprocess.run(
        ['git', '-C', str(garden), 'commit', '-m', f'index: integrate {ge_id}'],
        check=True
    )


def integrate(entry_path: str, garden_root: str = None,
              skip_validate: bool = False, skip_commit: bool = False) -> dict:
    path = Path(entry_path)
    garden = Path(garden_root) if garden_root else path.parent.parent
    fm, _ = parse_entry(path)
    domain = fm.get('domain', '')
    ge_id = fm.get('id') or path.stem  # frontmatter id wins; filename stem is fallback only

    update_summaries(domain, ge_id, fm, garden)
    update_domain_index(domain, ge_id, fm, garden)
    update_labels(fm, ge_id, garden)
    update_global_index(domain, garden)
    update_garden_by_technology(domain, ge_id, fm, garden)
    increment_drift_counter(garden)
    upsert_entry_index(garden, path, domain)
    if not skip_validate:
        run_validate(garden)
    if not skip_commit:
        git_commit(garden, ge_id)

    return {'status': 'ok', 'ge_id': ge_id, 'domain': domain}


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Update all garden indexes after an entry is submitted.'
    )
    parser.add_argument('entry_file', help='Path to the garden entry file')
    parser.add_argument('garden_root', nargs='?',
                        help='Path to the garden root (default: parent.parent of entry_file)')
    parser.add_argument('--skip-validate', action='store_true',
                        help='Skip structural validation (already done by validate_pr.py)')
    parser.add_argument('--skip-commit', action='store_true',
                        help='Update indexes on disk without committing (caller handles commit)')
    args = parser.parse_args()
    result = integrate(
        args.entry_file,
        args.garden_root,
        skip_validate=args.skip_validate,
        skip_commit=args.skip_commit,
    )
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
