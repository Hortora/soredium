#!/usr/bin/env python3
"""
Scan for and migrate existing methodology artifacts from project to workspace.

Called by workspace-init Step 9. Replaces find + cp + shell array blocks
that trigger Claude Code permission prompts.

Usage:
    python3 artifact_migrate.py <subcommand> <args...>

Subcommands:
    scan     <project_path>                                   Detect existing artifacts
    migrate  <project_path> <workspace_path> paths=<csv>      Copy artifacts to workspace

Output (KEY=value lines):
    FOUND=<json-array>             (scan)
    MIGRATED=<count>               (migrate)
    ERROR=<code>                   (on failure)
    ERROR_DETAIL=<message>         (on failure)

Exit codes:
    0  success
    1  missing required args or I/O error
"""

import json
import shutil
import sys
from pathlib import Path

from common import parse_args


# Paths to check for existing methodology artifacts.
# Format: (source_relative_path, is_directory)
ARTIFACT_CANDIDATES = [
    ("HANDOFF.md", False),
    ("HANDOVER.md", False),
    ("IDEAS.md", False),
    ("blog/", True),
    ("plans/", True),
    ("snapshots/", True),
    ("docs/blog/", True),
    ("docs/_posts/", True),
    ("docs/handoffs/", True),
    ("docs/ideas/IDEAS.md", False),
    ("docs/superpowers/plans/", True),
    (".superpowers/brainstorm/", True),
]


def cmd_scan(project: Path) -> int:
    if not project.is_dir():
        print("ERROR=project_not_found")
        print(f"ERROR_DETAIL=Path does not exist: {project}", flush=True)
        return 1

    found: list[str] = []
    for rel_path, is_dir in ARTIFACT_CANDIDATES:
        target = project / rel_path.rstrip("/")
        if is_dir:
            if target.is_dir():
                found.append(rel_path)
        else:
            if target.is_file():
                found.append(rel_path)

    print(f"FOUND={json.dumps(found)}")
    return 0


def cmd_migrate(project: Path, workspace: Path, params: dict[str, str]) -> int:
    if not project.is_dir():
        print("ERROR=project_not_found")
        print(f"ERROR_DETAIL=Path does not exist: {project}", flush=True)
        return 1

    if not workspace.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Path does not exist: {workspace}", flush=True)
        return 1

    paths_csv = params.get("paths", "")
    if not paths_csv:
        print("ERROR=missing_paths")
        print("ERROR_DETAIL=paths= argument is required", flush=True)
        return 1

    paths = [p.strip() for p in paths_csv.split(",") if p.strip()]
    migrated = 0

    for rel_path in paths:
        source = project / rel_path.rstrip("/")
        if not source.exists():
            print("ERROR=path_not_found")
            print(f"ERROR_DETAIL={rel_path}", flush=True)
            return 1

        # Determine destination — strip docs/ prefix for workspace layout
        dest_rel = rel_path
        if dest_rel.startswith("docs/superpowers/plans/"):
            dest_rel = "plans/"
        elif dest_rel.startswith("docs/_posts/"):
            dest_rel = "blog/"
        elif dest_rel.startswith("docs/blog/"):
            dest_rel = "blog/"
        elif dest_rel.startswith("docs/handoffs/"):
            dest_rel = "handoffs/"
        elif dest_rel.startswith("docs/ideas/"):
            dest_rel = dest_rel.replace("docs/ideas/", "")
        elif dest_rel.startswith(".superpowers/brainstorm/"):
            dest_rel = "specs/"

        dest = workspace / dest_rel.rstrip("/")

        # Verify destination is within workspace bounds
        try:
            dest.resolve().relative_to(workspace.resolve())
        except ValueError:
            print("ERROR=path_escape")
            print(f"ERROR_DETAIL=Destination {dest} escapes workspace", flush=True)
            return 1

        try:
            if source.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                # Copy contents into destination, merging
                for item in source.iterdir():
                    dest_item = dest / item.name
                    if item.is_dir():
                        shutil.copytree(str(item), str(dest_item), dirs_exist_ok=True)
                    else:
                        shutil.copy2(str(item), str(dest_item))
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(source), str(dest))
            migrated += 1
        except OSError as e:
            print("ERROR=copy_failed")
            print(f"ERROR_DETAIL={rel_path}: {e}", flush=True)
            return 1

    print(f"MIGRATED={migrated}")
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1

    subcmd = sys.argv[1]

    if subcmd == "scan":
        project = Path(sys.argv[2]).resolve()
        return cmd_scan(project)

    elif subcmd == "migrate":
        if len(sys.argv) < 4:
            print("ERROR=missing_args")
            print("ERROR_DETAIL=migrate requires <project> <workspace> paths=<csv>",
                  flush=True)
            return 1
        project = Path(sys.argv[2]).resolve()
        workspace = Path(sys.argv[3]).resolve()
        params = parse_args(sys.argv[4:])
        return cmd_migrate(project, workspace, params)

    else:
        print("ERROR=unknown_subcommand")
        print(f"ERROR_DETAIL=Unknown subcommand: {subcmd}. Valid: scan, migrate",
              flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
