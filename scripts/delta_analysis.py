"""Delta analysis — find new abstraction layers introduced between two git refs."""
import re
import subprocess
from pathlib import Path

_RE_INTERFACE = re.compile(r'\binterface\s+\w+')
_RE_ABSTRACT = re.compile(r'\babstract\s+class\s+\w+')
_SOURCE_EXTS = {'.java', '.kt', '.py'}


def get_major_version_tags(repo: Path) -> list[str]:
    result = subprocess.run(
        ['git', '-C', str(repo), 'tag', '--sort=version:refname'],
        capture_output=True, text=True, check=True,
    )
    return [t for t in result.stdout.splitlines() if t.strip()]


def _files_added_between(repo: Path, from_ref: str, to_ref: str) -> list[str]:
    if from_ref == to_ref:
        return []
    result = subprocess.run(
        ['git', '-C', str(repo), 'diff', '--name-status', from_ref, to_ref],
        capture_output=True, text=True, check=True,
    )
    added = []
    for line in result.stdout.splitlines():
        parts = line.split('\t', 1)
        if len(parts) == 2 and parts[0] == 'A':
            path = parts[1].strip()
            if Path(path).suffix in _SOURCE_EXTS:
                added.append(path)
    return added


def _file_content_at(repo: Path, ref: str, filepath: str) -> str:
    try:
        result = subprocess.run(
            ['git', '-C', str(repo), 'show', f'{ref}:{filepath}'],
            capture_output=True, text=True, check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return ''


def _blame_info(repo: Path, to_ref: str, filepath: str) -> dict:
    try:
        result = subprocess.run(
            ['git', '-C', str(repo), 'log', '-1', '--format=%H|%ae|%ad',
             '--date=short', to_ref, '--', filepath],
            capture_output=True, text=True, check=True,
        )
        parts = result.stdout.strip().split('|')
        if len(parts) == 3:
            return {'commit': parts[0][:7], 'author': parts[1], 'date': parts[2]}
    except subprocess.CalledProcessError:
        pass
    return {'commit': 'unknown', 'author': 'unknown', 'date': 'unknown'}


def delta_analysis(repo: Path, from_ref: str, to_ref: str) -> list[dict]:
    repo = Path(repo)
    added_files = _files_added_between(repo, from_ref, to_ref)
    candidates = []

    for filepath in added_files:
        content = _file_content_at(repo, to_ref, filepath)
        if not content:
            continue

        kind = None
        if _RE_INTERFACE.search(content):
            kind = 'interface'
        elif _RE_ABSTRACT.search(content):
            kind = 'abstract_class'

        if kind:
            blame = _blame_info(repo, to_ref, filepath)
            candidates.append({
                'file': filepath,
                'kind': kind,
                'introduced_at': to_ref,
                **blame,
            })

    return candidates
