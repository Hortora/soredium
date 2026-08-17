"""
plan_manager.py — .plan tree parser, writer, flatten, detect, advance.

The .plan file is the universal issue queue for the unified work lifecycle.
It replaces .epic as the source of truth for issue iteration order.
"""

import json
import re
import subprocess
import sys as _sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TaskItem:
    name: str
    batch: str
    done: bool = False


@dataclass
class QueueItem:
    issue_number: int
    title: str
    completed: bool = False
    active: bool = False
    is_epic: bool = False
    children: list['QueueItem'] = field(default_factory=list)
    batch: str | None = None
    tasks: list[TaskItem] = field(default_factory=list)


@dataclass
class DeferredItem:
    title: str
    scale: str
    complexity: str
    repos: list[str]
    completed: bool = False
    reason: str = ""


@dataclass
class PlanTree:
    heading: str
    queue: list[QueueItem]
    current_issue: int | None
    started: str
    last_wrap: str | None = None
    deferred: list[DeferredItem] = field(default_factory=list)
    state: dict[str, str] = field(default_factory=dict)


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
    has_deferred: bool = False


_ITEM_RE = re.compile(
    r'^(\s*)- \[([ x])\] #(\d+)\s*—\s*(.+?)(?:\s*\(epic\))?(?:\s*←\s*active)?$'
)
_EPIC_MARKER_RE = re.compile(r'\(epic\)')
_ACTIVE_MARKER_RE = re.compile(r'←\s*active')
_BATCH_RE = re.compile(r'^(\s*)###\s*(Batch\s+\d+\s*—\s*.+?)(?:\s*←\s*current)?$')
_DEFERRED_RE = re.compile(
    r'^- \[([ x])\]\s+(.+?)\s+\((\w+)\s*/\s*(\w+)\)\s+\[([^\]]+)\](?:\s+—\s+(.+))?$'
)
_TASK_BATCH_RE = re.compile(r'^\s*- \[([ x])\]\s*Batch\s+\d+:\s*(.+)')
_TASK_ITEM_RE = re.compile(r'^\s*- \[([ x])\]\s*Task\s+\d+:\s*(.+)')
_CURRENT_RE = re.compile(r'^Current:\s*#(\d+)')
_STARTED_RE = re.compile(r'^Started:\s*(.+)')
_LAST_WRAP_RE = re.compile(r'^Last wrap:\s*(.+)')


def _read_plan_state(plan_path: Path) -> dict[str, str]:
    """Read ## State section key-values from unified .plan."""
    fields: dict[str, str] = {}
    in_state = False
    for line in plan_path.read_text().splitlines():
        if line.strip() == "## State":
            in_state = True
            continue
        if line.startswith("## "):
            in_state = False
            continue
        if in_state and ':' in line:
            k, _, v = line.partition(':')
            fields[k.strip()] = v.strip()
    if not fields:
        for line in plan_path.read_text().splitlines():
            if ':' in line:
                k, _, v = line.partition(':')
                fields[k.strip()] = v.strip()
    return fields


def _emit_issue_events(plan_path: Path, repo_path: str,
                       completed: int, next_issue: int | None) -> None:
    try:
        _scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
        if _scripts_dir not in _sys.path:
            _sys.path.insert(0, _scripts_dir)
        import worklog

        fields = _read_plan_state(plan_path)
        branch = fields.get("branch", "")
        issue_repo = fields.get("issue-repo", "")
        if not branch:
            return

        conn = worklog.connect()
        worklog.record_issue_complete(conn, branch, repo_path, completed, issue_repo)
        if next_issue is not None:
            worklog.record_issue_activate(conn, branch, repo_path, next_issue, issue_repo)
        conn.close()
    except Exception as e:
        print(f"WARN=worklog_error detail={e}")


def _indent_level(line: str) -> int:
    return len(line) - len(line.lstrip())


