"""Tests for verify_slot_close.py (CLI) and verification/close_checks.py (library).

CLI tests use subprocess to invoke the script. Unit tests import from
verification.close_checks directly and assert on list[Finding].
"""

import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "work-end" / "verify_slot_close.py"


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


def _create_clean_single_repo(tmp_path: Path, branch: str = "issue-99-test") -> tuple[Path, Path]:
    remote = _init_bare(tmp_path / "remote.git")
    project = _init_repo(tmp_path / "project")
    _git(project, "remote", "add", "origin", str(remote))
    _git(project, "push", "origin", "main")

    _git(project, "checkout", "-b", branch)
    (project / "feature.txt").write_text("feature\n")
    _git(project, "add", "feature.txt")
    _git(project, "commit", "-m", "feat: add feature")
    _git(project, "push", "origin", branch)

    _git(project, "checkout", "main")
    _git(project, "merge", "--ff-only", branch)
    _git(project, "push", "origin", "main")

    sha = _git(project, "rev-parse", "main")
    _git(project, "checkout", branch)
    _git(project, "commit", "--allow-empty", "-m",
         f"chore: branch closed — landed as {sha} on main")
    _git(project, "push", "origin", branch, "--force-with-lease")
    _git(project, "checkout", "main")

    workspace = _init_repo(tmp_path / "workspace")
    _git(workspace, "checkout", "-b", branch)
    _git(workspace, "commit", "--allow-empty", "-m",
         f"chore: branch closed — landed as {sha} on main")
    _git(workspace, "checkout", "main")

    return project, workspace


def _run_verify(
    project: Path, workspace: Path, branch: str = "issue-99-test",
    **extra_args: str,
) -> subprocess.CompletedProcess:
    args = [
        sys.executable, str(SCRIPT),
        str(project), f"branch={branch}", f"workspace={workspace}",
    ]
    for k, v in extra_args.items():
        args.append(f"{k}={v}")
    return subprocess.run(args, capture_output=True, text=True)


# --- CLI integration tests (subprocess) ---

class TestVerifyAllPass:
    def test_single_repo_clean_state(self, tmp_path: Path) -> None:
        project, workspace = _create_clean_single_repo(tmp_path)
        result = _run_verify(project, workspace)
        assert result.returncode == 0
        assert "VERIFIED=yes" in result.stdout


class TestVerifyMissingStamp:
    def test_unstamped_branch(self, tmp_path: Path) -> None:
        branch = "issue-100-test"
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "f.txt").write_text("work\n")
        _git(project, "add", "f.txt")
        _git(project, "commit", "-m", "feat: work")
        _git(project, "push", "origin", branch)

        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)
        _git(project, "push", "origin", "main")

        workspace = _init_repo(tmp_path / "workspace")

        result = _run_verify(project, workspace, branch=branch)
        assert "VERIFIED=no" in result.stdout
        assert "project_stamped" in result.stdout


class TestVerifyUnpushedMain:
    def test_local_ahead_of_origin(self, tmp_path: Path) -> None:
        branch = "issue-101-test"
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "f.txt").write_text("work\n")
        _git(project, "add", "f.txt")
        _git(project, "commit", "-m", "feat: work")
        _git(project, "push", "origin", branch)

        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)

        sha = _git(project, "rev-parse", "main")
        _git(project, "checkout", branch)
        _git(project, "commit", "--allow-empty", "-m",
             f"chore: branch closed — landed as {sha} on main")
        _git(project, "checkout", "main")

        workspace = _init_repo(tmp_path / "workspace")

        result = _run_verify(project, workspace, branch=branch)
        assert "VERIFIED=no" in result.stdout


