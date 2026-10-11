"""Tests for verification/close_checks.py — unified close-time verification."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from verification import Finding, NOT_APPLICABLE
from verification.close_checks import (
    check_issues_closed,
    check_on_main,
    check_main_pushed,
    check_landed_marker,
    check_branch_stamp,
    check_branch_merged,
    check_canonical_sync,
    check_no_open_findings,
    check_artifacts_promoted,
    check_no_stale_scaffold,
    check_landed_completeness,
    check_slot_archive_status,
    check_slot_marker,
    resolve_canonical_repos,
)


class TestCheckIssuesClosed:
    def test_no_covers_returns_empty(self):
        findings = check_issues_closed("Hortora/soredium", [])
        assert findings == []

    def test_none_covers_returns_empty(self):
        findings = check_issues_closed("Hortora/soredium", None)
        assert findings == []

    @patch("verification.close_checks.subprocess.run")
    def test_all_closed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="CLOSED\n")
        findings = check_issues_closed("Hortora/soredium", [1, 2, 3])
        assert findings == []
        assert mock_run.call_count == 3

    @patch("verification.close_checks.subprocess.run")
    def test_one_open(self, mock_run):
        def side_effect(*args, **kwargs):
            issue_num = args[0][3]  # gh issue view <num>
            if issue_num == "2":
                return MagicMock(returncode=0, stdout="OPEN\n")
            return MagicMock(returncode=0, stdout="CLOSED\n")
        mock_run.side_effect = side_effect
        findings = check_issues_closed("Hortora/soredium", [1, 2, 3])
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert "#2" in findings[0].message

    @patch("verification.close_checks.subprocess.run")
    def test_gh_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        findings = check_issues_closed("Hortora/soredium", [42])
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert "#42" in findings[0].message


def _git(path: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(path)] + list(args),
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
    _git(path, "commit", "-m", "initial")
    return path


class TestCheckOnMain:
    def test_on_main(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        findings = check_on_main(repo)
        assert findings == []

    def test_on_feature_branch(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feature")
        findings = check_on_main(repo)
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert "feature" in findings[0].message

    def test_nonexistent_repo(self, tmp_path):
        findings = check_on_main(tmp_path / "nonexistent")
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"


def _init_repo_with_remote(tmp_path: Path, name: str = "repo") -> Path:
    bare = tmp_path / f"{name}-bare.git"
    bare.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    repo = _init_repo(tmp_path / name)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "main")
    return repo


class TestCheckMainPushed:
    def test_pushed(self, tmp_path):
        repo = _init_repo_with_remote(tmp_path)
        findings = check_main_pushed(repo)
        assert findings == []

    def test_unpushed_commits(self, tmp_path):
        repo = _init_repo_with_remote(tmp_path)
        (repo / "new.txt").write_text("new\n")
        _git(repo, "add", "new.txt")
        _git(repo, "commit", "-m", "unpushed")
        findings = check_main_pushed(repo)
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert "1" in findings[0].message

    def test_no_remote(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        findings = check_main_pushed(repo)
        assert findings == []

    def test_custom_base(self, tmp_path):
        repo = _init_repo_with_remote(tmp_path)
        findings = check_main_pushed(repo, base="main")
        assert findings == []


class TestCheckLandedMarker:
    def test_no_landed_file(self, tmp_path):
        findings = check_landed_marker(tmp_path)
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert "no .landed marker" in findings[0].message

    def test_landed_is_directory(self, tmp_path):
        (tmp_path / ".landed").mkdir()
        findings = check_landed_marker(tmp_path)
        assert len(findings) == 1
        assert "directory" in findings[0].message

    def test_valid_landed(self, tmp_path):
        (tmp_path / ".landed").write_text(
            "landed_shas=repo1:abc123,repo2:def456\n"
        )
        findings = check_landed_marker(tmp_path)
        assert findings == []

    def test_no_landed_shas_field(self, tmp_path):
        (tmp_path / ".landed").write_text("something_else=foo\n")
        findings = check_landed_marker(tmp_path)
        assert len(findings) == 1
        assert "no landed_shas" in findings[0].message

    def test_empty_sha_value(self, tmp_path):
        (tmp_path / ".landed").write_text(
            "landed_shas=repo1:abc123\n"
            "issue=42 repo=myrepo sha=\n"
        )
        findings = check_landed_marker(tmp_path)
        assert any(f.category == "landed-empty-sha" for f in findings)

    def test_partial_land_with_failed(self, tmp_path):
        (tmp_path / ".landed").write_text(
            "landed_shas=repo1:abc123\n"
            "failed=repo2\n"
        )
        findings = check_landed_marker(tmp_path)
        assert any(f.severity == "WARN" for f in findings)
        assert any("repo2" in f.message for f in findings)


class TestCheckBranchStamp:
    def test_stamped_branch(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feature")
        (repo / "work.txt").write_text("work\n")
        _git(repo, "add", "work.txt")
        _git(repo, "commit", "-m", "feat: work")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "feature", "--no-ff", "-m", "merge feature")
        _git(repo, "checkout", "feature")
        sha = _git(repo, "rev-parse", "main")
        _git(repo, "commit", "--allow-empty",
             "-m", f"chore: branch closed — landed as {sha} on main")
        findings = check_branch_stamp(repo, "feature")
        assert findings == []

    def test_unstamped_branch(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feature")
        (repo / "work.txt").write_text("work\n")
        _git(repo, "add", "work.txt")
        _git(repo, "commit", "-m", "feat: work")
        findings = check_branch_stamp(repo, "feature")
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert findings[0].category == "branch-not-stamped"

    def test_old_format_stamp_no_sha(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feature")
        _git(repo, "commit", "--allow-empty", "-m", "chore: branch closed")
        findings = check_branch_stamp(repo, "feature")
        assert len(findings) == 1
        assert findings[0].severity == "WARN"
        assert findings[0].category == "stamp-no-sha"

    def test_landing_sha_not_on_base(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feature")
        _git(repo, "commit", "--allow-empty",
             "-m", "chore: branch closed — landed as deadbeef1234 on main")
        findings = check_branch_stamp(repo, "feature")
        assert any(f.category == "stamp-sha-not-on-base" for f in findings)

    def test_branch_not_found(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        findings = check_branch_stamp(repo, "nonexistent")
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"


class TestCheckBranchMerged:
    def test_fully_merged(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feature")
        (repo / "work.txt").write_text("work\n")
        _git(repo, "add", "work.txt")
        _git(repo, "commit", "-m", "feat: work")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "feature", "--no-ff", "-m", "merge feature")
        _git(repo, "checkout", "feature")
        _git(repo, "commit", "--allow-empty", "-m", "chore: branch closed")
        findings = check_branch_merged(repo, "feature")
        assert findings == []

    def test_unmerged_commits(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feature")
        (repo / "work.txt").write_text("work\n")
        _git(repo, "add", "work.txt")
        _git(repo, "commit", "-m", "feat: unmerged work")
        findings = check_branch_merged(repo, "feature")
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert "UNMERGED" in findings[0].message

    def test_ceremony_commits_filtered(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feature")
        (repo / "work.txt").write_text("work\n")
        _git(repo, "add", "work.txt")
        _git(repo, "commit", "-m", "feat: work")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "feature", "--no-ff", "-m", "merge feature")
        _git(repo, "checkout", "feature")
        _git(repo, "commit", "--allow-empty",
             "-m", "chore: branch closed — landed as abc on main")
        _git(repo, "commit", "--allow-empty",
             "-m", "chore: commit lifecycle state")
        findings = check_branch_merged(repo, "feature")
        assert findings == []

    def test_branch_not_found(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        findings = check_branch_merged(repo, "nonexistent")
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"


def _make_slot_and_canonical(tmp_path, name="myrepo"):
    canonical = _init_repo(tmp_path / "canonical" / name)
    slot_dir = tmp_path / "slot"
    slot_dir.mkdir(parents=True)
    clone = slot_dir / name
    subprocess.run(["git", "clone", str(canonical), str(clone)],
                   capture_output=True, check=True)
    _git(clone, "config", "user.email", "test@test.com")
    _git(clone, "config", "user.name", "Test")
    _git(clone, "remote", "add", "local", str(canonical))
    return slot_dir, clone, canonical


class TestCheckCanonicalSync:
    def test_content_on_main(self, tmp_path):
        slot_dir, clone, canonical = _make_slot_and_canonical(tmp_path)
        _git(clone, "checkout", "-b", "feature")
        (clone / "work.txt").write_text("work\n")
        _git(clone, "add", "work.txt")
        _git(clone, "commit", "-m", "feat: work")
        sha = _git(clone, "rev-parse", "HEAD")
        _git(canonical, "pull", str(clone), "feature")
        (slot_dir / ".landed").write_text(f"landed_shas=myrepo:{sha}\n")
        findings = check_canonical_sync(slot_dir, "myrepo", canonical)
        assert findings == []

    def test_sha_not_on_canonical(self, tmp_path):
        slot_dir, clone, canonical = _make_slot_and_canonical(tmp_path)
        _git(clone, "checkout", "-b", "feature")
        (clone / "work.txt").write_text("work\n")
        _git(clone, "add", "work.txt")
        _git(clone, "commit", "-m", "feat: work")
        sha = _git(clone, "rev-parse", "HEAD")
        (slot_dir / ".landed").write_text(f"landed_shas=myrepo:{sha}\n")
        findings = check_canonical_sync(slot_dir, "myrepo", canonical)
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"

    def test_no_landed_file(self, tmp_path):
        slot_dir, clone, canonical = _make_slot_and_canonical(tmp_path)
        findings = check_canonical_sync(slot_dir, "myrepo", canonical)
        assert len(findings) == 1
        assert "no .landed" in findings[0].message

    def test_unchanged_repo_no_branch(self, tmp_path):
        slot_dir, clone, canonical = _make_slot_and_canonical(tmp_path)
        (slot_dir / ".landed").write_text("landed_shas=other:abc123\n")
        findings = check_canonical_sync(slot_dir, "myrepo", canonical, branch="feature")
        assert findings == []

    def test_no_sha_for_repo(self, tmp_path):
        slot_dir, clone, canonical = _make_slot_and_canonical(tmp_path)
        (slot_dir / ".landed").write_text("landed_shas=other:abc123\n")
        findings = check_canonical_sync(slot_dir, "myrepo", canonical)
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"


class TestCheckNoOpenFindings:
    def test_no_findings_file(self, tmp_path):
        findings = check_no_open_findings(tmp_path)
        assert findings == []

    def test_empty_findings_file(self, tmp_path):
        audit = tmp_path / ".audit"
        audit.mkdir()
        (audit / "findings.jsonl").write_text("")
        findings = check_no_open_findings(tmp_path)
        assert findings == []

    def test_open_findings(self, tmp_path):
        audit = tmp_path / ".audit"
        audit.mkdir()
        (audit / "findings.jsonl").write_text(
            '{"status": "open", "summary": "bug"}\n'
            '{"status": "resolved", "summary": "fixed"}\n'
        )
        findings = check_no_open_findings(tmp_path)
        assert len(findings) == 1
        assert "1 open" in findings[0].message

    def test_all_resolved(self, tmp_path):
        audit = tmp_path / ".audit"
        audit.mkdir()
        (audit / "findings.jsonl").write_text(
            '{"status": "resolved"}\n'
        )
        findings = check_no_open_findings(tmp_path)
        assert findings == []


class TestCheckArtifactsPromoted:
    def test_stamp_exists(self, tmp_path):
        (tmp_path / ".artifacts-promoted").write_text("done\n")
        findings = check_artifacts_promoted(tmp_path)
        assert findings == []

    def test_on_main_mode(self, tmp_path):
        findings = check_artifacts_promoted(tmp_path, on_main=True)
        assert findings == []

    def test_no_stamp(self, tmp_path):
        findings = check_artifacts_promoted(tmp_path)
        assert len(findings) == 1
        assert findings[0].severity == "WARN"

    def test_stamp_in_design_subdir(self, tmp_path):
        (tmp_path / "design").mkdir()
        (tmp_path / "design" / ".artifacts-promoted").write_text("done\n")
        findings = check_artifacts_promoted(tmp_path)
        assert findings == []


class TestCheckNoStaleScaffold:
    def test_clean(self, tmp_path):
        findings = check_no_stale_scaffold(tmp_path)
        assert findings == []

    def test_stale_files(self, tmp_path):
        (tmp_path / ".execute-progress").write_text("stale\n")
        (tmp_path / ".land-ledger.jsonl").write_text("stale\n")
        findings = check_no_stale_scaffold(tmp_path)
        assert len(findings) == 1
        assert "execute-progress" in findings[0].message


class TestCheckLandedCompleteness:
    def test_all_repos_landed(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text("landed_shas=repo1:abc,repo2:def\n")
        findings = check_landed_completeness(slot_dir, repos={"repo1", "repo2"})
        assert findings == []

    def test_missing_repo(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text("landed_shas=repo1:abc\n")
        findings = check_landed_completeness(slot_dir, repos={"repo1", "repo2"})
        assert len(findings) == 1
        assert "repo2" in findings[0].message

    def test_no_repos(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        findings = check_landed_completeness(slot_dir, repos=set())
        assert findings == []

    def test_unchanged_repo_auto_passes(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo = _init_repo(slot_dir / "repo2")
        (slot_dir / ".landed").write_text("landed_shas=repo1:abc\n")
        findings = check_landed_completeness(
            slot_dir, repos={"repo1", "repo2"}, branch="feature")
        assert findings == []


class TestCheckSlotArchiveStatus:
    def test_archived(self, tmp_path):
        attic = tmp_path / "attic" / "001"
        attic.mkdir(parents=True)
        findings = check_slot_archive_status(tmp_path / "001", str(attic))
        assert findings == []

    def test_landed_not_archived(self, tmp_path):
        slot = tmp_path / "001"
        slot.mkdir()
        (slot / ".landed").write_text("done\n")
        attic = tmp_path / "attic" / "001"
        findings = check_slot_archive_status(slot, str(attic))
        assert len(findings) == 1
        assert findings[0].severity == "WARN"

    def test_active(self, tmp_path):
        slot = tmp_path / "001"
        slot.mkdir()
        attic = tmp_path / "attic" / "001"
        findings = check_slot_archive_status(slot, str(attic))
        assert len(findings) == 1
        assert findings[0].severity == "WARN"

    def test_slot_not_found(self, tmp_path):
        findings = check_slot_archive_status(tmp_path / "001", str(tmp_path / "attic/001"))
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"


class TestCheckSlotMarker:
    def test_marker_exists(self, tmp_path):
        (tmp_path / ".phase-a-complete").write_text("done\n")
        findings = check_slot_marker(tmp_path, ".phase-a-complete")
        assert findings == []

    def test_marker_missing(self, tmp_path):
        findings = check_slot_marker(tmp_path, ".phase-a-complete")
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"

    def test_marker_is_directory(self, tmp_path):
        (tmp_path / ".phase-a-complete").mkdir()
        findings = check_slot_marker(tmp_path, ".phase-a-complete")
        assert len(findings) == 1
        assert "directory" in findings[0].message


class TestResolveCanonicalRepos:
    def test_finds_repos_with_local_remote(self, tmp_path):
        slot_dir = tmp_path / "slot"
        canonical = _init_repo(tmp_path / "canonical")
        clone = slot_dir / "myrepo"
        subprocess.run(["git", "clone", str(canonical), str(clone)],
                       capture_output=True, check=True)
        _git(clone, "remote", "add", "local", str(canonical))
        result = resolve_canonical_repos(slot_dir)
        assert "myrepo" in result
        assert Path(result["myrepo"]).resolve() == canonical.resolve()

    def test_skips_non_git_dirs(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / "not-a-repo").mkdir()
        result = resolve_canonical_repos(slot_dir)
        assert result == {}

    def test_skips_special_dirs(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".m2").mkdir()
        (slot_dir / "attic").mkdir()
        result = resolve_canonical_repos(slot_dir)
        assert result == {}
