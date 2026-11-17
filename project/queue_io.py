"""Single source of truth for .queue file I/O.

Owns all CRUD operations for the issue queue. The queue is never deleted
during normal operation — only read, written, and migrated from .plan.
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
    tm = _REF_TITLE_RE.match(rest)
    if tm:
        return QueueItem(ref=tm.group(1), title=tm.group(2),
                         completed=completed, active=active, done_branch=done_branch,
                         from_main=from_main)
    return QueueItem(ref=rest, title="", completed=completed, active=active,
                     done_branch=done_branch, from_main=from_main)


_KNOWN_STATE_FIELDS = {"branch", "issue-repo", "status", "covers"}


def read_queue(workspace: Path) -> Optional[Queue]:
    queue_path = workspace / ".queue"
    plan_path = workspace / ".plan"

    if queue_path.exists():
        path = queue_path
    elif plan_path.exists():
        migrate_plan_to_queue(workspace)
        if queue_path.exists():
            path = queue_path
        else:
            return None
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
        base = " (from main)" if item.from_main else ""
        if item.title:
            lines.append(f"- [{check}] {item.ref} — {item.title}{base}{marker}")
        else:
            lines.append(f"- [{check}] {item.ref}{base}{marker}")
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
    tmp = workspace / ".queue.tmp"
    tmp.write_text("\n".join(lines))
    tmp.replace(workspace / ".queue")


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
    queue_path = workspace / ".queue"
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
