"""Tests for verification/step_postconditions.py — step-level postcondition checks."""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "verification"))


@dataclass
class FakeCtx:
    project: Path
    workspace: Path
    branch: str = "issue-379-test"
    base_branch: str = "main"
    slot_path: Path | None = None
    family_root: Path | None = None
    slot_num: str = ""
    landed_shas: dict = field(default_factory=dict)
    covers: str = ""
    issue_repo: str = ""
    in_slot: bool = False
    on_main: bool = False
    current_repo_project: Path | None = None
    current_repo_workspace: Path | None = None


class TestRebasePostcondition:
    def test_returns_true_when_base_is_ancestor(self, tmp_path):
        from step_postconditions import rebase_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        with patch("step_postconditions._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0)
            assert rebase_postcondition(ctx) is True

    def test_returns_false_when_base_not_ancestor(self, tmp_path):
        from step_postconditions import rebase_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        with patch("step_postconditions._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=1)
            assert rebase_postcondition(ctx) is False

    def test_uses_current_repo_project_when_set(self, tmp_path):
        from step_postconditions import rebase_postcondition
        other = tmp_path / "other"
        other.mkdir()
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path,
                      current_repo_project=other)
        with patch("step_postconditions._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0)
            rebase_postcondition(ctx)
            call_args = mock_git.call_args[0]
            assert call_args[0] == other


class TestPushPostcondition:
    def test_returns_true_when_sha_on_remote(self, tmp_path):
        from step_postconditions import push_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path,
                      landed_shas={tmp_path.name: "abc123"})
        with patch("step_postconditions._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0)
            assert push_postcondition(ctx) is True

    def test_returns_false_when_no_landed_sha(self, tmp_path):
        from step_postconditions import push_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        assert push_postcondition(ctx) is False

    def test_returns_false_when_sha_not_on_remote(self, tmp_path):
        from step_postconditions import push_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path,
                      landed_shas={tmp_path.name: "abc123"})
        with patch("step_postconditions._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=1)
            assert push_postcondition(ctx) is False


class TestStampPostcondition:
    def test_returns_true_when_stamp_with_valid_sha(self, tmp_path):
        from step_postconditions import stamp_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        with patch("step_postconditions._git") as mock_git:
            def side_effect(*args):
                if "log" in args:
                    m = MagicMock(returncode=0)
                    m.stdout = "chore: branch closed — landed as abc123 on main"
                    return m
                if "merge-base" in args:
                    return MagicMock(returncode=0)
                return MagicMock(returncode=0)
            mock_git.side_effect = side_effect
            assert stamp_postcondition(ctx) is True

    def test_returns_false_when_no_stamp(self, tmp_path):
        from step_postconditions import stamp_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        with patch("step_postconditions._git") as mock_git:
            m = MagicMock(returncode=0)
            m.stdout = "feat: some feature"
            mock_git.return_value = m
            assert stamp_postcondition(ctx) is False

    def test_returns_true_for_old_format_stamp(self, tmp_path):
        from step_postconditions import stamp_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        with patch("step_postconditions._git") as mock_git:
            m = MagicMock(returncode=0)
            m.stdout = "chore: branch closed"
            mock_git.return_value = m
            assert stamp_postcondition(ctx) is True

    def test_returns_false_when_branch_not_found(self, tmp_path):
        from step_postconditions import stamp_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        with patch("step_postconditions._git") as mock_git:
            mock_git.return_value = MagicMock(returncode=1)
            assert stamp_postcondition(ctx) is False


class TestPromotePostcondition:
    def test_returns_true_when_stamp_exists(self, tmp_path):
        from step_postconditions import promote_postcondition
        (tmp_path / ".artifacts-promoted").write_text("timestamp=2026-01-01\n")
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        assert promote_postcondition(ctx) is True

    def test_returns_false_when_no_stamp(self, tmp_path):
        from step_postconditions import promote_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        assert promote_postcondition(ctx) is False

    def test_uses_current_repo_workspace(self, tmp_path):
        from step_postconditions import promote_postcondition
        other = tmp_path / "other_ws"
        other.mkdir()
        (other / ".artifacts-promoted").write_text("timestamp=2026-01-01\n")
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path,
                      current_repo_workspace=other)
        assert promote_postcondition(ctx) is True


class TestArchiveMovePostcondition:
    def test_returns_true_when_in_attic(self, tmp_path):
        from step_postconditions import archive_move_postcondition
        family = tmp_path / "family"
        family.mkdir()
        attic = family / "attic" / "42"
        attic.mkdir(parents=True)
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path,
                      slot_path=family / "slots" / "42",
                      family_root=family, slot_num="42")
        assert archive_move_postcondition(ctx) is True

    def test_returns_false_when_still_in_slots(self, tmp_path):
        from step_postconditions import archive_move_postcondition
        family = tmp_path / "family"
        slots = family / "slots" / "42"
        slots.mkdir(parents=True)
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path,
                      slot_path=slots, family_root=family, slot_num="42")
        assert archive_move_postcondition(ctx) is False

    def test_returns_false_when_no_slot_path(self, tmp_path):
        from step_postconditions import archive_move_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        assert archive_move_postcondition(ctx) is False


