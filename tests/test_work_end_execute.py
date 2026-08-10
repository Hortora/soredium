"""Tests for work-end/work_end_execute.py"""

import subprocess
import sys
from pathlib import Path

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

        progress_path = design / ".execute-progress"
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
        (design / ".execute-progress").write_text("default=promoted\n")
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

        _git(project, "checkout", "issue-102-test")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-102-test",
            "base_branch=main",
        )
        assert "ERROR=REBASE_CONFLICT" in result.stdout


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
        assert "MAIN_RESET=yes" in result.stdout
        assert "LANDED=yes" in result.stdout

        # Feature should be on main
        main_log = _git(project, "log", "--oneline", "main")
        assert "feat: feature work" in main_log

        # Quick fix should NOT be on main (it was rescued)
        assert "fix: quick fix" not in main_log

        # Rescue branch should exist with the quick fix
        rescue_log = _git(project, "log", "--oneline", f"rescue-{branch}")
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
        assert "PUSH_RETRY=1" in result.stdout
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
        assert "PUSHED_TO=upstream/main" in result.stdout

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
        assert "PUSHED_TO=origin/main" in result.stdout
        assert "MIRRORED_TO" not in result.stdout


class TestLandWorkspacePush:
    def test_land_pushes_workspace_branch_stamp(self, tmp_path: Path) -> None:
        """Workspace branch stamp must be pushed to origin."""
        remote = _init_bare(tmp_path / "remote.git")
        ws_remote = _init_bare(tmp_path / "ws-remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-204-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")
        _git(workspace, "remote", "add", "origin", str(ws_remote))
        _git(workspace, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: work")
        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")
        _git(workspace, "push", "origin", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0

        ws_remote_tip = subprocess.run(
            ["git", "--git-dir", str(ws_remote), "log", "-1", "--format=%s", branch],
            capture_output=True, text=True,
        ).stdout.strip()
        assert ws_remote_tip.startswith("chore: branch closed"), \
            f"workspace stamp not pushed to remote: {ws_remote_tip}"


class TestLandSlotMode:
    """Tests for slot-aware cmd_land — two-hop push (slot → original → GitHub)."""

    @staticmethod
    def _create_slot_layout(tmp_path: Path, branch: str = "issue-50-feature",
                            repo_names: list[str] | None = None) -> dict:
        """Create a slot layout with original repos, bare remotes, and clone-based slot.

        Layout:
          tmp_path/
            family/
              engine/             <- original project repo
              iot/                <- second original project repo (optional)
              slots/
                3/
                  engine/         <- git clone of family/engine
                  iot/            <- git clone of family/iot
                  work/           <- git clone of workspace
            workspace/            <- original workspace repo
            engine-remote.git/    <- bare remote (simulates GitHub) for engine
            iot-remote.git/       <- bare remote for iot
            ws-remote.git/        <- bare remote for workspace
        """
        if repo_names is None:
            repo_names = ["engine"]

        family = tmp_path / "family"
        family.mkdir()
        remotes: dict[str, Path] = {}
        originals: dict[str, Path] = {}

        for name in repo_names:
            remote = _init_bare(tmp_path / f"{name}-remote.git")
            remotes[name] = remote
            orig = _init_repo(family / name)
            _git(orig, "remote", "add", "origin", str(remote))
            _git(orig, "push", "origin", "main")
            originals[name] = orig

        ws_remote = _init_bare(tmp_path / "ws-remote.git")
        orig_workspace = _init_repo(tmp_path / "workspace")
        _git(orig_workspace, "remote", "add", "origin", str(ws_remote))
        _git(orig_workspace, "push", "origin", "main")

        slot_dir = family / "slots" / "3"
        slot_dir.mkdir(parents=True)

        slot_repos: dict[str, Path] = {}
        for name in repo_names:
            slot_repo = slot_dir / name
            subprocess.run(
                ["git", "clone", str(originals[name]), str(slot_repo)],
                capture_output=True, check=True,
            )
            _git(slot_repo, "config", "user.email", "test@test.com")
            _git(slot_repo, "config", "user.name", "Test")
            _git(slot_repo, "checkout", "-b", branch)
            (slot_repo / "feature.txt").write_text(f"work in {name}\n")
            _git(slot_repo, "add", "feature.txt")
            _git(slot_repo, "commit", "-m", f"feat: work in {name}")
            slot_repos[name] = slot_repo

        slot_ws = slot_dir / "work"
        subprocess.run(
            ["git", "clone", str(orig_workspace), str(slot_ws)],
            capture_output=True, check=True,
        )
        _git(slot_ws, "config", "user.email", "test@test.com")
        _git(slot_ws, "config", "user.name", "Test")
        _git(slot_ws, "checkout", "-b", branch)
        design = slot_ws / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(slot_ws, "add", ".")
        _git(slot_ws, "commit", "-m", "scaffold")

        return {
            "family": family,
            "originals": originals,
            "remotes": remotes,
            "orig_workspace": orig_workspace,
            "ws_remote": ws_remote,
            "slot_dir": slot_dir,
            "slot_repos": slot_repos,
            "slot_ws": slot_ws,
            "branch": branch,
        }

    def test_slot_land_single_repo_pushes_to_github(self, tmp_path: Path) -> None:
        """In slot mode, content must reach the bare remote (GitHub) via two-hop."""
        s = self._create_slot_layout(tmp_path)
        result = _run_execute(
            "land",
            f"project={s['slot_repos']['engine']}",
            f"branch={s['branch']}",
            "base_branch=main",
            f"workspace={s['slot_ws']}",
        )
        assert result.returncode == 0, f"land failed: {result.stdout}\n{result.stderr}"
        assert "LANDED=yes" in result.stdout

        remote_log = subprocess.run(
            ["git", "--git-dir", str(s['remotes']['engine']), "log", "--oneline", "main"],
            capture_output=True, text=True,
        ).stdout
        assert "feat: work in engine" in remote_log

    def test_slot_land_multi_repo_pushes_all(self, tmp_path: Path) -> None:
        """Multi-repo slot: all repos pushed to their respective GitHub remotes."""
        s = self._create_slot_layout(tmp_path, repo_names=["engine", "iot"])
        result = _run_execute(
            "land",
            f"project={s['slot_repos']['engine']}",
            f"branch={s['branch']}",
            "base_branch=main",
            f"workspace={s['slot_ws']}",
        )
        assert result.returncode == 0, f"land failed: {result.stdout}\n{result.stderr}"
        assert "LANDED=yes" in result.stdout

        for name in ("engine", "iot"):
            remote_log = subprocess.run(
                ["git", "--git-dir", str(s['remotes'][name]), "log", "--oneline", "main"],
                capture_output=True, text=True,
            ).stdout
            assert f"feat: work in {name}" in remote_log, f"{name} not on remote"

    def test_slot_land_stamps_all_project_branches(self, tmp_path: Path) -> None:
        """All project branches in the slot must be stamped."""
        s = self._create_slot_layout(tmp_path, repo_names=["engine", "iot"])
        _run_execute(
            "land",
            f"project={s['slot_repos']['engine']}",
            f"branch={s['branch']}",
            "base_branch=main",
            f"workspace={s['slot_ws']}",
        )
        for name in ("engine", "iot"):
            tip = _git(s['slot_repos'][name], "log", "-1", "--format=%s", s['branch'])
            assert tip.startswith("chore: branch closed"), f"{name} not stamped: {tip}"
            assert "landed as" in tip, f"{name} stamp missing SHA"

    def test_slot_land_stamps_workspace_with_sha(self, tmp_path: Path) -> None:
        """Workspace branch must be stamped with a landing SHA."""
        s = self._create_slot_layout(tmp_path)
        _run_execute(
            "land",
            f"project={s['slot_repos']['engine']}",
            f"branch={s['branch']}",
            "base_branch=main",
            f"workspace={s['slot_ws']}",
        )
        ws_tip = _git(s['slot_ws'], "log", "-1", "--format=%s", s['branch'])
        assert ws_tip.startswith("chore: branch closed"), f"workspace not stamped: {ws_tip}"
        assert "landed as" in ws_tip, "workspace stamp missing SHA"

    def test_slot_land_writes_landed_marker(self, tmp_path: Path) -> None:
        """Slot mode must write .landed marker with SHAs."""
        s = self._create_slot_layout(tmp_path, repo_names=["engine", "iot"])
        _run_execute(
            "land",
            f"project={s['slot_repos']['engine']}",
            f"branch={s['branch']}",
            "base_branch=main",
            f"workspace={s['slot_ws']}",
        )
        landed = s['slot_dir'] / ".landed"
        assert landed.exists(), ".landed marker not written"
        content = landed.read_text()
        assert "engine:" in content
        assert "iot:" in content
        assert f"branch={s['branch']}" in content

    def test_slot_land_originals_remain_on_main(self, tmp_path: Path) -> None:
        """After landing, original repos must still be on main."""
        s = self._create_slot_layout(tmp_path, repo_names=["engine", "iot"])
        _run_execute(
            "land",
            f"project={s['slot_repos']['engine']}",
            f"branch={s['branch']}",
            "base_branch=main",
            f"workspace={s['slot_ws']}",
        )
        for name in ("engine", "iot"):
            branch = _git(s['originals'][name], "branch", "--show-current")
            assert branch == "main", f"{name} not on main: {branch}"


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