def parse_plan(plan_path: Path) -> PlanTree:
    content = plan_path.read_text()
    lines = content.splitlines()

    heading = ""
    queue_lines: list[str] = []
    deferred_lines: list[str] = []
    state_dict: dict[str, str] = {}
    current_issue = None
    started = ""
    last_wrap = None
    in_state = False
    in_queue = False
    in_deferred = False
    in_session = False

    for line in lines:
        if line.startswith("# Work Plan"):
            heading = line[2:].strip()
            continue
        if line.strip() == "## State":
            in_state = True
            in_queue = False
            in_deferred = False
            in_session = False
            continue
        if line.strip() == "## Queue":
            in_state = False
            in_queue = True
            in_deferred = False
            in_session = False
            continue
        if line.strip() == "## Deferred":
            in_state = False
            in_queue = False
            in_deferred = True
            in_session = False
            continue
        if line.strip() == "## Session State":
            in_state = False
            in_queue = False
            in_deferred = False
            in_session = True
            continue
        if line.startswith("## "):
            in_state = False
            in_queue = False
            in_deferred = False
            in_session = False
            continue

        if in_state:
            stripped = line.strip()
            if ':' in stripped:
                k, _, v = stripped.partition(':')
                state_dict[k.strip()] = v.strip()

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
        if in_deferred:
            deferred_lines.append(line)

    queue = _parse_queue_lines(queue_lines)
    deferred = _parse_deferred_lines(deferred_lines)

    if state_dict and not started:
        started = state_dict.get("date", "")
    if state_dict and not last_wrap:
        last_wrap = state_dict.get("last-wrap") or None

    return PlanTree(heading=heading, queue=queue, current_issue=current_issue,
                    started=started, last_wrap=last_wrap, deferred=deferred,
                    state=state_dict)


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
                j = i + 1
                task_batch = ""
                while j < len(lines):
                    next_line = lines[j]
                    if not next_line.strip():
                        j += 1
                        continue
                    next_indent = _indent_level(next_line)
                    if next_indent <= indent:
                        break
                    bm = _TASK_BATCH_RE.match(next_line)
                    if bm:
                        task_batch = bm.group(2).strip()
                        j += 1
                        continue
                    tm = _TASK_ITEM_RE.match(next_line)
                    if tm:
                        item.tasks.append(TaskItem(
                            name=tm.group(2).strip(),
                            batch=task_batch,
                            done=tm.group(1) == "x",
                        ))
                        j += 1
                        continue
                    break
                i = j if item.tasks else i + 1

            items.append(item)
        else:
            i += 1

    return items


def _parse_deferred_lines(lines: list[str]) -> list[DeferredItem]:
    items: list[DeferredItem] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        m = _DEFERRED_RE.match(stripped)
        if m:
            completed = m.group(1) == "x"
            title = m.group(2).strip()
            scale = m.group(3).strip()
            complexity = m.group(4).strip()
            repos = [r.strip() for r in m.group(5).split(",")]
            reason = (m.group(6) or "").strip()
            items.append(DeferredItem(title, scale, complexity, repos, completed, reason))
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
        deferred=tree.deferred,
        state=tree.state,
    )
    tmp_path = plan_path.parent / '.plan.tmp'
    tmp_path.write_text(content)
    tmp_path.replace(plan_path)


def build_plan_content(branch_slug: str, items: list[QueueItem], date: str,
                       last_wrap: str | None = None,
                       deferred: list[DeferredItem] | None = None,
                       state: dict[str, str] | None = None) -> str:
    lines = [f"# Work Plan — {branch_slug}"]

    if state:
        lines.append("")
        lines.append("## State")
        for k, v in state.items():
            lines.append(f"{k}: {v}")

    lines.extend(["", "## Queue"])

    if not items:
        lines.append("(empty — issues created during design)")
    else:
        for item in items:
            _write_item(item, lines, indent=0)

    if deferred:
        lines.append("")
        lines.append("## Deferred")
        for d in deferred:
            check = "x" if d.completed else " "
            repos_str = ", ".join(d.repos)
            reason_suffix = f" — {d.reason}" if d.reason else ""
            lines.append(f"- [{check}] {d.title} ({d.scale} / {d.complexity}) [{repos_str}]{reason_suffix}")

    if not state:
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

    if item.tasks and not item.completed:
        _write_tasks(item.tasks, lines, indent + 1)


