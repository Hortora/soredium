"""Tests for work-start/branch_create.py"""

import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-start"))


BRANCH_CREATE = Path(__file__).parent.parent / "work-start" / "branch_create.py"


@pytest.fixture
def project_repo(tmp_path):
    """Create a project git repo with initial commit."""
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# Project\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


@pytest.fixture
def workspace_repo(tmp_path):
    """Create a workspace git repo with initial commit."""
    repo = tmp_path / "workspace"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# Workspace\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


# ---------------------------------------------------------------------------
# create-branches subcommand
# ---------------------------------------------------------------------------

def test_create_branches_happy_path(project_repo, workspace_repo):
    """create-branches creates matching branches in both repos."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=issue-42-feature"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "CREATED=yes" in result.stdout

    # Verify project is on the new branch
    proj_branch = subprocess.run(
        ["git", "-C", str(project_repo), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert proj_branch == "issue-42-feature"

    # Verify workspace is on the new branch
    ws_branch = subprocess.run(
        ["git", "-C", str(workspace_repo), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert ws_branch == "issue-42-feature"


def test_create_branches_with_base(project_repo, workspace_repo):
    """create-branches from a specified base branch."""
    # Create a base branch with a commit
    subprocess.run(["git", "-C", str(project_repo), "checkout", "-b", "base-branch"],
                    check=True, capture_output=True)
    (project_repo / "base.txt").write_text("base work")
    subprocess.run(["git", "-C", str(project_repo), "add", "base.txt"],
                    check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project_repo), "commit", "-m", "base work"],
                    check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=issue-10-stacked", "base=base-branch"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "CREATED=yes" in result.stdout

    # base.txt should be present (branched from base-branch)
    assert (project_repo / "base.txt").exists()


def test_create_branches_rollback_on_workspace_failure(project_repo, tmp_path):
    """If workspace branch fails, project branch is rolled back."""
    # Use a non-git dir as workspace to force failure
    bad_ws = tmp_path / "not-a-repo"
    bad_ws.mkdir()

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(bad_ws),
         "branch=issue-99-fail"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=workspace_branch_failed" in result.stdout

    # Project should NOT have the branch
    branches = subprocess.run(
        ["git", "-C", str(project_repo), "branch"],
        capture_output=True, text=True,
    ).stdout
    assert "issue-99-fail" not in branches


def test_create_branches_duplicate_name(project_repo, workspace_repo):
    """create-branches fails if branch already exists in project."""
    # Create branch first
    subprocess.run(["git", "-C", str(project_repo), "checkout", "-b", "issue-1-dup"],
                    check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project_repo), "checkout", "main"],
                    check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=issue-1-dup"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=project_branch_failed" in result.stdout


def test_create_branches_refuses_base_branch_name(project_repo, workspace_repo):
    """#600: create-branches with branch=main refuses before running git."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=main"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=project_branch_failed" in result.stdout
    assert "refused" in result.stdout


