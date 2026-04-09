#!/usr/bin/env python3
"""validate_pr.py — Validate a garden entry before PR merge.

Exits 0 (pass, may have warnings), 1 (CRITICAL failure).
Outputs structured JSON to stdout only — does NOT call gh API.
"""

import sys
import json
import re
import subprocess
from pathlib import Path

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


def validate(entry_path: str, garden_root: str = None) -> dict:
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

    return result


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: validate_pr.py <entry_file> [garden_root]'}))
        sys.exit(1)
    result = validate(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result['criticals'] else 0)


if __name__ == '__main__':
    main()
