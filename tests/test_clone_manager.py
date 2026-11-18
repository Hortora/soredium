"""Tests for project/clone_manager.py — permanent clone creation."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))


GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@t.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@t.com",
    "HOME": "/tmp",
}


def _git(cwd, *args):
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(
        ["git"] + list(args),
        cwd=str(cwd), capture_output=True, text=True, env=env,
    )


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "user.email", "t@t.com")
    (path / "README.md").write_text("init\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")
    return path


def make_family(tmp_path: Path, repo_name: str = "engine",
                with_workspace: bool = True) -> tuple[Path, Path]:
    """Create a family root with a canonical repo and optionally a workspace."""
    family = tmp_path / "family"
    family.mkdir()
    (family / "slots").mkdir()

    canonical = init_repo(family / repo_name)

    if with_workspace:
        ws = init_repo(family / "work")
        wksp_link = canonical / "wksp"
        wksp_link.symlink_to(os.path.relpath(ws, canonical))
        _git(canonical, "add", ".")
        _git(canonical, "commit", "-m", "add wksp symlink")

    return family, canonical


@pytest.fixture
def family_with_repo(tmp_path):
    family, canonical = make_family(tmp_path)
    return family, canonical


class TestCreateClone:
    def test_creates_clone_structure(self, family_with_repo):
        """Test 1: create makes <family>/clone/<repo>/{.slot,.permanent,<repo>/,<workspace>/}"""
        family, canonical = family_with_repo
        from clone_manager import create_clone
        result = create_clone(family, "engine")
        assert result["CREATED"] == "yes"
        target = family / "clone" / "engine"
        assert target.is_dir()
        assert (target / ".slot").exists()
        assert (target / ".permanent").exists()
        assert (target / "engine").is_dir()
        assert (target / "engine" / ".git").exists()
        ws_dirs = [d for d in target.iterdir()
                   if d.is_dir() and d.name != "engine"
                   and (d / ".git").exists()]
        assert len(ws_dirs) >= 1, "workspace clone not found"

    def test_clone_only_remote_is_local(self, family_with_repo):
        """Test 2: project clone's only remote is local, pointing at canonical."""
        family, canonical = family_with_repo
        from clone_manager import create_clone
        create_clone(family, "engine")
        clone_path = family / "clone" / "engine" / "engine"
        remotes = _git(clone_path, "remote").stdout.strip().split()
        assert remotes == ["local"], f"expected only 'local' remote, got {remotes}"
        url = _git(clone_path, "remote", "get-url", "local").stdout.strip()
        assert str(canonical.resolve()) in url or str(canonical) in url

    def test_workspace_clone_only_remote_is_local(self, family_with_repo):
        """Test 2 (workspace): workspace clone's only remote is local."""
        family, canonical = family_with_repo
        from clone_manager import create_clone
        create_clone(family, "engine")
        target = family / "clone" / "engine"
        ws_dirs = [d for d in target.iterdir()
                   if d.is_dir() and d.name != "engine"
                   and (d / ".git").exists()
                   and (d / ".workspace").exists()]
        assert ws_dirs, "no workspace clone found"
        ws_clone = ws_dirs[0]
        remotes = _git(ws_clone, "remote").stdout.strip().split()
        assert remotes == ["local"], f"workspace has unexpected remotes: {remotes}"

    def test_post_commit_hook_installed(self, family_with_repo):
        """Test 3: post-commit backup hook is installed in project clone."""
        family, canonical = family_with_repo
        from clone_manager import create_clone
        create_clone(family, "engine")
        hook = family / "clone" / "engine" / "engine" / ".git" / "hooks" / "post-commit"
        assert hook.exists()
        assert hook.stat().st_mode & 0o111
        content = hook.read_text()
        assert "canonical_sync" in content

    def test_proj_wksp_symlinks(self, family_with_repo):
        """Test 4: proj/ and wksp/ links resolve to each other inside the clone."""
        family, canonical = family_with_repo
        from clone_manager import create_clone
        create_clone(family, "engine")
        clone_path = family / "clone" / "engine" / "engine"
        wksp = clone_path / "wksp"
        assert wksp.is_symlink()
        ws_target = wksp.resolve()
        assert ws_target.is_dir()
        proj = ws_target / "proj"
        assert proj.is_symlink()
        assert proj.resolve() == clone_path.resolve()

    def test_idempotent_second_create(self, family_with_repo):
        """Test 5: second create returns already_exists and changes nothing."""
        family, canonical = family_with_repo
        from clone_manager import create_clone
        create_clone(family, "engine")
        clone_path = family / "clone" / "engine" / "engine"
        refs_before = _git(clone_path, "for-each-ref").stdout
        target = family / "clone" / "engine"
        listing_before = sorted(str(p.relative_to(target)) for p in target.rglob("*")
                                 if ".git" not in p.parts)
        result = create_clone(family, "engine")
        assert result["CREATED"] == "already_exists"
        refs_after = _git(clone_path, "for-each-ref").stdout
        listing_after = sorted(str(p.relative_to(target)) for p in target.rglob("*")
                                if ".git" not in p.parts)
        assert refs_before == refs_after
        assert listing_before == listing_after

    def test_canonical_missing_error(self, tmp_path):
        """Test 6: canonical missing -> ERROR=canonical_not_found, nothing created."""
        family = tmp_path / "family"
        family.mkdir()
        from clone_manager import create_clone
        result = create_clone(family, "nonexistent")
        assert result["ERROR"] == "canonical_not_found"
        assert not (family / "clone" / "nonexistent").exists()

    def test_canonical_sync_locate(self, family_with_repo):
        """Test 7: canonical_sync.locate(<project clone>).repo is the canonical repo."""
        family, canonical = family_with_repo
        from clone_manager import create_clone
        create_clone(family, "engine")
        clone_path = family / "clone" / "engine" / "engine"
        import canonical_sync
        c = canonical_sync.locate(clone_path)
        assert c.repo.resolve() == canonical.resolve()

    def test_topology_reports_in_slot(self, family_with_repo):
        """Test 8: topology reports IN_SLOT for the project clone."""
        family, canonical = family_with_repo
        from clone_manager import create_clone
        create_clone(family, "engine")
        clone_path = family / "clone" / "engine" / "engine"
        from topology import _detect_slot
        slot_dir, primary = _detect_slot(clone_path)
        assert slot_dir is not None
        assert primary == "engine"

    def test_list_slots_excludes_clone(self, family_with_repo):
        """Test 9: slot_query.list_slots(family_root) does not list the clone."""
        family, canonical = family_with_repo
        from clone_manager import create_clone
        create_clone(family, "engine")
        from slot_query import list_slots
        slots = list_slots(family)
        clone_numbers = [s["number"] for s in slots]
        assert len(slots) == 0 or all(isinstance(n, int) for n in clone_numbers)


