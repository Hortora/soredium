"""Tests that slot-related documentation uses clone terminology, not worktree.

Slots use standalone git clones (git clone --shared), not git worktrees.
The code handles this correctly but documentation must match. This test
catches regressions where "worktree" is used to describe slot operations.

Allowed contexts for "worktree" in slot files:
- The directory name "worktrees/" (it's the path, not the mechanism)
- References to using-git-worktrees (a different skill)
- The is_worktree() detection function (distinguishes clones from worktrees)
- ensure_clone_layout() migration context (converts worktrees TO clones)
- remove_slot worktree detection (legacy cleanup)
- Code comments explaining the worktree→clone migration
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

SLOT_FILES = [
    "work-end/SKILL.md",
    "work-slot/SKILL.md",
    "work-end/close_report.py",
]

ALLOWED_PATTERNS = [
    r"worktrees/",
    r"worktrees\\?/",
    r"`worktrees/",
    r"using-git-worktrees",
    r"is_worktree",
    r"ensure_clone_layout",
    r"git worktree remove.*force",
    r"worktree.*→.*clone",
    r"worktree.*migrat",
    r"\.worktrees/",
    r"EnterWorktree",
    r"ExitWorktree",
    r"not.*git worktree",
    r"not.*worktrees\b",
    r"indicates a git worktree",
    r"No.*`git worktree",
]


def _is_allowed(line: str) -> bool:
    """Check if a line's use of 'worktree' is in an allowed context."""
    for pattern in ALLOWED_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def _find_worktree_violations(filepath: Path) -> list[tuple[int, str]]:
    """Find lines that use 'worktree' to describe slot operations."""
    violations = []
    text = filepath.read_text()
    for i, line in enumerate(text.splitlines(), 1):
        if "worktree" not in line.lower():
            continue
        if _is_allowed(line):
            continue
        violations.append((i, line.strip()))
    return violations


class TestSlotTerminology:
    @pytest.mark.parametrize("relpath", SLOT_FILES)
    def test_no_worktree_terminology_in_slot_docs(self, relpath):
        filepath = REPO_ROOT / relpath
        if not filepath.exists():
            pytest.skip(f"{relpath} not found")
        violations = _find_worktree_violations(filepath)
        if violations:
            report = "\n".join(f"  line {n}: {line}" for n, line in violations)
            pytest.fail(
                f"{relpath} uses 'worktree' in slot context "
                f"(should be 'clone'):\n{report}"
            )

    def test_close_report_no_worktree_step_name(self):
        filepath = REPO_ROOT / "work-end" / "close_report.py"
        text = filepath.read_text()
        assert "worktree-remove" not in text, (
            "close_report.py still uses 'worktree-remove' step name — "
            "should be 'slot-archive'"
        )
        assert "Worktrees removed" not in text, (
            "close_report.py still uses 'Worktrees removed' label — "
            "should be 'Slot archived'"
        )

    def test_slot_manager_docstring_says_clone(self):
        filepath = REPO_ROOT / "work-slot" / "slot_manager.py"
        first_docstring = ""
        text = filepath.read_text()
        in_docstring = False
        for line in text.splitlines()[:10]:
            if '"""' in line and not in_docstring:
                in_docstring = True
                first_docstring += line
            elif '"""' in line and in_docstring:
                first_docstring += line
                break
            elif in_docstring:
                first_docstring += line
        assert "worktree" not in first_docstring.lower() or "clone" in first_docstring.lower(), (
            "slot_manager.py module docstring describes 'worktree' operations "
            "but slots use git clone --shared"
        )
