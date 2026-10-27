"""Tests for verification/outcomes.py — three-valued outcome verification."""
import pytest

from verification.outcomes import (
    VerifyResult,
    Verification,
    compose_verifications,
    verification_to_findings,
)


class TestVerifyResult:
    def test_values(self):
        assert VerifyResult.PASS.value == "pass"
        assert VerifyResult.FAIL.value == "fail"
        assert VerifyResult.UNKNOWN.value == "unknown"


class TestVerification:
    def test_creation(self):
        v = Verification("content_landed", VerifyResult.PASS,
                         {"method": "ancestry"}, "soredium")
        assert v.check == "content_landed"
        assert v.result == VerifyResult.PASS
        assert v.evidence == {"method": "ancestry"}
        assert v.repo == "soredium"

    def test_frozen(self):
        v = Verification("test", VerifyResult.PASS, {}, "repo")
        with pytest.raises(AttributeError):
            v.check = "other"


class TestComposeVerifications:
    def test_all_pass(self):
        v1 = Verification("a", VerifyResult.PASS, {"k": "1"}, "r")
        v2 = Verification("b", VerifyResult.PASS, {"k": "2"}, "r")
        result = compose_verifications("composite", v1, v2)
        assert result.result == VerifyResult.PASS
        assert result.check == "composite"
        assert "a" in result.evidence
        assert "b" in result.evidence

    def test_fail_wins_over_unknown(self):
        v1 = Verification("a", VerifyResult.UNKNOWN, {"reason": "x"}, "r")
        v2 = Verification("b", VerifyResult.FAIL, {"diff": "y"}, "r")
        result = compose_verifications("composite", v1, v2)
        assert result.result == VerifyResult.FAIL
        assert result.evidence["a"]["result"] == "unknown"
        assert result.evidence["b"]["result"] == "fail"

    def test_unknown_wins_over_pass(self):
        v1 = Verification("a", VerifyResult.PASS, {}, "r")
        v2 = Verification("b", VerifyResult.UNKNOWN, {"reason": "x"}, "r")
        result = compose_verifications("composite", v1, v2)
        assert result.result == VerifyResult.UNKNOWN

    def test_preserves_all_evidence(self):
        v1 = Verification("push", VerifyResult.UNKNOWN,
                          {"reason": "remote_unreachable"}, "repo")
        v2 = Verification("content", VerifyResult.FAIL,
                          {"diff_files": ["a.py"]}, "repo")
        result = compose_verifications("land", v1, v2)
        assert result.evidence["push"]["evidence"]["reason"] == "remote_unreachable"
        assert result.evidence["content"]["evidence"]["diff_files"] == ["a.py"]


class TestVerificationToFindings:
    def test_pass_returns_empty(self):
        v = Verification("check", VerifyResult.PASS, {}, "r")
        assert verification_to_findings(v) == []

    def test_fail_returns_error(self):
        v = Verification("content_landed", VerifyResult.FAIL,
                         {"diff_files": ["a.py"]}, "r")
        findings = verification_to_findings(v)
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert findings[0].category == "content_landed"

    def test_unknown_returns_warn(self):
        v = Verification("push", VerifyResult.UNKNOWN,
                         {"reason": "remote_unreachable"}, "r")
        findings = verification_to_findings(v)
        assert len(findings) == 1
        assert findings[0].severity == "WARN"
        assert findings[0].category == "push"


# --- verify_content_landed and verify_push tests ---

from pathlib import Path
from unittest.mock import patch, MagicMock
from verification.outcomes import verify_content_landed, verify_push


