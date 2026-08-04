"""
plan_manager.py — .plan tree parser, writer, flatten, detect, advance.

The .plan file is the universal issue queue for the unified work lifecycle.
It replaces .epic as the source of truth for issue iteration order.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class QueueItem:
    issue_number: int
    title: str
    completed: bool = False
    active: bool = False
    is_epic: bool = False
    children: list['QueueItem'] = field(default_factory=list)
    batch: str | None = None


@dataclass
class PlanTree:
    heading: str
    queue: list[QueueItem]
    current_issue: int | None
    started: str
    last_wrap: str | None = None


@dataclass
class LeafItem:
    issue_number: int
    title: str
    completed: bool
    active: bool
    parent_epic: int | None
    batch: str | None


@dataclass
class AdvanceResult:
    completed: int
    next_issue: int | None
    next_title: str | None = None
    batch_complete: bool = False
    epic_complete: bool = False
    safe_exit: bool = False


_ITEM_RE = re.compile(
    r'^(\s*)- \[([ x])\] #(\d+)\s*—\s*(.+?)(?:\s*\(epic\))?(?:\s*←\s*active)?$'
)
_EPIC_MARKER_RE = re.compile(r'\(epic\)')
_ACTIVE_MARKER_RE = re.compile(r'←\s*active')
_BATCH_RE = re.compile(r'^(\s*)###\s*(Batch\s+\d+\s*—\s*.+?)(?:\s*←\s*current)?$')
_CURRENT_RE = re.compile(r'^Current:\s*#(\d+)')
_STARTED_RE = re.compile(r'^Started:\s*(.+)')
_LAST_WRAP_RE = re.compile(r'^Last wrap:\s*(.+)')


def parse_plan(plan_path: Path) -> PlanTree:
    content = plan_path.read_text()
    lines = content.splitlines()

    heading = ""
    queue: list[QueueItem] = []
    current_issue = None
    started = ""
    last_wrap = None
    in_queue = False
    in_session = False

    for line in lines:
        if line.startswith("# Work Plan"):
            heading = line[2:].strip()
            continue
        if line.strip() == "## Queue":
            in_queue = True
            in_session = False
            continue
        if line.strip() == "## Session State":
            in_queue = False
            in_session = True
            continue
        if line.startswith("## ") and line.strip() != "## Queue" and line.strip() != "## Session State":
            in_queue = False
            in_session = False
            continue

        if in_session:
            m = _CURRENT_RE.match(line.strip())
            if m:
                current_issue = int(m.group(1))
            m = _STARTED_RE.match(line.strip())
            if m:
                started = m.group(1).strip()
            m = _LAST_WRAP_RE.match(line.strip())
            if m:
                last_wrap = m.group(1).strip()

        if in_queue:
            _parse_queue_line(line, queue, 0)

    return PlanTree(heading=heading, queue=queue, current_issue=current_issue,
                    started=started, last_wrap=last_wrap)


def _parse_queue_line(line: str, items: list[QueueItem], base_indent: int) -> None:
    pass


def _build_item_tree(lines: list[str]) -> list[QueueItem]:
    """Parse indented queue lines into a tree of QueueItems."""
    result: list[QueueItem] = []
    i = 0
    while i < len(lines):
        i = _parse_item_at(lines, i, result, 0)
    return result


def _indent_level(line: str) -> int:
    return len(line) - len(line.lstrip())


def parse_plan(plan_path: Path) -> PlanTree:
    content = plan_path.read_text()
    lines = content.splitlines()

    heading = ""
    queue_lines: list[str] = []
    current_issue = None
    started = ""
    last_wrap = None
    in_queue = False
    in_session = False

    for line in lines:
        if line.startswith("# Work Plan"):
            heading = line[2:].strip()
            continue
        if line.strip() == "## Queue":
            in_queue = True
            in_session = False
            continue
        if line.strip() == "## Session State":
            in_queue = False
            in_session = True
            continue
        if line.startswith("## "):
            in_queue = False
            in_session = False
            continue

        if in_session:
            stripped = line.strip()
            m = _CURRENT_RE.match(stripped)
            if m:
                current_issue = int(m.group(1))
            m = _STARTED_RE.match(stripped)
            if m:
                started = m.group(1).strip()
            m = _LAST_WRAP_RE.match(stripped)
            if m:
                last_wrap = m.group(1).strip()

        if in_queue:
            queue_lines.append(line)

    queue = _parse_queue_lines(queue_lines)

    return PlanTree(heading=heading, queue=queue, current_issue=current_issue,
                    started=started, last_wrap=last_wrap)


def _parse_queue_lines(lines: list[str]) -> list[QueueItem]:
    items: list[QueueItem] = []
    i = 0
    current_batch = None
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("("):
            i += 1
            continue

        batch_m = _BATCH_RE.match(line)
        if batch_m:
            current_batch = batch_m.group(2).strip()
            i += 1
            continue

        item_m = _ITEM_RE.match(line)
        if item_m:
            indent = len(item_m.group(1))
            completed = item_m.group(2) == "x"
            issue_num = int(item_m.group(3))
            title_raw = item_m.group(4).strip()
            title = _EPIC_MARKER_RE.sub("", title_raw).strip()
            title = _ACTIVE_MARKER_RE.sub("", title).strip()
            is_epic = bool(_EPIC_MARKER_RE.search(item_m.group(0)))
            active = bool(_ACTIVE_MARKER_RE.search(item_m.group(0)))

            item = QueueItem(
                issue_number=issue_num,
                title=title,
                completed=completed,
                active=active,
                is_epic=is_epic,
                batch=current_batch,
            )

            if is_epic:
                child_lines = []
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if not next_line.strip():
                        j += 1
                        continue
                    next_indent = _indent_level(next_line)
                    if next_indent <= indent and _ITEM_RE.match(next_line):
                        break
                    if next_indent <= indent and not _BATCH_RE.match(next_line):
                        break
                    child_lines.append(next_line)
                    j += 1

                item.children = _parse_queue_lines(child_lines)
                if not current_batch:
                    for child in item.children:
                        if child.batch:
                            break
                i = j
            else:
                i += 1

            items.append(item)
        else:
            i += 1

    return items


def flatten_leaves(tree: PlanTree) -> list[LeafItem]:
    result: list[LeafItem] = []
    _flatten_items(tree.queue, result, parent_epic=None)
    return result


def _flatten_items(items: list[QueueItem], result: list[LeafItem],
                   parent_epic: int | None) -> None:
    for item in items:
        if item.is_epic and item.children:
            _flatten_items(item.children, result, parent_epic=item.issue_number)
        else:
            result.append(LeafItem(
                issue_number=item.issue_number,
                title=item.title,
                completed=item.completed,
                active=item.active,
                parent_epic=parent_epic,
                batch=item.batch,
            ))


def rewrite_plan(plan_path: Path, tree: PlanTree) -> None:
    content = build_plan_content(
        tree.heading.replace("Work Plan — ", ""),
        tree.queue,
        tree.started,
        last_wrap=tree.last_wrap,
    )
    plan_path.write_text(content)


def build_plan_content(branch_slug: str, items: list[QueueItem], date: str,
                       last_wrap: str | None = None) -> str:
    lines = [f"# Work Plan — {branch_slug}", "", "## Queue"]

    if not items:
        lines.append("(empty — issues created during design)")
    else:
        for item in items:
            _write_item(item, lines, indent=0)

    lines.append("")
    lines.append("## Session State")

    active_leaf = _find_active_leaf(items)
    if active_leaf:
        lines.append(f"Current: #{active_leaf.issue_number} — {active_leaf.title}")
    else:
        lines.append("Current: none")

    lines.append(f"Started: {date}")
    if last_wrap:
        lines.append(f"Last wrap: {last_wrap}")

    lines.append("")
    return "\n".join(lines)


def _write_item(item: QueueItem, lines: list[str], indent: int) -> None:
    prefix = "  " * indent
    check = "x" if item.completed else " "
    epic_marker = " (epic)" if item.is_epic else ""
    active_marker = " ← active" if item.active else ""
    lines.append(f"{prefix}- [{check}] #{item.issue_number} — {item.title}{epic_marker}{active_marker}")

    if item.is_epic and item.children:
        current_batch = None
        for child in item.children:
            if child.batch and child.batch != current_batch:
                current_batch = child.batch
                batch_marker = ""
                if any(c.active for c in item.children if c.batch == current_batch):
                    batch_marker = " ← current"
                elif not any(c.active for c in item.children) and not all(c.completed for c in item.children if c.batch == current_batch):
                    first_uncompleted_batch = None
                    for c2 in item.children:
                        if not c2.completed and c2.batch:
                            first_uncompleted_batch = c2.batch
                            break
                    if current_batch == first_uncompleted_batch:
                        batch_marker = " ← current"
                lines.append(f"{prefix}  ### {current_batch}{batch_marker}")
            _write_item(child, lines, indent + 1)


def _find_active_leaf(items: list[QueueItem]) -> QueueItem | None:
    for item in items:
        if item.active and not item.is_epic:
            return item
        if item.is_epic and item.children:
            found = _find_active_leaf(item.children)
            if found:
                return found
    return None


def append_to_queue(plan_path: Path, new_items: list[QueueItem]) -> None:
    tree = parse_plan(plan_path)
    tree.queue.extend(new_items)
    active = _find_active_leaf(tree.queue)
    if active:
        tree.current_issue = active.issue_number
    rewrite_plan(plan_path, tree)


def detect(workspace_path: Path) -> dict | None:
    plan_path = workspace_path / "design" / ".plan"
    if not plan_path.exists():
        return None

    tree = parse_plan(plan_path)
    leaves = flatten_leaves(tree)
    completed_count = sum(1 for leaf in leaves if leaf.completed)
    total_count = len(leaves)
    active = _find_active_leaf(tree.queue)

    batch = None
    if active:
        for leaf in leaves:
            if leaf.active and leaf.batch:
                batch = leaf.batch
                break

    return {
        "has_plan": True,
        "plan_path": str(plan_path),
        "active_issue": active.issue_number if active else None,
        "active_title": active.title if active else None,
        "completed_count": completed_count,
        "total_count": total_count,
        "current_batch": batch,
    }
