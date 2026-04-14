#!/usr/bin/env python3
"""validate_schema.py — Validates SCHEMA.md federation config for a garden repo.

Usage:
  validate_schema.py <garden_path>

Exit codes: 0 = valid, 1 = invalid
"""

import re
import sys
from pathlib import Path

KNOWN_SCHEMA_VERSIONS = {'1.0'}
VALID_ROLES = {'canonical', 'child', 'peer'}
GE_PREFIX_RE = re.compile(r'^[A-Z]{1,3}-$')
FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---', re.DOTALL)


def parse_schema(content: str) -> dict | None:
    """Parse SCHEMA.md content. Returns field dict or None if no frontmatter."""
    content = content.replace('\r\n', '\n')
    m = FRONTMATTER_RE.match(content)
    if not m:
        return None
    return _parse_frontmatter(m.group(1))


def _parse_frontmatter(fm: str) -> dict:
    result = {}
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.startswith('#'):
            i += 1
            continue
        if ':' not in line:
            i += 1
            continue
        key, _, rest = line.partition(':')
        key = key.strip()
        rest = rest.strip()
        if not rest:
            # Block list
            items = []
            i += 1
            while i < len(lines) and re.match(r'^\s+-\s+', lines[i]):
                items.append(re.sub(r'^\s+-\s+', '', lines[i]).strip().strip('"\''))
                i += 1
            if items:
                result[key] = items
            continue
        elif rest.startswith('[') and rest.endswith(']'):
            inner = rest[1:-1]
            result[key] = [v.strip().strip('"\'') for v in inner.split(',') if v.strip()]
        else:
            result[key] = rest.strip('"\'')
        i += 1
    return result


def validate_name(schema: dict) -> list:
    name = schema.get('name', '')
    if not name:
        return ["'name' is required and must be non-empty"]
    return []


def validate_role(schema: dict) -> list:
    role = schema.get('role')
    if not role:
        return [f"'role' is required — must be one of: {', '.join(sorted(VALID_ROLES))}"]
    if role not in VALID_ROLES:
        return [f"'role' is {role!r} — must be one of: {', '.join(sorted(VALID_ROLES))}"]
    return []


def validate_ge_prefix(schema: dict) -> list:
    prefix = schema.get('ge_prefix', '')
    if not prefix:
        return ["'ge_prefix' is required (e.g. 'JE-', 'TE-')"]
    if not GE_PREFIX_RE.match(prefix):
        return [
            f"'ge_prefix' is {prefix!r} — must be 1–3 uppercase letters followed by "
            "a hyphen (e.g. 'JE-', 'TE-', 'JVM-')"
        ]
    return []


def validate_domains(schema: dict) -> list:
    domains = schema.get('domains')
    if domains is None:
        return ["'domains' is required — list of domain names (e.g. [java, quarkus])"]
    if not isinstance(domains, list):
        return ["'domains' must be a list"]
    if not domains:
        return ["'domains' must be non-empty"]
    return []


def validate_upstream(schema: dict) -> list:
    role = schema.get('role')
    upstream = schema.get('upstream')
    if role == 'child':
        if not upstream:
            return ["'upstream' is required for child gardens — list one or more parent garden URLs"]
        if not isinstance(upstream, list) or not upstream:
            return ["'upstream' must be a non-empty list for child gardens"]
        for item in upstream:
            if not isinstance(item, str):
                return [f"'upstream' items must be strings (URLs), got: {item!r}"]
    elif role in ('canonical', 'peer') and upstream:
        return [f"'upstream' must not be set for {role} gardens — only child gardens have upstream parents"]
    return []


def validate_schema(schema: dict) -> tuple:
    """Validate schema dict. Returns (errors, warnings)."""
    errors = []
    warnings = []
    errors.extend(validate_name(schema))
    errors.extend(validate_role(schema))
    errors.extend(validate_ge_prefix(schema))
    errors.extend(validate_domains(schema))
    errors.extend(validate_upstream(schema))
    version = schema.get('schema_version', '')
    if not version:
        errors.append("'schema_version' is required")
    elif version not in KNOWN_SCHEMA_VERSIONS:
        warnings.append(
            f"'schema_version' is {version!r} — known versions: "
            f"{', '.join(sorted(KNOWN_SCHEMA_VERSIONS))}"
        )
    return errors, warnings


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('--help', '-h'):
        print(__doc__)
        sys.exit(0)
    garden = Path(sys.argv[1]).expanduser().resolve()
    schema_path = garden / 'SCHEMA.md'
    if not schema_path.exists():
        print(f"ERROR: SCHEMA.md not found in {garden}")
        sys.exit(1)
    content = schema_path.read_text(encoding='utf-8')
    schema = parse_schema(content)
    if schema is None:
        print("ERROR: SCHEMA.md has no YAML frontmatter")
        sys.exit(1)
    errors, warnings = validate_schema(schema)
    for w in warnings:
        print(f"WARNING: {w}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        print(f"\n❌ {len(errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1)
    print(
        f"✅ SCHEMA.md valid — role={schema.get('role')}, "
        f"ge_prefix={schema.get('ge_prefix')}, domains={schema.get('domains')}"
    )
    sys.exit(0)


if __name__ == '__main__':
    main()
