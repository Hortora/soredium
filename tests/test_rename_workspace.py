"""Integration tests for scripts/rename_workspace.py."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))


def _init_repo(path: Path, files: dict[str, str] | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                   capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"],
                   capture_output=True)
    if files:
        for name, content in files.items():
            (path / name).parent.mkdir(parents=True, exist_ok=True)
            (path / name).write_text(content)
        subprocess.run(["git", "-C", str(path), "add", "."],
                       capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
                   capture_output=True, check=True)
    return path


CLAUDE_MD = (
    "# CLAUDE.md\n\n"
    "- **workspace:** `~/claude/public/old-ws`\n"
    "- GitHub: `testuser/wsp-old-ws`\n"
)

HANDOFF_MD = (
    "# Handover\n\n"
    "**Where to work:** clone at `wsp-old-ws/`\n"
    "## History\n"
    "old-ws was fine in the past\n"
)


@pytest.fixture
def workspace_family(tmp_path):
    root = tmp_path / "hortora"
    root.mkdir()
    public = tmp_path / "public"

    canonical = _init_repo(public / "old-ws", {
        "CLAUDE.md": CLAUDE_MD,
        "HANDOFF.md": HANDOFF_MD,
    })

    project = _init_repo(root / "myproject", {
        "CLAUDE.md": "# Project\n\nworkspace: `~/claude/public/old-ws`\n",
    })
    (project / "wksp").symlink_to(canonical)

    clone_root = root / "clone" / "myproject"
    clone_root.mkdir(parents=True)
    clone_ws = _init_repo(clone_root / "wsp-old-ws", {
        "CLAUDE.md": CLAUDE_MD,
        "HANDOFF.md": HANDOFF_MD,
    })
    alt_dir = clone_ws / ".git" / "objects" / "info"
    alt_dir.mkdir(parents=True, exist_ok=True)
    (alt_dir / "alternates").write_text(f"{canonical / '.git' / 'objects'}\n")
    subprocess.run(["git", "-C", str(clone_ws), "remote", "add", "local",
                    str(canonical)], capture_output=True)
    (clone_root / ".queue-root").write_text(
        f"since: 2026-01-01\nadopted-from: {clone_ws}/.queue\n")

    attic = root / "slots" / "attic" / "3" / "work-old-ws"
    _init_repo(attic)
    alt_dir3 = attic / ".git" / "objects" / "info"
    alt_dir3.mkdir(parents=True, exist_ok=True)
    (alt_dir3 / "alternates").write_text(f"{canonical / '.git' / 'objects'}\n")

    db = tmp_path / "worklog.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE repos (id INTEGER PRIMARY KEY, path TEXT, a, b, c, d)")
    conn.execute("INSERT INTO repos VALUES (1, ?, NULL, NULL, NULL, NULL)",
                 (str(canonical),))
    conn.execute("INSERT INTO repos VALUES (2, ?, NULL, NULL, NULL, NULL)",
                 (str(clone_ws),))
    conn.execute("INSERT INTO repos VALUES (3, '/other/repo', NULL, NULL, NULL, NULL)")
    conn.commit()
    conn.close()

    claude_projects = tmp_path / ".claude" / "projects"
    from rename_topo import mangle_path
    old_mangled = mangle_path(str(canonical))
    (claude_projects / old_mangled).mkdir(parents=True)
    (claude_projects / old_mangled / "memory").mkdir()

    return {
        "root": root,
        "public": public,
        "canonical": canonical,
        "project": project,
        "clone_root": clone_root,
        "clone_ws": clone_ws,
        "attic_ws": attic,
        "db": db,
        "claude_projects": claude_projects,
        "tmp": tmp_path,
    }


def _apply(wf, **kwargs):
    from rename_workspace import apply
    defaults = dict(
        family_root=wf["root"],
        old_name="old-ws",
        new_name="new-ws",
        public_dir=wf["public"],
        db_path=wf["db"],
        projects_dir=wf["claude_projects"],
        skip_github=True,
    )
    defaults.update(kwargs)
    return apply(**defaults)


def test_audit_finds_all_layers(workspace_family):
    from rename_workspace import audit
    findings = audit(
        family_root=workspace_family["root"],
        old_name="old-ws",
        new_name="new-ws",
        public_dir=workspace_family["public"],
        db_path=workspace_family["db"],
        projects_dir=workspace_family["claude_projects"],
        skip_github=True,
    )
    mechanical = [f for f in findings if f.category == "mechanical"]
    assert len(mechanical) >= 8


def test_apply_renames_directories(workspace_family):
    _apply(workspace_family)
    assert (workspace_family["public"] / "new-ws").is_dir()
    assert not (workspace_family["public"] / "old-ws").exists()
    assert (workspace_family["clone_root"] / "wsp-new-ws").is_dir()
    assert not (workspace_family["clone_root"] / "wsp-old-ws").exists()


def test_apply_preserves_attic_dir_name(workspace_family):
    _apply(workspace_family)
    assert (workspace_family["root"] / "slots" / "attic" / "3" / "work-old-ws").is_dir()


def test_apply_fixes_alternates(workspace_family):
    _apply(workspace_family)
    new_canonical = workspace_family["public"] / "new-ws"
    expected = str(new_canonical / ".git" / "objects")

    clone_alt = (workspace_family["clone_root"] / "wsp-new-ws" /
                 ".git" / "objects" / "info" / "alternates")
    assert expected in clone_alt.read_text()

    attic_alt = (workspace_family["root"] / "slots" / "attic" / "3" /
                 "work-old-ws" / ".git" / "objects" / "info" / "alternates")
    assert expected in attic_alt.read_text()


def test_apply_fixes_remotes(workspace_family):
    _apply(workspace_family)
    clone_ws = workspace_family["clone_root"] / "wsp-new-ws"
    result = subprocess.run(
        ["git", "-C", str(clone_ws), "remote", "get-url", "local"],
        capture_output=True, text=True)
    assert "new-ws" in result.stdout
    assert "old-ws" not in result.stdout


def test_apply_fixes_symlinks(workspace_family):
    _apply(workspace_family)
    wksp = workspace_family["project"] / "wksp"
    target = os.readlink(wksp)
    assert "new-ws" in target
    assert "old-ws" not in target


def test_apply_updates_worklog_with_backup(workspace_family):
    _apply(workspace_family)
    import datetime
    today = datetime.date.today().strftime("%Y%m%d")
    backup = workspace_family["db"].parent / f"worklog.db.before-rename-{today}"
    assert backup.exists()

    conn = sqlite3.connect(str(workspace_family["db"]))
    rows = conn.execute("SELECT path FROM repos WHERE id IN (1, 2)").fetchall()
    conn.close()
    assert all("new-ws" in r[0] for r in rows)
    assert all("old-ws" not in r[0] for r in rows)

    unchanged = sqlite3.connect(str(workspace_family["db"])).execute(
        "SELECT path FROM repos WHERE id = 3").fetchone()
    assert unchanged[0] == "/other/repo"


def test_apply_renames_claude_projects(workspace_family):
    from rename_topo import mangle_path
    _apply(workspace_family)
    new_canonical = workspace_family["public"] / "new-ws"
    new_mangled = mangle_path(str(new_canonical))
    assert (workspace_family["claude_projects"] / new_mangled).is_dir()
    assert (workspace_family["claude_projects"] / new_mangled / "memory").is_dir()


def test_apply_rewrites_claude_md(workspace_family):
    _apply(workspace_family)
    content = (workspace_family["public"] / "new-ws" / "CLAUDE.md").read_text()
    assert "~/claude/public/new-ws" in content
    assert "wsp-new-ws" in content
    assert "old-ws" not in content


def test_apply_rewrites_handoff_active_only(workspace_family):
    _apply(workspace_family)
    content = (workspace_family["public"] / "new-ws" / "HANDOFF.md").read_text()
    assert "wsp-new-ws" in content
    # Historical section preserved
    assert "old-ws was fine in the past" in content


def test_apply_rewrites_project_claude_md(workspace_family):
    _apply(workspace_family)
    content = (workspace_family["project"] / "CLAUDE.md").read_text()
    assert "~/claude/public/new-ws" in content
    assert "old-ws" not in content


def test_apply_rewrites_queue_root(workspace_family):
    _apply(workspace_family)
    content = (workspace_family["clone_root"] / ".queue-root").read_text()
    assert "wsp-new-ws" in content
    assert "wsp-old-ws" not in content


def test_idempotent_rerun(workspace_family):
    _apply(workspace_family)
    result = _apply(workspace_family)
    assert result == 0


def test_clone_ws_git_valid_after_rename(workspace_family):
    _apply(workspace_family)
    clone_ws = workspace_family["clone_root"] / "wsp-new-ws"
    result = subprocess.run(
        ["git", "-C", str(clone_ws), "status", "-sb"],
        capture_output=True, text=True)
    assert result.returncode == 0
    assert "unable to normalize" not in result.stderr