class TestLandedMarkerPostcondition:
    def test_returns_true_with_populated_shas(self, tmp_path):
        from step_postconditions import landed_marker_postcondition
        slot = tmp_path / "slot"
        slot.mkdir()
        (slot / ".landed").write_text("landed_shas=repo1:abc123,repo2:def456\n")
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path, slot_path=slot)
        assert landed_marker_postcondition(ctx) is True

    def test_returns_false_with_empty_shas(self, tmp_path):
        from step_postconditions import landed_marker_postcondition
        slot = tmp_path / "slot"
        slot.mkdir()
        (slot / ".landed").write_text("landed_shas=\n")
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path, slot_path=slot)
        assert landed_marker_postcondition(ctx) is False

    def test_returns_false_when_no_file(self, tmp_path):
        from step_postconditions import landed_marker_postcondition
        slot = tmp_path / "slot"
        slot.mkdir()
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path, slot_path=slot)
        assert landed_marker_postcondition(ctx) is False

    def test_returns_false_with_empty_sha_value(self, tmp_path):
        from step_postconditions import landed_marker_postcondition
        slot = tmp_path / "slot"
        slot.mkdir()
        (slot / ".landed").write_text("landed_shas=repo1:,repo2:def456\n")
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path, slot_path=slot)
        assert landed_marker_postcondition(ctx) is False


class TestCheckoutMainPostcondition:
    def test_returns_true_when_both_on_main(self, tmp_path):
        from step_postconditions import checkout_main_postcondition
        proj = tmp_path / "proj"
        ws = tmp_path / "ws"
        proj.mkdir()
        ws.mkdir()
        ctx = FakeCtx(project=proj, workspace=ws)
        with patch("step_postconditions._git") as mock_git:
            m = MagicMock(returncode=0)
            m.stdout = "main\n"
            mock_git.return_value = m
            assert checkout_main_postcondition(ctx) is True

    def test_returns_false_when_project_on_branch(self, tmp_path):
        from step_postconditions import checkout_main_postcondition
        proj = tmp_path / "proj"
        ws = tmp_path / "ws"
        proj.mkdir()
        ws.mkdir()
        ctx = FakeCtx(project=proj, workspace=ws)
        with patch("step_postconditions._git") as mock_git:
            m = MagicMock(returncode=0)
            m.stdout = "issue-379\n"
            mock_git.return_value = m
            assert checkout_main_postcondition(ctx) is False


class TestWriteMarkerPostcondition:
    def test_returns_true_when_marker_exists(self, tmp_path):
        from step_postconditions import write_marker_postcondition
        slot = tmp_path / "slot"
        slot.mkdir()
        (slot / ".phase-a-complete").write_text("branch=test\n")
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path, slot_path=slot)
        assert write_marker_postcondition(ctx) is True

    def test_returns_false_when_no_marker(self, tmp_path):
        from step_postconditions import write_marker_postcondition
        slot = tmp_path / "slot"
        slot.mkdir()
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path, slot_path=slot)
        assert write_marker_postcondition(ctx) is False

    def test_returns_false_when_no_slot_path(self, tmp_path):
        from step_postconditions import write_marker_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        assert write_marker_postcondition(ctx) is False


class TestCleanupScaffoldPostcondition:
    def test_returns_true_when_no_scaffold_files(self, tmp_path):
        from step_postconditions import cleanup_scaffold_postcondition
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        assert cleanup_scaffold_postcondition(ctx) is True

    def test_returns_false_when_journal_exists(self, tmp_path):
        from step_postconditions import cleanup_scaffold_postcondition
        (tmp_path / "JOURNAL.md").write_text("# Journal\n")
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        assert cleanup_scaffold_postcondition(ctx) is False

    def test_returns_false_when_execute_progress_exists(self, tmp_path):
        from step_postconditions import cleanup_scaffold_postcondition
        (tmp_path / ".execute-progress").write_text("key=val\n")
        ctx = FakeCtx(project=tmp_path, workspace=tmp_path)
        assert cleanup_scaffold_postcondition(ctx) is False
