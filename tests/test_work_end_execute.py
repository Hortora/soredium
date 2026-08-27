"""Tests for work-end/work_end_execute.py"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parent.parent / "work-end" / "work_end_execute.py"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("init\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial commit")
    return path


def _init_bare(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(path)], capture_output=True, check=True)
    return path


def _run_execute(
    subcommand: str, *extra_args: str,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), subcommand, *extra_args],
        capture_output=True, text=True, timeout=30,
    )


class TestPromoteSingleRepo:
    def test_promote_writes_progress(self, tmp_path: Path) -> None:
        workspace = _init_repo(tmp_path / "workspace")
        project = _init_repo(tmp_path / "project")
        branch = "issue-99-test"

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        _git(project, "checkout", "-b", branch)

        result = _run_execute(
            "promote",
            f"workspace={workspace}",
            f"project={project}",
            f"branch={branch}",
        )
        assert result.returncode == 0
        assert "PROMOTED=yes" in result.stdout

        progress_path = workspace / ".execute-progress"
        assert progress_path.exists()
        content = progress_path.read_text()
        assert "promoted" in content

    def test_promote_skips_already_promoted(self, tmp_path: Path) -> None:
        workspace = _init_repo(tmp_path / "workspace")
        project = _init_repo(tmp_path / "project")
        branch = "issue-100-test"

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        (workspace / ".execute-progress").write_text("default=promoted\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        _git(project, "checkout", "-b", branch)

        result = _run_execute(
            "promote",
            f"workspace={workspace}",
            f"project={project}",
            f"branch={branch}",
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout or "already" in result.stdout.lower()


class TestRebaseSingleRepo:
    def test_rebase_onto_base(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", "issue-101-test")
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: feature")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-101-test",
            "base_branch=main",
        )
        assert result.returncode == 0
        assert "REBASED=yes" in result.stdout

    def test_rebase_conflict_reports_error(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", "issue-102-test")
        (project / "README.md").write_text("branch version\n")
        _git(project, "add", "README.md")
        _git(project, "commit", "-m", "feat: branch change")

        _git(project, "checkout", "main")
        (project / "README.md").write_text("main version\n")
        _git(project, "add", "README.md")
        _git(project, "commit", "-m", "fix: main change")
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "issue-102-test")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-102-test",
            "base_branch=main",
        )
        assert "ERROR=REBASE_CONFLICT" in result.stdout

    def test_rebase_uses_blessed_remote_in_fork_model(self, tmp_path: Path) -> None:
        """In fork model, rebase should fetch from upstream, not origin."""
        blessed = _init_bare(tmp_path / "blessed.git")
        fork = _init_bare(tmp_path / "fork.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(fork))
        _git(project, "remote", "add", "upstream", str(blessed))
        _git(project, "push", "origin", "main")
        _git(project, "push", "upstream", "main")

        # Push a new commit to upstream only (not to origin/fork)
        other = tmp_path / "other"
        subprocess.run(["git", "clone", str(blessed), str(other)],
                       capture_output=True, check=True)
        _git(other, "config", "user.email", "other@test.com")
        _git(other, "config", "user.name", "Other")
        (other / "upstream-work.txt").write_text("from upstream\n")
        _git(other, "add", "upstream-work.txt")
        _git(other, "commit", "-m", "feat: upstream work")
        _git(other, "push", "origin", "main")

        _git(project, "checkout", "-b", "issue-fork-rebase")
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: our work")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-fork-rebase",
            "base_branch=main",
        )
        assert result.returncode == 0
        assert "REBASE_REMOTE=upstream" in result.stdout
        assert "REBASED=yes" in result.stdout

        log = _git(project, "log", "--oneline")
        assert "feat: upstream work" in log


    def test_rebase_onto_uses_onto_form(self, tmp_path: Path) -> None:
        """rebase_onto= uses git rebase --onto to handle filter-repo'd branches."""
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", "issue-305-test")
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: feature")

        old_base = _git(project, "merge-base", "main", "HEAD")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-305-test",
            "base_branch=main",
            f"rebase_onto={old_base}",
        )
        assert result.returncode == 0
        assert "REBASED=yes" in result.stdout
        assert "REBASE_ONTO=" in result.stdout


