"""Tests for work-slot/slot_metadata.py"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_metadata
from slot_test_helpers import init_repo, init_repo_with_workspace, init_repo_with_remote


def _create_merge_test_repos(tmp_path, repo_names):
    """Create a test family with clone-based slots for merge testing."""
    import slot_git
    family = tmp_path / "family"
    family.mkdir()
    slots_dir = family / "slots"
    slots_dir.mkdir()

    originals = {}
    for name in repo_names:
        originals[name] = init_repo_with_remote(family / name)
        slot_git.configure_update_instead(originals[name])

    slot = slots_dir / "1"
    slot.mkdir()
    branch = "issue-42-test"

    for name in repo_names:
        clone_dest = slot / name
        bare_path = family / f".{name}-bare.git"
        subprocess.run([
            "git", "clone", "--shared", "--branch", "main",
            str(originals[name]), str(clone_dest),
        ], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dest), "config", "user.email", "test@test.com"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dest), "checkout", "-b", branch], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "remote", "rename", "origin", "local"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "remote", "add", "origin", str(bare_path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "fetch", "origin"], capture_output=True)
        (clone_dest / "feature.py").write_text(f"# {name} feature\n")
        subprocess.run(["git", "-C", str(clone_dest), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "commit", "-m", f"feat: {name} feature"], capture_output=True, check=True)

    (slot / ".phase-a-complete").write_text(
        f"branch={branch}\nrepos={','.join(repo_names)}\ntimestamp=2026-07-18T14:32:00\n"
    )
    (slot / ".slot").write_text(
        f"# Slot 1 — {branch}\n\n## Issue\ntest/repo#42\nCovers: 42\n\n"
        f"## What to do\nTest\n\n## Repos\n" +
        "\n".join(f"- {n}" for n in repo_names) + "\n"
    )
    return family, originals, slot, branch


class TestWriteSlotMd:
    def test_writes_slot_md(self, tmp_path):
        slot_metadata.write_slot_md(
            tmp_path, 1, ["engine"], "issue-42-spi",
            "42", "casehubio/engine", "42", "Add SPI layer",
        )
        content = (tmp_path / ".slot").read_text()
        assert "# Slot 1" in content
        assert "issue-42-spi" in content
        assert "casehubio/engine#42" in content
        assert "Add SPI layer" in content
        assert "engine (primary)" in content

    def test_multi_repo_slot(self, tmp_path):
        slot_metadata.write_slot_md(
            tmp_path, 2, ["engine", "iot"], "issue-55-cross",
            "55", "casehubio/engine", "55,56", "Cross-repo work",
        )
        content = (tmp_path / ".slot").read_text()
        assert "engine (primary)" in content
        assert "- iot" in content
        assert "55,56" in content


class TestWriteSlotMdIsolation:
    def test_write_with_isolation(self, tmp_path):
        slot_metadata.write_slot_md(
            tmp_path, 7, ["soredium"], "issue-42-fix", "42",
            "Hortora/soredium", "42", "Fix scoring",
            isolation_type="isx", isx_instance="issue-42-fix",
            isx_template="tpl-java",
        )
        content = (tmp_path / ".slot").read_text()
        assert "## Isolation" in content
        assert "type: isx" in content
        assert "instance: issue-42-fix" in content
        assert "template: tpl-java" in content

    def test_write_without_isolation(self, tmp_path):
        slot_metadata.write_slot_md(
            tmp_path, 7, ["soredium"], "issue-42-fix", "42",
            "Hortora/soredium", "42", "Fix scoring",
        )
        content = (tmp_path / ".slot").read_text()
        assert "## Isolation" not in content

    def test_write_isolation_roundtrip(self, tmp_path):
        slot_metadata.write_slot_md(
            tmp_path, 7, ["soredium"], "issue-42-fix", "42",
            "Hortora/soredium", "42", "Fix scoring",
            isolation_type="isx", isx_instance="issue-42-fix",
            isx_template="tpl-java",
        )
        result = slot_metadata.parse_slot_md(tmp_path)
        assert result["isolation_type"] == "isx"
        assert result["isx_instance"] == "issue-42-fix"
        assert result["isx_template"] == "tpl-java"
        assert result["repos"] == ["soredium"]


class TestParseSlotMd:
    def test_parses_full_slot_md(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — issue-42-spi\n\n## Issue\ncasehubio/engine#42\n"
            "Covers: 42\n\n## What to do\nImplement SPI\n\n## Repos\n- engine (primary)\n- iot\n"
        )
        md = slot_metadata.parse_slot_md(tmp_path)
        assert md["branch"] == "issue-42-spi"
        assert md["issue"] == "42"
        assert md["issue_repo"] == "casehubio/engine"
        assert md["covers"] == "42"
        assert md["context"] == "Implement SPI"
        assert md["repos"] == ["engine", "iot"]

    def test_detects_epic_type(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — issue-50-profiles\n\n## Issue\n"
            "casehubio/engine#50\nCovers: 108\nType: epic\n"
            "Safe exit: after any completed batch\n\n"
            "## What to do\nEpic work\n\n## Repos\n- engine\n"
        )
        md = slot_metadata.parse_slot_md(tmp_path)
        assert md["is_epic"] is True
        assert md["issue"] == "50"
        assert md["issue_repo"] == "casehubio/engine"

    def test_non_epic_defaults_false(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — issue-42-spi\n\n## Issue\n"
            "casehubio/engine#42\nCovers: 42\n\n"
            "## What to do\nSPI work\n\n## Repos\n- engine\n"
        )
        md = slot_metadata.parse_slot_md(tmp_path)
        assert md.get("is_epic") is False

    def test_missing_slot_md(self, tmp_path):
        assert slot_metadata.parse_slot_md(tmp_path) == {}


class TestParseSlotMdIsolation:
    def test_parse_with_isolation_section(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 7 — issue-42-fix\n\n"
            "## Issue\nHortora/soredium#42\nCovers: 42\n\n"
            "## What to do\nFix scoring\n\n"
            "## Repos\n- soredium (primary)\n\n"
            "## Isolation\ntype: isx\ninstance: issue-42-fix\n"
            "template: tpl-java\n\n"
            "## Created\n2026-08-12, branch: issue-42-fix\n"
        )
        result = slot_metadata.parse_slot_md(tmp_path)
        assert result["isolation_type"] == "isx"
        assert result["isx_instance"] == "issue-42-fix"
        assert result["isx_template"] == "tpl-java"

    def test_parse_without_isolation_section(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 7 — issue-42-fix\n\n"
            "## Issue\nHortora/soredium#42\nCovers: 42\n\n"
            "## Repos\n- soredium (primary)\n\n"
            "## Created\n2026-08-12, branch: issue-42-fix\n"
        )
        result = slot_metadata.parse_slot_md(tmp_path)
        assert result["isolation_type"] == ""
        assert result["isx_instance"] == ""
        assert result["isx_template"] == ""

    def test_parse_isolation_preserves_existing_fields(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 7 — issue-42-fix\n\n"
            "## Issue\nHortora/soredium#42\nCovers: 42\n\n"
            "## What to do\nFix scoring\n\n"
            "## Repos\n- soredium (primary)\n\n"
            "## Isolation\ntype: isx\ninstance: issue-42-fix\n"
            "template: tpl-java\n\n"
            "## Created\n2026-08-12, branch: issue-42-fix\n"
        )
        result = slot_metadata.parse_slot_md(tmp_path)
        assert result["repos"] == ["soredium"]
        assert result["issue"] == "42"


class TestSlotDescription:
    def test_write_includes_description(self, tmp_path):
        slot_metadata.write_slot_md(
            tmp_path, 1, ["engine"], "issue-42-spi",
            "42", "casehubio/engine", "42", "Add SPI layer",
            description="Implement the SPI extraction for engine module separation.",
        )
        content = (tmp_path / ".slot").read_text()
        assert "## Description" in content
        assert "SPI extraction" in content

    def test_write_without_description_omits_section(self, tmp_path):
        slot_metadata.write_slot_md(
            tmp_path, 1, ["engine"], "issue-42-spi",
            "42", "casehubio/engine", "42", "Add SPI layer",
        )
        content = (tmp_path / ".slot").read_text()
        assert "## Description" not in content

    def test_parse_reads_description(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — issue-42-spi\n\n"
            "## Issue\ncasehubio/engine#42\nCovers: 42\n\n"
            "## Description\nImplement SPI extraction for module separation.\n"
            "This enables independent deployment of engine consumers.\n\n"
            "## What to do\nAdd SPI layer\n\n"
            "## Repos\n- engine (primary)\n"
        )
        result = slot_metadata.parse_slot_md(tmp_path)
        assert "SPI extraction" in result.get("description", "")
        assert "independent deployment" in result.get("description", "")

    def test_parse_empty_description(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — issue-42-spi\n\n"
            "## Issue\ncasehubio/engine#42\nCovers: 42\n\n"
            "## What to do\nAdd SPI layer\n\n"
            "## Repos\n- engine (primary)\n"
        )
        result = slot_metadata.parse_slot_md(tmp_path)
        assert result.get("description", "") == ""


class TestIsSlotLanded:
    def test_true_with_landed_marker(self, tmp_path):
        (tmp_path / ".landed").write_text("branch=test\n")
        assert slot_metadata.is_slot_landed(tmp_path) is True

    def test_false_without_landed_marker(self, tmp_path):
        assert slot_metadata.is_slot_landed(tmp_path) is False

    def test_stamp_commit_alone_is_not_sufficient(self, tmp_path):
        repo = tmp_path / "engine"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: /fake")
        assert slot_metadata.is_slot_landed(tmp_path) is False


class TestVerifyLandedShas:
    def test_passes_when_sha_on_main(self, tmp_path):
        import slot_lifecycle
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        ok, failures = slot_metadata.verify_landed_shas(slot, family)
        assert ok is True
        assert failures == []

    def test_fails_when_sha_not_on_main(self, tmp_path):
        from slot_core import run_cmd
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        rc, sha, _ = run_cmd(
            ["git", "-C", str(slot / "engine"), "rev-parse", "HEAD"]
        )
        (slot / ".landed").write_text(
            f"branch=issue-42-test\nrepos=engine\nlanded_shas=engine:{sha.strip()}\n"
        )

        ok, failures = slot_metadata.verify_landed_shas(slot, family)
        assert ok is False
        assert len(failures) == 1
        assert "not reachable from main" in failures[0]

    def test_fails_with_no_landed_marker(self, tmp_path):
        ok, failures = slot_metadata.verify_landed_shas(tmp_path, tmp_path)
        assert ok is False
        assert "no .landed marker" in failures[0]

    def test_fails_with_unknown_sha(self, tmp_path):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        (slot / ".landed").write_text(
            "branch=issue-42-test\nrepos=engine\nlanded_shas=engine:unknown\n"
        )

        ok, failures = slot_metadata.verify_landed_shas(slot, family)
        assert ok is False
        assert "unknown" in failures[0]


class TestReadPromotionStamp:
    """Tests for _read_promotion_stamp helper."""

    def test_reads_stamp_counts(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        repo = slot / "engine"
        (repo / "design").mkdir(parents=True)
        (repo / "design" / ".artifacts-promoted").write_text(
            "timestamp=2026-08-01T00:00:00\n"
            "branch=issue-42\n"
            "workspace_promoted=2\n"
            "project_promoted=1\n"
            "issues_closed=3\n"
            "blog_published=1\n"
            "plans_archived=2\n"
        )
        promoted, published, dest = slot_metadata._read_promotion_stamp(slot)
        assert "workspace:2" in promoted
        assert "project:1" in promoted
        assert "plans:2" in promoted
        assert "blog:1" in published

    def test_no_stamp(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        (slot / "engine").mkdir()
        promoted, published, dest = slot_metadata._read_promotion_stamp(slot)
        assert promoted == []
        assert published == []

    def test_zero_counts_excluded(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        repo = slot / "engine"
        (repo / "design").mkdir(parents=True)
        (repo / "design" / ".artifacts-promoted").write_text(
            "workspace_promoted=0\n"
            "project_promoted=0\n"
            "blog_published=0\n"
            "plans_archived=0\n"
        )
        promoted, published, _ = slot_metadata._read_promotion_stamp(slot)
        assert promoted == []
        assert published == []


class TestArchiveSlotCheckboxFix:
    """Tests for _fix_stale_checkboxes."""

    def test_fixes_stale_checkboxes(self, tmp_path):
        slot_dir = tmp_path / "slots" / "72"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot 72\n\n## Issue\norg/repo#50\nCovers: 83,84\nType: epic\n\n"
            "## Batch Plan\n\n### Batch 1 — Work\n"
            "- [ ] #83 — Task A\n- [x] #84 — Task B\n"
        )
        slot_metadata._fix_stale_checkboxes(slot_dir / ".slot", [83])
        content = (slot_dir / ".slot").read_text()
        assert "- [x] #83" in content
        assert "- [x] #84" in content

    def test_no_fix_needed(self, tmp_path):
        slot_dir = tmp_path / "slots" / "72"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot 72\n\n## Issue\norg/repo#50\nType: epic\n\n"
            "## Batch Plan\n\n### Batch 1 — Work\n"
            "- [x] #83 — Task A\n"
        )
        fixed = slot_metadata._fix_stale_checkboxes(slot_dir / ".slot", [83])
        assert fixed == 0

    def test_only_fixes_listed_issues(self, tmp_path):
        slot_dir = tmp_path / "slots" / "72"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot 72\n\n## Issue\norg/repo#50\nType: epic\n\n"
            "## Batch Plan\n\n### Batch 1 — Work\n"
            "- [ ] #83 — Task A\n- [ ] #84 — Task B\n"
        )
        slot_metadata._fix_stale_checkboxes(slot_dir / ".slot", [83])
        content = (slot_dir / ".slot").read_text()
        assert "- [x] #83" in content
        assert "- [ ] #84" in content
