"""Tests for work-slot/slot_git.py"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_git
import slot_core
import slot_manager
from slot_core import run_cmd
from slot_test_helpers import init_repo, init_repo_with_workspace, init_repo_with_remote

# These helpers need slot_git functions — import here to avoid circular deps
def _create_worktree_test_repos(tmp_path, repo_names):
    """Create a test family with worktree-based slots (legacy layout for migration tests)."""
    family = tmp_path / "family"
    family.mkdir()
    slots_dir = family / "slots"
    slots_dir.mkdir()
    originals = {}
    for name in repo_names:
        originals[name] = init_repo_with_remote(family / name)
        slot_git.configure_update_instead(originals[name])
    slot = slots_dir / "1"
    slot.mkdir()
    branch = "issue-42-test"
    for name in repo_names:
        subprocess.run([
            "git", "-C", str(originals[name]),
            "worktree", "add", str(slot / name), "-b", branch,
        ], capture_output=True, check=True)
        (slot / name / "feature.py").write_text(f"# {name} feature\n")
        subprocess.run(["git", "-C", str(slot / name), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(slot / name), "commit", "-m", f"feat: {name} feature"], capture_output=True, check=True)
    (slot / ".phase-a-complete").write_text(
        f"branch={branch}\nrepos={','.join(repo_names)}\ntimestamp=2026-07-18T14:32:00\n"
    )
    (slot / ".slot").write_text(
        f"# Slot 1 — {branch}\n\n## Issue\ntest/repo#42\nCovers: 42\n\n"
        f"## What to do\nTest\n\n## Repos\n" +
        "\n".join(f"- {n}" for n in repo_names) + "\n"
    )
    return family, originals, slot, branch


def _create_clone_test_repos(tmp_path, repo_names):
    """Create a test family with clone-based slots (new remote layout)."""
    family = tmp_path / "family"
    family.mkdir()
    slots_dir = family / "slots"
    slots_dir.mkdir()
    originals = {}
    for name in repo_names:
        originals[name] = init_repo_with_remote(family / name)
        slot_git.configure_update_instead(originals[name])
    slot = slots_dir / "1"
    slot.mkdir()
    branch = "issue-42-test"
    for name in repo_names:
        clone_dest = slot / name
        subprocess.run([
            "git", "clone", "--shared", "--branch", "main",
            str(originals[name]), str(clone_dest),
        ], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dest), "config", "user.email", "test@test.com"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dest), "checkout", "-b", branch], capture_output=True, check=True)
        bare_path = family / f".{name}-bare.git"
        subprocess.run(["git", "-C", str(clone_dest), "remote", "rename", "origin", "local"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "remote", "add", "origin", str(bare_path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "fetch", "origin"], capture_output=True)
        (clone_dest / "feature.py").write_text(f"# {name} feature\n")
        subprocess.run(["git", "-C", str(clone_dest), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "commit", "-m", f"feat: {name} feature"], capture_output=True, check=True)
    (slot / ".phase-a-complete").write_text(
        f"branch={branch}\nrepos={','.join(repo_names)}\ntimestamp=2026-07-18T14:32:00\n"
    )
    (slot / ".slot").write_text(
        f"# Slot 1 — {branch}\n\n## Issue\ntest/repo#42\nCovers: 42\n\n"
        f"## What to do\nTest\n\n## Repos\n" +
        "\n".join(f"- {n}" for n in repo_names) + "\n"
    )
    return family, originals, slot, branch


class TestExcludeSymlinks:
    def test_adds_entries_to_exclude(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        slot_git._exclude_symlinks(repo)
        exclude = (repo / ".git" / "info" / "exclude").read_text()
        assert "proj" in exclude
        assert "wksp" in exclude

    def test_idempotent(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        slot_git._exclude_symlinks(repo)
        slot_git._exclude_symlinks(repo)
        exclude = (repo / ".git" / "info" / "exclude").read_text()
        non_comment = [l.strip() for l in exclude.splitlines() if l.strip() and not l.startswith("#")]
        assert non_comment.count("proj") == 1
        assert non_comment.count("wksp") == 1



class TestConfigureSlotRemotes:
    def test_direct_model_renames_origin_adds_github(self, tmp_path):
        original = init_repo(tmp_path / "original")
        subprocess.run(["git", "-C", str(original), "remote", "add", "origin",
                        "https://github.com/user/repo.git"], capture_output=True)
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(original), str(clone)], capture_output=True)

        result = slot_git.configure_slot_remotes(clone, original)

        rc, local_url, _ = slot_core.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "local"])
        assert rc == 0
        assert str(original) in local_url.strip()

        rc, origin_url, _ = slot_core.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "origin"])
        assert rc == 0
        assert origin_url.strip() == "https://github.com/user/repo.git"

        assert result["upstream"] == ""

    def test_fork_model_adds_upstream(self, tmp_path):
        original = init_repo(tmp_path / "original")
        subprocess.run(["git", "-C", str(original), "remote", "add", "origin",
                        "https://github.com/mdproctor/repo.git"], capture_output=True)
        subprocess.run(["git", "-C", str(original), "remote", "add", "upstream",
                        "https://github.com/casehubio/repo.git"], capture_output=True)
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(original), str(clone)], capture_output=True)

        result = slot_git.configure_slot_remotes(clone, original)

        rc, origin_url, _ = slot_core.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "origin"])
        assert origin_url.strip() == "https://github.com/mdproctor/repo.git"

        rc, upstream_url, _ = slot_core.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "upstream"])
        assert rc == 0
        assert upstream_url.strip() == "https://github.com/casehubio/repo.git"

        assert result["upstream"] == "https://github.com/casehubio/repo.git"

    def test_no_remotes_on_original_skips(self, tmp_path):
        original = init_repo(tmp_path / "original")
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(original), str(clone)], capture_output=True)

        result = slot_git.configure_slot_remotes(clone, original)
        assert result["origin"] == ""



class TestConfigureUpdateInstead:
    def test_sets_config_on_original(self, tmp_path):
        original = init_repo(tmp_path / "original")
        slot_git.configure_update_instead(original)
        rc, value, _ = slot_core.run_cmd(
            ["git", "-C", str(original), "config", "receive.denyCurrentBranch"])
        assert rc == 0
        assert value.strip() == "updateInstead"

    def test_idempotent(self, tmp_path):
        original = init_repo(tmp_path / "original")
        slot_git.configure_update_instead(original)
        slot_git.configure_update_instead(original)
        rc, value, _ = slot_core.run_cmd(
            ["git", "-C", str(original), "config", "receive.denyCurrentBranch"])
        assert value.strip() == "updateInstead"



class TestEnsureCloneLayout:
    def test_migrates_worktree_to_clone(self, tmp_path):
        family, originals, slot, branch = _create_worktree_test_repos(tmp_path, ["engine"])
        assert slot_core.is_worktree(slot / "engine")
        count = slot_git.ensure_clone_layout(slot)
        assert count >= 1
        assert not slot_core.is_worktree(slot / "engine")
        assert (slot / "engine" / ".git").is_dir()
        assert (slot / "engine" / "feature.py").exists()

    def test_noop_on_clones(self, tmp_path):
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        count = slot_git.ensure_clone_layout(slot)
        assert count == 0

    def test_migrated_slot_can_merge(self, tmp_path):
        family, originals, slot, branch = _create_worktree_test_repos(tmp_path, ["engine"])
        slot_git.ensure_clone_layout(slot)
        import slot_lifecycle
        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code == 0
        assert (originals["engine"] / "feature.py").exists()



class TestMigrateWorktreeIdeCleanup:
    def test_migration_succeeds_despite_ide_artifacts(self, tmp_path):
        """After git worktree remove leaves .idea behind, migration should clean it and succeed."""
        family, originals, slot, branch = _create_worktree_test_repos(tmp_path, ["engine"])
        wt_path = slot / "engine"
        assert slot_core.is_worktree(wt_path)

        (wt_path / ".idea").mkdir()
        (wt_path / ".idea" / "workspace.xml").write_text("<xml/>")

        result = slot_git._migrate_worktree_to_clone(wt_path)
        assert result is True
        assert not slot_core.is_worktree(wt_path)
        assert (wt_path / ".git").is_dir()
        assert (wt_path / "feature.py").exists()



class TestRepackBrokenAlternates:
    """_repack_broken_alternates severs git alternates referencing a slot before archiving."""

    def test_repacks_repo_with_alternate_to_target_slot(self, tmp_path, capsys):
        slots = tmp_path / "slots"
        slot_a = slots / "10"
        slot_b = slots / "20"
        repo_a = init_repo(slot_a / "engine")
        repo_b = init_repo(slot_b / "engine")
        alt_file = repo_b / ".git" / "objects" / "info" / "alternates"
        alt_file.parent.mkdir(parents=True, exist_ok=True)
        alt_file.write_text(str(repo_a / ".git" / "objects") + "\n")

        count = slot_git._repack_broken_alternates(slot_a, tmp_path)

        assert count == 1
        assert not alt_file.exists()
        out = capsys.readouterr().out
        assert "REPACKED=" in out

    def test_preserves_unrelated_alternates(self, tmp_path):
        slots = tmp_path / "slots"
        slot_a = slots / "10"
        slot_b = slots / "20"
        other = tmp_path / "other-objects"
        other.mkdir(parents=True)
        init_repo(slot_a / "engine")
        repo_b = init_repo(slot_b / "engine")
        alt_file = repo_b / ".git" / "objects" / "info" / "alternates"
        alt_file.parent.mkdir(parents=True, exist_ok=True)
        alt_file.write_text(
            str(slot_a / "engine" / ".git" / "objects") + "\n"
            + str(other) + "\n"
        )

        slot_git._repack_broken_alternates(slot_a, tmp_path)

        assert alt_file.exists()
        remaining = alt_file.read_text().strip().splitlines()
        assert len(remaining) == 1
        assert str(other) in remaining[0]

    def test_skips_slot_with_no_alternates(self, tmp_path):
        slots = tmp_path / "slots"
        slot_a = slots / "10"
        slot_b = slots / "20"
        init_repo(slot_a / "engine")
        init_repo(slot_b / "engine")

        count = slot_git._repack_broken_alternates(slot_a, tmp_path)

        assert count == 0

    def test_skips_attic_directory(self, tmp_path):
        slots = tmp_path / "slots"
        slot_a = slots / "10"
        attic_slot = slots / "attic" / "5"
        init_repo(slot_a / "engine")
        repo_attic = init_repo(attic_slot / "engine")
        alt_file = repo_attic / ".git" / "objects" / "info" / "alternates"
        alt_file.parent.mkdir(parents=True, exist_ok=True)
        alt_file.write_text(str(slot_a / "engine" / ".git" / "objects") + "\n")

        count = slot_git._repack_broken_alternates(slot_a, tmp_path)

        assert count == 0
        assert alt_file.exists()

    def test_handles_multiple_repos_in_slot(self, tmp_path, capsys):
        slots = tmp_path / "slots"
        slot_a = slots / "10"
        slot_b = slots / "20"
        init_repo(slot_a / "engine")
        init_repo(slot_a / "work")
        repo_b1 = init_repo(slot_b / "engine")
        repo_b2 = init_repo(slot_b / "work")
        for repo_b in [repo_b1, repo_b2]:
            name = repo_b.name
            alt_file = repo_b / ".git" / "objects" / "info" / "alternates"
            alt_file.parent.mkdir(parents=True, exist_ok=True)
            alt_file.write_text(str(slot_a / name / ".git" / "objects") + "\n")

        count = slot_git._repack_broken_alternates(slot_a, tmp_path)

        assert count == 2



class TestInstallPostCommitHook:
    def test_installs_hook_in_clone(self, tmp_path):
        """install_post_commit_hook creates an executable post-commit hook."""
        clone = init_repo(tmp_path / "engine")
        slot_git.install_post_commit_hook(clone)
        hook = clone / ".git" / "hooks" / "post-commit"
        assert hook.exists()
        assert os.access(hook, os.X_OK)
        content = hook.read_text()
        assert "git push" in content

    def test_hook_pushes_to_origin(self, tmp_path):
        """The hook content pushes to origin HEAD."""
        clone = init_repo(tmp_path / "engine")
        slot_git.install_post_commit_hook(clone)
        hook = clone / ".git" / "hooks" / "post-commit"
        content = hook.read_text()
        assert "origin" in content
        assert "HEAD" in content

    def test_hook_is_idempotent(self, tmp_path):
        """Calling install twice doesn't duplicate or corrupt the hook."""
        clone = init_repo(tmp_path / "engine")
        slot_git.install_post_commit_hook(clone)
        content1 = (clone / ".git" / "hooks" / "post-commit").read_text()
        slot_git.install_post_commit_hook(clone)
        content2 = (clone / ".git" / "hooks" / "post-commit").read_text()
        assert content1 == content2

    def test_hook_does_not_clobber_existing(self, tmp_path):
        """If a post-commit hook already exists, don't overwrite it."""
        clone = init_repo(tmp_path / "engine")
        hooks_dir = clone / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        existing_hook = hooks_dir / "post-commit"
        existing_hook.write_text("#!/bin/sh\necho custom\n")
        existing_hook.chmod(0o755)
        slot_git.install_post_commit_hook(clone)
        assert existing_hook.read_text() == "#!/bin/sh\necho custom\n"



