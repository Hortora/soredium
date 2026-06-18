#!/usr/bin/env python3
"""
Install git hooks from skill directories into a project's .githooks/ folder.

Called by workspace-init Step 7c. Replaces cp + chmod + git config blocks
that trigger Claude Code permission prompts.

Usage:
    python3 hook_install.py <subcommand> <project_path> [key=value args...]

Subcommands:
    install    Copy a hook file to .githooks/ and make executable
    configure  Set git config core.hooksPath to .githooks

Output (KEY=value lines):
    INSTALLED=yes|skipped      (install)
    CONFIGURED=yes             (configure)
    ERROR=<code>               (on failure)
    ERROR_DETAIL=<message>     (on failure)

Exit codes:
    0  success
    1  missing required args or I/O error
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from common import parse_args


def cmd_install(project: Path, params: dict[str, str]) -> int:
    git_dir = project / ".git"
    if not git_dir.is_dir():
        print("ERROR=no_git_dir")
        print(f"ERROR_DETAIL=No .git directory in {project}", flush=True)
        return 1

    hook_src = params.get("hook-src", "")
    hook_name = params.get("hook-name", "")

    if not hook_src:
        print("ERROR=missing_args")
        print("ERROR_DETAIL=hook-src= is required", flush=True)
        return 1

    if not hook_name:
        print("ERROR=missing_args")
        print("ERROR_DETAIL=hook-name= is required", flush=True)
        return 1

    source = Path(hook_src).resolve()
    if not source.is_file():
        print("ERROR=source_not_found")
        print(f"ERROR_DETAIL=Hook source does not exist: {source}", flush=True)
        return 1

    hooks_dir = project / ".githooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    dest = hooks_dir / hook_name
    if dest.exists():
        print("INSTALLED=skipped")
        return 0

    try:
        shutil.copy2(str(source), str(dest))
        # Make executable
        st = os.stat(str(dest))
        os.chmod(str(dest), st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as e:
        print("ERROR=copy_failed")
        print(f"ERROR_DETAIL={e}", flush=True)
        return 1

    print("INSTALLED=yes")
    return 0


def cmd_configure(project: Path) -> int:
    git_dir = project / ".git"
    if not git_dir.is_dir():
        print("ERROR=no_git_dir")
        print(f"ERROR_DETAIL=No .git directory in {project}", flush=True)
        return 1

    try:
        subprocess.run(
            ["git", "-C", str(project), "config", "core.hooksPath", ".githooks"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        print("ERROR=git_config_failed")
        print(f"ERROR_DETAIL={e.stderr.strip()}", flush=True)
        return 1

    print("CONFIGURED=yes")
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1

    subcmd = sys.argv[1]
    project = Path(sys.argv[2]).resolve()

    if not project.is_dir():
        print("ERROR=project_not_found")
        print(f"ERROR_DETAIL=Path does not exist: {project}", flush=True)
        return 1

    if subcmd == "install":
        params = parse_args(sys.argv[3:])
        return cmd_install(project, params)

    elif subcmd == "configure":
        return cmd_configure(project)

    else:
        print("ERROR=unknown_subcommand")
        print(f"ERROR_DETAIL=Unknown subcommand: {subcmd}. Valid: install, configure",
              flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
