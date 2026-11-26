"""Structured closure refs in workspace git refs (#618).

Records what happened when a branch closed — the complement of branch_base.py's
creation-time refs.  Stored as git refs in the workspace repo:

  refs/soredium/closed/<branch>       last real commit (pre-stamp)
  refs/soredium/closed-meta/<branch>  blob with structured metadata
"""
from __future__ import annotations

import datetime
import subprocess
from pathlib import Path
from typing import Optional

from git_util import git


CLOSED_REF = "refs/soredium/closed"
META_REF = "refs/soredium/closed-meta"


def _out(repo: Path, *args: str) -> str:
    result = git(repo, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def record(workspace: Path, branch: str, *,
           landed_sha: str,
           base_branch: str,
           issue: str = "",
           promoted: Optional[list[str]] = None,
           published: Optional[list[str]] = None) -> str:
    """Write closure refs for a closed branch. Returns the meta blob SHA."""
    git(workspace, "update-ref", f"{CLOSED_REF}/{branch}", landed_sha)

    lines = [
        f"landed_sha: {landed_sha}",
        f"landed_on: {base_branch}",
        f"promoted: {','.join(promoted or [])}",
        f"published: {','.join(published or [])}",
        f"closed: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"issue: {issue}",
    ]
    blob_content = "\n".join(lines) + "\n"
    result = subprocess.run(
        ["git", "-C", str(workspace), "hash-object", "-w", "--stdin"],
        input=blob_content, capture_output=True, text=True)
    blob_sha = result.stdout.strip()
    if result.returncode != 0 or not blob_sha:
        return ""
    git(workspace, "update-ref", f"{META_REF}/{branch}", blob_sha)
    return blob_sha


def read(workspace: Path, branch: str) -> Optional[dict[str, str]]:
    """Read closure metadata for a branch. Returns None if no ref exists."""
    meta_sha = _out(workspace, "rev-parse", "--verify", "-q", f"{META_REF}/{branch}")
    if not meta_sha:
        return None
    content = _out(workspace, "cat-file", "blob", meta_sha)
    if not content:
        return None
    result: dict[str, str] = {}
    for line in content.splitlines():
        if ": " in line:
            key, _, value = line.partition(": ")
            result[key.strip()] = value.strip()
    return result


def closed_sha(workspace: Path, branch: str) -> str:
    """The last real commit (pre-stamp) of a closed branch, "" if not recorded."""
    return _out(workspace, "rev-parse", "--verify", "-q", f"{CLOSED_REF}/{branch}")


def list_closed(workspace: Path) -> list[str]:
    """Branch names that have closure refs."""
    output = _out(workspace, "for-each-ref", "--format=%(refname:lstrip=3)",
                  f"{CLOSED_REF}/")
    return [name for name in output.splitlines() if name]


def clear(workspace: Path, branch: str) -> None:
    """Remove closure refs for a branch."""
    git(workspace, "update-ref", "-d", f"{CLOSED_REF}/{branch}")
    git(workspace, "update-ref", "-d", f"{META_REF}/{branch}")
