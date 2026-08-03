#!/usr/bin/env python3
"""
Pre-push hook: enforce lifecycle state gates.

Blocks pushes to main/base branch unless the lifecycle state has passed
the artifact promotion gate — workspace and project promotion complete
(closing:pushed or later).

Install: symlink or copy to .git/hooks/pre-push in each repo.

Usage (git pre-push protocol):
    pre-push <remote-name> <remote-url>
    stdin: <local-ref> <local-sha> <remote-ref> <remote-sha> per line
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

_dir = Path(__file__).parent
if str(_dir) not in sys.path:
    sys.path.insert(0, str(_dir))
from lifecycle import read_state

PUSH_ALLOWED_STATES = frozenset({
    'closing:pushed', 'closing:merged', 'closing:stamped',
})


@dataclass
class HookResult:
    blocked: bool
    message: str = ""


def find_meta(repo_root: Path | None = None) -> Path | None:
    """Find .meta via wksp/ symlink, $WORKSPACE env, or local design/.meta."""
    if repo_root is None:
        repo_root = Path.cwd()

    wksp = repo_root / "wksp"
    if wksp.is_symlink():
        if wksp.is_dir():
            candidate = wksp.resolve() / "design" / ".meta"
            if candidate.exists():
                return candidate
        else:
            return None

    ws_env = os.environ.get("WORKSPACE")
    if ws_env:
        ws_path = Path(ws_env)
        if ws_path.is_dir():
            candidate = ws_path / "design" / ".meta"
            if candidate.exists():
                return candidate

    local = repo_root / "design" / ".meta"
    if local.exists():
        return local

    return None


def hook_check(
    meta_path: Path,
    push_to_main: bool = False,
    base_branch: str = "main",
) -> HookResult:
    """Check whether a push should be allowed given the lifecycle state."""
    state = read_state(meta_path)
    if state is None:
        return HookResult(blocked=False)
    if not push_to_main:
        return HookResult(blocked=False)
    if state in PUSH_ALLOWED_STATES:
        return HookResult(blocked=False)
    return HookResult(
        blocked=True,
        message=f"BLOCKED: state is '{state}'. Run work-end to complete the close sequence.",
    )


def main() -> int:
    meta = find_meta()
    if meta is None:
        return 0

    for line in sys.stdin:
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        remote_ref = parts[2]
        is_main = remote_ref.endswith('/main') or remote_ref.endswith('/master')
        if is_main:
            result = hook_check(meta, push_to_main=True)
            if result.blocked:
                print(result.message, file=sys.stderr)
                return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
