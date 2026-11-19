"""Safe promotion: to_project and sweep_promotion_gaps use a temporary checkout
so the project's working tree, index and checked-out branch are never touched (#558)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def g(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=check, env=GIT_ENV,
    ).stdout.strip()


def init(path: Path) -> Path:
    path.mkdir(parents=True)
    g(path, "init", "-q", "-b", "main")
    g(path, "config", "user.name", "T")
    g(path, "config", "user.email", "t@t")
    (path / "README.md").write_text("init\n")
    g(path, "add", ".")
    g(path, "commit", "-q", "-m", "init")
    return path


def with_remote(repo: Path, bare: Path) -> Path:
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(bare)],
        capture_output=True, check=True, env=GIT_ENV,
    )
    g(repo, "remote", "add", "origin", str(bare))
    g(repo, "push", "-q", "-u", "origin", "main")
    return bare


def slot_clone(canon: Path, slot: Path) -> Path:
    slot.mkdir(parents=True, exist_ok=True)
    (slot / ".slot").write_text("# Slot\n")
    clone = slot / canon.name
    subprocess.run(
        ["git", "clone", "-q", str(canon), str(clone)],
        capture_output=True, check=True, env=GIT_ENV,
    )
    g(clone, "config", "user.name", "T")
    g(clone, "config", "user.email", "t@t")
    g(clone, "remote", "rename", "origin", "local")
    return clone


def run(*args: str) -> tuple[int, dict[str, str], str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=GIT_ENV,
    )
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            if key not in out:
                out[key] = value
    return result.returncode, out, result.stdout + result.stderr


def _pair(tmp_path: Path):
    proj = init(tmp_path / "project")
    bare = with_remote(proj, tmp_path / "proj.git")
    ws = init(tmp_path / "workspace")
    (ws / "blog").mkdir()
    (ws / "blog" / "entry.md").write_text("the entry\n")
    return proj, ws, bare


class TestToProjectOnFeatureBranch:
    """a. project on a feature branch: promotion commit is on main, feature branch untouched."""

    def test_promotion_commit_on_main_not_feature_branch(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        g(proj, "checkout", "-q", "-b", "issue-42")
        (proj / "feature.txt").write_text("wip\n")
        feature_tip = g(proj, "rev-parse", "HEAD")
        main_tip = g(proj, "rev-parse", "main")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        assert g(proj, "branch", "--show-current") == "issue-42"
        assert g(proj, "rev-parse", "HEAD") == feature_tip
        new_main = g(proj, "rev-parse", "main")
        assert new_main != main_tip
        assert g(proj, "show", "main:docs/blog/entry.md") == "the entry"
        assert g(proj, "show", "issue-42:docs/blog/entry.md", check=False) == ""


class TestToProjectDirtyTree:
    """b. project dirty: modified tracked file + untracked file under docs/ untouched."""

    def test_dirty_project_on_feature_branch_untouched(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        g(proj, "checkout", "-q", "-b", "issue-42")
        (proj / "README.md").write_text("modified\n")
        (proj / "docs").mkdir(exist_ok=True)
        (proj / "docs" / "draft.md").write_text("untracked draft\n")

        status_before = g(proj, "status", "--porcelain")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert (proj / "README.md").read_text() == "modified\n"
        assert (proj / "docs" / "draft.md").read_text() == "untracked draft\n"
        assert g(proj, "branch", "--show-current") == "issue-42"
        assert g(proj, "status", "--porcelain") == status_before
        committed_files = g(proj, "diff-tree", "--no-commit-id", "--name-only", "-r", "main")
        assert "docs/draft.md" not in committed_files
        assert "README.md" not in committed_files


class TestPromotionCommitContent:
    """c. the promotion commit contains exactly the promoted files."""

    def test_commit_on_main_contains_only_promoted_files(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        g(proj, "checkout", "-q", "-b", "issue-42")
        main_before = g(proj, "rev-parse", "main")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        main_after = g(proj, "rev-parse", "main")
        assert main_after != main_before
        files_in_commit = g(proj, "diff-tree", "--no-commit-id", "--name-only", "-r", "main").splitlines()
        assert files_in_commit == ["docs/blog/entry.md"]

    def test_sweep_commit_excludes_stray_files(self, tmp_path):
        proj = init(tmp_path / "project")
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("the entry\n")
        (proj / "docs").mkdir(exist_ok=True)
        (proj / "docs" / "stray.md").write_text("stray untracked\n")

        rc, out, text = run("sweep-gaps", str(proj), str(ws))

        assert rc == 0, text
        files = g(proj, "diff-tree", "--no-commit-id", "--name-only", "-r", "main").splitlines()
        assert "docs/stray.md" not in files
        assert "docs/blog/entry.md" in files


class TestDryRun:
    """d. dry_run=yes changes nothing."""

    def test_dry_run_to_project(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        refs_before = g(proj, "for-each-ref")
        status_before = g(proj, "status", "--porcelain")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/", "dry_run=yes")

        assert rc == 0, text
        assert out.get("DRY_RUN") == "yes"
        assert g(proj, "for-each-ref") == refs_before
        assert g(proj, "status", "--porcelain") == status_before

    def test_dry_run_sweep(self, tmp_path):
        proj = init(tmp_path / "project")
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("the entry\n")
        refs_before = g(proj, "for-each-ref")
        status_before = g(proj, "status", "--porcelain")

        rc, out, text = run("sweep-gaps", str(proj), str(ws), "dry_run=yes")

        assert rc == 0, text
        assert out.get("DRY_RUN") == "yes"
        assert g(proj, "for-each-ref") == refs_before
        assert g(proj, "status", "--porcelain") == status_before


class TestConflict:
    """e. existing different file at destination -> CONFLICT, not overwritten."""

    def test_different_content_produces_conflict(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        (proj / "docs" / "blog").mkdir(parents=True)
        (proj / "docs" / "blog" / "entry.md").write_text("different content\n")
        g(proj, "add", ".")
        g(proj, "commit", "-q", "-m", "docs: existing entry")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out.get("CONFLICT") == "docs/blog/entry.md"
        assert g(proj, "show", "main:docs/blog/entry.md") == "different content"


class TestAlreadyPromoted:
    """f. existing identical file -> not counted as a gap, no empty commit."""

    def test_identical_file_not_a_gap(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        (proj / "docs" / "blog").mkdir(parents=True)
        (proj / "docs" / "blog" / "entry.md").write_text("the entry\n")
        g(proj, "add", ".")
        g(proj, "commit", "-q", "-m", "docs: existing entry")
        main_tip = g(proj, "rev-parse", "main")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["PROMOTED"] == "0"
        assert g(proj, "rev-parse", "main") == main_tip


class TestSlotClone:
    """g. slot clone project: commit reaches canonical main through `local`."""

    def test_slot_clone_lands_on_canonical(self, tmp_path):
        canon = init(tmp_path / "project")
        bare = with_remote(canon, tmp_path / "proj.git")
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("the entry\n")
        clone = slot_clone(canon, tmp_path / "slots" / "5")

        rc, out, text = run("to-project", str(clone), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        assert out["LANDED"] == "yes"
        assert g(canon, "show", "main:docs/blog/entry.md") == "the entry"


class TestScopeBranch:
    """h. scope=branch still commits on the working branch."""

    def test_scope_branch_commits_on_working_branch(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        g(proj, "checkout", "-q", "-b", "issue-42")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/", "scope=branch")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        assert g(proj, "show", "issue-42:docs/blog/entry.md") == "the entry"


class TestImageCopromotion:
    """i. image referenced by a promoted blog entry travels with it."""

    def test_image_travels_with_entry(self, tmp_path):
        proj = init(tmp_path / "project")
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "images").mkdir()
        (ws / "blog" / "entry.md").write_text("# Entry\n\n![diagram](images/arch.svg)\n")
        (ws / "blog" / "images" / "arch.svg").write_text(
            '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>\n'
        )

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        assert g(proj, "show", "main:docs/blog/images/arch.svg", check=False) != ""
        files = g(proj, "diff-tree", "--no-commit-id", "--name-only", "-r", "main").splitlines()
        assert "docs/blog/entry.md" in files
        assert "docs/blog/images/arch.svg" in files


class TestSweepOnFeatureBranch:
    """sweep_promotion_gaps: project on a feature branch, commit lands on main."""

    def test_sweep_commits_on_main(self, tmp_path):
        proj = init(tmp_path / "project")
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("the entry\n")
        g(proj, "checkout", "-q", "-b", "issue-42")
        feature_tip = g(proj, "rev-parse", "HEAD")

        rc, out, text = run("sweep-gaps", str(proj), str(ws))

        assert rc == 0, text
        assert g(proj, "branch", "--show-current") == "issue-42"
        assert g(proj, "rev-parse", "HEAD") == feature_tip
        assert g(proj, "show", "main:docs/blog/entry.md") == "the entry"

    def test_sweep_dirty_project_untouched(self, tmp_path):
        proj = init(tmp_path / "project")
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("the entry\n")
        (proj / "README.md").write_text("modified\n")
        (proj / "docs").mkdir(exist_ok=True)
        (proj / "docs" / "stray.md").write_text("stray\n")

        rc, out, text = run("sweep-gaps", str(proj), str(ws))

        assert rc == 0, text
        assert (proj / "README.md").read_text() == "modified\n"
        assert (proj / "docs" / "stray.md").read_text() == "stray\n"
        files = g(proj, "diff-tree", "--no-commit-id", "--name-only", "-r", "main").splitlines()
        assert "docs/stray.md" not in files


class TestOnMainClean:
    """Canonical project checked out on main, clean: after promotion status is
    empty and files are in both the working tree and HEAD."""

    def test_clean_project_on_main(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        assert g(proj, "status", "--porcelain") == ""
        assert (proj / "docs" / "blog" / "entry.md").exists()
        assert g(proj, "show", "main:docs/blog/entry.md") == "the entry"
        assert g(proj, "diff", "--cached", "--quiet", "HEAD", check=False) == ""


class TestOnMainDirtyWithStagedChange:
    """Canonical project on main with a modified tracked file, an untracked file,
    and an unrelated STAGED change: after promotion status is identical, the
    promotion commit contains only the promoted files, and the staged change is
    still staged."""

    def test_dirty_staged_project_on_main(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        (proj / "README.md").write_text("modified\n")
        (proj / "docs").mkdir(exist_ok=True)
        (proj / "docs" / "untracked.md").write_text("untracked\n")
        (proj / "NOTES.md").write_text("staged note\n")
        g(proj, "add", "NOTES.md")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        assert (proj / "README.md").read_text() == "modified\n"
        assert (proj / "docs" / "untracked.md").read_text() == "untracked\n"
        assert g(proj, "diff", "--cached", "--name-only").strip() == "NOTES.md"
        files = g(proj, "diff-tree", "--no-commit-id", "--name-only", "-r", "main").splitlines()
        assert files == ["docs/blog/entry.md"]


class TestUntrackedConflictAtDest:
    """An untracked file at a destination path with different content: CONFLICT,
    file untouched, no commit for it."""

    def test_untracked_conflict(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        (proj / "docs" / "blog").mkdir(parents=True)
        (proj / "docs" / "blog" / "entry.md").write_text("different\n")
        main_before = g(proj, "rev-parse", "main")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out.get("CONFLICT") == "docs/blog/entry.md"
        assert (proj / "docs" / "blog" / "entry.md").read_text() == "different\n"
        assert g(proj, "rev-parse", "main") == main_before


class TestCommitFailureRollback:
    """A commit-msg hook that rejects -> exit 1, nothing committed,
    git status identical to before."""

    def _install_reject_hook(self, repo: Path) -> None:
        hooks = repo / ".git" / "hooks"
        hooks.mkdir(exist_ok=True)
        hook = hooks / "commit-msg"
        hook.write_text("#!/bin/bash\nexit 1\n")
        hook.chmod(0o755)

    def test_to_project_rollback(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        self._install_reject_hook(proj)
        status_before = g(proj, "status", "--porcelain")
        main_before = g(proj, "rev-parse", "main")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 1, text
        assert out.get("ERROR") == "commit_failed"
        assert out.get("PROMOTED") == "0"
        assert g(proj, "status", "--porcelain") == status_before
        assert g(proj, "rev-parse", "main") == main_before
        assert g(proj, "diff", "--cached", "--quiet", check=False) == ""

    def test_sweep_rollback(self, tmp_path):
        proj = init(tmp_path / "project")
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("the entry\n")
        self._install_reject_hook(proj)
        status_before = g(proj, "status", "--porcelain")
        main_before = g(proj, "rev-parse", "main")

        rc, out, text = run("sweep-gaps", str(proj), str(ws))

        assert rc == 1, text
        assert out.get("ERROR") == "commit_failed"
        assert out.get("SWEPT") == "0"
        assert g(proj, "status", "--porcelain") == status_before
        assert g(proj, "rev-parse", "main") == main_before
        assert g(proj, "diff", "--cached", "--quiet", check=False) == ""


class TestCommitMsgPassesHook:
    """Commit message passes both hook generations."""

    def _install_old_hook(self, repo: Path) -> None:
        hooks = repo / ".git" / "hooks"
        hooks.mkdir(exist_ok=True)
        hook = hooks / "commit-msg"
        hook.write_text(
            '#!/bin/bash\n'
            'MSG=$(cat "$1")\n'
            'if echo "$MSG" | grep -qE \'(Refs|Closes|Fixes|Resolves) #[0-9]+\'; then exit 0; fi\n'
            'if echo "$MSG" | grep -qi \'no-issue\'; then exit 0; fi\n'
            'exit 1\n'
        )
        hook.chmod(0o755)

    def _install_current_hook(self, repo: Path) -> None:
        hooks = repo / ".git" / "hooks"
        hooks.mkdir(exist_ok=True)
        hook = hooks / "commit-msg"
        hook.write_text(
            '#!/bin/bash\n'
            'MSG=$(cat "$1")\n'
            "if echo \"$MSG\" | grep -qE '(Refs|Closes|Fixes|Resolves) ([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)?#[0-9]+'; then exit 0; fi\n"
            "if echo \"$MSG\" | grep -qi 'no-issue'; then exit 0; fi\n"
            'exit 1\n'
        )
        hook.chmod(0o755)

    def test_with_covers_old_hook(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        self._install_old_hook(proj)

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/", "covers=42")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"

    def test_with_covers_current_hook(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        self._install_current_hook(proj)

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/", "covers=42")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"

    def test_without_covers_old_hook(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        self._install_old_hook(proj)

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"

    def test_without_covers_current_hook(self, tmp_path):
        proj, ws, bare = _pair(tmp_path)
        self._install_current_hook(proj)

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"

    def test_sweep_with_covers_old_hook(self, tmp_path):
        proj = init(tmp_path / "project")
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("the entry\n")
        self._install_old_hook(proj)

        rc, out, text = run("sweep-gaps", str(proj), str(ws), "covers=42")

        assert rc == 0, text
        assert int(out["SWEPT"]) > 0

    def test_sweep_without_covers_current_hook(self, tmp_path):
        proj = init(tmp_path / "project")
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("the entry\n")
        self._install_current_hook(proj)

        rc, out, text = run("sweep-gaps", str(proj), str(ws))

        assert rc == 0, text
        assert int(out["SWEPT"]) > 0


class TestImageInNonStandardDir:
    """Blog entry referencing an image in a sibling directory that is not
    images/, svg/ or assets/ -> image is in the promotion commit, nothing
    left staged."""

    def test_image_in_custom_dir(self, tmp_path):
        proj = init(tmp_path / "project")
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "diagrams").mkdir()
        (ws / "blog" / "entry.md").write_text("# Entry\n\n![d](diagrams/flow.svg)\n")
        (ws / "blog" / "diagrams" / "flow.svg").write_text(
            '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>\n'
        )

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=blog/entry.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        files = g(proj, "diff-tree", "--no-commit-id", "--name-only", "-r", "main").splitlines()
        assert "docs/blog/entry.md" in files
        assert "docs/blog/diagrams/flow.svg" in files
        assert g(proj, "diff", "--cached", "--quiet", check=False) == ""


class TestDirectoryArtifactFileByFile:
    """Directory artifacts: destination directory holding an untracked file
    and a different-content file -> both untouched, CONFLICT printed,
    other files promoted."""

    def test_dir_conflict_and_partial_promote(self, tmp_path):
        proj = init(tmp_path / "project")
        ws = init(tmp_path / "workspace")
        spec_dir = ws / "specs"
        spec_dir.mkdir()
        (spec_dir / "a.md").write_text("spec a\n")
        (spec_dir / "b.md").write_text("spec b\n")
        (spec_dir / "c.md").write_text("spec c\n")
        (proj / "docs").mkdir()
        (proj / "docs" / "specs").mkdir(parents=True)
        (proj / "docs" / "specs" / "b.md").write_text("different b\n")
        (proj / "docs" / "specs" / "extra.md").write_text("untracked extra\n")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=specs", "dest-prefix=docs/")

        assert rc == 0, text
        assert "CONFLICT=docs/specs/b.md" in text
        assert (proj / "docs" / "specs" / "b.md").read_text() == "different b\n"
        assert (proj / "docs" / "specs" / "extra.md").read_text() == "untracked extra\n"
        files = g(proj, "diff-tree", "--no-commit-id", "--name-only", "-r", "main").splitlines()
        assert "docs/specs/a.md" in files
        assert "docs/specs/c.md" in files
        assert "docs/specs/b.md" not in files
        assert "docs/specs/extra.md" not in files
        assert g(proj, "diff", "--cached", "--quiet", check=False) == ""


class TestRollbackLeavesExistingFilesAlone:
    """A path that was already in the branch is restored, never removed."""

    def test_tracked_path_is_restored_and_new_path_removed(self, tmp_path):
        import subprocess
        import artifact_promote
        repo = tmp_path / "proj"
        repo.mkdir()
        def g(*a):
            return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)
        g("init", "-q", "-b", "main")
        (repo / "docs").mkdir()
        (repo / "docs" / "shared.png").write_bytes(b"original")
        g("add", "-A")
        assert g("-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q", "-m", "init").returncode == 0
        (repo / "docs" / "shared.png").write_bytes(b"overwritten by the run")
        (repo / "docs" / "new.md").write_text("copied by the run")
        g("add", "docs/shared.png", "docs/new.md")

        artifact_promote._rollback_copied(str(repo), ["docs/shared.png", "docs/new.md"])

        assert (repo / "docs" / "shared.png").read_bytes() == b"original"
        assert not (repo / "docs" / "new.md").exists()
        assert g("status", "--porcelain").stdout.strip() == ""
