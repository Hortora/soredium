#!/usr/bin/env python3
"""Migrate a permanent clone or canonical repo to the notes store model.

Usage:
    python3 project/migrate_to_notes.py <project-path> [--dry-run]

Steps:
    1. Activate notes store (.notes/ worktree on orphan notes branch)
    2. Copy queue from current location into .notes/.queue
    3. Remove wksp symlink from project clone (topology falls to single-repo)
    4. Remove .queue-root from clone root (queue_io uses .notes/)

Non-destructive: the original queue file and workspace clone stay on disk.
"""

import sys
from pathlib import Path

_project_dir = Path(__file__).resolve().parent
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))


def migrate(project: Path, dry_run: bool = False) -> list[str]:
    """Migrate project to notes store model. Returns list of actions taken."""
    from notes_store import NotesStore
    from queue_io import queue_dir, ROOT_QUEUE_MARKER

    actions: list[str] = []
    project = project.resolve()

    if not (project / ".git").exists():
        return [f"ERROR: {project} is not a git repository"]

    store = NotesStore(project)

    # Step 1: activate notes store
    if store.available:
        actions.append(f"notes store already active at {store.path}")
    elif dry_run:
        actions.append(f"WOULD create notes store at {project / '.notes'}")
    else:
        store.ensure()
        actions.append(f"created notes store at {store.path}")

    # Step 2: find and copy queue
    clone_root = project.parent
    queue_sources = []
    if (clone_root / ROOT_QUEUE_MARKER).exists():
        queue_sources.append(clone_root / ".queue")
    wksp_sym = project / "wksp"
    if wksp_sym.is_symlink() and wksp_sym.exists():
        ws = wksp_sym.resolve()
        if (ws / ".queue").exists():
            queue_sources.append(ws / ".queue")
        if (ws / ".plan").exists():
            queue_sources.append(ws / ".plan")
    if (project / ".queue").exists():
        queue_sources.append(project / ".queue")

    notes_queue = store.path / ".queue" if store.available else project / ".notes" / ".queue"
    if notes_queue.exists():
        actions.append(f"queue already in notes store at {notes_queue}")
    elif queue_sources:
        source = queue_sources[0]
        content = source.read_text()
        if dry_run:
            actions.append(f"WOULD copy queue from {source} to .notes/.queue ({len(content)} bytes)")
        else:
            store.write(".queue", content, "migrate queue to notes store")
            actions.append(f"copied queue from {source} to .notes/.queue")
    else:
        actions.append("no queue found to migrate")

    # Step 3: remove wksp symlink
    wksp_sym = project / "wksp"
    if wksp_sym.is_symlink():
        target = wksp_sym.resolve()
        if dry_run:
            actions.append(f"WOULD remove wksp symlink ({wksp_sym} -> {target})")
        else:
            wksp_sym.unlink()
            actions.append(f"removed wksp symlink (was -> {target})")
    else:
        actions.append("no wksp symlink to remove")

    # Step 4: remove .queue-root from clone root
    queue_root_marker = clone_root / ROOT_QUEUE_MARKER
    if queue_root_marker.exists():
        if dry_run:
            actions.append(f"WOULD remove {queue_root_marker}")
        else:
            queue_root_marker.unlink()
            actions.append(f"removed {queue_root_marker}")
    else:
        actions.append("no .queue-root marker to remove")

    # Step 5: copy pause stack if present
    for source_dir in [clone_root, project]:
        pause_stack = source_dir / ".pause-stack"
        if pause_stack.exists():
            notes_pause = store.path / ".pause-stack" if store.available else project / ".notes" / ".pause-stack"
            if notes_pause.exists():
                actions.append(f"pause stack already in notes store")
                break
            content = pause_stack.read_text()
            if dry_run:
                actions.append(f"WOULD copy pause stack from {pause_stack} to .notes/.pause-stack")
            else:
                store.write(".pause-stack", content, "migrate pause stack to notes store")
                actions.append(f"copied pause stack from {pause_stack}")
            break

    return actions


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: migrate_to_notes.py <project-path> [--dry-run]", file=sys.stderr)
        return 1

    project = Path(sys.argv[1]).resolve()
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("DRY RUN — no changes will be made\n")

    actions = migrate(project, dry_run=dry_run)
    for action in actions:
        print(f"  {action}")

    if any(a.startswith("ERROR") for a in actions):
        return 1

    if not dry_run:
        print("\nMigration complete. The old workspace clone stays on disk as a backup.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