def _write_tasks(tasks: list[TaskItem], lines: list[str], indent: int) -> None:
    prefix = "  " * indent
    current_batch = None
    batch_num = 0
    task_num = 0
    for task in tasks:
        if task.batch != current_batch:
            current_batch = task.batch
            batch_num += 1
            batch_check = "x" if all(t.done for t in tasks if t.batch == current_batch) else " "
            lines.append(f"{prefix}- [{batch_check}] Batch {batch_num}: {current_batch}")
        task_num += 1
        task_check = "x" if task.done else " "
        lines.append(f"{prefix}  - [{task_check}] Task {task_num}: {task.name}")


def _find_active_leaf(items: list[QueueItem]) -> QueueItem | None:
    for item in items:
        if item.active and not item.is_epic:
            return item
        if item.is_epic and item.children:
            found = _find_active_leaf(item.children)
            if found:
                return found
    return None


class NoQueueFile(Exception):
    pass


def advance(plan_path: Path,
            repo_path: str | None = None) -> AdvanceResult:
    tree = parse_plan(plan_path)
    leaves = flatten_leaves(tree)

    active_idx = None
    for i, leaf in enumerate(leaves):
        if leaf.active:
            active_idx = i
            break

    if active_idx is None:
        return AdvanceResult(
            completed=0, next_issue=None,
            epic_complete=True, has_deferred=len(tree.deferred) > 0,
        )

    completed_leaf = leaves[active_idx]

    _mark_completed(tree.queue, completed_leaf.issue_number)
    _mark_parent_epics_if_done(tree.queue)

    next_leaf = None
    if active_idx + 1 < len(leaves):
        next_leaf = leaves[active_idx + 1]
        _mark_active(tree.queue, next_leaf.issue_number)

    batch_complete = False
    safe_exit = False
    if completed_leaf.batch and next_leaf:
        if next_leaf.batch != completed_leaf.batch:
            batch_complete = True
            safe_exit = True
    if completed_leaf.batch and not next_leaf:
        batch_complete = True
        safe_exit = True

    epic_complete = next_leaf is None
    has_deferred = epic_complete and len(tree.deferred) > 0

    tree.current_issue = next_leaf.issue_number if next_leaf else None
    rewrite_plan(plan_path, tree)

    if repo_path:
        try:
            _emit_issue_events(
                plan_path, repo_path,
                completed_leaf.issue_number,
                next_leaf.issue_number if next_leaf else None,
            )
        except Exception as e:
            print(f"WARN=worklog_error detail={e}")

    return AdvanceResult(
        completed=completed_leaf.issue_number,
        next_issue=next_leaf.issue_number if next_leaf else None,
        next_title=next_leaf.title if next_leaf else None,
        batch_complete=batch_complete,
        epic_complete=epic_complete,
        safe_exit=safe_exit,
        has_deferred=has_deferred,
    )


def advance_issue(plan_path: Path | None,
                  repo_path: str | None = None) -> AdvanceResult:
    if plan_path and plan_path.exists():
        return advance(plan_path, repo_path=repo_path)
    raise NoQueueFile("No .plan found")


def complete_active_issue(plan_path: Path,
                          repo_path: str) -> int | None:
    tree = parse_plan(plan_path)
    active = _find_active_leaf(tree.queue)
    if not active:
        return None
    _emit_issue_events(plan_path, repo_path, active.issue_number, next_issue=None)
    return active.issue_number


def _mark_completed(items: list[QueueItem], issue_number: int) -> bool:
    for item in items:
        if item.issue_number == issue_number and not item.is_epic:
            item.completed = True
            item.active = False
            item.tasks = []
            return True
        if item.is_epic and item.children:
            if _mark_completed(item.children, issue_number):
                return True
    return False


def mark_completed(plan_path: Path, issue_number: int) -> bool:
    """Mark an issue as completed [x] in the plan. Public API for work_health.py."""
    tree = parse_plan(plan_path)
    changed = _mark_completed(tree.queue, issue_number)
    if changed:
        rewrite_plan(plan_path, tree)
    return changed


