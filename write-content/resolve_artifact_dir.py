#!/usr/bin/env python3
"""
resolve_artifact_dir.py — Unified artifact directory resolution with slot-escape detection.

Resolves the authoring directory for any artifact type (blog, adr, specs, plans)
from CLAUDE.md content. When a project path is provided, durable artifacts
(blog, specs, adr) default to the project's docs/<type>/ directory. Plans
default to the workspace (they are transient and never land).

When running inside a slot, detects absolute paths that escape the slot boundary
and falls back to the default.

Usage:
    python3 resolve_artifact_dir.py <type> <workspace> <claude_md_path> [slot_root=<path>] [project=<path>]

Output:
    ARTIFACT_DIR=<resolved path>
    WARNING=<message if escape detected, empty otherwise>
"""

import os
import re
import sys
from pathlib import Path

FIELD_NAMES = {
    "adr": "ADR",
    "blog": "Blog",
    "specs": "Specs",
    "plans": "Plans",
}

_DURABLE_TYPES = {"blog", "specs", "adr"}


def _parse_custom_dir(artifact_type: str, claude_text: str) -> str | None:
    field = FIELD_NAMES.get(artifact_type, artifact_type.title())
    m = re.search(rf"\*\*{field} directory:\*\*\s*`([^`]+)`", claude_text)
    if m:
        return m.group(1).rstrip("/")
    return None


def _resolve_path(raw: str, workspace: str) -> str:
    expanded = os.path.expanduser(raw)
    p = Path(expanded)
    if p.is_absolute():
        return str(p)
    return str(Path(workspace) / expanded)


def _is_inside(path: str, root: str) -> bool:
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


def _default_dir(artifact_type: str, workspace: str, project: str | None) -> str:
    if project and artifact_type in _DURABLE_TYPES:
        return str(Path(project) / "docs" / artifact_type)
    return str(Path(workspace) / artifact_type)


def resolve_with_warning(
    artifact_type: str,
    workspace: str,
    claude_text: str,
    slot_root: str | None = None,
    project: str | None = None,
) -> tuple[str, str]:
    default = _default_dir(artifact_type, workspace, project)
    raw = _parse_custom_dir(artifact_type, claude_text)

    if raw is None:
        return default, ""

    resolved = _resolve_path(raw, workspace)

    if slot_root is not None:
        if not _is_inside(resolved, slot_root):
            warning = (
                f"Artifact directory '{resolved}' escapes slot boundary "
                f"'{slot_root}'. Falling back to {default}."
            )
            return default, warning

    return resolved, ""


def resolve(
    artifact_type: str,
    workspace: str,
    claude_text: str,
    slot_root: str | None = None,
    project: str | None = None,
) -> str:
    path, _ = resolve_with_warning(artifact_type, workspace, claude_text, slot_root, project)
    return path


def main() -> int:
    if len(sys.argv) < 4:
        print("Usage: resolve_artifact_dir.py <type> <workspace> <claude_md_path> [slot_root=<path>] [project=<path>]")
        return 1

    artifact_type = sys.argv[1]
    workspace = sys.argv[2]
    claude_md_path = sys.argv[3]

    kv = {}
    for arg in sys.argv[4:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            kv[k] = v

    slot_root = kv.get("slot_root")
    project = kv.get("project")

    try:
        claude_text = Path(claude_md_path).read_text()
    except FileNotFoundError:
        claude_text = ""

    path, warning = resolve_with_warning(artifact_type, workspace, claude_text, slot_root, project)
    print(f"ARTIFACT_DIR={path}")
    if warning:
        print(f"WARNING={warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