class TestLandSingleRepo:
    def test_land_pushes_and_stamps(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-103-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: add feature")
        _git(project, "push", "origin", branch)

        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0
        assert "LANDED=yes" in result.stdout

        last_msg = _git(project, "log", "-1", "--format=%s", branch)
        assert last_msg.startswith("chore: branch closed")

    def test_land_pushes_main(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-104-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: add feature")
        _git(project, "push", "origin", branch)

        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0

        unpushed = _git(project, "log", "origin/main..main", "--oneline")
        assert not unpushed

    def test_land_stamps_workspace(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-105-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")
        _git(project, "checkout", "-b", branch)
        _git(project, "commit", "--allow-empty", "-m", "feat: work")
        _git(project, "push", "origin", branch)
        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0

        ws_tip = _git(workspace, "log", "-1", "--format=%s", branch)
        assert ws_tip.startswith("chore: branch closed")


class TestLandMergesBeforePush:
    def test_land_merges_branch_into_main_before_push(self, tmp_path: Path) -> None:
        """cmd_land must ff-merge the branch into main before pushing.

        Previously, callers had to merge externally. This caused #196/#197:
        main pushed without the branch commits, leaving work unlanded.
        """
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-197-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("new feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: add feature")

        # Do NOT merge into main — cmd_land should do this itself
        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0, f"land failed: {result.stdout}\n{result.stderr}"
        assert "LANDED=yes" in result.stdout

        # Main must include the branch commit
        main_log = _git(project, "log", "--oneline", "main")
        assert "feat: add feature" in main_log

        # Remote must also have it
        remote_log = subprocess.run(
            ["git", "--git-dir", str(remote), "log", "--oneline", "main"],
            capture_output=True, text=True,
        ).stdout
        assert "feat: add feature" in remote_log


class TestLandMainSync:
    def test_land_rescues_local_only_commits(self, tmp_path: Path) -> None:
        """If main has local-only commits not on blessed, rescue them
        to a branch and reset main before merging the feature branch."""
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-197-rescue"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        # Simulate a local-only commit on main (user committed directly)
        (project / "quickfix.txt").write_text("quick fix\n")
        _git(project, "add", "quickfix.txt")
        _git(project, "commit", "-m", "fix: quick fix on main")

        # Create feature branch from the pre-quickfix state
        _git(project, "checkout", "-b", branch, "origin/main")
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: feature work")

        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0, f"land failed: {result.stdout}\n{result.stderr}"
        assert "LOCAL_COMMITS=1" in result.stdout
        assert "RESCUED_TO=rescue-" in result.stdout
        assert "LANDED=yes" in result.stdout

        # Feature should be on main
        main_log = _git(project, "log", "--oneline", "main")
        assert "feat: feature work" in main_log

        # Quick fix should NOT be on main (it was rescued)
        assert "fix: quick fix" not in main_log

        # Rescue branch should exist with the quick fix
        import re
        match = re.search(r"RESCUED_TO=(\S+)", result.stdout)
        rescue_name = match.group(1) if match else f"rescue-{Path(project).name}"
        rescue_log = _git(project, "log", "--oneline", rescue_name)
        assert "fix: quick fix" in rescue_log

    def test_land_no_rescue_when_clean(self, tmp_path: Path) -> None:
        """No rescue when main matches blessed."""
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-197-clean"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: clean land")

        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0
        assert "LOCAL_COMMITS" not in result.stdout
        assert "RESCUED_TO" not in result.stdout
        assert "LANDED=yes" in result.stdout


class TestLandRetry:
    def test_land_retries_on_concurrent_push(self, tmp_path: Path) -> None:
        """If push fails (concurrent push), fetch+rebase and retry."""
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-197-retry"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: our work")

        _git(project, "checkout", "main")

        # Simulate concurrent push: clone, commit, push directly to remote
        other = tmp_path / "other"
        subprocess.run(["git", "clone", str(remote), str(other)],
                       capture_output=True, check=True)
        _git(other, "config", "user.email", "other@test.com")
        _git(other, "config", "user.name", "Other")
        (other / "other.txt").write_text("concurrent work\n")
        _git(other, "add", "other.txt")
        _git(other, "commit", "-m", "feat: concurrent work")
        _git(other, "push", "origin", "main")

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0, f"land failed: {result.stdout}\n{result.stderr}"
        assert "LANDED=yes" in result.stdout

        # Both commits should be on remote main
        remote_log = subprocess.run(
            ["git", "--git-dir", str(remote), "log", "--oneline", "main"],
            capture_output=True, text=True,
        ).stdout
        assert "feat: our work" in remote_log
        assert "feat: concurrent work" in remote_log


class TestLandPushTopology:
    def test_land_pushes_to_blessed_in_fork_model(self, tmp_path: Path) -> None:
        """In fork model (origin=fork, upstream=blessed), push to upstream."""
        blessed = _init_bare(tmp_path / "blessed.git")
        fork = _init_bare(tmp_path / "fork.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-197-topo"

        _git(project, "remote", "add", "origin", str(fork))
        _git(project, "remote", "add", "upstream", str(blessed))
        _git(project, "push", "origin", "main")
        _git(project, "push", "upstream", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: topology test")

        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0, f"land failed: {result.stdout}\n{result.stderr}"

        # Blessed must have the commit
        blessed_log = subprocess.run(
            ["git", "--git-dir", str(blessed), "log", "--oneline", "main"],
            capture_output=True, text=True,
        ).stdout
        assert "feat: topology test" in blessed_log

        # Fork should be mirrored
        assert "MIRRORED_TO=origin/main" in result.stdout

    def test_land_pushes_to_origin_in_direct_model(self, tmp_path: Path) -> None:
        """In direct model (origin only, no upstream), push to origin."""
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-197-direct"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: direct test")

        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0, f"land failed: {result.stdout}\n{result.stderr}"
        assert "MIRRORED_TO" not in result.stdout


class TestLandRollbackOnPushFailure:
    def test_merge_rolled_back_when_push_fails(self, tmp_path: Path) -> None:
        """If push fails after merge, local main must be rolled back
        to prevent orphaned merge commits that get rescued and lost."""
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-rollback-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: will fail to push")

        _git(project, "checkout", "main")
        pre_merge_sha = _git(project, "rev-parse", "HEAD")

        # Remove remote so push will fail
        _git(project, "remote", "remove", "origin")

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 1

        # Main should be rolled back to pre-merge state
        current_sha = _git(project, "rev-parse", "HEAD")
        assert current_sha == pre_merge_sha, (
            f"Main not rolled back: expected {pre_merge_sha[:12]}, got {current_sha[:12]}"
        )
        main_log = _git(project, "log", "--oneline", "main")
        assert "feat: will fail to push" not in main_log


class TestLandLedger:
    def test_land_writes_ledger_entry(self, tmp_path: Path) -> None:
        """Successful land should append to .land-ledger.jsonl."""
        import json

        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-ledger-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: ledger test")

        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0

        ledger = workspace / ".land-ledger.jsonl"
        assert ledger.exists(), "Land ledger should be created"

        entries = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
        land_entries = [e for e in entries if e.get("event") == "land"]
        assert len(land_entries) >= 1

        entry = land_entries[-1]
        assert entry["branch"] == branch
        assert entry["repo"] == project.name
        assert entry["push_target"] == "origin"
        assert entry["stamped"] is True
        assert "landed_sha" in entry
        assert "timestamp" in entry

    def test_land_does_not_write_ledger_on_failure(self, tmp_path: Path) -> None:
        """Failed land should NOT write to the ledger."""
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-no-ledger"

        _git(project, "checkout", "-b", branch)
        _git(project, "commit", "--allow-empty", "-m", "feat: no remote")
        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 1

        ledger = workspace / ".land-ledger.jsonl"
        assert not ledger.exists(), "Ledger should not exist after failed land"


class TestLandPostPushVerify:
    def test_land_verifies_sha_on_remote(self, tmp_path: Path) -> None:
        """After push, verify the landed SHA exists on the remote."""
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-verify-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: verify test")

        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0
        assert "LANDED=yes" in result.stdout


class TestBadArgs:
    def test_missing_subcommand(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_unknown_subcommand(self) -> None:
        result = _run_execute("unknown")
        assert result.returncode == 1
        assert "ERROR" in result.stdout


class TestWriteMarker:
    def test_writes_marker_with_correct_fields(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        result = _run_execute(
            "write-marker",
            f"slot_path={slot_dir}",
            "branch=issue-42-fix",
        )
        assert result.returncode == 0, f"write-marker failed: {result.stdout}\n{result.stderr}"
        marker = slot_dir / ".phase-a-complete"
        assert marker.exists()
        content = marker.read_text()
        assert "branch=issue-42-fix" in content
        assert "timestamp=" in content

    def test_marker_format_matches_merge_slot(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        _run_execute(
            "write-marker",
            f"slot_path={slot_dir}",
            "branch=issue-42-fix",
        )
        content = (slot_dir / ".phase-a-complete").read_text()
        branch_lines = [l for l in content.splitlines() if l.startswith("branch=")]
        assert len(branch_lines) == 1
        assert branch_lines[0] == "branch=issue-42-fix"

    def test_missing_slot_path(self) -> None:
        result = _run_execute("write-marker", "branch=test")
        assert result.returncode == 1
        assert "MISSING_ARGS" in result.stdout

    def test_missing_branch(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        result = _run_execute("write-marker", f"slot_path={slot_dir}")
        assert result.returncode == 1
        assert "MISSING_ARGS" in result.stdout

    def test_slot_path_not_exists(self, tmp_path: Path) -> None:
        result = _run_execute(
            "write-marker",
            f"slot_path={tmp_path / 'nonexistent'}",
            "branch=test",
        )
        assert result.returncode == 1
        assert "BAD_PATH" in result.stdout


class TestSafetyStash:
    def test_stash_created_when_dirty(self, tmp_path: Path) -> None:
        """safety_stash should stash uncommitted changes including untracked files."""
        project = _init_repo(tmp_path / "project")
        (project / "dirty.txt").write_text("uncommitted work\n")
        (project / "README.md").write_text("modified\n")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=main",
            "base_branch=main",
        )
        assert "SAFETY_STASH=" in result.stdout

        stash_list = _git(project, "stash", "list")
        assert "work-end safety stash" in stash_list

    def test_no_stash_when_clean(self, tmp_path: Path) -> None:
        """safety_stash should be a no-op when the tree is clean."""
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", "issue-clean")
        _git(project, "commit", "--allow-empty", "-m", "clean commit")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-clean",
            "base_branch=main",
        )
        assert "SAFETY_STASH=" not in result.stdout
        stash_list = _git(project, "stash", "list")
        assert stash_list == ""

    def test_land_does_not_stash(self, tmp_path: Path) -> None:
        """cmd_land should NOT stash — dirty files at land time are lifecycle
        artifacts, not cross-session work. Stashing them causes pop conflicts."""
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-stash-land"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: land stash test")
        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert "SAFETY_STASH=" not in result.stdout

    def test_stash_preserves_untracked_files(self, tmp_path: Path) -> None:
        """Untracked files must be included in the stash (the -u flag)."""
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", "issue-untracked")
        _git(project, "commit", "--allow-empty", "-m", "branch start")

        untracked = project / "new-untracked.txt"
        untracked.write_text("untracked\n")
        assert untracked.exists()

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-untracked",
            "base_branch=main",
        )
        assert "SAFETY_STASH=" in result.stdout
        assert not untracked.exists(), "Untracked file should be stashed (removed from tree)"

        _git(project, "stash", "pop")
        assert untracked.exists(), "Untracked file should be restored after stash pop"


class TestArchiveSlot:
    def _make_slot(self, tmp_path: Path, slot_num: int = 42) -> Path:
        """Create a minimal landed slot structure."""
        family = tmp_path / "family"
        family.mkdir()
        slot_dir = family / "slots" / str(slot_num)
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            f"slot: {slot_num}\nbranch: issue-{slot_num}-test\n"
        )
        (slot_dir / ".landed").write_text("landed=yes\n")
        repo = slot_dir / "myrepo"
        repo.mkdir()
        (repo / "file.txt").write_text("content\n")
        return family

    def test_archive_slot_moves_to_attic(self, tmp_path: Path) -> None:
        family = self._make_slot(tmp_path)
        result = _run_execute(
            "archive-slot",
            f"slot_path={family / 'slots' / '42'}",
            f"family_root={family}",
            "slot_num=42",
            "force=yes",
        )
        assert result.returncode == 0, f"archive failed: {result.stdout}\n{result.stderr}"
        assert "ARCHIVED=yes" in result.stdout
        assert (family / "slots" / "attic" / "42").exists()
        assert not (family / "slots" / "42").exists()

    def test_archive_slot_missing_args(self) -> None:
        result = _run_execute("archive-slot", "slot_num=42")
        assert result.returncode == 1
        assert "MISSING_ARGS" in result.stdout

    def test_archive_unlanded_slot_fails(self, tmp_path: Path) -> None:
        family = self._make_slot(tmp_path)
        (family / "slots" / "42" / ".landed").unlink()
        result = _run_execute(
            "archive-slot",
            f"slot_path={family / 'slots' / '42'}",
            f"family_root={family}",
            "slot_num=42",
        )
        assert result.returncode == 1
        assert "ARCHIVE_FAILED" in result.stdout or "not_landed" in result.stdout


class TestCloseIssues:
    def test_missing_repo(self) -> None:
        result = _run_execute("close-issues", "covers=42")
        assert result.returncode == 1
        assert "MISSING_ARGS" in result.stdout

    def test_missing_covers(self) -> None:
        result = _run_execute("close-issues", "repo=owner/repo")
        assert result.returncode == 1
        assert "MISSING_ARGS" in result.stdout

    def test_delegates_to_artifact_promote(self, tmp_path: Path, monkeypatch) -> None:
        work_end_dir = Path(__file__).parent.parent / "work-end"
        sys.path.insert(0, str(work_end_dir))
        import work_end_execute

        calls = []
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if isinstance(cmd, list) and any("artifact_promote.py" in str(c) for c in cmd):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "CLOSED=2\n", "")
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_run)
        rc = work_end_execute.cmd_close_issues({"repo": "owner/repo", "covers": "42,43"})
        assert rc == 0
        assert len(calls) == 1
        assert "close-issues" in calls[0]
        assert "owner/repo" in calls[0]
        assert "covers=42,43" in calls[0]


