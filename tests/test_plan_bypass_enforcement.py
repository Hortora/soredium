"""Static analysis: detect .plan bypass writers.

Runs at commit tier. Fails if any Python file outside the canonical
writers directly manipulates .plan files via write_text, unlink, or
shutil.copy2.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

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


def test_no_plan_bypass_writers():
    """No Python file outside canonical writers may directly manipulate .plan."""
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

    assert violations == [], (
        f"Found {len(violations)} .plan bypass write(s) outside canonical writers:\n"
        + "\n".join(violations)
    )