class TestVerifyContentLanded:
    def test_pass_via_ancestry(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="")
            result = verify_content_landed(tmp_path, "abc123", "main")
            assert result.result == VerifyResult.PASS
            assert result.check == "content_landed"

    def test_unknown_no_sha(self, tmp_path):
        result = verify_content_landed(tmp_path, "", "main")
        assert result.result == VerifyResult.UNKNOWN
        assert "no_landed_sha" in result.evidence.get("reason", "")

    def test_fail_with_diff(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            def git_side_effect(path, *args, **kwargs):
                if args[0] == "merge-base":
                    return MagicMock(returncode=1, stdout="")
                if args[0] == "diff" and "--name-only" in args:
                    return MagicMock(returncode=0, stdout="file.py\n")
                if args[0] == "diff":
                    return MagicMock(returncode=0,
                                    stdout="--- a/file.py\n+++ b/file.py\n")
                return MagicMock(returncode=0, stdout="")
            mock_git.side_effect = git_side_effect
            result = verify_content_landed(tmp_path, "abc123", "main")
            assert result.result == VerifyResult.FAIL

    def test_pass_via_empty_diff(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            def git_side_effect(path, *args, **kwargs):
                if args[0] == "merge-base":
                    return MagicMock(returncode=1, stdout="")
                return MagicMock(returncode=0, stdout="")
            mock_git.side_effect = git_side_effect
            result = verify_content_landed(tmp_path, "abc123", "main")
            assert result.result == VerifyResult.PASS


class TestVerifyPush:
    def test_pass_no_unpushed(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="")
            result = verify_push(tmp_path, "main")
            assert result.result == VerifyResult.PASS

    def test_fail_with_unpushed(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0,
                                              stdout="abc123 commit msg\n")
            result = verify_push(tmp_path, "main")
            assert result.result == VerifyResult.FAIL

    def test_unknown_remote_unreachable(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=128, stdout="",
                                              stderr="fatal: couldn't find remote ref")
            result = verify_push(tmp_path, "main")
            assert result.result == VerifyResult.UNKNOWN


from verification.outcomes import (
    verify_rebase, verify_branch_stamped, verify_artifacts_promoted,
)


class TestVerifyRebase:
    def test_pass(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0)
            result = verify_rebase(tmp_path, "feature", "main")
            assert result.result == VerifyResult.PASS

    def test_fail(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=1, stderr="")
            result = verify_rebase(tmp_path, "feature", "main")
            assert result.result == VerifyResult.FAIL

    def test_unknown_no_branch(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=128,
                stderr="fatal: Not a valid object name")
            result = verify_rebase(tmp_path, "nonexistent", "main")
            assert result.result == VerifyResult.UNKNOWN


class TestVerifyBranchStamped:
    def test_pass_with_sha(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            def side_effect(path, *args, **kw):
                if args[0] == "log":
                    return MagicMock(returncode=0,
                        stdout="chore: branch closed — landed as abc123 on main\n")
                if args[0] == "merge-base":
                    return MagicMock(returncode=0)
                return MagicMock(returncode=0, stdout="")
            mock_git.side_effect = side_effect
            result = verify_branch_stamped(tmp_path, "feature", "main")
            assert result.result == VerifyResult.PASS

    def test_fail_no_stamp(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0,
                stdout="feat: add something\nfix: repair thing\n")
            result = verify_branch_stamped(tmp_path, "feature", "main")
            assert result.result == VerifyResult.FAIL

    def test_unknown_sha_not_on_base(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            def side_effect(path, *args, **kw):
                if args[0] == "log":
                    return MagicMock(returncode=0,
                        stdout="chore: branch closed — landed as abc123 on main\n")
                if args[0] == "merge-base":
                    return MagicMock(returncode=1)
                return MagicMock(returncode=0, stdout="")
            mock_git.side_effect = side_effect
            result = verify_branch_stamped(tmp_path, "feature", "main")
            assert result.result == VerifyResult.UNKNOWN


class TestVerifyArtifactsPromoted:
    def test_pass_stamp_exists(self, tmp_path):
        (tmp_path / ".artifacts-promoted").touch()
        result = verify_artifacts_promoted(tmp_path, tmp_path, "feature", "main")
        assert result.result == VerifyResult.PASS

    def test_pass_no_diff(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="")
            result = verify_artifacts_promoted(tmp_path, tmp_path, "feature", "main")
            assert result.result == VerifyResult.PASS

    def test_fail_no_evidence(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            def side_effect(path, *args, **kw):
                if args[0] == "log":
                    return MagicMock(returncode=0, stdout="")
                if args[0] == "diff":
                    return MagicMock(returncode=0, stdout="file.md | 2 +-\n")
                return MagicMock(returncode=0, stdout="")
            mock_git.side_effect = side_effect
            result = verify_artifacts_promoted(tmp_path, tmp_path, "feature", "main")
            assert result.result == VerifyResult.FAIL


from verification.outcomes import (
    verify_checkout_main, verify_landed_marker, verify_slot_phase_complete,
    verify_fork_next, verify_checkout_fork, verify_cleanup_scaffold,
    verify_promote_plan_next, verify_issues_closed,
)


class TestVerifyCheckoutMain:
    def test_pass(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="main\n")
            result = verify_checkout_main(tmp_path, tmp_path)
            assert result.result == VerifyResult.PASS

    def test_fail(self, tmp_path):
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="feature\n")
            result = verify_checkout_main(tmp_path, tmp_path)
            assert result.result == VerifyResult.FAIL


    def test_extra_repos_all_on_main(self, tmp_path):
        """#476: extra slot repos should be checked."""
        peer = tmp_path / "peer"
        peer.mkdir()
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="main\n")
            result = verify_checkout_main(tmp_path, tmp_path, extra_repos=[peer])
            assert result.result == VerifyResult.PASS
            assert result.evidence.get("count") == 3

    def test_extra_repo_on_feature_branch(self, tmp_path):
        """#476: peer repo on feature branch should fail verification."""
        peer = tmp_path / "peer"
        peer.mkdir()
        calls = []
        def mock_git_fn(repo, *args):
            calls.append(repo)
            if repo == peer:
                return MagicMock(returncode=0, stdout="feature\n")
            return MagicMock(returncode=0, stdout="main\n")
        with patch("verification.outcomes._git", side_effect=mock_git_fn):
            result = verify_checkout_main(tmp_path, tmp_path, extra_repos=[peer])
            assert result.result == VerifyResult.FAIL
            assert result.evidence.get("repo") == "peer"

    def test_extra_repo_nonexistent_skipped(self, tmp_path):
        """#476: non-existent extra repos should be skipped."""
        missing = tmp_path / "missing"
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="main\n")
            result = verify_checkout_main(tmp_path, tmp_path, extra_repos=[missing])
            assert result.result == VerifyResult.PASS


class TestVerifyLandedMarker:
    def test_pass(self, tmp_path):
        (tmp_path / ".landed").write_text("landed_shas=repo:abc123\n")
        result = verify_landed_marker(tmp_path)
        assert result.result == VerifyResult.PASS

    def test_fail_missing(self, tmp_path):
        result = verify_landed_marker(tmp_path)
        assert result.result == VerifyResult.FAIL

    def test_fail_empty_shas(self, tmp_path):
        (tmp_path / ".landed").write_text("landed_shas=\n")
        result = verify_landed_marker(tmp_path)
        assert result.result == VerifyResult.FAIL


class TestVerifySlotPhaseComplete:
    def test_pass(self, tmp_path):
        (tmp_path / ".phase-a-complete").touch()
        result = verify_slot_phase_complete(tmp_path, ".phase-a-complete")
        assert result.result == VerifyResult.PASS

    def test_fail(self, tmp_path):
        result = verify_slot_phase_complete(tmp_path, ".phase-a-complete")
        assert result.result == VerifyResult.FAIL


class TestVerifyForkNext:
    def test_pass(self, tmp_path):
        progress = {"fork_next_branch": "issue-999-next"}
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0,
                                              stdout="  issue-999-next\n")
            result = verify_fork_next(tmp_path, progress)
            assert result.result == VerifyResult.PASS

    def test_fail_no_branch(self, tmp_path):
        progress = {"fork_next_branch": "issue-999-next"}
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="")
            result = verify_fork_next(tmp_path, progress)
            assert result.result == VerifyResult.FAIL


