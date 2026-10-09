"""Tests for work-slot/slot_metadata.py — retained functions only.

Parsing and writing tests moved to tests/test_slot_io.py (Phase 2, #425).
"""

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

    canonicals = {}
    for name in repo_names:
        canonicals[name] = init_repo_with_remote(family / name)
        slot_git.configure_update_instead(canonicals[name])

    slot = slots_dir / "1"
    slot.mkdir()
    branch = "issue-42-test"

    for name in repo_names:
        clone_dest = slot / name
        bare_path = family / f".{name}-bare.git"
        subprocess.run([
            "git", "clone", "--shared", "--branch", "main",
            str(canonicals[name]), str(clone_dest),
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
    return family, canonicals, slot, branch


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

    def test_passes_when_on_local_main_but_not_pushed(self, tmp_path):
        from slot_core import run_cmd
        from slot_test_helpers import init_repo_with_remote
        family = tmp_path / "family"
        family.mkdir()
        (family / "slots").mkdir()
        original = init_repo_with_remote(family / "engine")
        slot = family / "slots" / "1"
        slot.mkdir()

        (original / "feature.txt").write_text("feature\n")
        run_cmd(["git", "-C", str(original), "add", "."])
        run_cmd(["git", "-C", str(original), "commit", "-m", "feat: feature"])
        _, sha, _ = run_cmd(["git", "-C", str(original), "rev-parse", "HEAD"])
        sha = sha.strip()

        (slot / ".landed").write_text(
            f"branch=issue-42-test\nrepos=engine\nlanded_shas=engine:{sha}\n"
        )
        ok, failures = slot_metadata.verify_landed_shas(slot, family)
        assert ok is True, f"Should pass with local-only SHA, got failures: {failures}"

    def test_passes_squash_merged_content(self, tmp_path):
        from slot_core import run_cmd
        from slot_test_helpers import init_repo_with_remote
        family = tmp_path / "family"
        family.mkdir()
        (family / "slots").mkdir()
        original = init_repo_with_remote(family / "engine")
        slot = family / "slots" / "1"
        slot.mkdir()

        subprocess.run(["git", "-C", str(original), "checkout", "-b", "feature"], capture_output=True, check=True)
        (original / "feat.txt").write_text("feature\n")
        run_cmd(["git", "-C", str(original), "add", "."])
        run_cmd(["git", "-C", str(original), "commit", "-m", "feat: unique-squash-marker-test"])
        _, feature_sha, _ = run_cmd(["git", "-C", str(original), "rev-parse", "HEAD"])
        feature_sha = feature_sha.strip()

        subprocess.run(["git", "-C", str(original), "checkout", "main"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(original), "merge", "--squash", "feature"], capture_output=True, check=True)
        run_cmd(["git", "-C", str(original), "commit", "-m", "feat: unique-squash-marker-test"])

        (slot / ".landed").write_text(
            f"branch=feature\nrepos=engine\nlanded_shas=engine:{feature_sha}\n"
        )
        ok, failures = slot_metadata.verify_landed_shas(slot, family)
        assert ok is True, f"Squash-merged content should pass: {failures}"

    def test_passes_source_diff_empty(self, tmp_path):
        from slot_core import run_cmd
        from slot_test_helpers import init_repo_with_remote
        family = tmp_path / "family"
        family.mkdir()
        (family / "slots").mkdir()
        original = init_repo_with_remote(family / "engine")
        slot = family / "slots" / "1"
        slot.mkdir()

        subprocess.run(["git", "-C", str(original), "checkout", "-b", "feature"], capture_output=True, check=True)
        (original / "Feature.java").write_text("class Feature {}\n")
        run_cmd(["git", "-C", str(original), "add", "."])
        run_cmd(["git", "-C", str(original), "commit", "-m", "feat: add feature"])
        _, feature_sha, _ = run_cmd(["git", "-C", str(original), "rev-parse", "HEAD"])
        feature_sha = feature_sha.strip()

        subprocess.run(["git", "-C", str(original), "checkout", "main"], capture_output=True, check=True)
        (original / "Feature.java").write_text("class Feature {}\n")
        run_cmd(["git", "-C", str(original), "add", "."])
        run_cmd(["git", "-C", str(original), "commit", "-m", "chore: different message"])

        (slot / ".landed").write_text(
            f"branch=feature\nrepos=engine\nlanded_shas=engine:{feature_sha}\n"
        )
        ok, failures = slot_metadata.verify_landed_shas(slot, family)
        assert ok is True, f"Content-equal should pass: {failures}"


class TestReadPromotionStamp:
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