def inject_tasks(plan_path: Path, tasks: list[dict]) -> None:
    """Add task breakdown to the active issue in the plan.

    tasks: list of {"batch": str, "name": str}
    Replaces any existing tasks on the active issue.
    """
    tree = parse_plan(plan_path)
    active = _find_active_leaf(tree.queue)
    if not active:
        print("ERROR=no_active_issue")
        return
    active.tasks = [TaskItem(name=t["name"], batch=t["batch"]) for t in tasks]
    rewrite_plan(plan_path, tree)


def check_task(plan_path: Path, task_name: str) -> dict:
    """Mark a task as done on the active issue. Returns batch status."""
    tree = parse_plan(plan_path)
    active = _find_active_leaf(tree.queue)
    if not active:
        return {"error": "no_active_issue"}
    for task in active.tasks:
        if task.name == task_name and not task.done:
            task.done = True
            batch = task.batch
            batch_tasks = [t for t in active.tasks if t.batch == batch]
            batch_done = all(t.done for t in batch_tasks)
            all_done = all(t.done for t in active.tasks)
            remaining_batches = len({t.batch for t in active.tasks if not all(
                bt.done for bt in active.tasks if bt.batch == t.batch
            )})
            rewrite_plan(plan_path, tree)
            return {
                "checked": task_name,
                "batch": batch,
                "batch_done": batch_done,
                "all_done": all_done,
                "remaining_batches": remaining_batches,
            }
    return {"error": f"task_not_found: {task_name}"}


def create_main_plan(workspace_path: Path, items: list[dict],
                     project_name: str = "project") -> Path:
    """Create a main .plan on workspace main with the given issues.

    items: list of {"number": int, "title": str}
    Returns path to created .plan file.
    """
    from datetime import date
    plan_path = workspace_path / ".plan"
    queue_items = []
    for i, item in enumerate(items):
        queue_items.append(QueueItem(
            issue_number=item["number"],
            title=item["title"],
            active=(i == 0),
        ))
    content = build_plan_content(project_name, queue_items, str(date.today()))
    plan_path.write_text(content)
    return plan_path


def _mark_active(items: list[QueueItem], issue_number: int) -> bool:
    for item in items:
        if item.issue_number == issue_number and not item.is_epic:
            item.active = True
            return True
        if item.is_epic and item.children:
            if _mark_active(item.children, issue_number):
                return True
    return False


def _mark_parent_epics_if_done(items: list[QueueItem]) -> None:
    for item in items:
        if item.is_epic and item.children:
            _mark_parent_epics_if_done(item.children)
            if all(c.completed for c in item.children):
                item.completed = True


def append_to_queue(plan_path: Path, new_items: list[QueueItem]) -> None:
    tree = parse_plan(plan_path)
    tree.queue.extend(new_items)
    active = _find_active_leaf(tree.queue)
    if active:
        tree.current_issue = active.issue_number
    rewrite_plan(plan_path, tree)


def append_deferred(plan_path: Path, title: str, scale: str,
                    complexity: str, repos: list[str],
                    reason: str = "") -> None:
    tree = parse_plan(plan_path)
    tree.deferred.append(DeferredItem(title, scale, complexity, repos, reason=reason))
    rewrite_plan(plan_path, tree)


def list_deferred(plan_path: Path) -> list[DeferredItem]:
    tree = parse_plan(plan_path)
    return tree.deferred


def promote_deferred(plan_path: Path,
                     available_repos: list[str]) -> list[DeferredItem]:
    tree = parse_plan(plan_path)
    available = set(available_repos)
    to_promote: list[DeferredItem] = []
    remaining: list[DeferredItem] = []

    for d in tree.deferred:
        if all(r in available for r in d.repos):
            to_promote.append(d)
        else:
            remaining.append(d)

    if not to_promote:
        return []

    next_issue_num = 9000
    for existing in tree.queue:
        if existing.issue_number >= next_issue_num:
            next_issue_num = existing.issue_number + 1
    for d in to_promote:
        tree.queue.append(QueueItem(
            issue_number=next_issue_num,
            title=d.title,
        ))
        next_issue_num += 1

    if not _find_active_leaf(tree.queue):
        _set_first_uncompleted_active(tree.queue)

    tree.deferred = remaining
    rewrite_plan(plan_path, tree)
    return to_promote


