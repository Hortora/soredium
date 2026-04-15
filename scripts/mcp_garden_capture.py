#!/usr/bin/env python3
"""mcp_garden_capture.py — Entry submission for the MCP capture tool."""

import secrets
import subprocess
from datetime import date
from pathlib import Path

VALID_TYPES = {'gotcha', 'technique', 'undocumented'}
MIN_SCORE = 8
TODAY = date.today().isoformat()
DATE_COMPACT = date.today().strftime('%Y%m%d')


def generate_ge_id() -> str:
    """Generate a GE-YYYYMMDD-xxxxxx ID."""
    return f'GE-{DATE_COMPACT}-{secrets.token_hex(3)}'


def validate_capture_args(title: str, type: str, domain: str, stack: str,
                           tags: list, score: int, body: str) -> list:
    """Validate capture arguments. Returns list of error strings."""
    errors = []
    if not title.strip():
        errors.append("'title' is required and must be non-empty")
    if type not in VALID_TYPES:
        errors.append(f"'type' must be one of: {', '.join(sorted(VALID_TYPES))}")
    if not domain.strip():
        errors.append("'domain' is required")
    if score < MIN_SCORE:
        errors.append(f"'score' must be >= {MIN_SCORE} (got {score})")
    if not body.strip():
        errors.append("'body' is required")
    return errors


def build_entry_content(ge_id: str, title: str, type: str, domain: str,
                         stack: str, tags: list, score: int, body: str) -> str:
    """Build the full markdown content for a new entry."""
    tag_str = ', '.join(tags) if tags else ''
    return (
        f'---\n'
        f'id: {ge_id}\n'
        f'title: "{title}"\n'
        f'type: {type}\n'
        f'domain: {domain}\n'
        f'stack: "{stack}"\n'
        f'tags: [{tag_str}]\n'
        f'score: {score}\n'
        f'verified: true\n'
        f'staleness_threshold: 730\n'
        f'submitted: {TODAY}\n'
        f'---\n\n'
        f'## {title}\n\n'
        f'**ID:** {ge_id}\n'
        f'**Stack:** {stack}\n\n'
        f'{body}\n'
        f'\n*Score: {score}/15 · Submitted via garden_capture MCP tool*\n'
    )


def capture_entry(garden: Path, title: str, type: str, domain: str,
                  stack: str, tags: list, score: int, body: str) -> dict:
    """Create a new entry on a submit branch. Returns result dict."""
    garden = Path(garden).expanduser().resolve()

    errors = validate_capture_args(title, type, domain, stack, tags, score, body)
    if errors:
        return {'status': 'error', 'errors': errors, 'message': '; '.join(errors)}

    ge_id = generate_ge_id()
    branch = f'submit/{ge_id}'

    # Remember current branch
    try:
        current = subprocess.run(
            ['git', '-C', str(garden), 'branch', '--show-current'],
            capture_output=True, text=True, check=True
        ).stdout.strip() or 'main'
    except subprocess.CalledProcessError:
        current = 'main'

    try:
        subprocess.run(
            ['git', '-C', str(garden), 'checkout', '-b', branch],
            check=True, capture_output=True
        )

        domain_dir = garden / domain
        domain_dir.mkdir(exist_ok=True)
        entry_path = domain_dir / f'{ge_id}.md'
        entry_path.write_text(
            build_entry_content(ge_id, title, type, domain, stack, tags, score, body),
            encoding='utf-8'
        )

        subprocess.run(['git', '-C', str(garden), 'add', str(entry_path)],
                       check=True, capture_output=True)
        subprocess.run(
            ['git', '-C', str(garden), 'commit', '-m',
             f'submit({ge_id}): {title[:60]}'],
            check=True, capture_output=True
        )

        subprocess.run(
            ['git', '-C', str(garden), 'checkout', current],
            check=True, capture_output=True
        )

        return {
            'status': 'ok',
            'ge_id': ge_id,
            'branch': branch,
            'message': (
                f'Entry {ge_id} created on branch {branch}. '
                f'Open a PR to merge into the garden.'
            ),
        }

    except subprocess.CalledProcessError as e:
        try:
            subprocess.run(['git', '-C', str(garden), 'checkout', current],
                           capture_output=True)
        except Exception:
            pass
        return {
            'status': 'error',
            'errors': [str(e)],
            'message': f'Git operation failed: {e}',
        }
