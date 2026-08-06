#!/usr/bin/env python3
"""
garden_commit.py — Atomic git operations for the Hortora knowledge garden

Subcommands:
  commit <garden-path> files=<csv> message=<msg>
      Stage entry files, index directories, and garden.db, then commit.
      Output: COMMITTED=yes|no

  push <garden-path>
      Pull --rebase then push. Skips if no GitHub remote.
      Output: PUSHED=yes|no [REASON=no_remote]

  commit-and-push <garden-path> files=<csv> message=<msg>
      Commit then push in one call.
      Output: COMMITTED=yes|no PUSHED=yes|no
"""

import subprocess
import sys
from pathlib import Path

_INDEX_DIRS = ["_summaries", "_index", "labels"]
_INDEX_FILES = ["GARDEN.md", "garden.db"]


def _run(args: list[str], cwd: str) -> tuple[int, str, str]:
    result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout, result.stderr


def _has_pushable_remote(garden: str) -> bool:
    rc, url, _ = _run(["git", "remote", "get-url", "origin"], garden)
    return rc == 0 and bool(url.strip())


def commit(garden: str, files: list[str], message: str) -> dict:
    garden_path = Path(garden)
    if not garden_path.is_dir() or not (garden_path / ".git").exists():
        return {"committed": False, "error": f"not a git repo: {garden}"}

    for f in files:
        _run(["git", "add", f], garden)

    for d in _INDEX_DIRS:
        if (garden_path / d).is_dir():
            _run(["git", "add", d], garden)

    for f in _INDEX_FILES:
        if (garden_path / f).exists():
            _run(["git", "add", f], garden)

    _run(["git", "add", "--update"], garden)

    rc, status, _ = _run(["git", "diff", "--cached", "--quiet"], garden)
    if rc == 0:
        return {"committed": False}

    rc, _, stderr = _run(["git", "commit", "-m", message], garden)
    if rc != 0:
        return {"committed": False, "error": stderr.strip()}

    return {"committed": True}


def push(garden: str) -> dict:
    garden_path = Path(garden)
    if not garden_path.is_dir() or not (garden_path / ".git").exists():
        return {"pushed": False, "error": f"not a git repo: {garden}"}

    if not _has_pushable_remote(garden):
        return {"pushed": False, "reason": "no_remote"}

    rc, _, stderr = _run(["git", "pull", "--rebase", "origin", "main"], garden)
    if rc != 0:
        _run(["git", "rebase", "--abort"], garden)
        return {"pushed": False, "error": f"rebase conflict: {stderr.strip()}"}

    rc, _, stderr = _run(["git", "push", "origin", "main"], garden)
    if rc != 0:
        return {"pushed": False, "error": f"push failed: {stderr.strip()}"}

    return {"pushed": True}


def commit_and_push(garden: str, files: list[str], message: str) -> dict:
    result = commit(garden, files, message)
    if not result["committed"]:
        return result

    push_result = push(garden)
    result.update(push_result)
    return result


def _parse_args() -> dict:
    parsed = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            key, val = arg.split("=", 1)
            parsed[key] = val
        else:
            if "subcommand" not in parsed:
                parsed["subcommand"] = arg
            elif "garden" not in parsed:
                parsed["garden"] = arg
    return parsed


def main() -> None:
    if len(sys.argv) < 3:
        print("ERROR=missing_args", file=sys.stderr)
        sys.exit(1)

    args = _parse_args()
    subcmd = args.get("subcommand")
    garden = args.get("garden", "")

    if not garden:
        print("ERROR=missing_garden_path")
        sys.exit(1)

    files_str = args.get("files", "")
    files = [f.strip() for f in files_str.split(",") if f.strip()] if files_str else []
    message = args.get("message", "")

    if subcmd == "commit":
        result = commit(garden, files, message)
        print(f"COMMITTED={'yes' if result['committed'] else 'no'}")
        if "error" in result:
            print(f"ERROR={result['error']}")

    elif subcmd == "push":
        result = push(garden)
        print(f"PUSHED={'yes' if result['pushed'] else 'no'}")
        if "reason" in result:
            print(f"REASON={result['reason']}")
        if "error" in result:
            print(f"ERROR={result['error']}")

    elif subcmd == "commit-and-push":
        result = commit_and_push(garden, files, message)
        print(f"COMMITTED={'yes' if result['committed'] else 'no'}")
        print(f"PUSHED={'yes' if result.get('pushed') else 'no'}")
        if "error" in result:
            print(f"ERROR={result['error']}")

    else:
        print(f"ERROR=unknown_subcommand subcommand={subcmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
