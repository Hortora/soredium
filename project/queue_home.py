#!/usr/bin/env python3
"""Where an area of work keeps its queue (Hortora/soredium#577).

A queue is local to one area of work: a numbered slot, a permanent clone, or
a canonical workspace. It is never synced between areas.

A slot or clone that carries the marker file `.queue-root` uses the queue at
its root and nothing else; the `.queue` its workspace clones inherited from
their repos is ignored there and never removed. A slot without the marker
behaves as it always has: `home()` returns None and the caller's own search
applies. Existing slots are switched one at a time with `adopt`.

Usage:
    queue_home.py show <slot-or-clone-dir>
    queue_home.py adopt <slot-or-clone-dir> [from=<dir-holding-the-queue>] [--apply]
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from queue_io import (ROOT_QUEUE_MARKER, area_root, read_queue,  # noqa: E402,F401
                      root_queue_area, write_queue)

MARKER = ROOT_QUEUE_MARKER


class AdoptError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def uses_root(area: Path | str) -> bool:
    return (Path(area) / MARKER).is_file()


def home(path: Path | str) -> Optional[Path]:
    """The area root when `path` is in a slot or clone marked as using its root
    queue; None everywhere else. `queue_io.queue_dir` is what the tools call."""
    return root_queue_area(Path(path))


def mark(area: Path | str, adopted_from: str = "") -> None:
    """Record that this area uses the queue at its root. For new slots and clones."""
    lines = [f"since: {date.today().isoformat()}"]
    if adopted_from:
        lines.append(f"adopted-from: {adopted_from}")
    _write_atomically(Path(area) / MARKER, "\n".join(lines) + "\n")


@dataclass
class Candidate:
    directory: Path
    name: str            # ".queue" or ".plan"
    items: int = 0
    open_items: int = 0
    active: str = ""
    branch: str = ""
    status: str = ""
    readable: bool = True

    @property
    def path(self) -> Path:
        return self.directory / self.name


def _candidate(directory: Path) -> Optional[Candidate]:
    name = next((n for n in (".queue", ".plan") if (directory / n).is_file()), None)
    if name is None:
        return None
    found = Candidate(directory=directory, name=name)
    try:
        queue = read_queue(directory, exact=True)
    except Exception:
        queue = None
    if queue is None:
        found.readable = False
        return found
    active = queue.active_item()
    found.items = len(queue.items)
    found.open_items = sum(1 for item in queue.items if not item.completed)
    found.active = active.ref if active else ""
    found.branch = queue.state.branch or ""
    found.status = queue.state.status or ""
    return found


def candidates(area: Path | str) -> list[Candidate]:
    """Every queue file in the area: the root's, then each workspace clone's."""
    area = Path(area).resolve()
    found = []
    for directory in [area] + sorted(d for d in area.iterdir()
                                     if d.is_dir() and (d / ".workspace").exists()):
        candidate = _candidate(directory)
        if candidate is not None:
            found.append(candidate)
    return found


def _write_atomically(target: Path, content: str) -> None:
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, target)


def _backup_name(area: Path) -> Path:
    stem = f".queue.before-adopt-{date.today().isoformat()}"
    target, n = area / stem, 1
    while target.exists():
        n += 1
        target = area / f"{stem}.{n}"
    return target


def _queue_text(candidate: Candidate) -> str:
    """The candidate as sanitized .queue text for a new area.

    State is reset: branch cleared, status set to idle, all items deactivated.
    The new area has no branches yet, so inherited state would be misleading.
    """
    queue = read_queue(candidate.directory, exact=True)
    queue.state.branch = ""
    queue.state.status = "idle"
    for item in queue.items:
        item.active = False
    import tempfile
    with tempfile.TemporaryDirectory() as scratch:
        write_queue(Path(scratch), queue)
        return (Path(scratch) / ".queue").read_text()


def validate_queue(directory: Path | str) -> bool:
    """True if the queue file in directory is structurally valid (no conflict markers)."""
    directory = Path(directory)
    for name in (".queue", ".plan"):
        path = directory / name
        if path.is_file():
            content = path.read_text()
            if any(content.startswith(m) or f"\n{m}" in content
                   for m in ("<<<<<<< ", "======= ", "=======\n", ">>>>>>> ")):
                return False
            return True
    return True


def adopt(area: Path | str, source: Optional[Path | str] = None, apply: bool = False) -> dict:
    """Make one of the area's queues the queue at its root. Dry run unless `apply`.

    Nothing is removed: the previous root queue is kept under a dated name and
    every workspace clone keeps its own file. The marker is written last, so
    an adopt that fails part-way leaves the area behaving as before.
    """
    area = Path(area).resolve()
    if not (area / ".slot").is_file():
        raise AdoptError("not_an_area", f"{area} has no .slot file: not a slot or clone")
    if uses_root(area):
        raise AdoptError("already_adopted", f"{area.name} already uses the queue at its root")
    found = candidates(area)
    if source is not None:
        source = Path(source).resolve()
        chosen = next((c for c in found if c.directory == source), None)
        if chosen is None:
            raise AdoptError("no_queue_there", f"{source} holds no queue file in {area.name}")
    elif len(found) == 1:
        chosen = found[0]
    elif not found:
        chosen = None            # nothing to adopt: the area starts with an empty root queue
    else:
        raise AdoptError(
            "choose_one", f"{area.name} has {len(found)} queues; name the one to keep with "
                          f"from=<directory>")
    if chosen is not None and not chosen.readable:
        raise AdoptError("unreadable", f"{chosen.path} could not be read as a queue")

    plan = {
        "area": str(area),
        "chosen": str(chosen.path) if chosen else "",
        "backup": "",
        "applied": False,
    }
    root_queue = area / ".queue"
    replaces_root = chosen is not None and chosen.directory != area
    if replaces_root and root_queue.exists():
        plan["backup"] = str(_backup_name(area))
    if not apply:
        return plan

    if replaces_root or (chosen is not None and chosen.name == ".plan"):
        text = _queue_text(chosen)
        if plan["backup"]:
            _write_atomically(Path(plan["backup"]), root_queue.read_text())
        _write_atomically(root_queue, text)
        if read_queue(area, exact=True) is None:
            raise AdoptError("unreadable", f"{root_queue} did not read back as a queue; "
                                           f"the marker was not written")
    mark(area, adopted_from=str(chosen.path) if chosen else "")
    plan["applied"] = True
    return plan


def _describe(candidate: Candidate, area: Path) -> str:
    where = "(root)" if candidate.directory == area else candidate.directory.name
    if not candidate.readable:
        return f"{where}/{candidate.name}: unreadable"
    return (f"{where}/{candidate.name}: {candidate.items} items, {candidate.open_items} open, "
            f"active={candidate.active or 'none'} branch={candidate.branch or 'none'} "
            f"status={candidate.status or 'none'}")


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2 or argv[0] not in ("show", "adopt"):
        print(__doc__.strip())
        return 2
    area = Path(argv[1]).resolve()
    if not (area / ".slot").is_file():
        print("ERROR=not_an_area")
        print(f"DETAIL={area} has no .slot file: not a slot or clone")
        return 1
    print(f"AREA={area}")
    print(f"USES_ROOT_QUEUE={'yes' if uses_root(area) else 'no'}")
    for candidate in candidates(area):
        print("QUEUE=" + _describe(candidate, area))
    if argv[0] == "show":
        return 0
    options = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
    try:
        plan = adopt(area, source=options.get("from"), apply="--apply" in argv)
    except AdoptError as error:
        print(f"ERROR={error.code}")
        print(f"DETAIL={error.detail}")
        return 1
    print(f"CHOSEN={plan['chosen'] or 'none: the root queue starts empty'}")
    if plan["backup"]:
        print(f"BACKUP={plan['backup']}")
    print(f"APPLIED={'yes' if plan['applied'] else 'no (dry run; add --apply)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
