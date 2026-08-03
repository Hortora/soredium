"""Tests for write-content/resolve_blog_dir.py — blog directory resolution with slot-escape detection."""

import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "write-content"
sys.path.insert(0, str(skill_dir))

slot_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(slot_dir))

import resolve_blog_dir


class TestResolveBlogDir:
    """Test blog directory resolution from CLAUDE.md content."""

    def test_relative_blog_dir(self, tmp_path):
        """Relative Blog directory resolves relative to workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        claude_text = '**Blog directory:** `blog/`'
        result = resolve_blog_dir.resolve(str(workspace), claude_text)
        assert result == str(workspace / "blog")

    def test_absolute_blog_dir_non_slot(self, tmp_path):
        """Absolute Blog directory is used as-is when not in a slot."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        blog_path = tmp_path / "external" / "blog"
        claude_text = f'**Blog directory:** `{blog_path}/`'
        result = resolve_blog_dir.resolve(str(workspace), claude_text)
        assert result == str(blog_path)

    def test_no_blog_dir_field_defaults_to_blog(self, tmp_path):
        """No Blog directory field → defaults to workspace/blog/."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        claude_text = '# Project\n\nSome content.'
        result = resolve_blog_dir.resolve(str(workspace), claude_text)
        assert result == str(workspace / "blog")

    def test_routing_table_blog_to_workspace(self, tmp_path):
        """Routing table 'blog → workspace' resolves to workspace/blog/."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        claude_text = '## Routing\n\n| Artifact | Destination |\n|---|---|\n| blog | workspace |'
        result = resolve_blog_dir.resolve(str(workspace), claude_text)
        assert result == str(workspace / "blog")


class TestSlotEscapeDetection:
    """Test that absolute blog dirs are caught when running inside a slot."""

    def test_absolute_path_in_slot_detected(self, tmp_path):
        """Absolute Blog directory inside a slot → escape detected, falls back to workspace/blog/."""
        slot_workspace = tmp_path / "slots" / "1" / "work"
        slot_workspace.mkdir(parents=True)
        original_blog = "/Users/someone/claude/public/casehub/platform/blog"
        claude_text = f'**Blog directory:** `{original_blog}/`'

        result = resolve_blog_dir.resolve(
            str(slot_workspace), claude_text,
            slot_root=str(tmp_path / "slots" / "1"),
        )
        assert result == str(slot_workspace / "blog")

    def test_absolute_path_inside_slot_is_ok(self, tmp_path):
        """Absolute Blog directory that points INSIDE the slot → no escape, used as-is."""
        slot_root = tmp_path / "slots" / "1"
        slot_workspace = slot_root / "work"
        slot_workspace.mkdir(parents=True)
        blog_inside_slot = slot_workspace / "blog"
        claude_text = f'**Blog directory:** `{blog_inside_slot}/`'

        result = resolve_blog_dir.resolve(
            str(slot_workspace), claude_text,
            slot_root=str(slot_root),
        )
        assert result == str(blog_inside_slot)

    def test_relative_path_in_slot_is_ok(self, tmp_path):
        """Relative Blog directory in slot → resolves inside workspace, no escape."""
        slot_workspace = tmp_path / "slots" / "1" / "work"
        slot_workspace.mkdir(parents=True)
        claude_text = '**Blog directory:** `blog/`'

        result = resolve_blog_dir.resolve(
            str(slot_workspace), claude_text,
            slot_root=str(tmp_path / "slots" / "1"),
        )
        assert result == str(slot_workspace / "blog")

    def test_no_slot_root_skips_escape_check(self, tmp_path):
        """No slot_root → escape check skipped, absolute path used as-is."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        external = tmp_path / "external" / "blog"
        claude_text = f'**Blog directory:** `{external}/`'

        result = resolve_blog_dir.resolve(str(workspace), claude_text)
        assert result == str(external)

    def test_escape_returns_warning(self, tmp_path):
        """Escape detection returns a warning message alongside the fallback path."""
        slot_workspace = tmp_path / "slots" / "1" / "work"
        slot_workspace.mkdir(parents=True)
        original_blog = "/Users/someone/original/blog"
        claude_text = f'**Blog directory:** `{original_blog}/`'

        result, warning = resolve_blog_dir.resolve_with_warning(
            str(slot_workspace), claude_text,
            slot_root=str(tmp_path / "slots" / "1"),
        )
        assert result == str(slot_workspace / "blog")
        assert "escapes slot boundary" in warning
        assert original_blog in warning

    def test_no_escape_returns_empty_warning(self, tmp_path):
        """No escape → empty warning string."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        claude_text = '**Blog directory:** `blog/`'

        result, warning = resolve_blog_dir.resolve_with_warning(
            str(workspace), claude_text,
        )
        assert result == str(workspace / "blog")
        assert warning == ""


class TestEdgeCases:
    """Test edge cases in blog directory resolution."""

    def test_trailing_slash_stripped(self, tmp_path):
        """Trailing slash in blog dir path is stripped."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        claude_text = '**Blog directory:** `blog/`'
        result = resolve_blog_dir.resolve(str(workspace), claude_text)
        assert not result.endswith("/")

    def test_empty_claude_text(self, tmp_path):
        """Empty CLAUDE.md → defaults to workspace/blog/."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolve_blog_dir.resolve(str(workspace), "")
        assert result == str(workspace / "blog")

    def test_multiple_absolute_paths_with_different_slots(self, tmp_path):
        """Different slot roots correctly detect escape vs non-escape."""
        slot1 = tmp_path / "slots" / "1"
        slot2 = tmp_path / "slots" / "2"
        slot1_ws = slot1 / "work"
        slot1_ws.mkdir(parents=True)
        slot2_ws = slot2 / "work"
        slot2_ws.mkdir(parents=True)

        blog_in_slot1 = str(slot1_ws / "blog")
        claude_text = f'**Blog directory:** `{blog_in_slot1}/`'

        # From slot 1 → not an escape (blog is inside this slot)
        r1 = resolve_blog_dir.resolve(str(slot1_ws), claude_text, slot_root=str(slot1))
        assert r1 == blog_in_slot1

        # From slot 2 → escape! (blog points to slot 1, not slot 2)
        r2 = resolve_blog_dir.resolve(str(slot2_ws), claude_text, slot_root=str(slot2))
        assert r2 == str(slot2_ws / "blog")

    def test_tilde_expansion(self, tmp_path):
        """Tilde paths get expanded before escape check."""
        slot_workspace = tmp_path / "slots" / "1" / "work"
        slot_workspace.mkdir(parents=True)
        claude_text = '**Blog directory:** `~/claude/public/casehub/blog/`'

        result = resolve_blog_dir.resolve(
            str(slot_workspace), claude_text,
            slot_root=str(tmp_path / "slots" / "1"),
        )
        # ~ expands to home dir, which is outside the slot → escape
        assert result == str(slot_workspace / "blog")
