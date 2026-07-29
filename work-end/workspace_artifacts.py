#!/usr/bin/env python3
"""
Central artifact path resolver for soredium workspaces.

Given a workspace root Path, returns all promotable artifacts grouped
by category. Works identically for original workspaces, per-repo
subdirectories of multi-repo workspaces, and worktree slots — the
wksp symlink already resolves to the correct root before this module
is called.

No branch parameter: artifacts are not organized by branch.
No repo-name parameter: wksp symlink handles per-repo resolution.
"""

from pathlib import Path

CATEGORIES: dict[str, dict] = {
    "specs":     {"ext": ".md",  "exclude_names": {"INDEX.md"}},
    "adr":       {"ext": ".md",  "exclude_names": {"INDEX.md"}},
    "blog":      {"ext": ".md",  "exclude_names": {"INDEX.md"}},
    "plans":     {"ext": ".md",  "exclude_names": {"INDEX.md"}},
    "snapshots": {"ext": None,   "exclude_names": {"INDEX.md"}},
}


def scan(workspace: Path) -> dict[str, list[str]]:
    """Scan workspace for promotable artifacts.

    Returns category -> sorted list of paths relative to workspace root.
    """
    found: dict[str, list[str]] = {}

    for category, cfg in CATEGORIES.items():
        cat_dir = workspace / category
        if not cat_dir.is_dir():
            found[category] = []
            continue

        ext = cfg["ext"]
        exclude_names = cfg["exclude_names"]

        entries = []
        for f in cat_dir.iterdir():
            if f.name in exclude_names:
                continue
            if f.is_dir():
                continue
            if ext is not None and f.suffix != ext:
                continue
            entries.append(str(f.relative_to(workspace)))

        found[category] = sorted(entries)

    return found
