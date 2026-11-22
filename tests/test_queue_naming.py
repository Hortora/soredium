"""Pin the .plan → .queue rename in handler and skill docs.

The queue file was renamed from .plan to .queue in #574. Handler markdown
files and skill docs that tell the LLM about the queue must use the current
name. References to ".plan" that mean the queue file (not a plan document
or the plan_manager script) are stale and will mislead the LLM.

Refs Hortora/soredium#584
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

HANDLER_DIRS = [
    REPO / "work" / "handlers",
]

SKILL_DOCS = [
    REPO / "work" / "SKILL.md",
    REPO / "work-start" / "SKILL.md",
    REPO / "work-end" / "SKILL.md",
    REPO / "work-pause" / "SKILL.md",
    REPO / "work-resume" / "SKILL.md",
    REPO / "executing-plans" / "SKILL.md",
    REPO / "writing-plans" / "SKILL.md",
]

# Patterns that look like queue-file references (not plan documents or scripts)
STALE_QUEUE_REF = re.compile(
    r"""
    (?<!\w)              # not part of a longer word
    \.plan               # literal .plan
    (?!                  # not followed by...
        _manager         #   plan_manager
        | \.md           #   .plan.md (a file name)
        | \.py           #   .plan.py
        | s/             #   plans/ directory
        | \s+doc         #   "plan doc"
        | \s+file        #   "plan file"
        | \)             #   end of parenthetical like (writing-plans)
        | ning           #   "planning"
    )
    """,
    re.VERBOSE,
)

# Known exceptions: lines where .plan is legitimately used
EXCEPTIONS = {
    # The orphan marker is still named .orphaned-plan (not renamed)
    ".orphaned-plan",
}


def _collect_files():
    files = []
    for d in HANDLER_DIRS:
        if d.exists():
            files.extend(d.glob("*.md"))
    for f in SKILL_DOCS:
        if f.exists():
            files.append(f)
    return files


def _find_stale_refs(path: Path) -> list[tuple[int, str]]:
    hits = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if any(exc in line for exc in EXCEPTIONS):
            continue
        if STALE_QUEUE_REF.search(line):
            hits.append((i, line.strip()))
    return hits


@pytest.mark.parametrize("path", _collect_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_stale_plan_refs(path):
    hits = _find_stale_refs(path)
    if hits:
        detail = "\n".join(f"  line {n}: {text}" for n, text in hits)
        pytest.fail(
            f"{path.relative_to(REPO)} has stale .plan references "
            f"(should be .queue):\n{detail}"
        )
