#!/usr/bin/env python3
"""Squash-review marker: records the branch tip that git-squash reviewed.

The marker is a git ref, refs/squash-reviewed/<branch>, holding the tip SHA
at the moment the review finished. Any later commit or rebase makes it stale.

Usage:
    python3 squash_marker.py mark   <repo> [branch=<name>]
    python3 squash_marker.py status <repo> branch=<name> base=<name>
    python3 squash_marker.py clear  <repo> branch=<name>

Output (KEY=value lines):
    mark:   MARKED=<sha>  BRANCH=<name>
    status: REVIEW_NEEDED=yes|no  [REASON=<text>]
    clear:  CLEARED=<name>
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

REF_PREFIX = "refs/squash-reviewed/"


def marker_ref(branch: str) -> str:
    return f"{REF_PREFIX}{branch}"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _rev(repo: Path, ref: str) -> str:
    r = _git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
    return r.stdout.strip() if r.returncode == 0 else ""


def mark(repo: Path, branch: Optional[str] = None) -> str:
    """Record the branch's current tip as reviewed. Returns the SHA."""
    if not branch:
        branch = _git(repo, "branch", "--show-current").stdout.strip()
        if not branch:
            raise RuntimeError(f"{repo}: HEAD is detached and no branch was given")
    tip = _rev(repo, f"refs/heads/{branch}")
    if not tip:
        raise RuntimeError(f"{repo}: branch '{branch}' does not exist")
    r = _git(repo, "update-ref", marker_ref(branch), tip)
    if r.returncode != 0:
        raise RuntimeError(f"{repo}: could not write {marker_ref(branch)}: {r.stderr.strip()}")
    return tip


def clear(repo: Path, branch: str) -> None:
    if _rev(repo, marker_ref(branch)):
        _git(repo, "update-ref", "-d", marker_ref(branch))


def review_status(repo: Path, branch: str, base: str) -> Optional[str]:
    """Return None when the branch may land, otherwise the reason a squash review is needed."""
    tip = _rev(repo, f"refs/heads/{branch}")
    if not tip:
        raise RuntimeError(f"{repo}: branch '{branch}' does not exist")
    r = _git(repo, "rev-list", "--count", f"{base}..{tip}")
    if r.returncode != 0:
        raise RuntimeError(f"{repo}: cannot count commits on '{branch}' ahead of '{base}': "
                           f"{r.stderr.strip()}")
    ahead = int(r.stdout.strip())
    if ahead <= 1:
        return None

    marker = _rev(repo, marker_ref(branch))
    if not marker:
        return f"no squash review recorded for {ahead} commits — run git-squash"
    if marker == tip:
        return None
    if _git(repo, "merge-base", "--is-ancestor", marker, tip).returncode == 0:
        added = _git(repo, "rev-list", "--count", f"{marker}..{tip}").stdout.strip()
        return f"{added} commit(s) added since the squash review — run git-squash again"
    return ("the squash review marker is not part of this branch's history — the branch was "
            "rebased or rewritten after the review, or the marker is left over from other "
            "work. Run git-squash again")


def _parse(args: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in args:
        if "=" in a:
            k, _, v = a.partition("=")
            out[k] = v
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in ("mark", "status", "clear"):
        print(__doc__, file=sys.stderr)
        return 1
    command, repo = argv[1], Path(argv[2])
    opts = _parse(argv[3:])
    try:
        if command == "mark":
            branch = opts.get("branch") or _git(repo, "branch", "--show-current").stdout.strip()
            sha = mark(repo, branch or None)
            print(f"MARKED={sha}")
            print(f"BRANCH={branch}")
        elif command == "status":
            if "branch" not in opts or "base" not in opts:
                print("ERROR=branch= and base= are required", file=sys.stderr)
                return 1
            reason = review_status(repo, opts["branch"], opts["base"])
            print(f"REVIEW_NEEDED={'yes' if reason else 'no'}")
            if reason:
                print(f"REASON={reason}")
        else:
            if "branch" not in opts:
                print("ERROR=branch= is required", file=sys.stderr)
                return 1
            clear(repo, opts["branch"])
            print(f"CLEARED={opts['branch']}")
    except RuntimeError as e:
        print(f"ERROR={e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
