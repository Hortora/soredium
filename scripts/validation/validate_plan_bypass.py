#!/usr/bin/env python3
"""Commit-tier validator: detect .plan bypass writers.

Fails if any Python file outside canonical writers directly manipulates
.plan files. Wraps the logic from tests/test_plan_bypass_enforcement.py
for validate_all.py integration.

Exit codes: 0 = clean, 1 = CRITICAL (violations found).
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

CANONICAL_WRITERS = {
    "project/plan_io.py",
}

EXEMPT_PATHS = {
    "tests/",
    "work-end/audit_work_end.py",
    "engine/",
    ".worktrees/",
}

BYPASS_PATTERNS = [
    re.compile(r'plan[_.]?path\.write_text\('),
    re.compile(r'plan[_.]?path\.unlink\('),
    re.compile(r'\.plan.*\.write_text\('),
    re.compile(r'\.plan.*\.unlink\('),
    re.compile(r'tmp_path\.replace\(.*plan'),
    re.compile(r'\.plan\.tmp.*\.replace\('),
    re.compile(r'shutil\.copy2\(.*plan'),
    re.compile(r'_shutil\.copy2\(.*plan'),
]


def _is_exempt(rel_path: str) -> bool:
    if rel_path in CANONICAL_WRITERS:
        return True
    for exempt in EXEMPT_PATHS:
        if rel_path.startswith(exempt):
            return True
    return False


def main() -> int:
    violations = []

    for py_file in PROJECT_ROOT.rglob("*.py"):
        rel = str(py_file.relative_to(PROJECT_ROOT))
        if _is_exempt(rel):
            continue

        try:
            content = py_file.read_text()
        except UnicodeDecodeError:
            continue

        for i, line in enumerate(content.splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            for pattern in BYPASS_PATTERNS:
                if pattern.search(line):
                    violations.append(f"{rel}:{i}: {line.strip()}")

    if violations:
        print(f"CRITICAL: {len(violations)} .plan bypass write(s) outside canonical writers:")
        for v in violations:
            print(f"  {v}")
        return 1

    print("OK: no .plan bypass writers found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