def promote_selected(plan_path: Path,
                     indices: list[int]) -> list[DeferredItem]:
    """Promote specific deferred items (by 0-based index) to the queue."""
    tree = parse_plan(plan_path)
    index_set = set(indices)
    to_promote: list[DeferredItem] = []
    remaining: list[DeferredItem] = []

    for i, d in enumerate(tree.deferred):
        if i in index_set:
            to_promote.append(d)
        else:
            remaining.append(d)

    if not to_promote:
        return []

    next_issue_num = 9000
    for existing in tree.queue:
        if existing.issue_number >= next_issue_num:
            next_issue_num = existing.issue_number + 1
    for d in to_promote:
        tree.queue.append(QueueItem(
            issue_number=next_issue_num,
            title=d.title,
        ))
        next_issue_num += 1

    if not _find_active_leaf(tree.queue):
        _set_first_uncompleted_active(tree.queue)

    tree.deferred = remaining
    rewrite_plan(plan_path, tree)
    return to_promote


def _set_first_uncompleted_active(items: list[QueueItem]) -> bool:
    for item in items:
        if not item.completed and not item.is_epic:
            item.active = True
            return True
        if item.is_epic and item.children:
            if _set_first_uncompleted_active(item.children):
                return True
    return False


def detect(workspace_path: Path) -> dict | None:
    plan_path = workspace_path / ".plan"
    if not plan_path.exists():
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
        "state": tree.state,
    }


# --- Epic auto-detection ---

_SCOPE_CHILD_RE = re.compile(r'^- \[([ x])\]\s+#(\d+)\s*(?:—\s*(.+))?')


