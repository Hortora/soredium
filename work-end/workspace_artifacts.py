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
    "specs":     {"ext": ".md",  "exclude_names": {"INDEX.md"}, "exclude_dirs": set()},
    "adr":       {"ext": ".md",  "exclude_names": {"INDEX.md"}, "exclude_dirs": set(),
                  "alt_paths": ["docs/adr"]},
    "blog":      {"ext": ".md",  "exclude_names": {"INDEX.md"}, "exclude_dirs": set()},
    "plans":     {"ext": ".md",  "exclude_names": {"INDEX.md"}, "exclude_dirs": {"attic"}},
    "snapshots": {"ext": None,   "exclude_names": {"INDEX.md"}, "exclude_dirs": set()},
}


def _scan_dir(workspace: Path, cat_dir: Path, ext: str | None,
              exclude_names: set[str], exclude_dirs: set[str]) -> list[str]:
    """Recursively scan a category directory for promotable artifacts."""
    entries: list[str] = []
    if not cat_dir.is_dir():
        return entries
    for f in cat_dir.iterdir():
        if f.name in exclude_names:
            continue
        if f.is_dir():
            if f.name in exclude_dirs:
                continue
            entries.extend(_scan_dir(workspace, f, ext, exclude_names, exclude_dirs))
            continue
        if ext is not None and f.suffix != ext:
            continue
        entries.append(str(f.relative_to(workspace)))
    return entries


def scan(workspace: Path) -> dict[str, list[str]]:
    """Scan workspace for promotable artifacts.

    Returns category -> sorted list of paths relative to workspace root.
    Recurses into subdirectories (e.g. specs/issue-NNN-slug/).
    Also checks alternate paths (e.g. docs/adr/ in addition to adr/).
    """
    found: dict[str, list[str]] = {}

    for category, cfg in CATEGORIES.items():
        ext = cfg["ext"]
        exclude_names = cfg["exclude_names"]
        exclude_dirs = cfg.get("exclude_dirs", set())

        entries = _scan_dir(workspace, workspace / category, ext, exclude_names, exclude_dirs)

        for alt in cfg.get("alt_paths", []):
            entries.extend(_scan_dir(workspace, workspace / alt, ext, exclude_names, exclude_dirs))

        found[category] = sorted(entries)

    return found
