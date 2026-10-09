"""Tests for project/slot_io.py"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


class TestParseSlot:
    def test_well_formed_slot(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1\n"
            "slug: issue-42-feature\n"
            "title: Test Feature\n"
            "\n"
            "## Issue\n"
            "Hortora/soredium#42\n"
            "Covers: 42,43,44\n"
            "\n"
            "## Description\n"
            "A test description\n"
            "\n"
            "## What to do\n"
            "Build the feature\n"
            "\n"
            "## Repos\n"
            "- platform (primary)\n"
            "- engine\n"
            "- iot\n"
            "\n"
            "## Isolation\n"
            "type: isx\n"
            "instance: isx-1\n"
            "template: tmpl-1\n"
            "\n"
            "## State\n"
            "state: active\n"
        )
        from slot_io import parse_slot

        info = parse_slot(tmp_path)
        assert info is not None
        assert info.repos == ["platform", "engine", "iot"]
        assert info.primary == "platform"
        assert info.branch == "issue-42-feature"
        assert info.title == "Test Feature"
        assert info.description == "A test description"
        assert info.issue == "42"
        assert info.issue_repo == "Hortora/soredium"
        assert info.covers == "42,43,44"
        assert info.is_epic is False
        assert info.isolation_type == "isx"
        assert info.isx_instance == "isx-1"
        assert info.isx_template == "tmpl-1"
        assert info.state == "active"
        assert info.context == "Build the feature"
        assert info.slot_number == 1

    def test_legacy_header_format(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 3 — issue-99-legacy\n"
            "\n"
            "## Issue\n"
            "test/repo#99\n"
            "Covers: 99\n"
            "\n"
            "## Repos\n"
            "- myrepo (primary)\n"
            "\n"
            "## State\n"
            "state: active\n"
        )
        from slot_io import parse_slot

        info = parse_slot(tmp_path)
        assert info is not None
        assert info.branch == "issue-99-legacy"
        assert info.slot_number == 3

    def test_missing_file_returns_none(self, tmp_path):
        from slot_io import parse_slot

        assert parse_slot(tmp_path) is None

    def test_minimal_slot_defaults(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1\n"
            "\n"
            "## Repos\n"
            "- only-repo (primary)\n"
        )
        from slot_io import parse_slot

        info = parse_slot(tmp_path)
        assert info is not None
        assert info.repos == ["only-repo"]
        assert info.primary == "only-repo"
        assert info.branch == ""
        assert info.title == ""
        assert info.state == "active"
        assert info.is_epic is False

    def test_primary_is_always_first(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1\n"
            "\n"
            "## Repos\n"
            "- alpha\n"
            "- beta (primary)\n"
            "- gamma\n"
        )
        from slot_io import parse_slot

        info = parse_slot(tmp_path)
        assert info.primary == "beta"
        assert info.repos[0] == "beta"

    def test_no_dir_scan_contamination(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1\n"
            "\n"
            "## Repos\n"
            "- declared-repo (primary)\n"
        )
        extra = tmp_path / "undeclared-repo"
        extra.mkdir()
        (extra / ".git").mkdir()

        from slot_io import parse_slot

        info = parse_slot(tmp_path)
        assert info.repos == ["declared-repo"]

    def test_epic_type_detected(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1\n"
            "\n"
            "## Issue\n"
            "test/repo#10\n"
            "Type: epic\n"
            "Covers: 10\n"
            "\n"
            "## Repos\n"
            "- repo (primary)\n"
        )
        from slot_io import parse_slot

        info = parse_slot(tmp_path)
        assert info.is_epic is True

    def test_frozen(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1\n\n## Repos\n- r (primary)\n"
        )
        from slot_io import parse_slot

        info = parse_slot(tmp_path)
        with pytest.raises(AttributeError):
            info.state = "archived"


class TestParseLanded:
    def test_old_format(self, tmp_path):
        (tmp_path / ".landed").write_text(
            "landed_shas=engine:abc123,platform:def456\n"
            "issues=42,43\n"
            "branch=issue-42-feature\n"
        )
        from slot_io import parse_landed

        info = parse_landed(tmp_path)
        assert info is not None
        assert info.shas == {"engine": "abc123", "platform": "def456"}
        assert info.has_ledger is False
        assert info.issues == set()
        assert info.branch == "issue-42-feature"
        assert info.failed == ""

    def test_new_ledger_format(self, tmp_path):
        (tmp_path / ".landed").write_text(
            "issue=42 repo=engine sha=abc123\n"
            "issue=43 repo=platform sha=def456\n"
        )
        from slot_io import parse_landed

        info = parse_landed(tmp_path)
        assert info is not None
        assert info.has_ledger is True
        assert info.issues == {42, 43}
        assert info.shas == {"engine": "abc123", "platform": "def456"}

    def test_mixed_format(self, tmp_path):
        (tmp_path / ".landed").write_text(
            "landed_shas=engine:abc123\n"
            "issue=44 repo=platform sha=def456\n"
            "branch=issue-42-feature\n"
        )
        from slot_io import parse_landed

        info = parse_landed(tmp_path)
        assert info.shas == {"engine": "abc123", "platform": "def456"}
        assert info.has_ledger is True
        assert info.issues == {44}

    def test_no_sentinel_in_shas(self, tmp_path):
        (tmp_path / ".landed").write_text(
            "landed_shas=engine:abc123\n"
            "issue=42 repo=platform sha=def456\n"
        )
        from slot_io import parse_landed

        info = parse_landed(tmp_path)
        assert "_has_ledger_entries" not in info.shas

    def test_missing_file_returns_none(self, tmp_path):
        from slot_io import parse_landed

        assert parse_landed(tmp_path) is None

    def test_failed_repos(self, tmp_path):
        (tmp_path / ".landed").write_text(
            "landed_shas=engine:abc123\n"
            "failed=platform,iot\n"
            "branch=issue-42-feature\n"
        )
        from slot_io import parse_landed

        info = parse_landed(tmp_path)
        assert info.failed == "platform,iot"

    def test_frozen(self, tmp_path):
        (tmp_path / ".landed").write_text("landed_shas=e:a\nbranch=b\n")
        from slot_io import parse_landed

        info = parse_landed(tmp_path)
        with pytest.raises(AttributeError):
            info.branch = "new"


class TestDiscoverRepos:
    def test_finds_git_repos(self, tmp_path):
        for name in ["alpha", "beta"]:
            d = tmp_path / name
            d.mkdir()
            (d / ".git").mkdir()
        from slot_io import discover_repos

        result = discover_repos(tmp_path)
        assert result == ["alpha", "beta"]

    def test_excludes_m2_attic(self, tmp_path):
        for name in [".m2", "attic", "real-repo"]:
            d = tmp_path / name
            d.mkdir()
            (d / ".git").mkdir()
        from slot_io import discover_repos

        result = discover_repos(tmp_path)
        assert result == ["real-repo"]

    def test_excludes_workspace_clones(self, tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / ".git").mkdir()
        wsp = tmp_path / "wsp-myrepo"
        wsp.mkdir()
        (wsp / ".git").mkdir()
        (wsp / ".workspace").touch()
        from slot_io import discover_repos

        result = discover_repos(tmp_path)
        assert result == ["myrepo"]

    def test_excludes_non_git_dirs(self, tmp_path):
        (tmp_path / "not-a-repo").mkdir()
        from slot_io import discover_repos

        assert discover_repos(tmp_path) == []


class TestWriteSlot:
    def test_roundtrip(self, tmp_path):
        from slot_io import write_slot, parse_slot

        write_slot(
            tmp_path,
            slot_number=5,
            repos=["platform", "engine"],
            branch="issue-42-feature",
            issue="42",
            issue_repo="Hortora/soredium",
            covers="42,43",
            context="Build it",
            title="My Feature",
            description="A description",
            isolation_type="isx",
            isx_instance="isx-1",
            isx_template="tmpl-1",
        )
        info = parse_slot(tmp_path)
        assert info is not None
        assert info.repos == ["platform", "engine"]
        assert info.primary == "platform"
        assert info.branch == "issue-42-feature"
        assert info.title == "My Feature"
        assert info.description == "A description"
        assert info.issue == "42"
        assert info.issue_repo == "Hortora/soredium"
        assert info.covers == "42,43"
        assert info.isolation_type == "isx"
        assert info.state == "active"


class TestSetSlotState:
    def test_updates_state_field(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1\n\n## State\nstate: active\n"
        )
        from slot_io import set_slot_state, parse_slot

        result = set_slot_state(tmp_path, "archived")
        assert result is True
        assert parse_slot(tmp_path).state == "archived"

    def test_handles_legacy_status_field(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1\n\n## Status\nstatus: active\n"
        )
        from slot_io import set_slot_state, parse_slot

        result = set_slot_state(tmp_path, "paused")
        assert result is True
        assert parse_slot(tmp_path).state == "paused"

    def test_returns_false_when_no_slot(self, tmp_path):
        from slot_io import set_slot_state

        assert set_slot_state(tmp_path, "archived") is False

    def test_adds_state_when_missing(self, tmp_path):
        (tmp_path / ".slot").write_text("# Slot 1\n\n## Repos\n- r\n")
        from slot_io import set_slot_state, parse_slot

        set_slot_state(tmp_path, "paused")
        assert parse_slot(tmp_path).state == "paused"


class TestWriteLanded:
    def test_roundtrip(self, tmp_path):
        from slot_io import write_landed, parse_landed

        write_landed(
            tmp_path,
            shas={"engine": "abc123", "platform": "def456"},
            issues="42,43",
            branch="issue-42-feature",
        )
        info = parse_landed(tmp_path)
        assert info is not None
        assert info.shas == {"engine": "abc123", "platform": "def456"}
        assert info.branch == "issue-42-feature"

    def test_with_failed(self, tmp_path):
        from slot_io import write_landed, parse_landed

        write_landed(
            tmp_path,
            shas={"engine": "abc123"},
            issues="42",
            branch="b",
            failed="platform",
        )
        info = parse_landed(tmp_path)
        assert info.failed == "platform"
