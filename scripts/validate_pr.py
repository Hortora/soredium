#!/usr/bin/env python3
"""validate_pr.py — Validate a garden entry before PR merge.

Exits 0 (pass, may have warnings), 1 (CRITICAL failure).
Outputs structured JSON to stdout only — does NOT call gh API.
"""

import sys
import json
import re
import subprocess
import argparse as _argparse
from pathlib import Path

# Parse --upstream-garden flags before any other processing, strip them from sys.argv
# so the rest of the script sees only the positional arguments it expects.
_up_parser = _argparse.ArgumentParser(add_help=False)
_up_parser.add_argument('--upstream-garden', action='append', dest='upstream_gardens',
                        metavar='PATH', default=[])
_up_known, _up_remaining = _up_parser.parse_known_args()
_UPSTREAM_GARDENS = [Path(p).expanduser().resolve() for p in _up_known.upstream_gardens]
sys.argv = [sys.argv[0]] + _up_remaining

try:
    import yaml
except ImportError:
    print(json.dumps({'criticals': ['PyYAML not installed: pip install pyyaml']}))
    sys.exit(1)

REQUIRED_FIELDS = [
    'title', 'type', 'domain', 'score', 'tags', 'verified', 'staleness_threshold'
]
SCORE_MIN = 8
SCORE_AUTO_APPROVE = 12
JACCARD_WARNING = 0.4
JACCARD_INFO = 0.2
INJECTION_PATTERNS = [
    r'ignore (?:previous|above|all) instructions?',
    r'you are (?:now )?(?:an? )?(?:different|new|evil|unrestricted)',
    r'\bsystem prompt\b',
    r'disregard (?:your|the|all)',
    r'pretend (?:you are|to be)',
    r'\broleplay as\b',
    r'\bjailbreak\b',
]

BONUS_RULES = {
    'constraints':             1,  # +1 if constraints field present (string or list, non-empty)
    'alternatives_considered': 1,  # +1 if ### Alternatives considered has ≥1 list item
    'invalidation_triggers':   1,  # +1 if invalidation_triggers field present (string or list, non-empty)
}

GARDEN_DEFAULT = 'discovery'

GARDEN_TYPES = {
    'discovery': {
        'valid_types': ['gotcha', 'technique', 'undocumented'],
        'required_extra': [],
        'staleness_default': 730,
    },
    'patterns': {
        'valid_types': ['architectural', 'migration', 'integration', 'testing'],
        'required_extra': [],
        'staleness_default': 3650,
    },
    'examples': {
        'valid_types': ['code'],
        'required_extra': [],
        'staleness_default': 1095,
    },
    'evolution': {
        'valid_types': ['breaking', 'deprecation', 'capability'],
        'required_extra': ['changed_in'],
        'staleness_default': 1095,
    },
    'risk': {
        'valid_types': ['failure-mode', 'antipattern', 'incident'],
        'required_extra': ['severity'],
        'staleness_default': 1825,
    },
    'decisions': {
        'valid_types': ['architecture', 'technology', 'process'],
        'required_extra': [],
        'staleness_default': 3650,
    },
}


def compute_bonus(fm: dict, body: str) -> dict:
    """Return {field_name: bool} for each bonus rule. True = bonus earned."""
    results = {}

    # constraints: present and non-empty (string or list)
    constraints = fm.get('constraints')
    results['constraints'] = bool(constraints) if constraints is not None else False

    # alternatives_considered: heading + ≥1 list item in that section
    heading_match = re.search(
        r'^###\s+Alternatives considered\s*\n((?:(?!^###).)*)',
        body, re.MULTILINE | re.IGNORECASE | re.DOTALL
    )
    if heading_match:
        section = heading_match.group(1)
        results['alternatives_considered'] = bool(
            re.search(r'^\s*-\s+\S', section, re.MULTILINE)
        )
    else:
        results['alternatives_considered'] = False

    # invalidation_triggers: present and non-empty (string or list)
    triggers = fm.get('invalidation_triggers')
    results['invalidation_triggers'] = bool(triggers) if triggers is not None else False

    return results


