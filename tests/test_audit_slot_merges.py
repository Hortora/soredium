"""Tests for audit_slot_merges.py --fix mode."""

import subprocess
import textwrap
from pathlib import Path


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


def _create_slot_dir(
    tmp_path: Path, slot_num: int, branch: str, repos: list[str],
    primary: str | None = None,
) -> Path:
    slot_dir = tmp_path / "slots" / "attic" / str(slot_num)
    slot_dir.mkdir(parents=True, exist_ok=True)
    if primary is None:
        primary = repos[0]
    repo_lines = "\n".join(
        f"- {r} (primary)" if r == primary else f"- {r}"
        for r in repos
    )
    (slot_dir / ".slot").write_text(textwrap.dedent(f"""\
        # Slot {slot_num}

        branch: {branch}

        ## Repos
        {repo_lines}
    """))
    return slot_dir


def _create_merged_unstamped(tmp_path: Path, repo_name: str, branch: str) -> Path:
    """Create a repo where branch content is on main via ff-merge but not stamped."""
    repo = _init_repo(tmp_path / repo_name)
    _git(repo, "checkout", "-b", branch)
    (repo / "feature.txt").write_text("feature content\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", f"feat: add feature for {branch}")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--ff-only", branch)
    return repo


def _create_squash_merged_unstamped(
    tmp_path: Path, repo_name: str, branch: str,
) -> Path:
    """Create a repo where branch content is on main via squash but not stamped.

    Squash merge creates different SHAs — classified as UNMERGED(1) since
    git log main..branch still shows the original commit.
    """
    repo = _init_repo(tmp_path / repo_name)
    _git(repo, "checkout", "-b", branch)
    (repo / "feature.txt").write_text("feature content\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", f"feat: add feature for {branch}")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--squash", branch)
    _git(repo, "commit", "-m", f"feat: add feature for {branch}")
    return repo


def _create_already_stamped(tmp_path: Path, repo_name: str, branch: str) -> Path:
    """Create a repo where branch is properly merged and stamped."""
    repo = _create_merged_unstamped(tmp_path, repo_name, branch)
    sha = _git(repo, "rev-parse", "main")
    _git(repo, "checkout", branch)
    _git(repo, "commit", "--allow-empty", "-m",
         f"chore: branch closed — landed as {sha} on main")
    _git(repo, "checkout", "main")
    return repo


def _create_unmerged(tmp_path: Path, repo_name: str, branch: str) -> Path:
    """Create a repo where branch content is NOT on main."""
    repo = _init_repo(tmp_path / repo_name)
    _git(repo, "checkout", "-b", branch)
    (repo / "unique.txt").write_text("unique content not on main\n")
    _git(repo, "add", "unique.txt")
    _git(repo, "commit", "-m", "feat: unique work not merged")
    _git(repo, "checkout", "main")
    return repo


def _run_audit(family_root: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", "scripts/audit_slot_merges.py", str(family_root),
         "--all", *extra_args],
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent.parent),
    )


class TestFixStampsUnstamped:
    def test_fix_stamps_merged_unstamped_branch(self, tmp_path: Path) -> None:
        branch = "issue-42-test-feature"
        _create_merged_unstamped(tmp_path, "engine", branch)
        _create_slot_dir(tmp_path, 1, branch, ["engine"])

        result = _run_audit(tmp_path, "--fix")
        assert result.returncode == 0
        assert "STAMPED" in result.stdout

        last_msg = _git(tmp_path / "engine", "log", "-1", "--format=%s", branch)
        assert last_msg.startswith("chore: branch closed")

    def test_fix_skips_already_stamped(self, tmp_path: Path) -> None:
        branch = "issue-43-already-done"
        _create_already_stamped(tmp_path, "engine", branch)
        _create_slot_dir(tmp_path, 2, branch, ["engine"])

        result = _run_audit(tmp_path, "--fix")
        assert result.returncode == 0
        assert "STAMPED" not in result.stdout or "already" in result.stdout.lower()

        commit_count = _git(tmp_path / "engine", "rev-list", "--count", branch)
        original_count = _git(tmp_path / "engine", "rev-list", "--count",
                              f"{branch}~1")
        assert int(commit_count) == int(original_count) + 1

    def test_fix_does_not_stamp_unmerged(self, tmp_path: Path) -> None:
        branch = "issue-44-unmerged"
        _create_unmerged(tmp_path, "engine", branch)
        _create_slot_dir(tmp_path, 3, branch, ["engine"])

        result = _run_audit(tmp_path, "--fix")
        assert result.returncode != 0 or "UNMERGED" in result.stdout

        last_msg = _git(tmp_path / "engine", "log", "-1", "--format=%s", branch)
        assert not last_msg.startswith("chore: branch closed")

    def test_fix_produces_summary(self, tmp_path: Path) -> None:
        branch = "issue-45-summary"
        _create_merged_unstamped(tmp_path, "engine", branch)
        _create_slot_dir(tmp_path, 4, branch, ["engine"])

        result = _run_audit(tmp_path, "--fix")
        assert "Audit Summary" in result.stdout

    def test_fix_multi_repo_stamps_all_unstamped(self, tmp_path: Path) -> None:
        branch = "issue-46-multi"
        _create_merged_unstamped(tmp_path, "engine", branch)
        _create_merged_unstamped(tmp_path, "blocks", branch)
        _create_slot_dir(tmp_path, 5, branch, ["engine", "blocks"])

        result = _run_audit(tmp_path, "--fix")
        assert result.returncode == 0

        for repo_name in ["engine", "blocks"]:
            last_msg = _git(tmp_path / repo_name, "log", "-1", "--format=%s", branch)
            assert last_msg.startswith("chore: branch closed"), (
                f"{repo_name} not stamped: {last_msg}"
            )


    def test_fix_squash_merged_stamps_via_content_match(self, tmp_path: Path) -> None:
        branch = "issue-48-squash"
        _create_squash_merged_unstamped(tmp_path, "engine", branch)
        _create_slot_dir(tmp_path, 7, branch, ["engine"])

        result = _run_audit(tmp_path, "--fix")
        assert result.returncode == 0

        last_msg = _git(tmp_path / "engine", "log", "-1", "--format=%s", branch)
        assert last_msg.startswith("chore: branch closed")
        assert "landed as" in last_msg


class TestFixEdgeCases:
    def test_fix_with_no_slots(self, tmp_path: Path) -> None:
        result = _run_audit(tmp_path, "--fix")
        assert result.returncode == 0
        assert "Total slots scanned: 0" in result.stdout

    def test_fix_without_flag_does_not_stamp(self, tmp_path: Path) -> None:
        branch = "issue-47-no-fix"
        _create_merged_unstamped(tmp_path, "engine", branch)
        _create_slot_dir(tmp_path, 6, branch, ["engine"])

        result = _run_audit(tmp_path)
        last_msg = _git(tmp_path / "engine", "log", "-1", "--format=%s", branch)
        assert not last_msg.startswith("chore: branch closed")

    def test_bad_args(self) -> None:
        result = subprocess.run(
            ["python3", "scripts/audit_slot_merges.py"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
