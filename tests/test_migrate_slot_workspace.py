"""Tests for scripts/migrate_slot_workspace.py"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))


def init_repo(path: Path, bare=False) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True, check=True)
    return path


def _make_old_structure_slot(tmp_path, slot_num=1, repos=None, branch="issue-99-test"):
    """Create a slot with the old family-workspace-clone structure."""
    if repos is None:
        repos = ["connectors"]

    family = tmp_path / "casehub"
    family.mkdir(exist_ok=True)

    # Create original project repos and workspace repos
    for repo_name in repos:
        init_repo(family / repo_name)
        ws_repo = init_repo(tmp_path / "public" / "casehub" / repo_name)
        subprocess.run(["git", "-C", str(ws_repo), "remote", "add", "origin",
                         f"https://github.com/mdproctor/wsp-casehub-{repo_name}.git"],
                        capture_output=True, check=True)
        (family / repo_name / "wksp").symlink_to(ws_repo)

    # Create slot with old structure
    slot_dir = family / "slots" / str(slot_num)
    slot_dir.mkdir(parents=True)
    (slot_dir / ".m2").mkdir()

    # Clone project repos into slot
    for repo_name in repos:
        clone = slot_dir / repo_name
        subprocess.run(["git", "clone", "--shared", str(family / repo_name), str(clone)],
                        capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone), "checkout", "-b", branch],
                        capture_output=True, check=True)

    # Clone family workspace (old structure — one clone for all)
    family_ws = init_repo(tmp_path / "public" / "casehub-parent")
    for repo_name in repos:
        subdir = family_ws / repo_name
        subdir.mkdir(exist_ok=True)
        (subdir / ".gitkeep").touch()
    subprocess.run(["git", "-C", str(family_ws), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(family_ws), "commit", "-m", "add subdirs"],
                    capture_output=True, check=True)

    ws_clone = slot_dir / "work-casehub"
    subprocess.run(["git", "clone", "--shared", str(family_ws), str(ws_clone)],
                    capture_output=True, check=True)
    subprocess.run(["git", "-C", str(ws_clone), "checkout", "-b", branch],
                    capture_output=True, check=True)
    (ws_clone / ".workspace").touch()

    # Point project wksp symlinks to family workspace subdirs (old structure)
    for repo_name in repos:
        wksp = slot_dir / repo_name / "wksp"
        if wksp.is_symlink():
            wksp.unlink()
        rel = os.path.relpath(ws_clone / repo_name, slot_dir / repo_name)
        wksp.symlink_to(rel)

    # Write .slot file
    primary = repos[0]
    slot_file = slot_dir / ".slot"
    lines = [f"# Slot {slot_num} — {branch}", "", "## Issue", f"casehubio/{primary}#99",
             "", "## Repos"]
    for i, r in enumerate(repos):
        lines.append(f"- {r}{' (primary)' if i == 0 else ''}")
    slot_file.write_text("\n".join(lines) + "\n")

    return family, slot_dir


class TestMigrateSlotWorkspace:
    def test_detects_old_structure(self, tmp_path):
        """Old structure detected by presence of work-* workspace clone."""
        family, slot_dir = _make_old_structure_slot(tmp_path)
        from migrate_slot_workspace import needs_migration
        assert needs_migration(slot_dir) is True

    def test_new_structure_does_not_need_migration(self, tmp_path):
        """Slot with per-repo workspaces (wsp-*) does not need migration."""
        family, slot_dir = _make_old_structure_slot(tmp_path)
        # Simulate already-migrated: rename work-casehub to have no work- prefix
        # and add wsp- directories
        from migrate_slot_workspace import needs_migration
        ws = init_repo(slot_dir / "wsp-casehub-connectors")
        (ws / ".workspace").touch()
        (slot_dir / "work-casehub").rename(slot_dir / "old-work-casehub")
        assert needs_migration(slot_dir) is False

    def test_migrates_single_repo(self, tmp_path):
        """Migration creates per-repo workspace clone and symlink bridge."""
        family, slot_dir = _make_old_structure_slot(tmp_path, repos=["connectors"])
        from migrate_slot_workspace import migrate_slot
        result = migrate_slot(slot_dir, family)

        assert result["status"] == "migrated"
        assert "connectors" in result["repos_migrated"]

        # New workspace clone exists with marker
        new_ws = slot_dir / "wsp-casehub-connectors"
        assert new_ws.is_dir()
        assert (new_ws / ".workspace").exists()
        assert (new_ws / ".git").exists()

        # Project wksp symlink repointed to new workspace
        wksp = slot_dir / "connectors" / "wksp"
        assert wksp.is_symlink()
        resolved = wksp.resolve()
        assert resolved == new_ws.resolve()

        # Old family workspace subdir replaced with symlink
        old_subdir = slot_dir / "work-casehub" / "connectors"
        assert old_subdir.is_symlink()

    def test_migrates_multiple_repos(self, tmp_path):
        """Each repo gets its own workspace clone."""
        family, slot_dir = _make_old_structure_slot(
            tmp_path, repos=["connectors", "pages"])
        from migrate_slot_workspace import migrate_slot
        result = migrate_slot(slot_dir, family)

        assert result["status"] == "migrated"
        assert len(result["repos_migrated"]) == 2
        assert (slot_dir / "wsp-casehub-connectors").is_dir()
        assert (slot_dir / "wsp-casehub-pages").is_dir()

    def test_replays_branch_commits(self, tmp_path):
        """Commits on the feature branch in the family workspace subdir
        are replayed into the new per-repo workspace clone."""
        family, slot_dir = _make_old_structure_slot(tmp_path, repos=["connectors"])

        # Add a commit to the family workspace's connectors subdir
        ws_clone = slot_dir / "work-casehub"
        spec_file = ws_clone / "connectors" / "spec.md"
        spec_file.write_text("# Design spec\n")
        subprocess.run(["git", "-C", str(ws_clone), "add", "connectors/spec.md"],
                        capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws_clone), "commit", "-m", "add spec"],
                        capture_output=True, check=True)

        from migrate_slot_workspace import migrate_slot
        result = migrate_slot(slot_dir, family)

        assert result["status"] == "migrated"
        # The spec file should exist in the new workspace clone
        new_ws = slot_dir / "wsp-casehub-connectors"
        assert (new_ws / "spec.md").exists()
        assert (new_ws / "spec.md").read_text() == "# Design spec\n"

    def test_idempotent(self, tmp_path):
        """Running migration twice produces same result."""
        family, slot_dir = _make_old_structure_slot(tmp_path, repos=["connectors"])
        from migrate_slot_workspace import migrate_slot
        migrate_slot(slot_dir, family)
        result = migrate_slot(slot_dir, family)
        assert result["status"] == "already_migrated"

    def test_resumes_from_progress(self, tmp_path):
        """If .migration-progress has partial completion, only migrates remaining."""
        family, slot_dir = _make_old_structure_slot(
            tmp_path, repos=["connectors", "pages"])
        from migrate_slot_workspace import migrate_slot

        # Simulate partial progress: connectors already done
        progress = slot_dir / ".migration-progress"
        progress.write_text("connectors=complete\n")
        # Manually create the wsp for connectors as if migration ran
        ws = init_repo(slot_dir / "wsp-casehub-connectors")
        (ws / ".workspace").touch()

        result = migrate_slot(slot_dir, family)
        assert result["status"] == "migrated"
        assert "pages" in result["repos_migrated"]
        assert "connectors" not in result["repos_migrated"]

    def test_no_patches_when_no_branch_commits(self, tmp_path):
        """Fresh clone on feature branch with no commits beyond main
        doesn't need format-patch replay — should still succeed."""
        family, slot_dir = _make_old_structure_slot(tmp_path, repos=["connectors"])
        from migrate_slot_workspace import migrate_slot
        result = migrate_slot(slot_dir, family)
        assert result["status"] == "migrated"
        assert not result.get("errors")

    def test_dry_run(self, tmp_path):
        """dry_run=True reports what would change without touching disk."""
        family, slot_dir = _make_old_structure_slot(tmp_path, repos=["connectors"])
        from migrate_slot_workspace import migrate_slot
        result = migrate_slot(slot_dir, family, dry_run=True)
        assert result["status"] == "would_migrate"
        # Nothing actually changed
        assert not (slot_dir / "wsp-casehub-connectors").exists()