class TestEnabled:
    def test_disabled_by_default(self, tmp_path):
        """Test 10a: is_enabled false by default."""
        family = tmp_path / "family"
        family.mkdir()
        from clone_manager import is_enabled
        assert is_enabled(family) is False

    def test_enabled_after_enable(self, tmp_path):
        """Test 10b: true after enable."""
        family = tmp_path / "family"
        family.mkdir()
        from clone_manager import is_enabled, enable
        enable(family)
        assert is_enabled(family) is True

    def test_independent_between_families(self, tmp_path):
        """Test 10c: independent between two family roots."""
        family_a = tmp_path / "family_a"
        family_b = tmp_path / "family_b"
        family_a.mkdir()
        family_b.mkdir()
        from clone_manager import is_enabled, enable
        enable(family_a)
        assert is_enabled(family_a) is True
        assert is_enabled(family_b) is False


class TestMultipleClones:
    def test_two_clones_coexist(self, tmp_path):
        """Test 11: a clone of repo A and a clone of repo B in one family coexist."""
        family = tmp_path / "family"
        family.mkdir()
        (family / "slots").mkdir()
        init_repo(family / "alpha")
        init_repo(family / "beta")
        from clone_manager import create_clone, clone_exists
        result_a = create_clone(family, "alpha")
        result_b = create_clone(family, "beta")
        assert result_a["CREATED"] == "yes"
        assert result_b["CREATED"] == "yes"
        assert clone_exists(family, "alpha") is not None
        assert clone_exists(family, "beta") is not None
        assert (family / "clone" / "alpha" / "alpha").is_dir()
        assert (family / "clone" / "beta" / "beta").is_dir()