class TestVerifyBadArgs:
    def test_missing_args(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


# --- Unit tests (import from verification.close_checks) ---

from verification.close_checks import (
    check_landed_marker,
    check_canonical_sync,
    check_branch_stamp,
    check_branch_merged,
    check_landed_completeness,
    check_slot_archive_status,
    check_issues_closed,
    resolve_canonical_repos,
    _find_tree_on_ref,
    _verify_sha_on_ref,
)


class TestCheckLandedMarker:
    def test_landed_marker_present(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text(
            "branch=issue-42\nrepos=engine,work\n"
            "landed_shas=engine:abc123,work:def456\n"
            "timestamp=2026-08-12T00:00:00Z\n"
        )
        findings = check_landed_marker(slot_dir)
        assert findings == []

    def test_landed_marker_absent(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        findings = check_landed_marker(slot_dir)
        assert len(findings) == 1
        assert "no .landed marker" in findings[0].message

    def test_landed_marker_no_shas(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text("branch=issue-42\n")
        findings = check_landed_marker(slot_dir)
        assert len(findings) == 1
        assert "no landed_shas" in findings[0].message


class TestCheckLandedShasPopulated:
    def test_pass_when_no_landed_file(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        findings = check_landed_marker(slot_dir)
        assert any("no .landed" in f.message for f in findings)

    def test_pass_when_shas_present(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text("landed_shas=engine:abc123\n")
        findings = check_landed_marker(slot_dir)
        assert findings == []

    def test_fail_when_empty_sha(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text(
            "landed_shas=engine:abc\n"
            "issue=42 title=Fix-login branch=issue-42 sha= date=2026-08-29\n"
            "issue=43 title=Add-tests branch=issue-42 sha= date=2026-08-29\n"
        )
        findings = check_landed_marker(slot_dir)
        empty_sha_findings = [f for f in findings if f.category == "landed-empty-sha"]
        assert len(empty_sha_findings) == 2

    def test_pass_when_sha_populated(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text(
            "landed_shas=engine:abc123\n"
            "issue=42 title=Fix-login branch=issue-42 sha=abc123 date=2026-08-29\n"
        )
        findings = check_landed_marker(slot_dir)
        assert findings == []


class TestCheckCanonicalSync:
    def test_canonical_in_sync(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        canonical = _init_repo(tmp_path / "canonical")
        clone = _init_repo(slot_dir / "engine")
        orig_sha = _git(canonical, "rev-parse", "HEAD")
        (slot_dir / ".landed").write_text(f"landed_shas=engine:{orig_sha}\n")
        findings = check_canonical_sync(slot_dir, "engine", canonical)
        assert findings == []

    def test_canonical_behind(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        canonical = _init_repo(tmp_path / "canonical")
        clone = _init_repo(slot_dir / "engine")
        (clone / "extra.txt").write_text("new\n")
        _git(clone, "add", "extra.txt")
        _git(clone, "commit", "-m", "extra")
        clone_sha = _git(clone, "rev-parse", "HEAD")
        (slot_dir / ".landed").write_text(f"landed_shas=engine:{clone_sha}\n")
        findings = check_canonical_sync(slot_dir, "engine", canonical)
        assert len(findings) == 1
        assert "not reachable" in findings[0].message

    def test_no_landed_marker(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        findings = check_canonical_sync(slot_dir, "engine", tmp_path / "canonical")
        assert len(findings) == 1
        assert "no .landed" in findings[0].message

    def test_tree_sha_fallback_after_rebase(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        canonical = _init_repo(tmp_path / "canonical")
        clone = _init_repo(slot_dir / "engine")
        (clone / "feature.txt").write_text("feature content\n")
        _git(clone, "add", "feature.txt")
        _git(clone, "commit", "-m", "add feature")
        clone_sha = _git(clone, "rev-parse", "HEAD")
        clone_tree = _git(clone, "rev-parse", "HEAD^{tree}")
        (canonical / "feature.txt").write_text("feature content\n")
        _git(canonical, "add", "feature.txt")
        _git(canonical, "commit", "-m", "add feature (rebased)")
        orig_sha = _git(canonical, "rev-parse", "HEAD")
        assert clone_sha != orig_sha
        orig_tree = _git(canonical, "rev-parse", "HEAD^{tree}")
        assert clone_tree == orig_tree
        (slot_dir / ".landed").write_text(f"landed_shas=engine:{clone_sha}\n")
        findings = check_canonical_sync(slot_dir, "engine", canonical)
        assert findings == []


class TestCheckLandingShaTreeFallback:
    def test_landing_sha_after_rebase(self, tmp_path: Path) -> None:
        project = _init_repo(tmp_path / "project")
        _git(project, "checkout", "-b", "feature")
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "add feature")
        _git(project, "checkout", "main")
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "add feature (rebased by github)")
        main_sha = _git(project, "rev-parse", "HEAD")
        _git(project, "checkout", "feature")
        _git(project, "commit", "--allow-empty", "--amend", "-m",
             f"chore: branch closed — landed as {main_sha} on main")
        findings = check_branch_stamp(project, "feature")
        assert findings == []


class TestCheckLandingShaHistory:
    def test_backward_compatible_no_history(self, tmp_path: Path) -> None:
        project = _init_repo(tmp_path / "project")
        _git(project, "checkout", "-b", "feature")
        (project / "f.txt").write_text("work\n")
        _git(project, "add", "f.txt")
        _git(project, "commit", "-m", "feat: work")
        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", "feature")
        sha = _git(project, "rev-parse", "main")
        _git(project, "checkout", "feature")
        _git(project, "commit", "--allow-empty", "-m",
             f"chore: branch closed — landed as {sha} on main")
        _git(project, "checkout", "main")
        findings = check_branch_stamp(project, "feature")
        assert findings == []


class TestDiffFallbackAfterSquashRebase:
    def test_diff_fallback_when_tree_search_exhausted(self, tmp_path: Path) -> None:
        project = _init_repo(tmp_path / "project")
        _git(project, "checkout", "-b", "feature")
        (project / "a.txt").write_text("a\n")
        _git(project, "add", "a.txt")
        _git(project, "commit", "-m", "add a")
        feature_sha = _git(project, "rev-parse", "HEAD")
        _git(project, "checkout", "main")
        (project / "a.txt").write_text("a\n")
        _git(project, "add", "a.txt")
        _git(project, "commit", "-m", "add a (rebased)")
        for i in range(3):
            _git(project, "commit", "--allow-empty", "-m", f"padding {i}")

        import verification.close_checks as cc
        orig_fn = cc._find_tree_on_ref
        cc._find_tree_on_ref = lambda repo, tree, ref, max_commits=500: None
        try:
            findings = _verify_sha_on_ref(project, feature_sha, "main")
            assert findings == []
        finally:
            cc._find_tree_on_ref = orig_fn

    def test_max_commits_increased_to_500(self) -> None:
        import inspect
        sig = inspect.signature(_find_tree_on_ref)
        assert sig.parameters["max_commits"].default == 500


class TestCheckSlotArchiveStatus:
    def test_archived(self, tmp_path: Path) -> None:
        attic_dir = tmp_path / "slots" / "attic" / "1"
        attic_dir.mkdir(parents=True)
        findings = check_slot_archive_status(tmp_path / "slots" / "1", str(attic_dir))
        assert findings == []

    def test_landed_not_archived(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".landed").write_text("landed\n")
        findings = check_slot_archive_status(slot_dir, str(tmp_path / "slots" / "attic" / "1"))
        assert len(findings) == 1
        assert findings[0].severity == "WARN"
        assert "landed but not archived" in findings[0].message

    def test_active(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        findings = check_slot_archive_status(slot_dir, str(tmp_path / "slots" / "attic" / "1"))
        assert len(findings) == 1
        assert findings[0].severity == "WARN"
        assert "active" in findings[0].message


class TestCheckIssuesClosed:
    def test_all_closed(self, tmp_path: Path, monkeypatch) -> None:
        import verification.close_checks as cc
        def fake_run(cmd, **kwargs):
            if "gh" in cmd and "issue" in cmd and "view" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "CLOSED\n", "")
            return subprocess.run(cmd, **kwargs)
        monkeypatch.setattr(cc.subprocess, "run", fake_run)
        findings = check_issues_closed("owner/repo", [42, 43])
        assert findings == []

    def test_one_open(self, tmp_path: Path, monkeypatch) -> None:
        import verification.close_checks as cc
        call_count = {"n": 0}
        def fake_run(cmd, **kwargs):
            if "gh" in cmd and "issue" in cmd and "view" in cmd:
                call_count["n"] += 1
                state = "CLOSED" if call_count["n"] == 1 else "OPEN"
                return subprocess.CompletedProcess(cmd, 0, f"{state}\n", "")
            return subprocess.run(cmd, **kwargs)
        monkeypatch.setattr(cc.subprocess, "run", fake_run)
        findings = check_issues_closed("owner/repo", [42, 43])
        assert len(findings) == 1
        assert "#43" in findings[0].message

    def test_gh_failure_is_fail(self, tmp_path: Path, monkeypatch) -> None:
        import verification.close_checks as cc
        def fake_run(cmd, **kwargs):
            if "gh" in cmd and "issue" in cmd and "view" in cmd:
                return subprocess.CompletedProcess(cmd, 1, "", "network error")
            return subprocess.run(cmd, **kwargs)
        monkeypatch.setattr(cc.subprocess, "run", fake_run)
        findings = check_issues_closed("owner/repo", [42])
        assert len(findings) == 1

    def test_empty_covers_is_pass(self) -> None:
        findings = check_issues_closed("owner/repo", [])
        assert findings == []

    def test_none_covers_is_pass(self) -> None:
        findings = check_issues_closed("owner/repo", None)
        assert findings == []


class TestVerifySlotModeCLI:
    def test_slot_dir_enables_slot_checks(self, tmp_path: Path) -> None:
        project, workspace = _create_clean_single_repo(tmp_path)
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text(
            "branch=issue-99-test\nrepos=project\n"
            "landed_shas=project:abc123\ntimestamp=2026-08-12\n"
        )
        result = _run_verify(project, workspace, slot_dir=str(slot_dir))
        assert result.returncode == 0
        assert "landed_marker" in result.stdout


class TestResolveCanonicalReposScoped:
    def _make_slot_with_repos(self, tmp_path, repos):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir(exist_ok=True)
        for name in repos:
            repo = slot_dir / name
            repo.mkdir(exist_ok=True)
            subprocess.run(["git", "init", str(repo)], capture_output=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "t@t.com"],
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "T"],
                capture_output=True,
            )
            orig = tmp_path / "canonical" / name
            orig.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "-C", str(repo), "remote", "add", "local", str(orig)],
                capture_output=True,
            )
        return slot_dir

    def test_scoped_to_covers(self, tmp_path):
        slot_dir = self._make_slot_with_repos(tmp_path, ["engine", "work", "aml"])
        result = resolve_canonical_repos(slot_dir, covers_repos={"engine", "work"})
        assert "engine" in result
        assert "work" in result
        assert "aml" not in result

    def test_no_covers_returns_all(self, tmp_path):
        slot_dir = self._make_slot_with_repos(tmp_path, ["engine", "work", "aml"])
        result = resolve_canonical_repos(slot_dir)
        assert "engine" in result
        assert "work" in result
        assert "aml" in result


class TestLandedCompletenessScoped:
    def test_scoped_completeness_passes(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("## Repos\n- engine\n- work\n- aml\n")
        (slot_dir / ".landed").write_text("landed_shas=engine:abc,work:def\n")
        findings = check_landed_completeness(slot_dir, repos={"engine", "work"})
        assert findings == []

    def test_unscoped_fails_when_repos_missing(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("## Repos\n- engine\n- work\n- aml\n")
        (slot_dir / ".landed").write_text("landed_shas=engine:abc,work:def\n")
        findings = check_landed_completeness(slot_dir)
        assert len(findings) == 1
        assert "aml" in findings[0].message

    def test_fallback_when_no_covers(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("## Repos\n- engine\n- work\n")
        (slot_dir / ".landed").write_text("landed_shas=engine:abc,work:def\n")
        findings = check_landed_completeness(slot_dir)
        assert findings == []


class TestLandedCompletenessAutoPass:
    def test_missing_repo_without_branch_auto_passes(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("## Repos\n- engine\n- blocks\n")
        (slot_dir / ".landed").write_text("landed_shas=engine:abc\n")
        clone = slot_dir / "blocks"
        clone.mkdir()
        subprocess.run(["git", "init"], cwd=clone, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=clone, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=clone, capture_output=True)
        (clone / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=clone, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=clone, capture_output=True)
        findings = check_landed_completeness(slot_dir, branch="issue-42-feature")
        assert findings == []

    def test_missing_repo_with_branch_still_fails(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("## Repos\n- engine\n- blocks\n")
        (slot_dir / ".landed").write_text("landed_shas=engine:abc\n")
        clone = slot_dir / "blocks"
        clone.mkdir()
        subprocess.run(["git", "init"], cwd=clone, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=clone, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=clone, capture_output=True)
        (clone / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=clone, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=clone, capture_output=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=clone, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "issue-42-feature"], cwd=clone, capture_output=True)
        (clone / "feature.txt").write_text("change")
        subprocess.run(["git", "add", "."], cwd=clone, capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: change"], cwd=clone, capture_output=True)
        findings = check_landed_completeness(slot_dir, branch="issue-42-feature")
        assert len(findings) == 1
        assert "blocks" in findings[0].message

    def test_branch_exists_zero_commits_auto_passes(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("## Repos\n- engine\n- blocks\n")
        (slot_dir / ".landed").write_text("landed_shas=engine:abc\n")
        clone = slot_dir / "blocks"
        clone.mkdir()
        subprocess.run(["git", "init"], cwd=clone, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=clone, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=clone, capture_output=True)
        (clone / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=clone, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=clone, capture_output=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=clone, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "issue-42-feature"], cwd=clone, capture_output=True)
        findings = check_landed_completeness(slot_dir, branch="issue-42-feature")
        assert findings == []

    def test_no_clone_dir_auto_passes(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("## Repos\n- engine\n- ghost\n")
        (slot_dir / ".landed").write_text("landed_shas=engine:abc\n")
        findings = check_landed_completeness(slot_dir, branch="issue-42-feature")
        assert findings == []


class TestCeremonyCommitFilter:
    def test_lifecycle_state_commit_filtered(self, tmp_path):
        branch = "issue-371-test"
        project = _init_repo(tmp_path / "project")
        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("work\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: add feature")
        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)
        _git(project, "checkout", branch)
        _git(project, "commit", "--allow-empty",
             "-m", "chore: commit lifecycle state before branch switch")
        _git(project, "commit", "--allow-empty",
             "-m", "chore: branch closed — landed as abc123 on main")
        _git(project, "checkout", "main")
        findings = check_branch_merged(project, branch)
        assert findings == []

    def test_strip_lifecycle_commit_filtered(self, tmp_path):
        branch = "issue-371-test"
        project = _init_repo(tmp_path / "project")
        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("work\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: add feature")
        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)
        _git(project, "checkout", branch)
        _git(project, "commit", "--allow-empty",
             "-m", "chore: strip lifecycle files before close")
        _git(project, "commit", "--allow-empty",
             "-m", "chore: branch closed — landed as abc123 on main")
        _git(project, "checkout", "main")
        findings = check_branch_merged(project, branch)
        assert findings == []

    def test_real_unmerged_commit_still_fails(self, tmp_path):
        branch = "issue-371-test"
        project = _init_repo(tmp_path / "project")
        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("work\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: add feature")
        _git(project, "checkout", "main")
        _git(project, "checkout", branch)
        _git(project, "commit", "--allow-empty",
             "-m", "feat: extra unmerged work")
        _git(project, "checkout", "main")
        findings = check_branch_merged(project, branch)
        assert len(findings) == 1
        assert "UNMERGED" in findings[0].message
