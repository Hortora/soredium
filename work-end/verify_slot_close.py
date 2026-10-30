#!/usr/bin/env python3
"""Thin CLI wrapper for close-time verification.
All check logic: verification/close_checks.py. Composition: verification/close_verify.py.
"""
import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, _repo_root)
_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
from common import parse_args
from plan_io import parse_covers_qualified
from slot_io import parse_slot as _parse_slot
from verification.close_checks import resolve_canonical_repos
from verification.close_verify import verify


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: verify_slot_close.py <project> branch=<name> workspace=<path> "
              "[covers=N,M] [issue_repo=<repo>] [slot_dir=<path>] [on_main=yes]", file=sys.stderr)
        return 1
    project = Path(sys.argv[1])
    opts = parse_args(sys.argv[2:])
    branch = opts.get("branch", "")
    workspace_str = opts.get("workspace", "")
    if not branch:
        print("ERROR=MISSING_ARGS\nERROR_DETAIL=branch= is required")
        return 1
    if not workspace_str:
        print("ERROR=MISSING_ARGS\nERROR_DETAIL=workspace= is required")
        return 1
    workspace = Path(workspace_str)
    base = opts.get("base_branch", "main")
    on_main = opts.get("on_main", "no") == "yes"
    covers_str = opts.get("covers", "")
    covers = [ref.number for ref in parse_covers_qualified(covers_str)] if covers_str else None
    issue_repo = opts.get("issue_repo", "")
    slot_dir_str = opts.get("slot_dir", "")
    slot_dir = Path(slot_dir_str) if slot_dir_str else None
    canonical_repos, covers_repos = None, None
    if slot_dir:
        si = _parse_slot(slot_dir)
        covers_repos = set(si.repos) if si else None
        canonical_repos = resolve_canonical_repos(slot_dir, covers_repos=covers_repos)
    verify(project, branch, workspace, base, covers, issue_repo=issue_repo,
           slot_dir=slot_dir, canonical_repos=canonical_repos,
           on_main=on_main, covers_repos=covers_repos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
