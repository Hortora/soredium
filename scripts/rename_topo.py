"""Topology discovery for workspace and project renames.

Shared layer: finds every location that references a workspace name
across a family's canonical, clone, slot and attic directories.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Finding:
    location: str
    current: str
    proposed: str
    category: str  # "mechanical" | "historical" | "advisory"


@dataclass
class WorkspaceDir:
    path: Path
    layout: str  # "canonical" | "clone" | "slot" | "attic" | "quarantine"
    active: bool
    rename_dir: bool


def discover_workspace_dirs(
    family_root: Path,
    old_name: str,
    public_dir: Path | None = None,
) -> list[WorkspaceDir]:
    """Find every workspace directory matching old_name in the family."""
    if public_dir is None:
        public_dir = family_root.parent / "public"

    dirs: list[WorkspaceDir] = []

    canonical = public_dir / old_name
    if canonical.is_dir():
        dirs.append(WorkspaceDir(
            path=canonical, layout="canonical", active=True, rename_dir=True))

    clone_base = family_root / "clone"
    if clone_base.is_dir():
        for project_dir in sorted(clone_base.iterdir()):
            if not project_dir.is_dir():
                continue
            for ws_name in (f"wsp-{old_name}", f"work-{old_name}"):
                ws = project_dir / ws_name
                if ws.is_dir():
                    dirs.append(WorkspaceDir(
                        path=ws, layout="clone", active=True,
                        rename_dir=ws_name.startswith("wsp-")))

    for sub, layout, active in [
        ("slots", "slot", True),
        (os.path.join("slots", "attic"), "attic", False),
        (os.path.join("slots", "quarantine"), "quarantine", False),
    ]:
        base = family_root / sub
        if not base.is_dir():
            continue
        for slot_dir in sorted(base.iterdir()):
            if not slot_dir.is_dir():
                continue
            for ws_name in (f"wsp-{old_name}", f"work-{old_name}"):
                ws = slot_dir / ws_name
                if ws.is_dir():
                    dirs.append(WorkspaceDir(
                        path=ws, layout=layout, active=active,
                        rename_dir=False))

    return dirs


def find_alternates(
    dirs: list[WorkspaceDir],
    old_path: str,
    new_path: str,
) -> list[Finding]:
    """Find .git/objects/info/alternates referencing old_path."""
    findings: list[Finding] = []
    for d in dirs:
        alt_file = d.path / ".git" / "objects" / "info" / "alternates"
        if not alt_file.exists():
            continue
        content = alt_file.read_text()
        if old_path in content:
            findings.append(Finding(
                location=str(alt_file),
                current=content.strip(),
                proposed=content.replace(old_path, new_path).strip(),
                category="mechanical",
            ))
    return findings


def find_remotes(
    dirs: list[WorkspaceDir],
    old_path: str,
    new_path: str,
) -> list[Finding]:
    """Find git remotes referencing old_path."""
    findings: list[Finding] = []
    for d in dirs:
        result = subprocess.run(
            ["git", "-C", str(d.path), "remote", "-v"],
            capture_output=True, text=True)
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            if old_path in line and "(fetch)" in line:
                parts = line.split()
                remote_name = parts[0]
                remote_url = parts[1]
                findings.append(Finding(
                    location=f"{d.path}:{remote_name}",
                    current=remote_url,
                    proposed=remote_url.replace(old_path, new_path),
                    category="mechanical",
                ))
    return findings


def find_symlinks(
    family_root: Path,
    old_path: str,
    new_path: str,
) -> list[Finding]:
    """Find wksp/proj symlinks pointing at old_path."""
    findings: list[Finding] = []
    search_dirs = []

    for child in sorted(family_root.iterdir()):
        if child.is_dir() and (child / ".git").exists():
            search_dirs.append(child)

    clone_base = family_root / "clone"
    if clone_base.is_dir():
        for project_dir in sorted(clone_base.iterdir()):
            if not project_dir.is_dir():
                continue
            for sub in sorted(project_dir.iterdir()):
                if sub.is_dir() and (sub / ".git").exists():
                    search_dirs.append(sub)

    for base in search_dirs:
        for name in ("wksp", "proj"):
            link = base / name
            if link.is_symlink():
                target = os.readlink(link)
                if old_path in target:
                    findings.append(Finding(
                        location=str(link),
                        current=target,
                        proposed=target.replace(old_path, new_path),
                        category="mechanical",
                    ))
    return findings


def find_file_references(
    file_path: Path,
    old_patterns: list[str],
    new_patterns: list[str],
) -> list[Finding]:
    """Find lines in a file containing old patterns, skipping historical sections."""
    if not file_path.exists():
        return []
    findings: list[Finding] = []
    lines = file_path.read_text().splitlines()
    in_historical = False
    for i, line in enumerate(lines, 1):
        if line.startswith("#"):
            heading = line.strip().lstrip("#").strip().lower()
            if any(w in heading for w in ("history", "migration", "retro", "legacy")):
                in_historical = True
            else:
                in_historical = False
        if in_historical:
            continue
        for old_p, new_p in zip(old_patterns, new_patterns):
            if old_p in line:
                findings.append(Finding(
                    location=f"{file_path}:{i}",
                    current=line.strip(),
                    proposed=line.replace(old_p, new_p).strip(),
                    category="mechanical",
                ))
                break
    return findings


def find_worklog_rows(
    old_path: str,
    new_path: str,
    db_path: Path | None = None,
) -> list[Finding]:
    """Find worklog repos table rows with old_path."""
    if db_path is None:
        db_path = Path.home() / ".hortora" / "worklog.db"
    if not db_path.exists():
        return []
    findings: list[Finding] = []
    conn = sqlite3.connect(str(db_path))
    try:
        for row in conn.execute(
            "SELECT id, path FROM repos WHERE path LIKE ?",
            (f"%{old_path}%",),
        ):
            findings.append(Finding(
                location=f"worklog:repos:id={row[0]}",
                current=row[1],
                proposed=row[1].replace(old_path, new_path),
                category="mechanical",
            ))
    finally:
        conn.close()
    return findings


def mangle_path(path: str) -> str:
    """Encode a path the way Claude Code does for project directories."""
    return path.replace("/", "-")


def find_claude_projects(
    old_path: str,
    new_path: str,
    projects_dir: Path | None = None,
) -> list[Finding]:
    """Find .claude/projects/ directories keyed by old_path."""
    if projects_dir is None:
        projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.is_dir():
        return []
    old_mangled = mangle_path(old_path)
    new_mangled = mangle_path(new_path)
    findings: list[Finding] = []
    for d in sorted(projects_dir.iterdir()):
        if d.is_dir() and d.name == old_mangled:
            findings.append(Finding(
                location=str(d),
                current=d.name,
                proposed=new_mangled,
                category="mechanical",
            ))
    return findings
