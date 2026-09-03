"""Single source of truth for .plan file I/O.

Owns all CRUD operations: create, read, update, delete.
Every consumer imports from here — no inline section walking.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class QueueItem:
    repo: str
    number: int
    title: str
    completed: bool
    active: bool


@dataclass(frozen=True)
class PlanState:
    fields: dict[str, str]
    queue_items: list[QueueItem]
    unparsed_lines: list[str]


_ITEM_RE = re.compile(
    r'^(\s*)- \[([ x])\] '
    r'(?:([A-Za-z0-9._-]+/[A-Za-z0-9._-]+))?#(\d+)'
    r'\s*—\s*(.+?)(?:\s*\(epic\))?(?:\s*←\s*active)?$'
)

_ACTIVE_RE = re.compile(r'←\s*active')
_EPIC_RE = re.compile(r'\(epic\)')


def read_plan(plan_path: Path) -> Optional[PlanState]:
    if not plan_path.exists():
        return None
    content = plan_path.read_text()
    lines = content.splitlines()

    fields: dict[str, str] = {}
    queue_items: list[QueueItem] = []
    unparsed_lines: list[str] = []

    section: Optional[str] = None
    has_sections = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            section = stripped
            has_sections = True
            continue

        if section == "## State" or (not has_sections and ":" in line and not line.startswith("#") and not line.startswith("-")):
            if ":" in line and not line.startswith("#") and not line.startswith("-"):
                k, _, v = line.partition(":")
                k = k.strip()
                if k:
                    fields[k] = v.strip()

        elif section == "## Queue":
            if not stripped or stripped.startswith("###") or stripped.startswith("("):
                continue
            m = _ITEM_RE.match(line)
            if m:
                repo = m.group(3) or ""
                title_raw = m.group(5).strip()
                title = _EPIC_RE.sub("", title_raw).strip()
                title = _ACTIVE_RE.sub("", title).strip()
                queue_items.append(QueueItem(
                    repo=repo,
                    number=int(m.group(4)),
                    title=title,
                    completed=m.group(2) == "x",
                    active=bool(_ACTIVE_RE.search(line)),
                ))
            elif stripped.startswith("- "):
                unparsed_lines.append(stripped)

    return PlanState(fields=fields, queue_items=queue_items, unparsed_lines=unparsed_lines)


def read_field(plan_path: Path, field_name: str) -> Optional[str]:
    state = read_plan(plan_path)
    if state is None:
        return None
    return state.fields.get(field_name)


def parse_covers(covers_str: str) -> list[int]:
    result = []
    for part in covers_str.split(","):
        part = part.strip()
        if part.isdigit():
            result.append(int(part))
    return result


def has_uncompleted_items(plan_state: PlanState) -> bool:
    return any(not item.completed for item in plan_state.queue_items)


def write_field(plan_path: Path, field_name: str, value: str) -> None:
    write_fields(plan_path, {field_name: value})


def write_fields(plan_path: Path, updates: dict[str, str]) -> None:
    content = plan_path.read_text()
    lines = content.splitlines()

    in_state = False
    has_sections = False
    state_end = len(lines)
    updated: set[str] = set()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "## State":
            in_state = True
            has_sections = True
            continue
        if stripped.startswith("## ") and in_state:
            state_end = i
            in_state = False
            continue

        check = in_state if has_sections else (
            ":" in line and not line.startswith("#") and not line.startswith("-")
        )
        if check:
            k = line.split(":", 1)[0].strip()
            if k in updates:
                lines[i] = f"{k}: {updates[k]}"
                updated.add(k)

    for k, v in updates.items():
        if k not in updated:
            lines.insert(state_end, f"{k}: {v}")
            state_end += 1

    tmp = plan_path.parent / ".plan.tmp"
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(plan_path)


def remove_plan(plan_path: Path) -> None:
    if plan_path.exists():
        plan_path.unlink()