class TestVerifyCheckoutFork:
    def test_pass(self, tmp_path):
        progress = {"fork_next_branch": "issue-999-next"}
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0,
                                              stdout="issue-999-next\n")
            result = verify_checkout_fork(tmp_path, progress)
            assert result.result == VerifyResult.PASS

    def test_fail(self, tmp_path):
        progress = {"fork_next_branch": "issue-999-next"}
        with patch("verification.outcomes._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="main\n")
            result = verify_checkout_fork(tmp_path, progress)
            assert result.result == VerifyResult.FAIL


class TestVerifyCleanupScaffold:
    def test_pass(self, tmp_path):
        result = verify_cleanup_scaffold(tmp_path)
        assert result.result == VerifyResult.PASS

    def test_fail_remaining(self, tmp_path):
        (tmp_path / "JOURNAL.md").touch()
        result = verify_cleanup_scaffold(tmp_path)
        assert result.result == VerifyResult.FAIL


class TestVerifyPromotePlanNext:
    def test_pass(self, tmp_path):
        result = verify_promote_plan_next(tmp_path)
        assert result.result == VerifyResult.PASS

    def test_fail(self, tmp_path):
        (tmp_path / ".plan-next").touch()
        result = verify_promote_plan_next(tmp_path)
        assert result.result == VerifyResult.FAIL


class TestVerifyIssuesClosed:
    def test_pass_no_covers(self):
        result = verify_issues_closed("", "", None)
        assert result.result == VerifyResult.PASS

    def test_unknown_gh_fails(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="",
                                              stderr="auth required")
            result = verify_issues_closed("Hortora/soredium", "42", None)
            assert result.result == VerifyResult.UNKNOWN
