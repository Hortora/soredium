"""Tests for the shared land flow (work-end convergence)."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))


def _init_repo(path: Path) -> Path:
    """Create a git repo with a bare remote and initial commit on main."""
    bare = path.parent / f".{path.name}-bare.git"
    bare.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", str(bare), str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], capture_output=True)
    (path / "README.md").write_text(f"# {path.name}\n")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "initial"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "push", "-u", "origin", "main"], capture_output=True, check=True)
    return path


def _add_feature(repo: Path, branch: str, filename: str = "feature.py") -> None:
    """Create a feature branch with a commit."""
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", branch], capture_output=True, check=True)
    (repo / filename).write_text(f"# {filename}\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", f"feat: add {filename}"], capture_output=True, check=True)


def _make_slot_clone(original: Path, clone_path: Path, branch: str) -> Path:
    """Create a slot-style clone with local remote pointing at original."""
    subprocess.run(
        ["git", "-C", str(original), "config", "receive.denyCurrentBranch", "updateInstead"],
        capture_output=True,
    )
    subprocess.run(
        ["git", "clone", "--shared", str(original), str(clone_path)],
        capture_output=True, check=True,
    )
    subprocess.run(["git", "-C", str(clone_path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(clone_path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(clone_path), "remote", "rename", "origin", "local"], capture_output=True, check=True)
    bare = original.parent / f".{original.name}-bare.git"
    subprocess.run(["git", "-C", str(clone_path), "remote", "add", "origin", str(bare)], capture_output=True)
    subprocess.run(["git", "-C", str(clone_path), "fetch", "origin"], capture_output=True)
    subprocess.run(["git", "-C", str(clone_path), "checkout", "-b", branch], capture_output=True, check=True)
    (clone_path / "feature.py").write_text("# slot feature\n")
    subprocess.run(["git", "-C", str(clone_path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(clone_path), "commit", "-m", "feat: slot feature"], capture_output=True, check=True)
    return clone_path


# ---------------------------------------------------------------------------
# Data structure tests
# ---------------------------------------------------------------------------


class TestTransportEnum:
    def test_values(self):
        from land_flow import Transport
        assert Transport.DIRECT.value == "direct"
        assert Transport.TWO_HOP.value == "two-hop"


class TestRepoDescriptor:
    def test_direct_descriptor(self):
        from land_flow import RepoDescriptor, Transport
        d = RepoDescriptor(
            repo_path=Path("/tmp/repo"),
            original_path=Path("/tmp/repo"),
            push_target="origin",
            base_branch="main",
            is_workspace=False,
            transport=Transport.DIRECT,
        )
        assert d.repo_path == d.original_path
        assert d.transport == Transport.DIRECT
        assert not d.is_workspace

    def test_two_hop_descriptor(self):
        from land_flow import RepoDescriptor, Transport
        d = RepoDescriptor(
            repo_path=Path("/tmp/clone"),
            original_path=Path("/tmp/original"),
            push_target="local",
            base_branch="main",
            is_workspace=False,
            transport=Transport.TWO_HOP,
        )
        assert d.repo_path != d.original_path
        assert d.transport == Transport.TWO_HOP

    def test_project_sorts_before_workspace(self):
        from land_flow import RepoDescriptor, Transport
        ws = RepoDescriptor(
            repo_path=Path("/tmp/ws"), original_path=Path("/tmp/ws"),
            push_target="origin", base_branch="main",
            is_workspace=True, transport=Transport.DIRECT,
        )
        proj = RepoDescriptor(
            repo_path=Path("/tmp/proj"), original_path=Path("/tmp/proj"),
            push_target="origin", base_branch="main",
            is_workspace=False, transport=Transport.DIRECT,
        )
        batch = sorted([ws, proj], key=lambda d: d.is_workspace)
        assert not batch[0].is_workspace
        assert batch[1].is_workspace


# ---------------------------------------------------------------------------
# Direct transport end-to-end
# ---------------------------------------------------------------------------


class TestLandBatchDirectSingleRepo:
    def test_merges_pushes_and_stamps(self, tmp_path):
        from land_flow import RepoDescriptor, Transport, land_batch
        repo = _init_repo(tmp_path / "project")
        branch = "issue-42-test"
        _add_feature(repo, branch)

        desc = RepoDescriptor(
            repo_path=repo, original_path=repo, push_target="origin",
            base_branch="main", is_workspace=False, transport=Transport.DIRECT,
        )
        result = land_batch([desc], branch, tmp_path / ".progress")

        assert result.success
        assert len(result.repos) == 1
        s = result.repos[0]
        assert s.merged
        assert s.pushed
        assert s.stamped
        assert s.landed_sha
        # Feature file should be on main
        subprocess.run(["git", "-C", str(repo), "checkout", "main"], capture_output=True)
        assert (repo / "feature.py").exists()

    def test_stamp_commit_exists(self, tmp_path):
        from land_flow import RepoDescriptor, Transport, land_batch
        repo = _init_repo(tmp_path / "project")
        branch = "issue-42-test"
        _add_feature(repo, branch)

        desc = RepoDescriptor(
            repo_path=repo, original_path=repo, push_target="origin",
            base_branch="main", is_workspace=False, transport=Transport.DIRECT,
        )
        land_batch([desc], branch, tmp_path / ".progress")

        log = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%s", branch],
            capture_output=True, text=True,
        )
        assert log.stdout.strip().startswith("chore: branch closed")
        assert "Refs #42" in log.stdout.strip()

    def test_pushed_to_remote(self, tmp_path):
        from land_flow import RepoDescriptor, Transport, land_batch
        repo = _init_repo(tmp_path / "project")
        branch = "issue-42-test"
        _add_feature(repo, branch)

        desc = RepoDescriptor(
            repo_path=repo, original_path=repo, push_target="origin",
            base_branch="main", is_workspace=False, transport=Transport.DIRECT,
        )
        result = land_batch([desc], branch, tmp_path / ".progress")

        # Verify SHA is on remote
        bare = tmp_path / ".project-bare.git"
        sha = subprocess.run(
            ["git", "-C", str(bare), "rev-parse", "main"],
            capture_output=True, text=True,
        )
        assert sha.stdout.strip() == result.repos[0].landed_sha


class TestLandBatchDirectProjectAndWorkspace:
    def test_both_repos_landed(self, tmp_path):
        from land_flow import RepoDescriptor, Transport, land_batch
        proj = _init_repo(tmp_path / "project")
        ws = _init_repo(tmp_path / "workspace")
        branch = "issue-42-test"
        _add_feature(proj, branch, "feature.py")
        _add_feature(ws, branch, "notes.md")

        descs = [
            RepoDescriptor(
                repo_path=proj, original_path=proj, push_target="origin",
                base_branch="main", is_workspace=False, transport=Transport.DIRECT,
            ),
            RepoDescriptor(
                repo_path=ws, original_path=ws, push_target="origin",
                base_branch="main", is_workspace=True, transport=Transport.DIRECT,
            ),
        ]
        result = land_batch(descs, branch, tmp_path / ".progress")

        assert result.success
        assert len(result.repos) == 2
        assert all(s.merged and s.pushed and s.stamped for s in result.repos)

    def test_project_lands_before_workspace(self, tmp_path):
        """Project repos ordered before workspace repos regardless of input order."""
        from land_flow import RepoDescriptor, Transport, land_batch
        proj = _init_repo(tmp_path / "project")
        ws = _init_repo(tmp_path / "workspace")
        branch = "issue-42-test"
        _add_feature(proj, branch, "feature.py")
        _add_feature(ws, branch, "notes.md")

        descs = [
            RepoDescriptor(
                repo_path=ws, original_path=ws, push_target="origin",
                base_branch="main", is_workspace=True, transport=Transport.DIRECT,
            ),
            RepoDescriptor(
                repo_path=proj, original_path=proj, push_target="origin",
                base_branch="main", is_workspace=False, transport=Transport.DIRECT,
            ),
        ]
        result = land_batch(descs, branch, tmp_path / ".progress")

        assert result.success
        # First in result should be project (sorted by is_workspace)
        assert result.repos[0].repo_path == proj
        assert result.repos[1].repo_path == ws


# ---------------------------------------------------------------------------
# Two-hop transport end-to-end
# ---------------------------------------------------------------------------


class TestLandBatchTwoHop:
    def test_merges_and_pushes_via_original(self, tmp_path):
        from land_flow import RepoDescriptor, Transport, land_batch
        original = _init_repo(tmp_path / "original")
        branch = "issue-42-test"
        clone = _make_slot_clone(original, tmp_path / "clone", branch)

        desc = RepoDescriptor(
            repo_path=clone, original_path=original, push_target="local",
            base_branch="main", is_workspace=False, transport=Transport.TWO_HOP,
        )
        result = land_batch([desc], branch, tmp_path / ".progress")

        assert result.success
        assert len(result.repos) == 1
        s = result.repos[0]
        assert s.merged
        assert s.pushed
        assert s.stamped
        assert s.landed_sha
        # Feature should be on original's main
        subprocess.run(["git", "-C", str(original), "checkout", "main"], capture_output=True)
        assert (original / "feature.py").exists()

    def test_stamps_all_repos_including_workspace(self, tmp_path):
        from land_flow import RepoDescriptor, Transport, land_batch
        proj_orig = _init_repo(tmp_path / "proj-orig")
        ws_orig = _init_repo(tmp_path / "ws-orig")
        branch = "issue-42-test"
        proj_clone = _make_slot_clone(proj_orig, tmp_path / "proj-clone", branch)
        ws_clone = _make_slot_clone(ws_orig, tmp_path / "ws-clone", branch)

        descs = [
            RepoDescriptor(
                repo_path=proj_clone, original_path=proj_orig, push_target="local",
                base_branch="main", is_workspace=False, transport=Transport.TWO_HOP,
            ),
            RepoDescriptor(
                repo_path=ws_clone, original_path=ws_orig, push_target="local",
                base_branch="main", is_workspace=True, transport=Transport.TWO_HOP,
            ),
        ]
        result = land_batch(descs, branch, tmp_path / ".progress")

        assert result.success
        assert all(s.stamped for s in result.repos)
        subprocess.run(["git", "-C", str(proj_orig), "checkout", "main"], capture_output=True)
        assert (proj_orig / "feature.py").exists(), "Project original must have feature"

    def test_pushed_to_bare_remote(self, tmp_path):
        """Two-hop push lands on the bare remote (GitHub equivalent)."""
        from land_flow import RepoDescriptor, Transport, land_batch
        original = _init_repo(tmp_path / "original")
        branch = "issue-42-test"
        clone = _make_slot_clone(original, tmp_path / "clone", branch)

        desc = RepoDescriptor(
            repo_path=clone, original_path=original, push_target="local",
            base_branch="main", is_workspace=False, transport=Transport.TWO_HOP,
        )
        result = land_batch([desc], branch, tmp_path / ".progress")

        bare = tmp_path / ".original-bare.git"
        sha = subprocess.run(
            ["git", "-C", str(bare), "rev-parse", "main"],
            capture_output=True, text=True,
        )
        assert sha.stdout.strip() == result.repos[0].landed_sha


# ---------------------------------------------------------------------------
# Progress and resume
# ---------------------------------------------------------------------------


class TestLandBatchProgress:
    def test_writes_progress_file(self, tmp_path):
        from land_flow import RepoDescriptor, Transport, land_batch
        repo = _init_repo(tmp_path / "project")
        branch = "issue-42-test"
        _add_feature(repo, branch)

        desc = RepoDescriptor(
            repo_path=repo, original_path=repo, push_target="origin",
            base_branch="main", is_workspace=False, transport=Transport.DIRECT,
        )
        progress = tmp_path / ".progress"
        land_batch([desc], branch, progress)

        assert progress.exists()
        content = progress.read_text()
        assert "stamped" in content

    def test_skips_already_stamped(self, tmp_path):
        from land_flow import RepoDescriptor, Transport, land_batch
        repo = _init_repo(tmp_path / "project")
        branch = "issue-42-test"
        _add_feature(repo, branch)

        desc = RepoDescriptor(
            repo_path=repo, original_path=repo, push_target="origin",
            base_branch="main", is_workspace=False, transport=Transport.DIRECT,
        )
        progress = tmp_path / ".progress"
        progress.write_text(f"project:{branch}=stamped\n")

        result = land_batch([desc], branch, progress)

        assert result.success
        assert len(result.repos) == 1
        assert result.repos[0].skipped


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Adapter tests
# ---------------------------------------------------------------------------


class TestBuildSlotBatch:
    def _make_slot_with_workspace(self, tmp_path, branch="issue-42-test"):
        """Create a slot with one project and one workspace repo."""
        proj_orig = _init_repo(tmp_path / "engine")
        ws_orig = _init_repo(tmp_path / "wsp-casehub-engine")
        for r in [proj_orig, ws_orig]:
            subprocess.run(
                ["git", "-C", str(r), "config", "receive.denyCurrentBranch", "updateInstead"],
                capture_output=True,
            )
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        proj_clone = _make_slot_clone(proj_orig, slot_dir / "engine", branch)
        ws_clone = _make_slot_clone(ws_orig, slot_dir / "wsp-casehub-engine", branch)
        (ws_clone / ".workspace").touch()
        return slot_dir, proj_orig, ws_orig

    def test_includes_both_project_and_workspace(self, tmp_path):
        from land_flow import build_slot_batch
        slot_dir, _, _ = self._make_slot_with_workspace(tmp_path)
        batch = build_slot_batch(slot_dir)
        assert len(batch) == 2
        names = {d.repo_path.name for d in batch}
        assert "engine" in names
        assert "wsp-casehub-engine" in names

    def test_all_two_hop_transport(self, tmp_path):
        from land_flow import build_slot_batch, Transport
        slot_dir, _, _ = self._make_slot_with_workspace(tmp_path)
        batch = build_slot_batch(slot_dir)
        assert all(d.transport == Transport.TWO_HOP for d in batch)

    def test_project_repos_before_workspace(self, tmp_path):
        from land_flow import build_slot_batch
        slot_dir, _, _ = self._make_slot_with_workspace(tmp_path)
        batch = build_slot_batch(slot_dir)
        assert not batch[0].is_workspace
        assert batch[1].is_workspace

    def test_push_target_is_local(self, tmp_path):
        from land_flow import build_slot_batch
        slot_dir, _, _ = self._make_slot_with_workspace(tmp_path)
        batch = build_slot_batch(slot_dir)
        assert all(d.push_target == "local" for d in batch)

    def test_original_path_resolves(self, tmp_path):
        from land_flow import build_slot_batch
        slot_dir, proj_orig, ws_orig = self._make_slot_with_workspace(tmp_path)
        batch = build_slot_batch(slot_dir)
        proj_desc = [d for d in batch if not d.is_workspace][0]
        assert proj_desc.original_path.resolve() == proj_orig.resolve()


class TestBuildBranchBatch:
    def test_direct_transport(self, tmp_path):
        from land_flow import build_branch_batch, Transport
        proj = _init_repo(tmp_path / "project")
        branch = "issue-42-test"
        _add_feature(proj, branch)
        batch = build_branch_batch(proj, None, branch)
        assert len(batch) == 1
        assert batch[0].transport == Transport.DIRECT

    def test_push_target_from_topology(self, tmp_path):
        from land_flow import build_branch_batch
        proj = _init_repo(tmp_path / "project")
        branch = "issue-42-test"
        _add_feature(proj, branch)
        batch = build_branch_batch(proj, None, branch)
        assert batch[0].push_target == "origin"

    def test_includes_workspace_with_branch(self, tmp_path):
        from land_flow import build_branch_batch
        proj = _init_repo(tmp_path / "project")
        ws = _init_repo(tmp_path / "workspace")
        branch = "issue-42-test"
        _add_feature(proj, branch)
        _add_feature(ws, branch, "notes.md")
        batch = build_branch_batch(proj, ws, branch)
        assert len(batch) == 2
        assert not batch[0].is_workspace
        assert batch[1].is_workspace

    def test_excludes_workspace_without_branch(self, tmp_path):
        from land_flow import build_branch_batch
        proj = _init_repo(tmp_path / "project")
        ws = _init_repo(tmp_path / "workspace")
        branch = "issue-42-test"
        _add_feature(proj, branch)
        batch = build_branch_batch(proj, ws, branch)
        assert len(batch) == 1

    def test_repo_and_original_same_for_direct(self, tmp_path):
        from land_flow import build_branch_batch
        proj = _init_repo(tmp_path / "project")
        branch = "issue-42-test"
        _add_feature(proj, branch)
        batch = build_branch_batch(proj, None, branch)
        assert batch[0].repo_path == batch[0].original_path


class TestLandBatchErrors:
    def test_no_remote_fails_preflight(self, tmp_path):
        from land_flow import RepoDescriptor, Transport, land_batch
        repo = tmp_path / "no-remote"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"], capture_output=True)
        (repo / "README.md").write_text("# test\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], capture_output=True)
        branch = "issue-42-test"
        _add_feature(repo, branch)

        desc = RepoDescriptor(
            repo_path=repo, original_path=repo, push_target="origin",
            base_branch="main", is_workspace=False, transport=Transport.DIRECT,
        )
        result = land_batch([desc], branch, tmp_path / ".progress")

        assert not result.success
        assert result.repos[0].error
        assert "no_remote" in result.repos[0].error

    def test_merge_conflict_fails(self, tmp_path):
        from land_flow import RepoDescriptor, Transport, land_batch
        repo = _init_repo(tmp_path / "project")
        branch = "issue-42-test"
        _add_feature(repo, branch)
        bare = tmp_path / ".project-bare.git"
        conflict_repo = tmp_path / "conflict-maker"
        subprocess.run(["git", "clone", str(bare), str(conflict_repo)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(conflict_repo), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(conflict_repo), "config", "user.email", "test@test.com"], capture_output=True)
        (conflict_repo / "feature.py").write_text("# conflicting content\n")
        subprocess.run(["git", "-C", str(conflict_repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(conflict_repo), "commit", "-m", "conflict"], capture_output=True)
        subprocess.run(["git", "-C", str(conflict_repo), "push", "origin", "main"], capture_output=True)

        desc = RepoDescriptor(
            repo_path=repo, original_path=repo, push_target="origin",
            base_branch="main", is_workspace=False, transport=Transport.DIRECT,
        )
        result = land_batch([desc], branch, tmp_path / ".progress")

        assert not result.success


# --- Crash-safety tests for _write_progress ---

class TestWriteProgressAtomic:

    def test_write_and_read_roundtrip(self, tmp_path):
        from land_flow import _write_progress, _read_progress
        progress = tmp_path / ".execute-progress"
        _write_progress(progress, "repo:branch", "pushed")
        _write_progress(progress, "repo:branch2", "stamped")
        result = _read_progress(progress)
        assert result["repo:branch"] == "pushed"
        assert result["repo:branch2"] == "stamped"

    def test_no_tmp_file_left(self, tmp_path):
        from land_flow import _write_progress
        progress = tmp_path / ".execute-progress"
        _write_progress(progress, "repo:branch", "pushed")
        assert not (tmp_path / ".execute-progress.tmp").exists()

    def test_survives_crash(self, tmp_path):
        from land_flow import _write_progress, _read_progress
        from unittest.mock import patch
        progress = tmp_path / ".execute-progress"
        _write_progress(progress, "repo:branch", "pushed")

        with patch("os.replace", side_effect=OSError("simulated crash")):
            try:
                _write_progress(progress, "repo:branch", "stamped")
            except OSError:
                pass

        result = _read_progress(progress)
        assert result["repo:branch"] == "pushed", "Prior progress must survive"


class TestDirectWorkspaceMergeAndCleanup:
    """DIRECT workspace repos get merged to main with lifecycle file cleanup (#326)."""

    def _setup_workspace_with_lifecycle(self, tmp_path, branch="issue-326-test"):
        """Create project + workspace with lifecycle files on workspace branch."""
        proj = _init_repo(tmp_path / "project")
        ws = _init_repo(tmp_path / "workspace")
        _add_feature(proj, branch, "feature.py")

        subprocess.run(["git", "-C", str(ws), "checkout", "-b", branch],
                       capture_output=True, check=True)
        (ws / "specs").mkdir(exist_ok=True)
        (ws / "specs" / "design.md").write_text("# Design spec\n")
        (ws / ".plan").write_text("branch: " + branch + "\nstate: active\n")
        (ws / "JOURNAL.md").write_text("# Journal\n")
        (ws / ".execute-progress").write_text("default=promoted\n")
        (ws / ".land-ledger.jsonl").write_text("{}\n")
        (ws / ".artifacts-promoted").write_text("timestamp=2026-01-01\n")
        (ws / ".close-progress").write_text("code_review=done\n")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "feat: workspace artifacts"],
                       capture_output=True, check=True)
        return proj, ws

    def test_direct_workspace_merged_to_main(self, tmp_path: Path):
        """DIRECT workspace branch content (specs) should be on main after land."""
        from land_flow import RepoDescriptor, Transport, land_batch
        proj, ws = self._setup_workspace_with_lifecycle(tmp_path)
        branch = "issue-326-test"

        descs = [
            RepoDescriptor(repo_path=proj, original_path=proj, base_branch="main",
                           push_target="origin", is_workspace=False, transport=Transport.DIRECT),
            RepoDescriptor(repo_path=ws, original_path=ws, base_branch="main",
                           push_target="origin", is_workspace=True, transport=Transport.DIRECT),
        ]
        result = land_batch(descs, branch, tmp_path / ".progress")
        assert result.success

        subprocess.run(["git", "-C", str(ws), "checkout", "main"], capture_output=True)
        assert (ws / "specs" / "design.md").exists(), "Specs should be on workspace main"

    def test_lifecycle_files_cleaned_from_main(self, tmp_path: Path):
        """Lifecycle files must NOT exist on workspace main after land."""
        from land_flow import RepoDescriptor, Transport, land_batch
        proj, ws = self._setup_workspace_with_lifecycle(tmp_path)
        branch = "issue-326-test"

        descs = [
            RepoDescriptor(repo_path=proj, original_path=proj, base_branch="main",
                           push_target="origin", is_workspace=False, transport=Transport.DIRECT),
            RepoDescriptor(repo_path=ws, original_path=ws, base_branch="main",
                           push_target="origin", is_workspace=True, transport=Transport.DIRECT),
        ]
        result = land_batch(descs, branch, tmp_path / ".progress")
        assert result.success

        subprocess.run(["git", "-C", str(ws), "checkout", "main"], capture_output=True)
        for f in [".plan", "JOURNAL.md", ".execute-progress",
                  ".land-ledger.jsonl", ".artifacts-promoted", ".close-progress"]:
            assert not (ws / f).exists(), f"{f} should NOT be on workspace main"

    def test_workspace_stamped_after_merge(self, tmp_path: Path):
        """Workspace branch still gets stamped after merge."""
        from land_flow import RepoDescriptor, Transport, land_batch
        proj, ws = self._setup_workspace_with_lifecycle(tmp_path)
        branch = "issue-326-test"

        descs = [
            RepoDescriptor(repo_path=proj, original_path=proj, base_branch="main",
                           push_target="origin", is_workspace=False, transport=Transport.DIRECT),
            RepoDescriptor(repo_path=ws, original_path=ws, base_branch="main",
                           push_target="origin", is_workspace=True, transport=Transport.DIRECT),
        ]
        result = land_batch(descs, branch, tmp_path / ".progress")
        assert result.success

        stamp = subprocess.run(["git", "-C", str(ws), "log", "-1", "--format=%s", branch],
                               capture_output=True, text=True).stdout.strip()
        assert "branch closed" in stamp, f"Workspace not stamped, tip: {stamp}"

    def test_workspace_pushed_to_remote(self, tmp_path: Path):
        """Workspace main pushed to remote after merge+cleanup."""
        from land_flow import RepoDescriptor, Transport, land_batch
        proj, ws = self._setup_workspace_with_lifecycle(tmp_path)
        branch = "issue-326-test"

        descs = [
            RepoDescriptor(repo_path=proj, original_path=proj, base_branch="main",
                           push_target="origin", is_workspace=False, transport=Transport.DIRECT),
            RepoDescriptor(repo_path=ws, original_path=ws, base_branch="main",
                           push_target="origin", is_workspace=True, transport=Transport.DIRECT),
        ]
        result = land_batch(descs, branch, tmp_path / ".progress")
        assert result.success

        ws_status = next(s for s in result.repos if s.repo_path == ws)
        assert ws_status.pushed, "Workspace should be pushed"
        assert ws_status.merged, "Workspace should be merged"