def bonus_points(bonus_results: dict) -> int:
    """Sum bonus points from detection results using BONUS_RULES."""
    return sum(BONUS_RULES.get(k, 0) for k, present in bonus_results.items() if present)


def parse_entry(path: Path) -> tuple:
    """Return (frontmatter_dict, body_str, raw_content). Raises on parse failure."""
    content = path.read_text(encoding='utf-8')
    if not content.startswith('---'):
        raise ValueError("No YAML frontmatter")
    parts = content.split('---', 2)
    if len(parts) < 3:
        raise ValueError("Incomplete frontmatter — missing closing '---'")
    return yaml.safe_load(parts[1]) or {}, parts[2].strip(), content


def check_injection(content: str) -> list:
    return [
        f"Injection pattern detected: '{p}'"
        for p in INJECTION_PATTERNS
        if re.search(p, content, re.IGNORECASE)
    ]


VALID_AUTHOR_ROLES = {'originator', 'adopter', 'innovator'}
VALID_STABILITY = {'low', 'medium', 'high'}


def validate_patterns_extended(fm: dict) -> list:
    """Return warning strings for malformed optional patterns-garden fields."""
    warnings = []

    # observed_in: must be a list; each item must have 'project'
    observed_in = fm.get('observed_in')
    if observed_in is not None:
        if not isinstance(observed_in, list):
            warnings.append("observed_in must be a list of project dicts")
        else:
            for i, item in enumerate(observed_in):
                if not isinstance(item, dict) or 'project' not in item:
                    warnings.append(
                        f"observed_in[{i}] missing required 'project' key"
                    )

    # authors: must be a list; each item must have github_handle and valid role
    authors = fm.get('authors')
    if authors is not None:
        if not isinstance(authors, list):
            warnings.append("authors must be a list of dicts")
        else:
            for i, item in enumerate(authors):
                if not isinstance(item, dict):
                    warnings.append(f"authors[{i}] must be a dict")
                    continue
                if 'github_handle' not in item:
                    warnings.append(f"authors[{i}] missing required 'github_handle'")
                role = item.get('role')
                if role is None:
                    warnings.append(
                        f"authors[{i}] missing required 'role' "
                        f"(valid: {sorted(VALID_AUTHOR_ROLES)})"
                    )
                elif role not in VALID_AUTHOR_ROLES:
                    warnings.append(
                        f"authors[{i}] invalid role '{role}' "
                        f"(valid: {sorted(VALID_AUTHOR_ROLES)})"
                    )

    return warnings


def tokenise(text: str) -> set:
    return set(re.findall(r'\b[a-z]{3,}\b', text.lower()))


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def scan_domain(domain: str, garden_root: Path, exclude_stem: str) -> list:
    """Return [(stem, token_set)] for existing entries in domain."""
    results = []
    domain_path = garden_root / domain
    if not domain_path.exists():
        return results
    for f in domain_path.glob('GE-*.md'):
        if f.stem == exclude_stem:
            continue
        try:
            fm, _, _raw = parse_entry(f)
            text = f"{fm.get('title', '')} {' '.join(fm.get('tags', []))} {fm.get('summary', '')}"
            results.append((f.stem, tokenise(text)))
        except Exception:
            continue
    return results


def detect_mode(garden_root: str) -> str:
    """Return 'github' or 'local' based on git remote URL."""
    try:
        result = subprocess.run(
            ['git', '-C', garden_root, 'remote', 'get-url', 'origin'],
            capture_output=True, text=True
        )
        if result.returncode == 0 and 'github.com' in result.stdout:
            return 'github'
    except Exception:
        pass
    return 'local'


