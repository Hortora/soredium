"""Tests for work-end/workspace_artifacts.py"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))

from workspace_artifacts import scan, extract_image_refs


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

    def test_specs_in_issue_subdirectories_found(self, tmp_path):
        """Specs organized in issue-specific subdirectories must be found."""
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "design.md").write_text("spec")
        issue_dir = tmp_path / "specs" / "issue-273-cloudevent-adapter"
        issue_dir.mkdir()
        (issue_dir / "2026-06-23-adapter-design.md").write_text("nested spec")

        result = scan(tmp_path)
        assert "specs/design.md" in result["specs"]
        assert "specs/issue-273-cloudevent-adapter/2026-06-23-adapter-design.md" in result["specs"]

    def test_blogs_in_subdirectories_found(self, tmp_path):
        """Blog entries in subdirectories must be found."""
        (tmp_path / "blog").mkdir()
        (tmp_path / "blog" / "2026-07-01-entry.md").write_text("top-level")
        sub = tmp_path / "blog" / "2026-07"
        sub.mkdir()
        (sub / "2026-07-15-deep.md").write_text("nested")

        result = scan(tmp_path)
        assert "blog/2026-07-01-entry.md" in result["blog"]
        assert "blog/2026-07/2026-07-15-deep.md" in result["blog"]

    def test_plans_attic_subdirectory_excluded(self, tmp_path):
        """Plans in attic/ subdirectories must still be excluded."""
        (tmp_path / "plans").mkdir()
        (tmp_path / "plans" / "current-plan.md").write_text("plan")
        attic = tmp_path / "plans" / "attic" / "issue-87"
        attic.mkdir(parents=True)
        (attic / "archived-plan.md").write_text("old")

        result = scan(tmp_path)
        assert result["plans"] == ["plans/current-plan.md"]

    def test_adrs_in_docs_adr_found(self, tmp_path):
        """ADRs at docs/adr/ (not just adr/) must be found."""
        docs_adr = tmp_path / "docs" / "adr"
        docs_adr.mkdir(parents=True)
        (docs_adr / "0001-decision.md").write_text("# ADR")
        (docs_adr / "INDEX.md").write_text("# Index")

        result = scan(tmp_path)
        assert result["adr"] == ["docs/adr/0001-decision.md"]

    def test_adrs_from_both_locations_merged(self, tmp_path):
        """If both adr/ and docs/adr/ exist, both are scanned."""
        (tmp_path / "adr").mkdir()
        (tmp_path / "adr" / "0001-top.md").write_text("# ADR")
        docs_adr = tmp_path / "docs" / "adr"
        docs_adr.mkdir(parents=True)
        (docs_adr / "0002-nested.md").write_text("# ADR")

        result = scan(tmp_path)
        assert "adr/0001-top.md" in result["adr"]
        assert "docs/adr/0002-nested.md" in result["adr"]

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


class TestExtractImageRefs:
    def test_markdown_image_extracted(self, tmp_path):
        img = tmp_path / "specs" / "images" / "arch.png"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"\x89PNG")
        md = tmp_path / "specs" / "design.md"
        md.write_text("# Design\n\n![Architecture](images/arch.png)\n")

        result = extract_image_refs(md, tmp_path)
        assert result == ["specs/images/arch.png"]

    def test_html_img_extracted(self, tmp_path):
        img = tmp_path / "blog" / "photo.jpg"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"\xff\xd8")
        md = tmp_path / "blog" / "entry.md"
        md.write_text('<img src="photo.jpg" width="400">\n')

        result = extract_image_refs(md, tmp_path)
        assert result == ["blog/photo.jpg"]

    def test_html_img_single_quotes(self, tmp_path):
        img = tmp_path / "blog" / "photo.jpg"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"\xff\xd8")
        md = tmp_path / "blog" / "entry.md"
        md.write_text("<img src='photo.jpg' alt='test'>\n")

        result = extract_image_refs(md, tmp_path)
        assert result == ["blog/photo.jpg"]

    def test_external_urls_excluded(self, tmp_path):
        md = tmp_path / "blog" / "entry.md"
        md.parent.mkdir(parents=True)
        md.write_text("![Logo](https://example.com/logo.png)\n![Other](http://example.com/other.png)\n")

        result = extract_image_refs(md, tmp_path)
        assert result == []

    def test_template_vars_excluded(self, tmp_path):
        md = tmp_path / "blog" / "entry.md"
        md.parent.mkdir(parents=True)
        md.write_text('<img src="{thumb_src}" alt="thumb">\n')

        result = extract_image_refs(md, tmp_path)
        assert result == []

    def test_protocol_uris_excluded(self, tmp_path):
        md = tmp_path / "blog" / "entry.md"
        md.parent.mkdir(parents=True)
        md.write_text("![Icon](chrome://skype/icon.png)\n![Data](data:image/png;base64,abc)\n")

        result = extract_image_refs(md, tmp_path)
        assert result == []

    def test_missing_image_warned(self, tmp_path, capsys):
        md = tmp_path / "specs" / "design.md"
        md.parent.mkdir(parents=True)
        md.write_text("![Missing](images/gone.png)\n")

        result = extract_image_refs(md, tmp_path)
        assert result == []
        assert "gone.png" in capsys.readouterr().err

    def test_nested_image_paths_preserved(self, tmp_path):
        img = tmp_path / "specs" / "images" / "sub" / "deep.svg"
        img.parent.mkdir(parents=True)
        img.write_text("<svg/>")
        md = tmp_path / "specs" / "design.md"
        md.write_text("![Diagram](images/sub/deep.svg)\n")

        result = extract_image_refs(md, tmp_path)
        assert result == ["specs/images/sub/deep.svg"]

    def test_multiple_refs_in_one_file(self, tmp_path):
        (tmp_path / "blog").mkdir()
        for name in ["a.png", "b.jpg"]:
            (tmp_path / "blog" / name).write_bytes(b"\x00")
        md = tmp_path / "blog" / "entry.md"
        md.write_text("![A](a.png)\n\n![B](b.jpg)\n")

        result = extract_image_refs(md, tmp_path)
        assert sorted(result) == ["blog/a.png", "blog/b.jpg"]

    def test_duplicate_refs_deduplicated(self, tmp_path):
        (tmp_path / "blog").mkdir()
        (tmp_path / "blog" / "logo.png").write_bytes(b"\x00")
        md = tmp_path / "blog" / "entry.md"
        md.write_text("![Logo](logo.png)\n\n![Logo again](logo.png)\n")

        result = extract_image_refs(md, tmp_path)
        assert result == ["blog/logo.png"]


class TestScanImageRefs:
    def test_image_refs_included_in_scan(self, tmp_path):
        (tmp_path / "specs").mkdir()
        img = tmp_path / "specs" / "images" / "arch.svg"
        img.parent.mkdir()
        img.write_text("<svg/>")
        md = tmp_path / "specs" / "design.md"
        md.write_text("# Design\n\n![Architecture](images/arch.svg)\n")

        result = scan(tmp_path)
        assert "specs/design.md" in result["specs"]
        assert "specs/images/arch.svg" in result["specs"]

    def test_image_refs_across_all_categories(self, tmp_path):
        for cat in ("specs", "adr", "blog", "plans"):
            d = tmp_path / cat
            d.mkdir()
            img = d / "photo.png"
            img.write_bytes(b"\x89PNG")
            md = d / "entry.md"
            md.write_text("![Photo](photo.png)\n")

        result = scan(tmp_path)
        for cat in ("specs", "adr", "blog", "plans"):
            assert f"{cat}/photo.png" in result[cat], \
                f"image not found in {cat}: {result[cat]}"

    def test_non_referenced_images_excluded(self, tmp_path):
        (tmp_path / "specs").mkdir()
        (tmp_path / "specs" / "design.md").write_text("# No images\n")
        (tmp_path / "specs" / "orphan.png").write_bytes(b"\x89PNG")

        result = scan(tmp_path)
        assert result["specs"] == ["specs/design.md"]

    def test_snapshots_unchanged(self, tmp_path):
        (tmp_path / "snapshots").mkdir()
        (tmp_path / "snapshots" / "doc.md").write_text("snap")
        (tmp_path / "snapshots" / "diagram.png").write_bytes(b"\x89PNG")

        result = scan(tmp_path)
        assert len(result["snapshots"]) == 2

    def test_image_dedup_across_md_files(self, tmp_path):
        (tmp_path / "specs").mkdir()
        img = tmp_path / "specs" / "shared.png"
        img.write_bytes(b"\x89PNG")
        (tmp_path / "specs" / "a.md").write_text("![X](shared.png)\n")
        (tmp_path / "specs" / "b.md").write_text("![Y](shared.png)\n")

        result = scan(tmp_path)
        assert result["specs"].count("specs/shared.png") == 1
