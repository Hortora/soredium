"""CLI dispatch for slot_manager.

Thin wrapper: parse args, validate, call lifecycle/query functions, format output.
"""

import json
import sys
from pathlib import Path

from slot_core import SlotCreationError, _resolve_slot_dir_for_number
from slot_lifecycle import (
    create_slot, remove_slot, merge_slot,
    archive_slot, restore_slot, add_repo, migrate_remotes,
)
from slot_query import list_slots, scan_ready, check_cross_deps
from slot_isx import sync_isx
from slot_git import ensure_clone_layout
from slot_claude import sweep_orphaned_claude_projects


__doc__ = """
slot_manager.py — Clone-based slot operations for multi-repo families

Subcommands:
  create-slot <family-root> repos=<csv> branch=<name> issue=<N> issue-repo=<o/r> [covers=<csv>] [context=<text>]
  list-slots <family-root> [--all]
  remove-slot <family-root> slot=<N> [--force] [resolution=<delivered|superseded|obsolete>]
  scan-ready <family-root>
  merge-slot <family-root> slot=<N>
  archive-slot <family-root> slot=<N> [--force] [resolution=<delivered|superseded|obsolete>]
  restore-slot <family-root> slot=<N>
  check-cross-deps <family-root> slot=<N>
  sync-isx [<slot-dir>] [slot=<N>]
  migrate-remotes <family-root>
  repair-claude-projects <family-root>

Note: remove-slot always archives to slots/attic/. --force skips the .landed check.

All commands output KEY=VALUE pairs on stdout for easy parsing.
"""


def parse_args() -> dict[str, str]:
    parsed = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            key, val = arg.split("=", 1)
            parsed[key] = val
        else:
            if "subcommand" not in parsed:
                parsed["subcommand"] = arg
            elif "target" not in parsed:
                parsed["target"] = arg
    return parsed


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    args = parse_args()
    subcommand = args.get("subcommand")

    if subcommand == "create-slot":
        family_root = Path(args.get("target", "."))
        repos = [r.strip() for r in args.get("repos", "").split(",") if r.strip()]
        if not repos:
            print("ERROR=missing_repos")
            sys.exit(1)
        branch = args.get("branch", "")
        if not branch:
            print("ERROR=missing_branch")
            sys.exit(1)
        try:
            result = create_slot(
                family_root=family_root,
                repos=repos,
                branch=branch,
                issue=args.get("issue", ""),
                issue_repo=args.get("issue-repo", ""),
                covers=args.get("covers", args.get("issue", "")),
                context=args.get("context", ""),
                isx=args.get("isx", "").lower() in ("yes", "true", "1"),
                isx_template=args.get("template", ""),
                isx_instance=args.get("instance", ""),
            )
        except SlotCreationError as e:
            print(f"ERROR={e}")
            sys.exit(1)
        print(f"SLOT_NUMBER={result['slot_number']}")
        print(f"SLOT_DIR={result['slot_dir']}")
        print(f"BRANCH={result['branch']}")

    elif subcommand == "list-slots":
        family_root = Path(args.get("target", "."))
        include_archived = "--all" in sys.argv
        slots = list_slots(family_root, include_archived=include_archived)
        for s in slots:
            repos_str = ",".join(s["repos"]) if isinstance(s["repos"], list) else s["repos"]
            wksp = "ok" if s.get("wksp_ok", True) else "broken"
            print(f"SLOT={s['number']} BRANCH={s['branch']} REPOS={repos_str} STATE={s['state']} ISOLATION={s.get('isolation', 'none')} WKSP={wksp}")
        print(f"COUNT={len(slots)}")

    elif subcommand == "remove-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        force = "--force" in sys.argv or "--force-delete" in sys.argv
        resolution = args.get("resolution")
        remove_slot(family_root, slot_num, force=force, resolution=resolution)

    elif subcommand == "scan-ready":
        family_root = Path(args.get("target", "."))
        slots = scan_ready(family_root)
        print(json.dumps({"slots": slots}, indent=2))

    elif subcommand == "merge-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        sys.exit(merge_slot(family_root, slot_num))

    elif subcommand == "archive-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        force = "--force" in sys.argv
        resolution = args.get("resolution")
        archive_slot(family_root, slot_num, force=force, resolution=resolution)

    elif subcommand == "restore-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        restore_slot(family_root, slot_num)

    elif subcommand == "ensure-clone-layout":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        slot_dir = _resolve_slot_dir_for_number(family_root, slot_num)
        if not slot_dir.exists():
            print(f"ERROR=slot_not_found slot={slot_num}")
            sys.exit(1)
        count = ensure_clone_layout(slot_dir)
        print(f"MIGRATED_COUNT={count}")

    elif subcommand == "check-cross-deps":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        sys.exit(check_cross_deps(family_root, slot_num))

    elif subcommand == "migrate-remotes":
        family_root = Path(args.get("target", "."))
        count = migrate_remotes(family_root)
        print(f"COUNT={count}")

    elif subcommand == "repair-claude-projects":
        family_root = Path(args.get("target", "."))
        count = sweep_orphaned_claude_projects(family_root)
        print(f"SWEPT_COUNT={count}")

    elif subcommand == "sync-isx":
        target = args.get("target", "")
        slot_num_str = args.get("slot", "")
        if slot_num_str:
            family_root = Path(target) if target else Path(".")
            slot_dir = _resolve_slot_dir_for_number(family_root, int(slot_num_str))
        elif target:
            slot_dir = Path(target)
        else:
            slot_dir = Path(".")
        if not slot_dir.exists():
            print("ERROR=slot_not_found")
            sys.exit(1)
        sys.exit(sync_isx(slot_dir))

    else:
        print(f"ERROR=unknown_subcommand subcommand={subcommand}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
