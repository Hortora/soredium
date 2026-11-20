"""Tests for scripts/rename_topo.py — topology discovery for workspace renames."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                   capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"],
                   capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
                   capture_output=True, check=True)
    return path


@pytest.fixture
def family(tmp_path):
    """Minimal family layout with canonical, clone, slot and attic."""
    root = tmp_path / "hortora"
    root.mkdir()

    public = tmp_path / "public"
    canonical = public / "old-name"
    _init_repo(canonical)

    project = root / "myproject"
    _init_repo(project)

    clone_root = root / "clone" / "myproject"
    clone_root.mkdir(parents=True)
    clone_ws = clone_root / "wsp-old-name"
    _init_repo(clone_ws)
    alt_dir = clone_ws / ".git" / "objects" / "info"
    alt_dir.mkdir(parents=True, exist_ok=True)
    (alt_dir / "alternates").write_text(
        f"{canonical / '.git' / 'objects'}\n")
    subprocess.run(["git", "-C", str(clone_ws), "remote", "add", "local",
                    str(canonical)], capture_output=True)

    slot9 = root / "slots" / "9"
    slot9.mkdir(parents=True)
    slot_ws = slot9 / "work-old-name"
    _init_repo(slot_ws)
    alt_dir9 = slot_ws / ".git" / "objects" / "info"
    alt_dir9.mkdir(parents=True, exist_ok=True)
    (alt_dir9 / "alternates").write_text(
        f"{canonical / '.git' / 'objects'}\n")
    subprocess.run(["git", "-C", str(slot_ws), "remote", "add", "local",
                    str(canonical)], capture_output=True)

    attic3 = root / "slots" / "attic" / "3"
    attic3.mkdir(parents=True)
    attic_ws = attic3 / "work-old-name"
    _init_repo(attic_ws)
    alt_dir3 = attic_ws / ".git" / "objects" / "info"
    alt_dir3.mkdir(parents=True, exist_ok=True)
    (alt_dir3 / "alternates").write_text(
        f"{canonical / '.git' / 'objects'}\n")

    return {
        "root": root,
        "public": public,
        "canonical": canonical,
        "project": project,
        "clone_root": clone_root,
        "clone_ws": clone_ws,
        "slot_ws": slot_ws,
        "attic_ws": attic_ws,
    }


# --- Task 1: Discovery ---

def test_discover_finds_canonical(family):
    from rename_topo import discover_workspace_dirs
    dirs = discover_workspace_dirs(
        family["root"], "old-name", public_dir=family["public"])
    canonical = [d for d in dirs if d.layout == "canonical"]
    assert len(canonical) == 1
    assert canonical[0].path == family["canonical"]
    assert canonical[0].rename_dir is True


def test_discover_finds_clone(family):
    from rename_topo import discover_workspace_dirs
    dirs = discover_workspace_dirs(
        family["root"], "old-name", public_dir=family["public"])
    clones = [d for d in dirs if d.layout == "clone"]
    assert len(clones) == 1
    assert clones[0].path == family["clone_ws"]
    assert clones[0].rename_dir is True


def test_discover_finds_active_slot(family):
    from rename_topo import discover_workspace_dirs
    dirs = discover_workspace_dirs(
        family["root"], "old-name", public_dir=family["public"])
    slots = [d for d in dirs if d.layout == "slot"]
    assert len(slots) == 1
    assert slots[0].active is True
    assert slots[0].rename_dir is False


def test_discover_finds_attic_slot(family):
    from rename_topo import discover_workspace_dirs
    dirs = discover_workspace_dirs(
        family["root"], "old-name", public_dir=family["public"])
    attics = [d for d in dirs if d.layout == "attic"]
    assert len(attics) == 1
    assert attics[0].active is False
    assert attics[0].rename_dir is False


# --- Task 2: Finders ---

def test_find_alternates(family):
    from rename_topo import discover_workspace_dirs, find_alternates
    dirs = discover_workspace_dirs(
        family["root"], "old-name", public_dir=family["public"])
    old_path = str(family["canonical"])
    new_path = str(family["public"] / "new-name")
    findings = find_alternates(dirs, old_path, new_path)
    assert len(findings) == 3
    assert all(f.category == "mechanical" for f in findings)
    for f in findings:
        assert new_path in f.proposed


def test_find_remotes(family):
    from rename_topo import discover_workspace_dirs, find_remotes
    dirs = discover_workspace_dirs(
        family["root"], "old-name", public_dir=family["public"])
    old_path = str(family["canonical"])
    new_path = str(family["public"] / "new-name")
    findings = find_remotes(dirs, old_path, new_path)
    assert len(findings) == 2
    assert all(f.category == "mechanical" for f in findings)


def test_find_symlinks(family):
    from rename_topo import find_symlinks
    wksp = family["project"] / "wksp"
    wksp.symlink_to(family["canonical"])
    findings = find_symlinks(family["root"], str(family["canonical"]),
                             str(family["public"] / "new-name"))
    assert len(findings) == 1
    assert "new-name" in findings[0].proposed


def test_find_file_references(family):
    from rename_topo import find_file_references
    claude_md = family["canonical"] / "CLAUDE.md"
    claude_md.write_text(
        "workspace: ~/claude/public/old-name\n"
        "## History\n"
        "old-name was renamed from something\n"
    )
    subprocess.run(["git", "-C", str(family["canonical"]), "add", "."],
                   capture_output=True)
    subprocess.run(["git", "-C", str(family["canonical"]), "commit", "-m", "add"],
                   capture_output=True)
    findings = find_file_references(
        claude_md,
        ["~/claude/public/old-name"],
        ["~/claude/public/new-name"],
    )
    assert len(findings) == 1
    assert "new-name" in findings[0].proposed


def test_find_file_references_skips_historical(family):
    from rename_topo import find_file_references
    claude_md = family["canonical"] / "CLAUDE.md"
    claude_md.write_text(
        "## Migration Status\n"
        "workspace: ~/claude/public/old-name was migrated\n"
    )
    findings = find_file_references(
        claude_md,
        ["~/claude/public/old-name"],
        ["~/claude/public/new-name"],
    )
    assert len(findings) == 0


def test_find_worklog_rows(tmp_path):
    db = tmp_path / "worklog.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE repos (id INTEGER PRIMARY KEY, path TEXT, a, b, c, d)")
    conn.execute("INSERT INTO repos VALUES (1, '/old/path', NULL, NULL, NULL, NULL)")
    conn.execute("INSERT INTO repos VALUES (2, '/other', NULL, NULL, NULL, NULL)")
    conn.commit()
    conn.close()
    from rename_topo import find_worklog_rows
    findings = find_worklog_rows("/old/path", "/new/path", db_path=db)
    assert len(findings) == 1
    assert findings[0].current == "/old/path"
    assert findings[0].proposed == "/new/path"


def test_find_claude_projects(tmp_path):
    from rename_topo import find_claude_projects, mangle_path
    projects_dir = tmp_path / ".claude" / "projects"
    old_mangled = mangle_path("/Users/me/claude/public/old-name")
    (projects_dir / old_mangled).mkdir(parents=True)
    findings = find_claude_projects(
        "/Users/me/claude/public/old-name",
        "/Users/me/claude/public/new-name",
        projects_dir=projects_dir,
    )
    assert len(findings) == 1
    assert "new-name" in findings[0].proposed


def test_mangle_path():
    from rename_topo import mangle_path
    assert mangle_path("/Users/me/claude/public/foo") == "-Users-me-claude-public-foo"