def validate(entry_path: str, garden_root: str = None, upstream_gardens: list = None) -> dict:
    result = {'file': entry_path, 'criticals': [], 'warnings': [], 'infos': []}
    path = Path(entry_path)

    try:
        fm, body, raw_content = parse_entry(path)
    except FileNotFoundError:
        result['criticals'].append(f"File not found: {entry_path}")
        return result
    except Exception as e:
        result['criticals'].append(f"YAML parse error: {e}")
        return result

    for field in REQUIRED_FIELDS:
        if field not in fm:
            result['criticals'].append(f"Missing required field: '{field}'")
    if result['criticals']:
        return result

    score = fm.get('score', 0)
    if not isinstance(score, (int, float)):
        result['criticals'].append(f"'score' must be a number, got: {score!r}")
        return result
    if score < SCORE_MIN:
        result['criticals'].append(f"Score {score} below minimum {SCORE_MIN}")

    result['criticals'].extend(check_injection(raw_content))
    if result['criticals']:
        return result

    # Garden type validation
    garden = fm.get('garden', GARDEN_DEFAULT)
    if garden not in GARDEN_TYPES:
        result['criticals'].append(
            f"Unknown garden '{garden}'. Valid: {sorted(GARDEN_TYPES)}"
        )
        return result

    garden_cfg = GARDEN_TYPES[garden]

    # Entry type must be valid for this garden
    entry_type = fm.get('type', '')
    if entry_type not in garden_cfg['valid_types']:
        result['criticals'].append(
            f"Type '{entry_type}' invalid for {garden}-garden. "
            f"Valid: {garden_cfg['valid_types']}"
        )

    # Garden-specific required fields
    for field in garden_cfg['required_extra']:
        if field not in fm:
            result['criticals'].append(
                f"Missing required field for {garden}-garden: '{field}'"
            )

    if score >= SCORE_AUTO_APPROVE:
        result['infos'].append(f"Score {score} >= {SCORE_AUTO_APPROVE}: auto-approve eligible")
    else:
        result['warnings'].append(f"Score {score} in range 8-11: human review required")

    if garden_root:
        domain = fm.get('domain', '')
        target_text = f"{fm.get('title', '')} {' '.join(fm.get('tags', []))} {fm.get('summary', '')}"
        target_tokens = tokenise(target_text)
        for stem, tokens in scan_domain(domain, Path(garden_root), path.stem):
            j = jaccard(target_tokens, tokens)
            if j >= JACCARD_WARNING:
                result['warnings'].append(f"Jaccard {j:.2f} >= 0.4 with {stem}: possible duplicate")
            elif j >= JACCARD_INFO:
                result['infos'].append(f"Jaccard {j:.2f} with {stem}: related entry")

        # Vocabulary check
        labels_path = Path(garden_root) / 'labels'
        if labels_path.exists():
            known = {f.stem for f in labels_path.glob('*.md')}
            for tag in fm.get('tags', []):
                if tag not in known:
                    result['warnings'].append(
                        f"Tag '{tag}' not in controlled vocabulary (labels/)"
                    )

    # Upstream garden dedup check
    if upstream_gardens:
        domain = fm.get('domain', '')
        target_text = f"{fm.get('title', '')} {' '.join(fm.get('tags', []))} {fm.get('summary', '')}"
        target_tokens = tokenise(target_text)
        for upstream_path in upstream_gardens:
            for stem, tokens in scan_domain(domain, upstream_path, ''):
                j = jaccard(target_tokens, tokens)
                if j >= JACCARD_WARNING:
                    result['criticals'].append(
                        f"Upstream duplicate: Jaccard {j:.2f} >= 0.4 with {stem} in {upstream_path.name}"
                    )

    # Bonus scoring for WHY fields
    bonus_results = compute_bonus(fm, body)
    bonus = bonus_points(bonus_results)
    if bonus > 0:
        effective = score + bonus
        result['infos'].append(
            f"Score {score}/15 base + {bonus} bonus = {effective} effective"
        )
        for k, present in bonus_results.items():
            if present:
                result['infos'].append(f"  ✓ {k} present (+{BONUS_RULES[k]})")
            else:
                result['infos'].append(f"  ✗ {k} missing (optional — adds +{BONUS_RULES[k]})")

    # Author field warning
    if 'author' not in fm:
        result['warnings'].append(
            "No 'author' field — entry won't appear on contributor scoreboard"
        )

    return result


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: validate_pr.py <entry_file> [garden_root]'}))
        sys.exit(1)
    result = validate(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else None,
        upstream_gardens=_UPSTREAM_GARDENS if _UPSTREAM_GARDENS else None,
    )
    print(json.dumps(result, indent=2))
    sys.exit(1 if result['criticals'] else 0)


if __name__ == '__main__':
    main()