def test_create_branches_resumes_known_branches(project_repo, workspace_repo):
    """#600: create-branches resumes when both repos have known branches."""
    # First create branches normally
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=issue-42-feature"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "CREATED=yes" in result.stdout

    # Switch both back to main
    subprocess.run(["git", "-C", str(project_repo), "checkout", "main"],
                    check=True, capture_output=True)
    subprocess.run(["git", "-C", str(workspace_repo), "checkout", "main"],
                    check=True, capture_output=True)

    # Try again — should resume, not fail
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=issue-42-feature"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "RESUMED=yes" in result.stdout

    # Verify both repos are on the branch
    proj_branch = subprocess.run(
        ["git", "-C", str(project_repo), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert proj_branch == "issue-42-feature"
    ws_branch = subprocess.run(
        ["git", "-C", str(workspace_repo), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert ws_branch == "issue-42-feature"


def test_create_branches_resumes_project_creates_workspace(project_repo, workspace_repo):
    """#600: branch exists in project only — resume project, create workspace."""
    # Create branch in project only (simulates partial failure)
    subprocess.run(["git", "-C", str(project_repo), "checkout", "-b", "issue-50-partial"],
                    check=True, capture_output=True)
    # Record a base ref so it's recognised as a known branch
    main_sha = subprocess.run(
        ["git", "-C", str(project_repo), "rev-parse", "main"],
        capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(project_repo), "update-ref",
                    "refs/soredium/base/issue-50-partial", main_sha],
                    check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project_repo), "checkout", "main"],
                    check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=issue-50-partial"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    # Project resumed, workspace created — both succeed
    proj_branch = subprocess.run(
        ["git", "-C", str(project_repo), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert proj_branch == "issue-50-partial"
    ws_branch = subprocess.run(
        ["git", "-C", str(workspace_repo), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert ws_branch == "issue-50-partial"


def test_create_branches_no_rollback_on_resumed_project(project_repo, workspace_repo):
    """#600: if project was resumed but workspace fails, don't delete the project branch."""
    # Create known branch in project
    subprocess.run(["git", "-C", str(project_repo), "checkout", "-b", "issue-60-keep"],
                    check=True, capture_output=True)
    main_sha = subprocess.run(
        ["git", "-C", str(project_repo), "rev-parse", "main"],
        capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(project_repo), "update-ref",
                    "refs/soredium/base/issue-60-keep", main_sha],
                    check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project_repo), "checkout", "main"],
                    check=True, capture_output=True)

    # Create a conflicting unknown branch in workspace (no base record)
    subprocess.run(["git", "-C", str(workspace_repo), "checkout", "-b", "issue-60-keep"],
                    check=True, capture_output=True)
    subprocess.run(["git", "-C", str(workspace_repo), "checkout", "main"],
                    check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=issue-60-keep"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1

    # Project branch must still exist (it was pre-existing, not created by us)
    branches = subprocess.run(
        ["git", "-C", str(project_repo), "branch"],
        capture_output=True, text=True,
    ).stdout
    assert "issue-60-keep" in branches


def test_create_branches_missing_branch_arg(project_repo, workspace_repo):
    """create-branches without branch= fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_branch" in result.stdout


# ---------------------------------------------------------------------------
# commit-scaffold subcommand
# ---------------------------------------------------------------------------

def test_commit_scaffold_happy_path(workspace_repo):
    """commit-scaffold commits design files."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-5-scaffold"],
                    check=True, capture_output=True)

    # Create scaffold files at workspace root
    (ws / ".plan").write_text("# Work Plan — issue-5\n\n## State\nbranch: issue-5-scaffold\nstate: scaffolded\n\n## Queue\n(empty)\n")
    (ws / "JOURNAL.md").write_text("# Design Journal\n")

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "commit-scaffold", str(ws),
         "branch=issue-5-scaffold"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout
    assert "BACKED_UP=refs/backup/" in result.stdout
    assert "PUSHED" not in result.stdout

    # Verify commit message
    log = subprocess.run(
        ["git", "-C", str(ws), "log", "-1", "--format=%s"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert "init(issue-5-scaffold): scaffold workspace branch" in log


def test_commit_scaffold_missing_branch_arg(workspace_repo):
    """commit-scaffold without branch= fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "commit-scaffold", str(workspace_repo)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_branch" in result.stdout


def test_commit_scaffold_includes_plan_file(workspace_repo):
    """commit-scaffold includes .plan (unified format)."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-99-epic"],
                    check=True, capture_output=True)

    (ws / ".plan").write_text("# Work Plan — issue-99\n\n## State\nbranch: issue-99-epic\nstate: scaffolded\n\n## Queue\n- [ ] #99 — Epic ← active\n")
    (ws / "JOURNAL.md").write_text("# Design Journal\n")

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "commit-scaffold", str(ws),
         "branch=issue-99-epic"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout

    show = subprocess.run(
        ["git", "-C", str(ws), "show", "--name-only", "--format="],
        capture_output=True, text=True,
    ).stdout.strip()
    assert ".plan" in show


def test_commit_scaffold_no_scaffold_files(workspace_repo):
    """commit-scaffold returns success with no_changes when scaffold files
    don't exist — nothing to commit is a no-op, not an error (#471)."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-6-nodir"],
                    check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "commit-scaffold", str(ws),
         "branch=issue-6-nodir"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=no_changes" in result.stdout


# ---------------------------------------------------------------------------
# General tests
# ---------------------------------------------------------------------------

def test_unknown_subcommand():
    """Unknown subcommand fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "unknown"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=unknown_subcommand" in result.stdout


def test_missing_subcommand():
    """No subcommand fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_subcommand" in result.stdout


def test_create_branches_missing_args():
    """create-branches without project/workspace args fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_args" in result.stdout


def test_commit_scaffold_missing_workspace():
    """commit-scaffold without workspace arg fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "commit-scaffold"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_args" in result.stdout


# ---------------------------------------------------------------------------
# sync-main subcommand
# ---------------------------------------------------------------------------

def _init_repo_with_bare(tmp_path, name, remote_name="origin"):
    """Create a repo cloned from a bare, simulating a remote."""
    bare = tmp_path / f".{name}-bare.git"
    bare.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    repo = tmp_path / name
    subprocess.run(["git", "clone", str(bare), str(repo)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"], capture_output=True)
    (repo / "README.md").write_text(f"# {name}\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"], capture_output=True)
    return repo, bare


def _sync(project, workspace):
    return subprocess.run(
        ["python3", str(BRANCH_CREATE), "sync-main", str(project), str(workspace), "base=main"],
        capture_output=True, text=True,
    )


def _sha(repo, ref="main"):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", ref],
                          capture_output=True, text=True).stdout.strip()


def _someone_else_pushes(tmp_path, bare, filename="theirs.txt"):
    other = tmp_path / f"other-{filename}"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(other), "config", "user.name", "Other"], capture_output=True)
    subprocess.run(["git", "-C", str(other), "config", "user.email", "o@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(other), "checkout", "-q", "main"], capture_output=True)
    (other / filename).write_text("theirs\n")
    subprocess.run(["git", "-C", str(other), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(other), "commit", "-q", "-m", "feat: theirs"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(other), "push", "-q", "origin", "main"],
                   capture_output=True, check=True)
    return _sha(other)


def _local_commit(repo, filename="mine.txt"):
    (repo / filename).write_text("mine\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "feat: landed, not published"],
                   capture_output=True, check=True)
    return _sha(repo)


def test_sync_main_single_remote(tmp_path):
    project, bare = _init_repo_with_bare(tmp_path, "project")
    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")

    result = _sync(project, workspace)

    assert result.returncode == 0
    assert "SYNCED=yes" in result.stdout
    assert "MODEL=single" in result.stdout
    assert "STRATEGY=current repo=project" in result.stdout


def test_sync_main_fast_forwards_to_the_remote(tmp_path):
    project, bare = _init_repo_with_bare(tmp_path, "project")
    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")
    theirs = _someone_else_pushes(tmp_path, bare)

    result = _sync(project, workspace)

    assert "STRATEGY=fast-forward repo=project" in result.stdout
    assert _sha(project) == theirs
    assert (project / "theirs.txt").exists()


def test_sync_main_leaves_unpublished_commits_exactly_as_they_are(tmp_path):
    """Commits on main the remote lacks are landed work awaiting publish. They used to be
    rebased, and the fork force-pushed."""
    project, bare = _init_repo_with_bare(tmp_path, "project")
    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")
    mine = _local_commit(project)
    remote_before = _sha(bare)

    result = _sync(project, workspace)

    assert "STRATEGY=ahead repo=project" in result.stdout
    assert "UNPUBLISHED=1 repo=project" in result.stdout
    assert _sha(project) == mine
    assert _sha(bare) == remote_before
    assert "SYNCED=yes" in result.stdout


def test_sync_main_never_rewrites_or_merges_when_the_remote_also_moved(tmp_path):
    project, bare = _init_repo_with_bare(tmp_path, "project")
    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")
    mine = _local_commit(project)
    theirs = _someone_else_pushes(tmp_path, bare)

    result = _sync(project, workspace)

    assert result.returncode == 0
    assert "STRATEGY=diverged repo=project" in result.stdout
    assert "NOTE=diverged repo=project" in result.stdout
    assert _sha(project) == mine                       # not rebased, not merged
    assert _sha(bare) == theirs                        # nothing pushed
    merges = subprocess.run(["git", "-C", str(project), "rev-list", "--merges", "--count", "main"],
                            capture_output=True, text=True).stdout.strip()
    assert merges == "0"
    assert "SYNCED=yes" in result.stdout               # work can start from canonical


def test_sync_main_with_upstream_and_fork_pushes_to_neither(tmp_path):
    project, blessed_bare = _init_repo_with_bare(tmp_path, "project")
    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")
    fork_bare = tmp_path / ".fork-bare.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(blessed_bare), str(fork_bare)],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(project), "remote", "rename", "origin", "upstream"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(project), "remote", "add", "origin", str(fork_bare)],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(project), "fetch", "-q", "--all"], capture_output=True)
    theirs = _someone_else_pushes(tmp_path, blessed_bare)
    fork_before = _sha(fork_bare)

    result = _sync(project, workspace)

    assert "MODEL=upstream" in result.stdout
    assert _sha(project) == theirs
    assert _sha(fork_bare) == fork_before               # the fork only moves when publishing


def test_sync_main_with_fork_remote_reports_the_model(tmp_path):
    project, bare = _init_repo_with_bare(tmp_path, "project")
    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")
    fork_bare = tmp_path / ".fork-bare.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(bare), str(fork_bare)],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(project), "remote", "add", "fork", str(fork_bare)],
                   capture_output=True, check=True)

    result = _sync(project, workspace)

    assert "MODEL=fork" in result.stdout
    assert "SYNCED=yes" in result.stdout


def test_sync_main_missing_args():
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "sync-main"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_args" in result.stdout


def test_sync_main_network_failure_non_fatal(tmp_path):
    project, bare = _init_repo_with_bare(tmp_path, "project")
    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")
    subprocess.run(["git", "-C", str(project), "remote", "set-url", "origin",
                    str(tmp_path / "gone.git")], capture_output=True, check=True)
    before = _sha(project)

    result = _sync(project, workspace)

    assert result.returncode == 0
    assert "SYNCED=partial" in result.stdout
    assert "WARN=fetch_project_failed" in result.stdout
    assert "STRATEGY=offline repo=project" in result.stdout
    assert _sha(project) == before


def test_sync_main_repo_without_a_remote(tmp_path):
    project = tmp_path / "project"
    workspace = tmp_path / "workspace"
    for repo in (project, workspace):
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "init"], check=True)

    result = _sync(project, workspace)

    assert result.returncode == 0
    assert "SYNCED=yes" in result.stdout
    assert "MODEL=none" in result.stdout


def test_sync_main_does_not_disturb_a_canonical_checkout_on_another_branch(tmp_path):
    project, bare = _init_repo_with_bare(tmp_path, "project")
    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")
    theirs = _someone_else_pushes(tmp_path, bare)
    subprocess.run(["git", "-C", str(project), "checkout", "-q", "-b", "in-progress"], check=True)
    (project / "draft.txt").write_text("uncommitted\n")

    result = _sync(project, workspace)

    assert "STRATEGY=fast-forward repo=project" in result.stdout
    assert _sha(project, "main") == theirs
    head = subprocess.run(["git", "-C", str(project), "branch", "--show-current"],
                          capture_output=True, text=True).stdout.strip()
    assert head == "in-progress"
    assert (project / "draft.txt").read_text() == "uncommitted\n"


class TestSyncMainInASlot:
    def _slot(self, tmp_path):
        canon, bare = _init_repo_with_bare(tmp_path, "project")
        canon_ws, _ = _init_repo_with_bare(tmp_path, "workspace")
        slot = tmp_path / "slots" / "4"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("# Slot 4\n")
        clones = []
        for source in (canon, canon_ws):
            clone = slot / source.name
            subprocess.run(["git", "clone", "-q", str(source), str(clone)],
                           capture_output=True, check=True)
            subprocess.run(["git", "-C", str(clone), "config", "user.name", "Test"], capture_output=True)
            subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@test.com"], capture_output=True)
            subprocess.run(["git", "-C", str(clone), "remote", "rename", "origin", "local"],
                           capture_output=True, check=True)
            clones.append(clone)
        return canon, bare, clones[0], clones[1]

    def test_slot_clone_follows_the_remote_through_canonical(self, tmp_path):
        canon, bare, clone, clone_ws = self._slot(tmp_path)
        theirs = _someone_else_pushes(tmp_path, bare)

        result = _sync(clone, clone_ws)

        assert result.returncode == 0, result.stdout
        assert _sha(canon) == theirs
        assert _sha(clone) == theirs
        assert _sha(clone, "local/main") == theirs
        remotes = subprocess.run(["git", "-C", str(clone), "remote"],
                                 capture_output=True, text=True).stdout.split()
        assert remotes == ["local"]

    def test_slot_clone_follows_what_landed_in_canonical_on_disk(self, tmp_path):
        canon, bare, clone, clone_ws = self._slot(tmp_path)
        landed = _local_commit(canon)

        result = _sync(clone, clone_ws)

        assert _sha(clone) == landed
        assert "UNPUBLISHED=1 repo=project" in result.stdout

    def test_stray_commits_on_the_clones_main_are_reported_and_kept(self, tmp_path):
        canon, bare, clone, clone_ws = self._slot(tmp_path)
        stray = _local_commit(clone, "stray.txt")

        result = _sync(clone, clone_ws)

        assert "STRAY=project state=ahead" in result.stdout
        assert _sha(clone) == stray

    def test_clone_with_no_canonical_is_a_warning_not_a_crash(self, tmp_path):
        canon, bare, clone, clone_ws = self._slot(tmp_path)
        subprocess.run(["git", "-C", str(clone), "remote", "remove", "local"],
                       capture_output=True, check=True)

        result = _sync(clone, clone_ws)

        assert result.returncode == 0
        assert "WARN=no_canonical_project" in result.stdout
        assert "SYNCED=partial" in result.stdout


# ---------------------------------------------------------------------------
# Slot resume: branch exists in one repo only (#600)
# ---------------------------------------------------------------------------


class TestSlotResumePartial:
    """#600: in a slot, the branch exists in one clone but not the other."""

    def _slot_pair(self, tmp_path):
        """Two local repos simulating a slot's project and workspace clones."""
        slot = tmp_path / "family" / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("# Slot 1\n")
        for name in ("project", "workspace"):
            repo = slot / name
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True)
            (repo / "README.md").write_text(f"# {name}\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, capture_output=True)
        return slot / "project", slot / "workspace"

    def test_resumes_project_creates_workspace(self, tmp_path):
        proj, ws = self._slot_pair(tmp_path)
        main_sha = subprocess.run(
            ["git", "-C", str(proj), "rev-parse", "main"],
            capture_output=True, text=True,
        ).stdout.strip()
        subprocess.run(["git", "-C", str(proj), "checkout", "-q", "-b", "issue-77-slot"],
                        check=True, capture_output=True)
        subprocess.run(["git", "-C", str(proj), "update-ref",
                        "refs/soredium/base/issue-77-slot", main_sha],
                        check=True, capture_output=True)
        subprocess.run(["git", "-C", str(proj), "checkout", "-q", "main"],
                        check=True, capture_output=True)

        result = subprocess.run(
            ["python3", str(BRANCH_CREATE), "create-branches",
             str(proj), str(ws), "branch=issue-77-slot"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout
        assert "RESUMED=yes" in result.stdout
        proj_branch = subprocess.run(
            ["git", "-C", str(proj), "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
        ws_branch = subprocess.run(
            ["git", "-C", str(ws), "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
        assert proj_branch == "issue-77-slot"
        assert ws_branch == "issue-77-slot"

    def test_creates_project_resumes_workspace(self, tmp_path):
        proj, ws = self._slot_pair(tmp_path)
        main_sha = subprocess.run(
            ["git", "-C", str(ws), "rev-parse", "main"],
            capture_output=True, text=True,
        ).stdout.strip()
        subprocess.run(["git", "-C", str(ws), "checkout", "-q", "-b", "issue-78-slot"],
                        check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ws), "update-ref",
                        "refs/soredium/base/issue-78-slot", main_sha],
                        check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ws), "checkout", "-q", "main"],
                        check=True, capture_output=True)

        result = subprocess.run(
            ["python3", str(BRANCH_CREATE), "create-branches",
             str(proj), str(ws), "branch=issue-78-slot"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout
        assert "RESUMED=yes" in result.stdout
        proj_branch = subprocess.run(
            ["git", "-C", str(proj), "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
        ws_branch = subprocess.run(
            ["git", "-C", str(ws), "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
        assert proj_branch == "issue-78-slot"
        assert ws_branch == "issue-78-slot"


# ---------------------------------------------------------------------------
# Slot re-entry cleanup (Refs #351)
# ---------------------------------------------------------------------------

import branch_create


def _make_slot(tmp_path, name="1"):
    """Create a minimal slot directory structure under .../slots/<name>."""
    slot_dir = tmp_path / "family" / "slots" / name
    slot_dir.mkdir(parents=True)
    return slot_dir


class TestSlotReentryCleanup:
    """Refs #351: _slot_reentry_cleanup must orient, validate, and self-heal."""

    def test_clears_landed_marker(self, tmp_path, capsys):
        slot_dir = _make_slot(tmp_path)
        (slot_dir / ".landed").write_text("landed_shas=abc:123\n")
        branch_create._slot_reentry_cleanup(slot_dir)
        assert not (slot_dir / ".landed").exists()
        captured = capsys.readouterr()
        assert "CLEARED_STALE=.landed" in captured.out
        assert "SLOT_REENTRY=yes" in captured.out
        assert "PREV_STATE=landed" in captured.out

    def test_clears_phase_a_complete(self, tmp_path, capsys):
        slot_dir = _make_slot(tmp_path)
        (slot_dir / ".phase-a-complete").write_text("repo=blocks sha=abc\n")
        branch_create._slot_reentry_cleanup(slot_dir)
        assert not (slot_dir / ".phase-a-complete").exists()
        captured = capsys.readouterr()
        assert "CLEARED_STALE=.phase-a-complete" in captured.out
        assert "PREV_STATE=partial-close" in captured.out

    def test_clears_workspace_markers(self, tmp_path, capsys):
        slot_dir = _make_slot(tmp_path)
        wksp = slot_dir / "wsp-casehub-blocks"
        wksp.mkdir()
        (wksp / ".close-progress").write_text("step=promote\n")
        (wksp / ".artifacts-promoted").write_text("done\n")
        (wksp / ".plan").write_text("# Plan\n## State\nstate: closing:promoted\n")
        branch_create._slot_reentry_cleanup(slot_dir)
        assert not (wksp / ".close-progress").exists()
        assert not (wksp / ".artifacts-promoted").exists()
        assert not (wksp / ".plan").exists()
        captured = capsys.readouterr()
        assert "CLEARED_STALE=" in captured.out

    def test_clears_design_subdir_markers(self, tmp_path, capsys):
        slot_dir = _make_slot(tmp_path)
        wksp = slot_dir / "wsp-casehub-blocks"
        design = wksp / "design"
        design.mkdir(parents=True)
        (design / ".artifacts-promoted").write_text("done\n")
        branch_create._slot_reentry_cleanup(slot_dir)
        assert not (design / ".artifacts-promoted").exists()
        captured = capsys.readouterr()
        assert "CLEARED_STALE=" in captured.out

    def test_no_markers_is_noop(self, tmp_path, capsys):
        slot_dir = _make_slot(tmp_path)
        branch_create._slot_reentry_cleanup(slot_dir)
        captured = capsys.readouterr()
        assert "SLOT_REENTRY" not in captured.out

    def test_non_slot_dir_is_noop(self, tmp_path, capsys):
        regular_dir = tmp_path / "not-a-slot"
        regular_dir.mkdir()
        (regular_dir / ".landed").write_text("test\n")
        branch_create._slot_reentry_cleanup(regular_dir)
        assert (regular_dir / ".landed").exists()
        captured = capsys.readouterr()
        assert "SLOT_REENTRY" not in captured.out

    def test_warns_on_stuck_close_state(self, tmp_path, capsys):
        slot_dir = _make_slot(tmp_path)
        wksp = slot_dir / "wsp-work"
        wksp.mkdir()
        (wksp / ".plan").write_text("# Plan\n\n## State\nstate: closing:promoted\n\n## Queue\n")
        branch_create._slot_reentry_cleanup(slot_dir)
        captured = capsys.readouterr()
        assert "WARN=stuck_close_state" in captured.out
        assert "closing:promoted" in captured.out

    def test_warns_on_repo_on_main(self, tmp_path, capsys):
        slot_dir = _make_slot(tmp_path)
        repo = slot_dir / "engine"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)
        (repo / "f").write_text("x")
        subprocess.run(["git", "add", "f"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        (slot_dir / ".landed").write_text("marker\n")
        branch_create._slot_reentry_cleanup(slot_dir)
        captured = capsys.readouterr()
        assert "WARN=repo_on_main repo=engine" in captured.out

    def test_full_scenario_landed_plus_stale_scaffold(self, tmp_path, capsys):
        """Simulates slot 177: landed from issue-411, new work starts for issue-413."""
        slot_dir = _make_slot(tmp_path)
        (slot_dir / ".landed").write_text("landed_shas=blocks:abc123\n")
        (slot_dir / ".phase-a-complete").write_text("repo=blocks sha=abc\n")
        wksp = slot_dir / "wsp-casehub-blocks"
        wksp.mkdir()
        (wksp / ".plan").write_text("# Plan\n\n## State\nstate: drained\n")
        (wksp / ".close-progress").write_text("done\n")
        (wksp / ".close-report.json").write_text("{}\n")
        (wksp / ".land-ledger.jsonl").write_text("{}\n")
        (wksp / ".artifacts-promoted").write_text("done\n")

        branch_create._slot_reentry_cleanup(slot_dir)

        assert not (slot_dir / ".landed").exists()
        assert not (slot_dir / ".phase-a-complete").exists()
        assert not (wksp / ".plan").exists()
        assert not (wksp / ".close-progress").exists()
        assert not (wksp / ".close-report.json").exists()
        assert not (wksp / ".land-ledger.jsonl").exists()
        assert not (wksp / ".artifacts-promoted").exists()

        captured = capsys.readouterr()
        assert "SLOT_REENTRY=yes PREV_STATE=landed" in captured.out
        assert captured.out.count("CLEARED_STALE=") == 7


class TestCommitScaffoldNothingToCommit:
    """commit_scaffold handles 'nothing to commit' gracefully (#471)."""

    def test_returns_success_when_nothing_to_commit(self, tmp_path):
        """When scaffold files are already committed, return success."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=ws, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=ws, capture_output=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=ws, capture_output=True)
        (ws / ".plan").write_text("branch: test-branch\nstate: active\n")
        (ws / "JOURNAL.md").write_text("# Journal\n")
        subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=ws, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "test-branch"], cwd=ws, check=True, capture_output=True)

        result = subprocess.run(
            [sys.executable, str(BRANCH_CREATE), "commit-scaffold",
             str(ws), "branch=test-branch"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "COMMITTED=no_changes" in result.stdout

    def test_commits_when_files_modified(self, tmp_path):
        """When scaffold files are modified, commit them normally."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=ws, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=ws, capture_output=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=ws, capture_output=True)
        (ws / "README.md").write_text("# WS\n")
        subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=ws, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "test-branch"], cwd=ws, check=True, capture_output=True)
        (ws / ".plan").write_text("branch: test-branch\nstate: active\n")
        (ws / "JOURNAL.md").write_text("# Journal\n")

        result = subprocess.run(
            [sys.executable, str(BRANCH_CREATE), "commit-scaffold",
             str(ws), "branch=test-branch"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "COMMITTED=yes" in result.stdout


# ---------------------------------------------------------------------------
# Single-repo (workspace == project) — #573 orphan branch model
# ---------------------------------------------------------------------------


class TestSingleRepoCreateBranches:
    """When workspace == project, branch is created only once."""

    def test_create_branches_single_repo(self, project_repo):
        result = subprocess.run(
            ["python3", str(BRANCH_CREATE), "create-branches",
             str(project_repo), str(project_repo),
             "branch=issue-99-single"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "CREATED=yes" in result.stdout

        branch = subprocess.run(
            ["git", "-C", str(project_repo), "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
        assert branch == "issue-99-single"

    def test_create_branches_single_repo_with_base(self, project_repo):
        (project_repo / "base.txt").write_text("on main\n")
        subprocess.run(["git", "-C", str(project_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(project_repo), "commit", "-m", "base work"], check=True, capture_output=True)

        result = subprocess.run(
            ["python3", str(BRANCH_CREATE), "create-branches",
             str(project_repo), str(project_repo),
             "branch=issue-100-based", "base=main"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "CREATED=yes" in result.stdout

    def test_create_branches_single_repo_resumes_existing(self, project_repo):
        """Create branch via script, switch back, then resume — single repo."""
        result = subprocess.run(
            ["python3", str(BRANCH_CREATE), "create-branches",
             str(project_repo), str(project_repo),
             "branch=issue-101-exists"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

        subprocess.run(
            ["git", "-C", str(project_repo), "checkout", "main"],
            check=True, capture_output=True,
        )

        result = subprocess.run(
            ["python3", str(BRANCH_CREATE), "create-branches",
             str(project_repo), str(project_repo),
             "branch=issue-101-exists"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "RESUMED=yes" in result.stdout


class TestSingleRepoSyncMain:
    """When workspace == project, sync only runs on the project."""

    def test_sync_main_single_repo(self, tmp_path):
        project, bare = _init_repo_with_bare(tmp_path, "project")

        result = _sync(project, project)

        assert result.returncode == 0
        assert "SYNCED=yes" in result.stdout
        lines = result.stdout.strip().splitlines()
        strategy_lines = [l for l in lines if "STRATEGY=" in l]
        assert len(strategy_lines) == 1, f"expected 1 strategy line, got {strategy_lines}"
        assert "repo=project" in strategy_lines[0]