class TestIsPermanent:
    def test_permanent_marker(self, tmp_path):
        from clone_manager import is_permanent
        assert is_permanent(tmp_path) is False
        (tmp_path / ".permanent").touch()
        assert is_permanent(tmp_path) is True


class TestTargetExists:
    def test_preexisting_dir_with_file(self, tmp_path):
        """Pre-existing directory containing a file -> ERROR=target_exists, file still there."""
        family = tmp_path / "family"
        family.mkdir()
        (family / "slots").mkdir()
        init_repo(family / "engine")
        target = family / "clone" / "engine"
        target.mkdir(parents=True)
        sentinel = target / "important.txt"
        sentinel.write_text("do not delete\n")
        from clone_manager import create_clone
        result = create_clone(family, "engine")
        assert result["ERROR"] == "target_exists"
        assert sentinel.exists()
        assert sentinel.read_text() == "do not delete\n"

    def test_failed_clone_leaves_nothing(self, tmp_path):
        """Canonical with no main branch -> clone fails, no target dir left behind."""
        family = tmp_path / "family"
        family.mkdir()
        (family / "slots").mkdir()
        no_main = family / "engine"
        no_main.mkdir(parents=True)
        _git(no_main, "init", "-b", "develop")
        _git(no_main, "config", "user.name", "Test")
        _git(no_main, "config", "user.email", "t@t.com")
        (no_main / "README.md").write_text("init\n")
        _git(no_main, "add", ".")
        _git(no_main, "commit", "-m", "init")
        from clone_manager import create_clone
        result = create_clone(family, "engine")
        assert "ERROR" in result
        assert not (family / "clone" / "engine").exists()


class TestLifecycleFilesPreserved:
    def test_workspace_lifecycle_files_kept(self, tmp_path):
        """Canonical workspace has HANDOFF.md and .queue committed -> both
        exist in clone workspace, git status --porcelain is empty."""
        family = tmp_path / "family"
        family.mkdir()
        (family / "slots").mkdir()
        canonical = init_repo(family / "engine")
        ws = init_repo(family / "work")
        (ws / "HANDOFF.md").write_text("# Handoff\nSome state\n")
        (ws / ".queue").write_text("state: active\nbranch: main\n")
        _git(ws, "add", ".")
        _git(ws, "commit", "-m", "add lifecycle files")
        wksp_link = canonical / "wksp"
        wksp_link.symlink_to(os.path.relpath(ws, canonical))
        _git(canonical, "add", ".")
        _git(canonical, "commit", "-m", "add wksp symlink")
        from clone_manager import create_clone
        result = create_clone(family, "engine")
        assert result["CREATED"] == "yes"
        target = family / "clone" / "engine"
        ws_dirs = [d for d in target.iterdir()
                   if d.is_dir() and d.name != "engine"
                   and (d / ".git").exists()
                   and (d / ".workspace").exists()]
        assert ws_dirs, "workspace clone not found"
        ws_clone = ws_dirs[0]
        assert (ws_clone / "HANDOFF.md").exists()
        assert (ws_clone / ".queue").exists()
        status_lines = _git(ws_clone, "status", "--porcelain").stdout.strip().splitlines()
        lifecycle_dirty = [l for l in status_lines
                          if "HANDOFF" in l or ".queue" in l]
        assert lifecycle_dirty == [], f"lifecycle files are dirty: {lifecycle_dirty}"


class TestCLIMissingArgs:
    def test_create_missing_family_root(self):
        from clone_manager import cmd_create
        assert cmd_create({"repo": "engine"}) == 1

    def test_create_missing_repo(self):
        from clone_manager import cmd_create
        assert cmd_create({"family_root": "/tmp"}) == 1

    def test_create_missing_both(self):
        from clone_manager import cmd_create
        assert cmd_create({}) == 1

    def test_status_missing_family_root(self):
        from clone_manager import cmd_status
        assert cmd_status({"repo": "engine"}) == 1

    def test_status_missing_repo(self):
        from clone_manager import cmd_status
        assert cmd_status({"family_root": "/tmp"}) == 1

    def test_enable_missing_family_root(self):
        from clone_manager import cmd_enable
        assert cmd_enable({}) == 1

    def test_enabled_missing_family_root(self):
        from clone_manager import cmd_enabled
        assert cmd_enabled({}) == 1
