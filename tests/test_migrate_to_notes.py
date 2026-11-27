"""Tests for project/migrate_to_notes.py — permanent clone migration."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "project" / "migrate_to_notes.py"
PROJECT_DIR = SCRIPT.parent


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )


@pytest.fixture(autouse=True)
def _setup_path():
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))


def _make_clone(tmp_path):
    """Create a minimal permanent clone layout."""
    family = tmp_path / "family"
    family.mkdir()
    (family / "slots").mkdir()

    canonical = family / "myrepo"
    canonical.mkdir()
    _git(canonical, "init", "-b", "main")
    _git(canonical, "config", "user.email", "test@test.com")
    _git(canonical, "config", "user.name", "Test")
    _git(canonical, "commit", "--allow-empty", "-m", "init")

    clone_root = family / "clone" / "myrepo"
    clone_root.mkdir(parents=True)

    project = clone_root / "myrepo"
    subprocess.run(["git", "clone", str(canonical), str(project)],
                   capture_output=True, check=True)
    _git(project, "config", "user.email", "test@test.com")
    _git(project, "config", "user.name", "Test")

    workspace = clone_root / "wsp-myrepo"
    workspace.mkdir()
    _git(workspace, "init", "-b", "main")
    _git(workspace, "config", "user.email", "test@test.com")
    _git(workspace, "config", "user.name", "Test")
    _git(workspace, "commit", "--allow-empty", "-m", "init workspace")

    (project / "wksp").symlink_to("../wsp-myrepo")

    (clone_root / ".slot").write_text("# Slot\n\n## Repos\n- myrepo (primary)\n")
    (clone_root / ".permanent").touch()
    (clone_root / ".queue-root").write_text("# queue at root\n")
    (clone_root / ".queue").write_text("- [ ] hortora/myrepo#1 — first issue\n\n## State\nbranch: main\nissue-repo: hortora/myrepo\nstatus: active\n")

    return clone_root, project, workspace


class TestMigrate:
    def test_dry_run_changes_nothing(self, tmp_path):
        clone_root, project, workspace = _make_clone(tmp_path)
        from migrate_to_notes import migrate
        actions = migrate(project, dry_run=True)
        assert any("WOULD" in a for a in actions)
        assert not (project / ".notes").exists()
        assert (project / "wksp").is_symlink()
        assert (clone_root / ".queue-root").exists()

    def test_full_migration(self, tmp_path):
        clone_root, project, workspace = _make_clone(tmp_path)
        from migrate_to_notes import migrate
        actions = migrate(project)
        assert not any("ERROR" in a for a in actions)

        from notes_store import NotesStore
        store = NotesStore(project)
        assert store.available
        assert (store.path / ".queue").exists()

        content = store.read(".queue")
        assert "hortora/myrepo#1" in content

        assert not (project / "wksp").exists()
        assert not (clone_root / ".queue-root").exists()

        # original queue stays at clone root
        assert (clone_root / ".queue").exists()
        # workspace clone stays on disk
        assert workspace.is_dir()

    def test_idempotent(self, tmp_path):
        clone_root, project, workspace = _make_clone(tmp_path)
        from migrate_to_notes import migrate
        migrate(project)
        actions = migrate(project)
        assert any("already active" in a for a in actions)
        assert any("already in notes" in a for a in actions)

    def test_no_queue_to_migrate(self, tmp_path):
        clone_root, project, workspace = _make_clone(tmp_path)
        (clone_root / ".queue").unlink()
        (clone_root / ".queue-root").unlink()
        from migrate_to_notes import migrate
        actions = migrate(project)
        assert any("no queue found" in a for a in actions)

    def test_topology_resolves_after_migration(self, tmp_path):
        clone_root, project, workspace = _make_clone(tmp_path)
        from migrate_to_notes import migrate
        migrate(project)

        import importlib
        import topology
        importlib.reload(topology)
        topo = topology.resolve(str(project))
        assert topo.notes_path == (project / ".notes").resolve()
        assert topo.workspace == topo.project

    def test_queue_io_routes_to_notes_after_migration(self, tmp_path):
        clone_root, project, workspace = _make_clone(tmp_path)
        from migrate_to_notes import migrate
        migrate(project)

        import importlib
        import queue_io
        importlib.reload(queue_io)
        qdir = queue_io.queue_dir(project)
        assert qdir == project / ".notes"
