#!/usr/bin/env python3
"""Clone manager — permanent per-repo clones in <family>/clone/<repo>/.

A permanent clone mirrors the slot structure (project + workspace under one
directory, .slot file, local remote to canonical) but has no slot number and
no worklog row. The clone has one queue, at its root (#577); the handoff lives
in the clone's workspace and travels with its base branch. It is invisible to slot_query.list_slots.

Commands:
  create   family_root=<path> repo=<name>
  status   family_root=<path> repo=<name>
  enable   family_root=<path>
  enabled  family_root=<path>
"""

import sys
from pathlib import Path

_slot_dir = str(Path(__file__).resolve().parent.parent / "work-slot")
if _slot_dir not in sys.path:
    sys.path.insert(0, _slot_dir)
_project_dir = str(Path(__file__).resolve().parent)
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from slot_core import SlotCreationError
from slot_io import write_slot
from slot_lifecycle import clone_repo_pair


def is_enabled(family_root: Path) -> bool:
    return (family_root / ".clone-enabled").exists()


def enable(family_root: Path) -> None:
    (family_root / ".clone-enabled").touch()


def clone_exists(family_root: Path, repo: str) -> Path | None:
    """Return the project clone path if it exists, None otherwise."""
    clone_path = family_root / "clone" / repo / repo
    if clone_path.is_dir() and (clone_path / ".git").exists():
        return clone_path
    return None


def is_permanent(slot_dir: Path) -> bool:
    return (slot_dir / ".permanent").exists()


def create_clone(family_root: Path, repo: str) -> dict[str, str]:
    """Create a permanent clone of a canonical repo.

    Target layout: <family_root>/clone/<repo>/
      <repo>/        project clone (--shared, local remote)
      <workspace>/   workspace clone (if canonical has wksp symlink)
      .slot          slot file (slot_number=None)
      .permanent     marker file

    The workspace clone keeps its lifecycle files (.queue, HANDOFF.md)
    so the queue and handoff travel with the base branch.
    """
    canonical = family_root / repo
    if not canonical.is_dir() or not (canonical / ".git").exists():
        return {"ERROR": "canonical_not_found",
                "ERROR_DETAIL": f"No git repo at {canonical}"}

    target = family_root / "clone" / repo
    if target.exists():
        if (target / ".slot").exists():
            return {"CREATED": "already_exists",
                    "CLONE_PATH": str(target / repo)}
        return {"ERROR": "target_exists",
                "ERROR_DETAIL": str(target)}

    target.mkdir(parents=True)

    try:
        result = clone_repo_pair(target, canonical, branch="",
                                 strip_lifecycle=False)
    except SlotCreationError as e:
        import shutil
        shutil.rmtree(str(target), ignore_errors=True)
        return {"ERROR": str(e).split(" ")[0] if " " in str(e) else str(e),
                "ERROR_DETAIL": str(e)}

    write_slot(target, slot_number=None, repos=[repo], branch="",
               issue="", issue_repo="", covers="", context="")
    (target / ".permanent").touch()

    # One queue for the clone, at its root (#577). The workspace clone arrived
    # with the repo's own queue; that backlog becomes the clone's queue by copy,
    # and the inherited file is left as it is. If the choice is not clear the
    # clone is left unswitched and says so; `queue_home.py adopt` settles it.
    import queue_home
    try:
        queue_home.adopt(target, apply=True)
        queue = "root"
    except queue_home.AdoptError as error:
        queue = f"not_switched: {error.detail}"

    return {"CREATED": "yes",
            "CLONE_PATH": str(result.clone_dest),
            "QUEUE": queue}


def cmd_create(opts: dict[str, str]) -> int:
    family_root_str = opts.get("family_root", "")
    repo = opts.get("repo", "")
    if not family_root_str or not repo:
        print("ERROR=missing_args")
        print("ERROR_DETAIL=family_root and repo are required")
        return 1
    result = create_clone(Path(family_root_str), repo)
    for k, v in result.items():
        print(f"{k}={v}")
    return 1 if "ERROR" in result else 0


def cmd_status(opts: dict[str, str]) -> int:
    family_root_str = opts.get("family_root", "")
    repo = opts.get("repo", "")
    if not family_root_str or not repo:
        print("ERROR=missing_args")
        return 1
    existing = clone_exists(Path(family_root_str), repo)
    if existing:
        print("EXISTS=yes")
        print(f"CLONE_PATH={existing}")
    else:
        print("EXISTS=no")
    return 0


def cmd_enable(opts: dict[str, str]) -> int:
    family_root_str = opts.get("family_root", "")
    if not family_root_str:
        print("ERROR=missing_args")
        return 1
    enable(Path(family_root_str))
    print("ENABLED=yes")
    return 0


def cmd_enabled(opts: dict[str, str]) -> int:
    family_root_str = opts.get("family_root", "")
    if not family_root_str:
        print("ERROR=missing_args")
        return 1
    print(f"ENABLED={'yes' if is_enabled(Path(family_root_str)) else 'no'}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: clone_manager.py <create|status|enable|enabled> key=value ...",
              file=sys.stderr)
        return 1

    command = sys.argv[1]
    opts: dict[str, str] = {}
    for arg in sys.argv[2:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            opts[k] = v

    if command == "create":
        return cmd_create(opts)
    elif command == "status":
        return cmd_status(opts)
    elif command == "enable":
        return cmd_enable(opts)
    elif command == "enabled":
        return cmd_enabled(opts)
    else:
        print("ERROR=unknown_command")
        return 1


if __name__ == "__main__":
    sys.exit(main())
