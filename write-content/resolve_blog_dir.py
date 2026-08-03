#!/usr/bin/env python3
"""
resolve_blog_dir.py — Blog directory resolution with slot-escape detection.

Resolves the blog directory from CLAUDE.md content. When running inside a slot,
detects absolute paths that escape the slot boundary and falls back to
$WORKSPACE/blog/ to prevent artifacts landing in the wrong repo.

Usage:
    python3 resolve_blog_dir.py <workspace> <claude_md_path> [slot_root=<path>]

Output:
    BLOG_DIR=<resolved path>
    WARNING=<message if escape detected, empty otherwise>
"""

import os
import re
import sys
from pathlib import Path


def _parse_blog_dir(claude_text: str) -> str | None:
    """Extract Blog directory from CLAUDE.md content. Returns raw value or None."""
    m = re.search(r"\*\*Blog directory:\*\*\s*`([^`]+)`", claude_text)
    if m:
        return m.group(1).rstrip("/")
    return None


def _resolve_path(raw: str, workspace: str) -> str:
    """Resolve a blog dir path — expand ~ and make absolute relative to workspace."""
    expanded = os.path.expanduser(raw)
    p = Path(expanded)
    if p.is_absolute():
        return str(p)
    return str(Path(workspace) / expanded)


def _is_inside(path: str, root: str) -> bool:
    """Check if path is inside root (resolved, no symlink following)."""
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


def resolve_with_warning(
    workspace: str,
    claude_text: str,
    slot_root: str | None = None,
) -> tuple[str, str]:
    """Resolve blog directory and return (path, warning).

    Warning is non-empty when an absolute path escapes the slot boundary.
    """
    default = str(Path(workspace) / "blog")
    raw = _parse_blog_dir(claude_text)

    if raw is None:
        return default, ""

    resolved = _resolve_path(raw, workspace)

    if slot_root is not None:
        if not _is_inside(resolved, slot_root):
            warning = (
                f"Blog directory '{resolved}' escapes slot boundary '{slot_root}'. "
                f"Falling back to {default}."
            )
            return default, warning

    return resolved, ""


def resolve(
    workspace: str,
    claude_text: str,
    slot_root: str | None = None,
) -> str:
    """Resolve blog directory. Returns the path (falls back on escape)."""
    path, _ = resolve_with_warning(workspace, claude_text, slot_root)
    return path


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: resolve_blog_dir.py <workspace> <claude_md_path> [slot_root=<path>]")
        return 1

    workspace = sys.argv[1]
    claude_md_path = sys.argv[2]

    kv = {}
    for arg in sys.argv[3:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            kv[k] = v

    slot_root = kv.get("slot_root")

    try:
        claude_text = Path(claude_md_path).read_text()
    except FileNotFoundError:
        claude_text = ""

    path, warning = resolve_with_warning(workspace, claude_text, slot_root)
    print(f"BLOG_DIR={path}")
    if warning:
        print(f"WARNING={warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
