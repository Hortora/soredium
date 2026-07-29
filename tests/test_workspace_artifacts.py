"""Tests for work-end/workspace_artifacts.py"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))

from workspace_artifacts import scan


# ── Fixture builders ──────────────────────────────────────────────
# Each creates a realistic directory tree in tmp_path and returns it.
# No absolute paths — everything relative to the tmp root.

def build_single_repo_workspace(root: Path) -> Path:
    """Flat workspace (e.g. cc-praxis for soredium).

    Layout:
        root/
          specs/        <- flat, files directly here
            2026-06-17-design.md
            2026-07-28-epic-design.md
          adr/
            0001-doc-completeness.md
            INDEX.md     <- excluded from scan
          blog/
            2026-07-29-entry.md
            INDEX.md
          plans/
            2026-07-29-plan.md
            INDEX.md
            attic/       <- excluded from scan
              issue-87/
                archived-plan.md
          snapshots/
            2026-07-01-snapshot.md
            INDEX.md
          design/
            .meta
            JOURNAL.md
    """
    (root / "specs").mkdir()
    (root / "specs" / "2026-06-17-design.md").write_text("# Design\n")
    (root / "specs" / "2026-07-28-epic-design.md").write_text("# Epic\n")

    (root / "adr").mkdir()
    (root / "adr" / "0001-doc-completeness.md").write_text("# ADR\n")
    (root / "adr" / "INDEX.md").write_text("# Index\n")

    (root / "blog").mkdir()
    (root / "blog" / "2026-07-29-entry.md").write_text("# Blog\n")
    (root / "blog" / "INDEX.md").write_text("# Index\n")

    (root / "plans").mkdir()
    (root / "plans" / "2026-07-29-plan.md").write_text("# Plan\n")
    (root / "plans" / "INDEX.md").write_text("# Index\n")
    (root / "plans" / "attic" / "issue-87").mkdir(parents=True)
    (root / "plans" / "attic" / "issue-87" / "archived-plan.md").write_text("old")

    (root / "snapshots").mkdir()
    (root / "snapshots" / "2026-07-01-snapshot.md").write_text("# Snap\n")
    (root / "snapshots" / "INDEX.md").write_text("# Index\n")

    (root / "design").mkdir()
    (root / "design" / ".meta").write_text("issue: 112\n")
    (root / "design" / "JOURNAL.md").write_text("# Journal\n")

    return root


def build_multi_repo_workspace_subdir(root: Path) -> Path:
    """Per-repo subdirectory of a multi-repo workspace (e.g. casehub/blocks).

    The wksp symlink resolves to this subdirectory, so scan() sees it
    as a flat workspace — same shape as single-repo from scan()'s POV.

    Layout:
        root/           <- this IS the per-repo subdir (e.g. casehub/blocks/)
          specs/
            2026-05-14-spi-design.md
          adr/
            0001-decision.md
            INDEX.md
          blog/
            2026-05-10-entry.md
          plans/
            2026-05-09-plan.md
          snapshots/
            2026-05-12-snapshot.md
          design/
            .meta
    """
    (root / "specs").mkdir()
    (root / "specs" / "2026-05-14-spi-design.md").write_text("# Spec\n")

    (root / "adr").mkdir()
    (root / "adr" / "0001-decision.md").write_text("# ADR\n")
    (root / "adr" / "INDEX.md").write_text("# Index\n")

    (root / "blog").mkdir()
    (root / "blog" / "2026-05-10-entry.md").write_text("# Blog\n")

    (root / "plans").mkdir()
    (root / "plans" / "2026-05-09-plan.md").write_text("# Plan\n")

    (root / "snapshots").mkdir()
    (root / "snapshots" / "2026-05-12-snapshot.md").write_text("# Snap\n")

    (root / "design").mkdir()
    (root / "design" / ".meta").write_text("issue: 50\n")

    return root


def build_slot_workspace(root: Path) -> Path:
    """Workspace worktree inside a slot (e.g. worktrees/1/cc-praxis).

    Same internal structure — scan() doesn't care that the root is
    inside a worktrees/ directory. The structure is identical to
    single-repo because wksp was repointed by slot_manager.

    Layout:
        root/           <- the workspace worktree root
          specs/
            2026-07-20-slot-spec.md
          adr/
            0002-slot-decision.md
          blog/
            2026-07-20-slot-entry.md
          plans/
            (empty — no plans in this slot session)
          snapshots/
            (none)
          design/
            .meta
    """
    (root / "specs").mkdir()
    (root / "specs" / "2026-07-20-slot-spec.md").write_text("# Slot Spec\n")

    (root / "adr").mkdir()
    (root / "adr" / "0002-slot-decision.md").write_text("# ADR\n")

    (root / "blog").mkdir()
    (root / "blog" / "2026-07-20-slot-entry.md").write_text("# Blog\n")

    (root / "plans").mkdir()

    (root / "design").mkdir()
    (root / "design" / ".meta").write_text("issue: 99\n")

    return root


def build_empty_workspace(root: Path) -> Path:
    """Workspace with no artifact directories at all."""
    return root


# ── Tests ─────────────────────────────────────────────────────────

class TestScanSingleRepo:
    def test_finds_all_artifact_types(self, tmp_path):
        ws = build_single_repo_workspace(tmp_path)
        result = scan(ws)

        assert result["specs"] == [
            "specs/2026-06-17-design.md",
            "specs/2026-07-28-epic-design.md",
        ]
        assert result["adr"] == ["adr/0001-doc-completeness.md"]
        assert result["blog"] == ["blog/2026-07-29-entry.md"]
        assert result["plans"] == ["plans/2026-07-29-plan.md"]
        assert result["snapshots"] == ["snapshots/2026-07-01-snapshot.md"]

    def test_excludes_index_md_from_all_categories(self, tmp_path):
        ws = build_single_repo_workspace(tmp_path)
        result = scan(ws)
        for category, paths in result.items():
            assert not any("INDEX.md" in p for p in paths), \
                f"INDEX.md found in {category}: {paths}"

    def test_excludes_plans_attic(self, tmp_path):
        ws = build_single_repo_workspace(tmp_path)
        result = scan(ws)
        assert not any("attic" in p for p in result["plans"]), \
            f"attic content found in plans: {result['plans']}"


class TestScanMultiRepoSubdir:
    def test_finds_artifacts_in_per_repo_subdir(self, tmp_path):
        ws = build_multi_repo_workspace_subdir(tmp_path)
        result = scan(ws)

        assert result["specs"] == ["specs/2026-05-14-spi-design.md"]
        assert result["adr"] == ["adr/0001-decision.md"]
        assert result["blog"] == ["blog/2026-05-10-entry.md"]
        assert result["plans"] == ["plans/2026-05-09-plan.md"]
        assert result["snapshots"] == ["snapshots/2026-05-12-snapshot.md"]


class TestScanSlotWorkspace:
    def test_finds_artifacts_in_worktree(self, tmp_path):
        ws = build_slot_workspace(tmp_path)
        result = scan(ws)

        assert result["specs"] == ["specs/2026-07-20-slot-spec.md"]
        assert result["adr"] == ["adr/0002-slot-decision.md"]
        assert result["blog"] == ["blog/2026-07-20-slot-entry.md"]
        assert result["plans"] == []
        assert result["snapshots"] == []

    def test_worktree_nested_in_deep_path(self, tmp_path):
        """Scan works regardless of how deep the workspace root is."""
        deep = tmp_path / "family" / "worktrees" / "1" / "cc-praxis"
        deep.mkdir(parents=True)
        ws = build_slot_workspace(deep)
        result = scan(ws)
        assert result["specs"] == ["specs/2026-07-20-slot-spec.md"]


class TestScanEmptyWorkspace:
    def test_returns_empty_lists(self, tmp_path):
        ws = build_empty_workspace(tmp_path)
        result = scan(ws)
        assert result == {
            "specs": [],
            "adr": [],
            "blog": [],
            "plans": [],
            "snapshots": [],
        }


class TestScanEdgeCases:
    def test_non_md_files_in_specs_ignored(self, tmp_path):
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "design.md").write_text("spec")
        (tmp_path / "specs" / "diagram.png").write_bytes(b"\x89PNG")
        (tmp_path / "specs" / ".DS_Store").write_bytes(b"x")

        result = scan(tmp_path)
        assert result["specs"] == ["specs/design.md"]

    def test_non_md_snapshots_included(self, tmp_path):
        """Snapshots can be any file type (diagrams, exports)."""
        (tmp_path / "snapshots").mkdir()
        (tmp_path / "snapshots" / "arch.md").write_text("snap")
        (tmp_path / "snapshots" / "diagram.png").write_bytes(b"\x89PNG")

        result = scan(tmp_path)
        assert len(result["snapshots"]) == 2

    def test_subdirectories_in_artifact_dirs_ignored(self, tmp_path):
        """Only top-level files are scanned, not nested subdirs."""
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "design.md").write_text("spec")
        (tmp_path / "specs" / "subfolder").mkdir()
        (tmp_path / "specs" / "subfolder" / "nested.md").write_text("nested")

        result = scan(tmp_path)
        assert result["specs"] == ["specs/design.md"]

    def test_design_dir_not_scanned_as_artifact(self, tmp_path):
        """design/ contains .meta and JOURNAL.md — not an artifact category."""
        (tmp_path / "design").mkdir()
        (tmp_path / "design" / ".meta").write_text("issue: 1")
        (tmp_path / "design" / "JOURNAL.md").write_text("journal")

        result = scan(tmp_path)
        assert "design" not in result

    def test_scan_returns_sorted_paths(self, tmp_path):
        """Paths within each category are sorted for determinism."""
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "z-spec.md").write_text("z")
        (tmp_path / "specs" / "a-spec.md").write_text("a")
        (tmp_path / "specs" / "m-spec.md").write_text("m")

        result = scan(tmp_path)
        assert result["specs"] == [
            "specs/a-spec.md",
            "specs/m-spec.md",
            "specs/z-spec.md",
        ]