# --- Crash-safety tests for write_progress ---

class TestWriteProgressAtomic:
    """write_progress must use atomic write-then-rename."""

    def _import_module(self):
        work_end_dir = str(Path(__file__).parent.parent / "work-end")
        if work_end_dir not in sys.path:
            sys.path.insert(0, work_end_dir)
        import work_end_execute
        return work_end_execute

    def test_write_and_read_roundtrip(self, tmp_path):
        mod = self._import_module()
        progress = tmp_path / ".execute-progress"
        mod.write_progress(progress, "step1", "done")
        mod.write_progress(progress, "step2", "pending")
        result = mod.read_progress(progress)
        assert result["step1"] == "done"
        assert result["step2"] == "pending"

    def test_no_tmp_file_left(self, tmp_path):
        mod = self._import_module()
        progress = tmp_path / ".execute-progress"
        mod.write_progress(progress, "step1", "done")
        assert not (tmp_path / ".execute-progress.tmp").exists()

    def test_survives_crash_between_truncate_and_write(self, tmp_path):
        mod = self._import_module()
        progress = tmp_path / ".execute-progress"
        mod.write_progress(progress, "step1", "done")

        with patch("os.replace", side_effect=OSError("simulated crash")):
            try:
                mod.write_progress(progress, "step2", "done")
            except OSError:
                pass

        result = mod.read_progress(progress)
        assert result.get("step1") == "done", "Prior progress must survive a crash"
        assert "step2" not in result, "Crashed write must not appear"