class TestSymlinkGitignoredAssets:
    """Tests for _symlink_gitignored_assets — carries gitignored asset dirs into slot clones."""

    def test_symlinks_gitignored_directory(self, tmp_path):
        """A gitignored directory present in source should be symlinked into clone."""
        source = init_repo(tmp_path / "source")
        (source / ".gitignore").write_text(".casehub-packages\n")
        subprocess.run(["git", "-C", str(source), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "add gitignore"], capture_output=True)
        pkg_dir = source / ".casehub-packages"
        pkg_dir.mkdir()
        (pkg_dir / "graph-core").mkdir()
        (pkg_dir / "graph-core" / "index.js").write_text("module.exports = {}")

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(source), str(clone)], capture_output=True, check=True)

        linked = slot_git._symlink_gitignored_assets(source, clone)
        assert ".casehub-packages" in linked
        assert (clone / ".casehub-packages").is_symlink()
        assert (clone / ".casehub-packages" / "graph-core" / "index.js").exists()

    def test_skips_regenerable_directories(self, tmp_path):
        """node_modules, build, dist, target etc. should NOT be symlinked."""
        source = init_repo(tmp_path / "source")
        (source / ".gitignore").write_text("node_modules\nbuild\ndist\ntarget\n.idea\n")
        subprocess.run(["git", "-C", str(source), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "add gitignore"], capture_output=True)
        for name in ["node_modules", "build", "dist", "target", ".idea"]:
            d = source / name
            d.mkdir()
            (d / "file.txt").write_text("content")

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(source), str(clone)], capture_output=True, check=True)

        linked = slot_git._symlink_gitignored_assets(source, clone)
        assert linked == []
        for name in ["node_modules", "build", "dist", "target", ".idea"]:
            assert not (clone / name).is_symlink()

    def test_skips_directories_already_in_clone(self, tmp_path):
        """If the directory already exists in the clone, don't symlink over it."""
        source = init_repo(tmp_path / "source")
        (source / ".gitignore").write_text(".cache\n")
        subprocess.run(["git", "-C", str(source), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "add gitignore"], capture_output=True)
        (source / ".cache").mkdir()
        (source / ".cache" / "data").write_text("cached")

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(source), str(clone)], capture_output=True, check=True)
        (clone / ".cache").mkdir()
        (clone / ".cache" / "local").write_text("clone-local")

        linked = slot_git._symlink_gitignored_assets(source, clone)
        assert ".cache" not in linked
        assert not (clone / ".cache").is_symlink()
        assert (clone / ".cache" / "local").read_text() == "clone-local"

    def test_skips_non_gitignored_directories(self, tmp_path):
        """Directories that are tracked (not gitignored) should not be symlinked."""
        source = init_repo(tmp_path / "source")
        src_dir = source / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("print('hi')")
        subprocess.run(["git", "-C", str(source), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "add src"], capture_output=True)

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(source), str(clone)], capture_output=True, check=True)

        linked = slot_git._symlink_gitignored_assets(source, clone)
        assert linked == []

    def test_skips_files_not_directories(self, tmp_path):
        """Gitignored files (not directories) should not be symlinked."""
        source = init_repo(tmp_path / "source")
        (source / ".gitignore").write_text(".env\n")
        subprocess.run(["git", "-C", str(source), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "add gitignore"], capture_output=True)
        (source / ".env").write_text("SECRET=abc")

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(source), str(clone)], capture_output=True, check=True)

        linked = slot_git._symlink_gitignored_assets(source, clone)
        assert linked == []
        assert not (clone / ".env").exists()



class TestSyncMainDoesNotMutateBranch:
    def test_sync_main_preserves_feature_branch_when_origin_advanced(self, tmp_path):
        """sync_main must not rebase the source repo when it is on a feature branch."""
        repo = init_repo_with_remote(tmp_path / "repo")
        bare = tmp_path / ".repo-bare.git"

        # Create a second clone, push a new commit to origin/main
        other = tmp_path / "other"
        subprocess.run(["git", "clone", str(bare), str(other)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(other), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(other), "config", "user.email", "t@t"], capture_output=True)
        (other / "upstream.txt").write_text("new upstream work")
        subprocess.run(["git", "-C", str(other), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(other), "commit", "-m", "feat: upstream advance"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(other), "push", "origin", "main"],
                       capture_output=True, check=True)

        # Switch source repo to a feature branch with its own commit
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feature-work"],
                       capture_output=True, check=True)
        (repo / "feature.txt").write_text("work in progress")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "wip: feature"],
                       capture_output=True, check=True)
        feature_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()

        slot_git.sync_main(str(repo))

        current_branch = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
        current_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        assert current_branch == "feature-work", f"Branch changed to {current_branch}"
        assert current_sha == feature_sha, "HEAD SHA changed — rebase mutated the feature branch"
