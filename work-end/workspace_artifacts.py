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

import re
import sys
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


_MD_IMG = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
_HTML_IMG = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']')
_SKIP_PREFIXES = ("http://", "https://", "chrome://", "data:")


def extract_image_refs(md_path: Path, root: Path) -> list[str]:
    """Extract image paths referenced by a markdown file.

    Returns paths relative to root, matching scan() convention.
    Only includes references where the resolved file exists on disk.
    Logs a warning to stderr for missing references.
    """
    text = md_path.read_text(errors="replace")
    seen: set[str] = set()
    results: list[str] = []

    for pattern in (_MD_IMG, _HTML_IMG):
        for match in pattern.finditer(text):
            raw = match.group(1).split(" ")[0]
            if any(raw.startswith(p) for p in _SKIP_PREFIXES):
                continue
            if "{" in raw or "}" in raw:
                continue
            resolved = (md_path.parent / raw).resolve()
            if not resolved.is_file():
                print(f"WARNING: image ref not found: {raw} (in {md_path})",
                      file=sys.stderr)
                continue
            try:
                rel = str(resolved.relative_to(root.resolve()))
            except ValueError:
                continue
            if rel not in seen:
                seen.add(rel)
                results.append(rel)

    return results


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

        if ext == ".md":
            seen = set(entries)
            for entry in list(entries):
                md_path = workspace / entry
                for img_ref in extract_image_refs(md_path, workspace):
                    if img_ref not in seen:
                        seen.add(img_ref)
                        entries.append(img_ref)

        found[category] = sorted(entries)

    return found
