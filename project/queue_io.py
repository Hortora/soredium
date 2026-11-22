"""Single source of truth for .queue file I/O.

Owns all CRUD operations for the issue queue. The queue is never deleted
during normal operation — only read, written, and migrated from .plan.

When a workspace has a notes worktree (``.notes/`` on an orphan ``notes``
branch), the queue is read from and written to ``.notes/.queue`` instead of
``workspace/.queue``.  Each write through the notes store is one commit on
the ``notes`` branch.  When no notes worktree exists, behaviour is unchanged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class QueueItem:
    ref: str
    title: str
    completed: bool
    active: bool
    # Done but not closed: finished on this branch, close ceremony not yet run.
    done_branch: str = ""
    # Its branch starts from the base branch, not stacked on the item before it.
    from_main: bool = False
    scale: str = ""
    complexity: str = ""


@dataclass
class QueueState:
    branch: str = ""
    issue_repo: str = ""
    status: str = "idle"
    covers: str = ""
    extra_fields: dict[str, str] = field(default_factory=dict)


@dataclass
class Queue:
    items: list[QueueItem] = field(default_factory=list)
    state: QueueState = field(default_factory=QueueState)
    deferred_lines: list[str] = field(default_factory=list)
    sub_task_lines: dict[int, list[str]] = field(default_factory=dict)

    def active_item(self) -> Optional[QueueItem]:
        for item in self.items:
            if item.active:
                return item
        return None

    def complete_active(self) -> None:
        item = self.active_item()
        if item:
            item.completed = True
            item.active = False

    def done_items(self) -> list[QueueItem]:
        """Items finished on a branch and awaiting the close ceremony, in queue order."""
        return [i for i in self.items if i.done_branch and not i.completed]

    def complete(self, ref: str) -> bool:
        """Close one named item. Used once its landing and stamp have succeeded."""
        for item in self.items:
            if item.ref == ref and not item.completed:
                item.completed = True
                item.active = False
                item.done_branch = ""
                return True
        return False

    def _open(self, item: QueueItem) -> bool:
        return not item.completed and not item.active and not item.done_branch

    def has_next(self) -> bool:
        return any(self._open(item) for item in self.items)

    def activate_next(self) -> None:
        if self.active_item() is not None:
            return
        for item in self.items:
            if self._open(item):
                item.active = True
                return

    def set_status(self, status: str) -> None:
        if status not in ("active", "paused", "drained", "idle"):
            raise ValueError(f"invalid status: {status}")
        self.state.status = status


_ITEM_RE = re.compile(
    r"^- \[([ x])\] "
    r"(.+?)(?:\s+← active)?$"
)
_DONE_RE = re.compile(r"\s*(?:←|<-)\s*done on (\S+)")
_FROM_MAIN_RE = re.compile(r"\s*\(from main\)")
_SCALE_RE = re.compile(r"\s*\((XS|S|M|L|XL)/(Low|Med|High)\)")
_REF_TITLE_RE = re.compile(r"^(.+?) — (.+)$")
_SUB_TASK_RE = re.compile(r"^\s+- \[[ x]\] ")


def _parse_item(line: str) -> Optional[QueueItem]:
    m = _ITEM_RE.match(line.strip())
    if not m:
        return None
    completed = m.group(1) == "x"
    active = "← active" in line
    rest = m.group(2).strip()
    if "← active" in rest:
        rest = rest.replace("← active", "").strip()
    done_m = _DONE_RE.search(rest)
    done_branch = done_m.group(1) if done_m and not completed else ""
    rest = _DONE_RE.sub("", rest).strip()
    rest = re.sub(r"\s*\(epic\)\s*", "", rest).strip()
    from_main = bool(_FROM_MAIN_RE.search(rest))
    rest = _FROM_MAIN_RE.sub("", rest).strip()
    sc_m = _SCALE_RE.search(rest)
    scale = sc_m.group(1) if sc_m else ""
    complexity = sc_m.group(2) if sc_m else ""
    if sc_m:
        rest = rest[:sc_m.start()] + rest[sc_m.end():]
        rest = rest.strip()
    tm = _REF_TITLE_RE.match(rest)
    if tm:
        return QueueItem(ref=tm.group(1), title=tm.group(2),
                         completed=completed, active=active, done_branch=done_branch,
                         from_main=from_main, scale=scale, complexity=complexity)
    return QueueItem(ref=rest, title="", completed=completed, active=active,
                     done_branch=done_branch, from_main=from_main,
                     scale=scale, complexity=complexity)


_KNOWN_STATE_FIELDS = {"branch", "issue-repo", "status", "covers"}


ROOT_QUEUE_MARKER = ".queue-root"


def _has_notes_store(workspace: Path) -> bool:
    """True if workspace has a .notes/ worktree on the notes branch."""
    from notes_store import NotesStore
    return NotesStore(workspace).available


def area_root(path: Path) -> Optional[Path]:
    """The slot or clone directory `path` is, or sits directly inside."""
    path = Path(path).resolve()
    for candidate in (path, path.parent):
        if (candidate / ".slot").is_file():
            return candidate
    return None


def root_queue_area(path: Path) -> Optional[Path]:
    """The slot or clone whose root queue serves `path`; None when it has none.

    Only an area carrying the marker file uses its root queue (#577). Without
    the marker a slot behaves as it always has.
    """
    area = area_root(path)
    return area if area is not None and (area / ROOT_QUEUE_MARKER).is_file() else None


def queue_dir(workspace: Path) -> Path:
    """The one directory that holds the queue for work at `workspace`.

    A queue is local to its area of work and is never synced between areas:

    1. a slot or clone marked as using its root queue: the area root, whichever
       of its directories the caller is in. The `.queue` its workspace clones
       inherited from their repos is not looked at there.
    2. a workspace whose `.notes` worktree already holds a queue: `.notes`.
    3. a workspace that still has its own `.queue` or `.plan`: the workspace.
       An existing queue is never left behind because a worktree appeared;
       it moves to `.notes` only when it is migrated on purpose.
    4. a workspace with a `.notes` worktree and no queue anywhere yet: `.notes`.
    5. otherwise the workspace.
    """
    workspace = _workspace_of(Path(workspace))
    area = root_queue_area(workspace)
    if area is not None:
        return area
    notes = workspace / ".notes"
    if (notes / ".queue").is_file() and _has_notes_store(workspace):
        return notes
    if (workspace / ".queue").exists() or (workspace / ".plan").exists():
        return workspace
    if notes.is_dir() and _has_notes_store(workspace):
        return notes
    return workspace


def _workspace_of(path: Path) -> Path:
    """A caller handed the `.notes` directory itself means the workspace it belongs to."""
    return path.parent if path.name == ".notes" else path


def _plan_dir(workspace: Path, qdir: Path) -> Path:
    """Where an older `.plan` is looked for: beside the queue, except that a
    workspace using `.notes` keeps any old `.plan` in the workspace itself."""
    return workspace if qdir.name == ".notes" else qdir


def read_queue(workspace: Path, exact: bool = False) -> Optional[Queue]:
    """The queue for work at `workspace`. `exact=True` reads the file in that very
    directory, whatever area it belongs to (for listing every queue in a slot)."""
    workspace = Path(workspace) if exact else _workspace_of(Path(workspace))
    qdir = workspace if exact else queue_dir(workspace)
    queue_path = qdir / ".queue"
    plan_path = _plan_dir(workspace, qdir) / ".plan"

    # Reading never changes a file. A workspace still on the older `.plan` name
    # is read in place: the parser below understands both. It is renamed to
    # `.queue` only when something writes the queue (write_queue, or
    # ensure_queue_file before a writer that needs the path).
    if queue_path.exists():
        path = queue_path
    elif plan_path.exists():
        path = plan_path
    else:
        return None

    content = path.read_text()
    lines = content.splitlines()

    items: list[QueueItem] = []
    state = QueueState()
    deferred: list[str] = []
    sub_tasks: dict[int, list[str]] = {}
    section = "queue"

    for line in lines:
        stripped = line.strip()
        if stripped == "## State":
            section = "state"
            continue
        elif stripped == "## Deferred":
            section = "deferred"
            continue
        elif stripped == "## Queue":
            section = "queue"
            continue
        elif stripped.startswith("## ") and section != "queue":
            section = "tail"
            deferred.append(line)
            continue

        if section == "queue":
            if _SUB_TASK_RE.match(line):
                if items:
                    idx = len(items) - 1
                    sub_tasks.setdefault(idx, []).append(line)
                continue
            item = _parse_item(line)
            if item:
                items.append(item)
        elif section == "state":
            if ":" in stripped and not stripped.startswith("#") and not stripped.startswith("-"):
                key, _, val = stripped.partition(":")
                key, val = key.strip(), val.strip()
                if key == "branch":
                    state.branch = val
                elif key == "issue-repo":
                    state.issue_repo = val
                elif key == "status":
                    state.status = val
                elif key == "state":
                    state.status = _migrate_lifecycle_state(val)
                elif key == "covers":
                    state.covers = val
                elif key not in ("evidence-era",):
                    state.extra_fields[key] = val
        elif section == "deferred":
            deferred.append(line)
        elif section == "tail":
            deferred.append(line)

    return Queue(items=items, state=state, deferred_lines=deferred,
                 sub_task_lines=sub_tasks)


def write_queue(workspace: Path, queue: Queue) -> None:
    lines: list[str] = []
    for i, item in enumerate(queue.items):
        check = "x" if item.completed else " "
        marker = "        ← active" if item.active else ""
        if item.done_branch and not item.completed and not item.active:
            marker = f" ← done on {item.done_branch}"
        scale_str = f" ({item.scale}/{item.complexity})" if item.scale else ""
        base = " (from main)" if item.from_main else ""
        if item.title:
            lines.append(f"- [{check}] {item.ref} — {item.title}{scale_str}{base}{marker}")
        else:
            lines.append(f"- [{check}] {item.ref}{scale_str}{base}{marker}")
        if i in queue.sub_task_lines:
            lines.extend(queue.sub_task_lines[i])
    lines.append("")
    lines.append("## State")
    lines.append(f"branch: {queue.state.branch}")
    lines.append(f"issue-repo: {queue.state.issue_repo}")
    lines.append(f"status: {queue.state.status}")
    if queue.state.covers:
        lines.append(f"covers: {queue.state.covers}")
    for k, v in queue.state.extra_fields.items():
        lines.append(f"{k}: {v}")
    if queue.deferred_lines:
        has_deferred_header = any(
            l.strip() == "## Deferred" for l in queue.deferred_lines
        )
        if not has_deferred_header:
            lines.append("")
            lines.append("## Deferred")
        lines.extend(queue.deferred_lines)
    lines.append("")
    content = "\n".join(lines)
    workspace = _workspace_of(Path(workspace))
    qdir = queue_dir(workspace)
    if qdir.name == ".notes" and qdir.parent == workspace:
        from notes_store import NotesStore
        NotesStore(workspace).write(".queue", content, "update queue")
    else:
        converting = not (qdir / ".queue").exists()
        tmp = qdir / ".queue.tmp"
        tmp.write_text(content)
        tmp.replace(qdir / ".queue")
        if converting:
            # Only the write that creates .queue retires the older file. Where both
            # already exist, .plan is some earlier leftover (it may be tracked in
            # git) and renaming it on every write would leave a deletion behind.
            _retire_plan_file(qdir)


def _retire_plan_file(workspace: Path) -> None:
    """Once `.queue` holds the queue, the older `.plan` is kept aside as `.plan.bak`.

    Said out loud on stderr: a file being renamed is never done silently.
    """
    plan_path = workspace / ".plan"
    if plan_path.exists() and (workspace / ".queue").exists():
        plan_path.rename(workspace / ".plan.bak")
        import sys
        print(f"MIGRATED_PLAN={workspace} (.plan kept as .plan.bak; the queue is now .queue)",
              file=sys.stderr)


def ensure_queue_file(workspace: Path) -> bool:
    """Make sure `.queue` exists before a writer that needs its path.

    Returns True when an older `.plan` was converted just now. Called only by
    code that is about to write the queue, never on a read.
    """
    workspace = queue_dir(Path(workspace))
    if workspace.name == ".notes":
        return False            # a notes store never holds an older .plan
    if (workspace / ".queue").exists() or not (workspace / ".plan").exists():
        return False
    migrate_plan_to_queue(workspace)
    import sys
    print(f"MIGRATED_PLAN={workspace} (.plan kept as .plan.bak; the queue is now .queue)",
          file=sys.stderr)
    return True


def _migrate_lifecycle_state(state_val: str) -> str:
    if state_val.startswith("closing:"):
        return "active"
    mapping = {
        "active": "active",
        "scaffolded": "active",
        "transitioning": "active",
        "paused": "paused",
        "drained": "drained",
        "idle": "idle",
    }
    return mapping.get(state_val, "active")


def migrate_plan_to_queue(workspace: Path) -> None:
    plan_path = workspace / ".plan"
    queue_path = workspace / ".queue"
    if not plan_path.exists() or queue_path.exists():
        return

    content = plan_path.read_text()
    lines = content.splitlines()
    out: list[str] = []
    in_state = False
    status_found = False

    for line in lines:
        stripped = line.strip()
        if stripped == "## State":
            in_state = True
            out.append(line)
            continue
        if in_state and stripped.startswith("## "):
            in_state = False
            out.append(line)
            continue

        if in_state:
            if stripped.startswith("state:"):
                val = stripped.split(":", 1)[1].strip()
                out.append(f"status: {_migrate_lifecycle_state(val)}")
                status_found = True
                continue
            if stripped.startswith("status:"):
                status_found = True
            if stripped == "evidence-era: true":
                continue
            out.append(line)
        else:
            out.append(line)

    if not status_found:
        state_idx = next(
            (i for i, l in enumerate(out) if l.strip() == "## State"), None
        )
        if state_idx is not None:
            out.insert(state_idx + 1, "status: active")

    tmp = queue_path.with_suffix(".queue.tmp")
    tmp.write_text("\n".join(out) + "\n")
    tmp.replace(queue_path)
    plan_path.rename(plan_path.parent / ".plan.bak")


# --- covers parsing (migrated from plan_io.py) ---

@dataclass(frozen=True)
class CoverRef:
    number: int
    repo: str = ""

    def __int__(self) -> int:
        return self.number

    def __str__(self) -> str:
        return f"{self.repo}#{self.number}" if self.repo else str(self.number)


def parse_covers(covers_str: str) -> list[int]:
    result = []
    for part in covers_str.split(","):
        part = part.strip()
        if part.isdigit():
            result.append(int(part))
    return result


@dataclass
class Finding:
    scenario: str
    severity: str
    detail: str
    actions: list[str] = field(default_factory=list)
    auto_recoverable: bool = False
    auto_action: str = ""


def validate_queue(workspace: Path, queue: Queue,
                   current_branch: str, base_branch: str) -> list[Finding]:
    findings: list[Finding] = []
    if not queue.state.status:
        findings.append(Finding("S1_MISSING_STATUS", "high",
                                "queue has no status",
                                actions=["accept_default"],
                                auto_recoverable=True,
                                auto_action="accept_default"))
    if queue.state.branch and current_branch != base_branch:
        if current_branch != queue.state.branch:
            findings.append(Finding("S5_BRANCH_MISMATCH", "high",
                                    f"branch mismatch: queue={queue.state.branch} actual={current_branch}",
                                    actions=["update_plan_branch", "switch_to_plan_branch", "ignore"],
                                    auto_recoverable=True,
                                    auto_action="update_plan_branch"))
    queue_path = queue_dir(Path(workspace)) / ".queue"
    if queue_path.exists():
        content = queue_path.read_text()
        if "<<<<<<" in content or "======" in content or ">>>>>>" in content:
            findings.append(Finding("S13_MERGE_CONFLICT", "critical",
                                    "merge conflict markers in .queue",
                                    actions=["remove_plan"],
                                    auto_recoverable=True,
                                    auto_action="remove_plan"))
    return findings


_COVER_QUALIFIED_RE = re.compile(
    r"^([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)#(\d+)$"
)


def parse_covers_qualified(covers_str: str) -> list[CoverRef]:
    result: list[CoverRef] = []
    for part in covers_str.split(","):
        part = part.strip()
        if not part:
            continue
        m = _COVER_QUALIFIED_RE.match(part)
        if m:
            result.append(CoverRef(number=int(m.group(2)), repo=m.group(1)))
            continue
        if part.isdigit():
            result.append(CoverRef(number=int(part)))
    return result