def _gh_issue_body(issue_number: int, issue_repo: str) -> str:
    result = subprocess.run(
        ["gh", "issue", "view", str(issue_number), "--repo", issue_repo,
         "--json", "body", "--jq", ".body"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _gh_issue_title(issue_number: int, issue_repo: str) -> str:
    result = subprocess.run(
        ["gh", "issue", "view", str(issue_number), "--repo", issue_repo,
         "--json", "title", "--jq", ".title"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else f"Issue #{issue_number}"


def detect_epic(issue_number: int, issue_repo: str) -> QueueItem:
    body = _gh_issue_body(issue_number, issue_repo)
    title = _gh_issue_title(issue_number, issue_repo)

    in_scope = False
    children: list[QueueItem] = []

    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "## Scope":
            in_scope = True
            continue
        if stripped.startswith("## ") and stripped != "## Scope":
            in_scope = False
            continue

        if in_scope:
            m = _SCOPE_CHILD_RE.match(stripped)
            if m:
                checked = m.group(1) == "x"
                child_num = int(m.group(2))
                child_title = (m.group(3) or "").strip()
                if not checked:
                    if not child_title:
                        child_title = _gh_issue_title(child_num, issue_repo)
                    children.append(QueueItem(child_num, child_title))

    if children:
        return QueueItem(issue_number, title, is_epic=True, children=children)
    return QueueItem(issue_number, title)


def build_queue(issue_numbers: list[int], issue_repo: str,
                visited: set[int] | None = None) -> list[QueueItem]:
    if visited is None:
        visited = set()

    queue: list[QueueItem] = []
    for n in issue_numbers:
        if n in visited:
            continue
        visited.add(n)

        item = detect_epic(n, issue_repo)
        if item.is_epic and item.children:
            child_numbers = [c.issue_number for c in item.children]
            item.children = build_queue(child_numbers, issue_repo, visited)

        queue.append(item)

    # Set first leaf as active
    if queue and not any(_find_active_leaf(queue) is not None for _ in [1]):
        _set_first_leaf_active(queue)

    return queue


def _set_first_leaf_active(items: list[QueueItem]) -> bool:
    for item in items:
        if not item.is_epic or not item.children:
            item.active = True
            return True
        if _set_first_leaf_active(item.children):
            return True
    return False


def _tick_github_checkboxes(issue_repo: str, epic_number: int,
                            completed_issues: list[int]) -> bool:
    """Tick checkboxes on the GitHub epic issue body. Returns True on success."""
    try:
        r = subprocess.run(
            ["gh", "api", f"repos/{issue_repo}/issues/{epic_number}",
             "--jq", ".body"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return False
        body = r.stdout
        updated = body
        for issue_num in completed_issues:
            updated = re.sub(
                rf'- \[ \] #?{issue_num}\b',
                f'- [x] #{issue_num}',
                updated,
            )
        if updated == body:
            return True
        r = subprocess.run(
            ["gh", "api", "-X", "PATCH",
             f"repos/{issue_repo}/issues/{epic_number}",
             "-f", f"body={updated}"],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def _parse_cli_args(args: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            k, _, v = arg.partition("=")
            result[k.strip()] = v.strip()
    return result


def main() -> int:
    if len(_sys.argv) < 3:
        print("Usage: plan_manager.py <command> <plan_path> [key=value ...]",
              file=_sys.stderr)
        return 1

    command = _sys.argv[1]
    plan_path = Path(_sys.argv[2])
    opts = _parse_cli_args(_sys.argv[3:])

    if command == "defer":
        title = opts.get("title", "")
        scale = opts.get("scale", "M")
        complexity = opts.get("complexity", "Med")
        repos_str = opts.get("repos", "")
        reason = opts.get("reason", "")
        if not title:
            print("ERROR=title is required", file=_sys.stderr)
            return 1
        repos = [r.strip() for r in repos_str.split(",") if r.strip()] if repos_str else []
        append_deferred(plan_path, title, scale, complexity, repos, reason)
        print(f"DEFERRED={title}")
        return 0

    elif command == "list-deferred":
        items = list_deferred(plan_path)
        for i, d in enumerate(items):
            reason_suffix = f" — {d.reason}" if d.reason else ""
            print(f"{i}. {d.title} ({d.scale} / {d.complexity}) [{', '.join(d.repos)}]{reason_suffix}")
        print(f"TOTAL={len(items)}")
        return 0

    elif command == "promote-selected":
        indices_str = opts.get("indices", "")
        if not indices_str:
            print("ERROR=indices is required", file=_sys.stderr)
            return 1
        indices = [int(x.strip()) for x in indices_str.split(",") if x.strip()]
        promoted = promote_selected(plan_path, indices)
        for d in promoted:
            print(f"PROMOTED={d.title}")
        print(f"PROMOTED_COUNT={len(promoted)}")
        return 0

    elif command == "inject-tasks":
        tasks_raw = opts.get("tasks", "")
        if not tasks_raw:
            print("ERROR=tasks is required (format: batch1:task1,batch1:task2,batch2:task3)",
                  file=_sys.stderr)
            return 1
        tasks = []
        for entry in tasks_raw.split(","):
            entry = entry.strip()
            if ":" not in entry:
                continue
            batch, name = entry.split(":", 1)
            tasks.append({"batch": batch.strip(), "name": name.strip()})
        if not tasks:
            print("ERROR=no valid tasks parsed", file=_sys.stderr)
            return 1
        inject_tasks(plan_path, tasks)
        print(f"INJECTED={len(tasks)}")
        return 0

    elif command == "check-task":
        task_name = opts.get("task", "")
        if not task_name:
            print("ERROR=task is required", file=_sys.stderr)
            return 1
        result = check_task(plan_path, task_name)
        if "error" in result:
            print(f"ERROR={result['error']}")
            return 1
        for k, v in result.items():
            print(f"{k.upper()}={v}")
        return 0

    elif command == "detect":
        ws = plan_path.parent.parent if plan_path.parent.name == "design" else plan_path.parent
        result = detect(ws)
        if result:
            for k, v in result.items():
                print(f"{k.upper()}={v}")
        else:
            print("HAS_PLAN=no")
        return 0

    else:
        print(f"Unknown command: {command}", file=_sys.stderr)
        return 1


if __name__ == "__main__":
    _sys.exit(main())