class TestTwoHopWorkspaceStampOnly:
    """TWO_HOP workspace repos remain stamp-only — no merge (slot mode)."""

    def test_two_hop_workspace_not_merged(self, tmp_path: Path):
        """Slot workspace clones should NOT be merged — stamp only."""
        from land_flow import RepoDescriptor, Transport, land_batch
        proj_orig = _init_repo(tmp_path / "proj-orig")
        ws_orig = _init_repo(tmp_path / "ws-orig")
        branch = "issue-326-slot"
        proj_clone = _make_slot_clone(proj_orig, tmp_path / "proj-clone", branch)
        ws_clone = _make_slot_clone(ws_orig, tmp_path / "ws-clone", branch)

        descs = [
            RepoDescriptor(repo_path=proj_clone, original_path=proj_orig, push_target="local",
                           base_branch="main", is_workspace=False, transport=Transport.TWO_HOP),
            RepoDescriptor(repo_path=ws_clone, original_path=ws_orig, push_target="local",
                           base_branch="main", is_workspace=True, transport=Transport.TWO_HOP),
        ]
        result = land_batch(descs, branch, tmp_path / ".progress")
        assert result.success
        assert all(s.stamped for s in result.repos)

        log = subprocess.run(["git", "-C", str(ws_orig), "log", "--oneline", "main"],
                             capture_output=True, text=True).stdout.strip()
        assert "slot feature" not in log, "Slot workspace should NOT be merged to original"


