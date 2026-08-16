"""
plan_migrate.py — one-time migration from .meta (+ optional old .plan/.epic) to unified .plan.

Called by work_state.detect() before plan detection. If .meta exists alongside
.plan without ## State, merges .meta into .plan and deletes .meta. If .meta
exists alone, creates a unified .plan from covers: field.

Epic parsing is inlined (not imported from epic_manager.py) so migration
survives after epic_manager.py is deleted.
"""

import re
import sys
from pathlib import Path

_slot_dir = str(Path(__file__).parent)
if _slot_dir not in sys.path:
    sys.path.insert(0, _slot_dir)


def _parse_meta(meta_path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in meta_path.read_text().splitlines():
        if ':' in line:
            k, _, v = line.partition(':')
            fields[k.strip()] = v.strip()
    return fields


def _has_state_section(plan_path: Path) -> bool:
    for line in plan_path.read_text().splitlines():
        if line.strip() == "## State":
            return True
    return False


def _queue_items_from_covers(covers: str):
    from plan_manager import QueueItem
    items = []
    for i, part in enumerate(covers.split(",")):
        num = part.strip()
        if num and num.isdigit():
            items.append(QueueItem(
                issue_number=int(num),
                title=f"Issue #{num}",
                active=(i == 0),
            ))
    return items


_EPIC_ITEM_RE = re.compile(
    r'^(\s*)- \[([ x])\] #(\d+)\s*—\s*(.+?)(?:\s*←\s*(?:active|current))?$'
)


def _queue_items_from_epic(epic_path: Path):
    from plan_manager import QueueItem
    items = []
    first_uncompleted = True
    for line in epic_path.read_text().splitlines():
        m = _EPIC_ITEM_RE.match(line)
        if m:
            completed = m.group(2) == "x"
            issue_num = int(m.group(3))
            title = m.group(4).strip()
            active = not completed and first_uncompleted
            if active:
                first_uncompleted = False
            items.append(QueueItem(issue_num, title, completed=completed, active=active))
    return items


def migrate_to_root(workspace: Path) -> bool:
    """Move scaffold files from design/ subdirectory to workspace root.

    Called once at session entry (ctx.py). After this, all code reads
    from root only — no per-file fallback logic needed anywhere.
    """
    design = workspace / "design"
    if not design.is_dir():
        return False

    moved = False
    for name in (".plan", "JOURNAL.md", ".execute-progress",
                 ".artifacts-promoted", ".land-ledger.jsonl",
                 ".pause-stack", ".pausing", ".resuming"):
        src = design / name
        dst = workspace / name
        if src.exists() and not dst.exists():
            try:
                src.rename(dst)
                moved = True
            except FileNotFoundError:
                moved = True

    for name in (".meta", ".epic"):
        old = design / name
        if old.exists() and not (workspace / ".plan").exists():
            migrate_if_needed(design)
            plan_in_design = design / ".plan"
            if plan_in_design.exists():
                try:
                    plan_in_design.rename(workspace / ".plan")
                    moved = True
                except FileNotFoundError:
                    moved = True
            break

    for stale in (".meta", ".epic", ".plan"):
        p = design / stale
        if p.exists() and (stale != ".plan" or (workspace / ".plan").exists()):
            p.unlink()
            moved = True

    if design.is_dir() and not any(design.iterdir()):
        try:
            design.rmdir()
        except OSError:
            pass

    return moved


def migrate_if_needed(design_dir: Path) -> bool:
    meta_path = design_dir / ".meta"
    plan_path = design_dir / ".plan"
    epic_path = design_dir / ".epic"

    if not meta_path.exists():
        return False

    if plan_path.exists() and _has_state_section(plan_path):
        meta_path.unlink()
        return True

    meta = _parse_meta(meta_path)
    meta.pop("issue", None)
    meta.pop("plan", None)

    from plan_manager import parse_plan, build_plan_content, rewrite_plan

    if plan_path.exists():
        tree = parse_plan(plan_path)
        tree.state = meta
        if tree.started and "date" not in meta:
            tree.state["date"] = tree.started
        if tree.last_wrap:
            tree.state["last-wrap"] = tree.last_wrap
        rewrite_plan(plan_path, tree)
    elif epic_path.exists():
        items = _queue_items_from_epic(epic_path)
        if not items:
            items = _queue_items_from_covers(meta.get("covers", ""))
        content = build_plan_content(
            meta.get("branch", "migrated"), items,
            meta.get("date", ""), state=meta)
        plan_path.write_text(content)
        epic_path.unlink()
    else:
        items = _queue_items_from_covers(meta.get("covers", ""))
        content = build_plan_content(
            meta.get("branch", "migrated"), items,
            meta.get("date", ""), state=meta)
        plan_path.write_text(content)

    meta_path.unlink()
    return True