class TestLandWorkspaceStampOnly:
    """Workspace branch is stamp-only — no merge. Artifacts promoted separately."""

    def _setup_repos(self, tmp_path: Path, branch: str = "issue-345-test"):
        proj_remote = _init_bare(tmp_path / "proj-remote.git")
        ws_remote = _init_bare(tmp_path / "ws-remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")

        _git(project, "remote", "add", "origin", str(proj_remote))
        _git(project, "push", "origin", "main")
        _git(workspace, "remote", "add", "origin", str(ws_remote))
        _git(workspace, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.py").write_text("# feature\n")
        _git(project, "add", "feature.py")
        _git(project, "commit", "-m", "feat: project feature")

        _git(workspace, "checkout", "-b", branch)
        (workspace / "spec.md").write_text("# spec\n")
        _git(workspace, "add", "spec.md")
        _git(workspace, "commit", "-m", "docs: workspace spec")

        return project, workspace, branch

    def test_workspace_branch_stamped(self, tmp_path: Path):
        """After land, workspace branch must have a stamp commit."""
        project, workspace, branch = self._setup_repos(tmp_path)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0, f"land failed: {result.stdout}\n{result.stderr}"

        stamp = _git(workspace, "log", "-1", "--format=%s", branch)
        assert "branch closed" in stamp, f"Workspace branch not stamped, tip: {stamp}"

    def test_workspace_main_not_modified(self, tmp_path: Path):
        """After land, workspace main must NOT have branch content — no merge."""
        project, workspace, branch = self._setup_repos(tmp_path)

        main_sha_before = _git(workspace, "rev-parse", "main")

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0

        main_sha_after = _git(workspace, "rev-parse", "main")
        assert main_sha_before == main_sha_after, "Workspace main should not change — no merge"

    def test_reports_workspace_status(self, tmp_path: Path):
        """Land output must report WORKSPACE_LANDED."""
        project, workspace, branch = self._setup_repos(tmp_path)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0
        assert "WORKSPACE_LANDED=yes" in result.stdout