# ---------------------------------------------------------------------------
# Content verification postcondition
# ---------------------------------------------------------------------------


class TestVerifyContentLanded:
    def test_returns_none_when_content_landed(self, tmp_path):
        """Branch content on main → None (safe to stamp)."""
        from land_flow import RepoDescriptor, Transport, _verify_content_landed
        repo = _init_repo(tmp_path / "repos" / "engine")
        _add_feature(repo, "feat-1", "feature.py")
        subprocess.run(["git", "-C", str(repo), "checkout", "main"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "merge", "--ff-only", "feat-1"], capture_output=True)
        desc = RepoDescriptor(
            repo_path=repo, original_path=repo, push_target="origin",
            base_branch="main", is_workspace=False, transport=Transport.DIRECT,
        )
        result = _verify_content_landed(desc, "feat-1")
        assert result is None

    def test_returns_error_when_content_not_landed(self, tmp_path):
        """Branch has source files not on main → error string."""
        from land_flow import RepoDescriptor, Transport, _verify_content_landed
        repo = _init_repo(tmp_path / "repos" / "engine")
        _add_feature(repo, "feat-1", "feature.py")
        subprocess.run(["git", "-C", str(repo), "checkout", "main"], capture_output=True)
        desc = RepoDescriptor(
            repo_path=repo, original_path=repo, push_target="origin",
            base_branch="main", is_workspace=False, transport=Transport.DIRECT,
        )
        result = _verify_content_landed(desc, "feat-1")
        assert result is not None
        assert "content_not_landed" in result

    def test_returns_none_for_docs_only_branch(self, tmp_path):
        """Branch with only non-source files → None (no false positives)."""
        from land_flow import RepoDescriptor, Transport, _verify_content_landed
        repo = _init_repo(tmp_path / "repos" / "engine")
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "docs-only"], capture_output=True)
        (repo / "docs.md").write_text("# docs\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "docs"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "main"], capture_output=True)
        desc = RepoDescriptor(
            repo_path=repo, original_path=repo, push_target="origin",
            base_branch="main", is_workspace=False, transport=Transport.DIRECT,
        )
        result = _verify_content_landed(desc, "docs-only")
        assert result is None


class TestRebaseFailureWorklog:
    def test_rebase_failure_records_worklog_event(self, tmp_path, monkeypatch):
        """Rebase failure records event via _record_rebase_failure."""
        from land_flow import _record_rebase_failure
        import land_flow

        recorded = []
        class FakeWl:
            @staticmethod
            def connect():
                return FakeConn()
            @staticmethod
            def record_close_event(conn, event_type, mode, branch, **kwargs):
                recorded.append({"event_type": event_type, "branch": branch, **kwargs})
        class FakeConn:
            def close(self):
                pass
            def commit(self):
                pass

        monkeypatch.setattr(land_flow, "_wl", FakeWl())
        _record_rebase_failure(
            repo_path="/tmp/test/engine", branch="feat-1",
            commit_count=849, main_ahead=200,
            error_detail="conflict in feature.py",
        )
        assert len(recorded) == 1
        assert recorded[0]["event_type"] == "rebase_failed"
        assert recorded[0]["branch"] == "feat-1"
        assert recorded[0]["commit_count"] == 849

    def test_record_rebase_failure_survives_missing_worklog(self, tmp_path, monkeypatch):
        """No crash when worklog module is unavailable."""
        import land_flow
        monkeypatch.setattr(land_flow, "_wl", None)
        from land_flow import _record_rebase_failure
        _record_rebase_failure(
            repo_path="/tmp/test/engine", branch="feat-1",
            commit_count=10, main_ahead=5, error_detail="test",
        )


class TestPreflightUntrackedFiles:
    def test_untracked_files_do_not_block_landing(self, tmp_path):
        """Untracked files (?? prefix) should not cause dirty_worktree error."""
        original = _init_repo(tmp_path / "original")
        (original / "untracked.png").write_text("screenshot")

        from land_flow import _preflight_two_hop, RepoDescriptor, Transport
        desc = RepoDescriptor(
            repo_path=tmp_path / "clone",
            original_path=original,
            push_target="origin",
            base_branch="main",
            is_workspace=False,
            transport=Transport.TWO_HOP,
        )
        result = _preflight_two_hop(desc)
        assert result is None or "dirty_worktree" not in result, (
            f"Untracked files should not block: {result}"
        )

    def test_staged_changes_still_block(self, tmp_path):
        """Staged but uncommitted changes should still block."""
        original = _init_repo(tmp_path / "original")
        (original / "dirty.txt").write_text("modified")
        subprocess.run(["git", "-C", str(original), "add", "dirty.txt"],
                       capture_output=True)

        from land_flow import _preflight_two_hop, RepoDescriptor, Transport
        desc = RepoDescriptor(
            repo_path=tmp_path / "clone",
            original_path=original,
            push_target="origin",
            base_branch="main",
            is_workspace=False,
            transport=Transport.TWO_HOP,
        )
        result = _preflight_two_hop(desc)
        assert result is not None and "dirty_worktree" in result
