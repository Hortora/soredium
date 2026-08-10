"""Tests for write-content/resolve_artifact_dir.py — unified artifact directory resolution."""

import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "write-content"
sys.path.insert(0, str(skill_dir))

import resolve_artifact_dir


ARTIFACT_TYPES = ["blog", "adr", "specs", "plans"]


class TestDefaultResolution:
    """Without CLAUDE.md overrides, all types default to $WORKSPACE/<type>/."""

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_defaults_to_workspace_subdir(self, tmp_path, artifact_type):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolve_artifact_dir.resolve(artifact_type, str(workspace), "")
        assert result == str(workspace / artifact_type)

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_empty_claude_text(self, tmp_path, artifact_type):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolve_artifact_dir.resolve(artifact_type, str(workspace), "")
        assert result == str(workspace / artifact_type)


class TestCustomDirectoryOverride:
    """CLAUDE.md **<Type> directory:** field overrides default."""

    def test_blog_directory_override(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        claude_text = "**Blog directory:** `custom-blog/`"
        result = resolve_artifact_dir.resolve("blog", str(workspace), claude_text)
        assert result == str(workspace / "custom-blog")

    def test_adr_directory_override(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        claude_text = "**ADR directory:** `custom-adr/`"
        result = resolve_artifact_dir.resolve("adr", str(workspace), claude_text)
        assert result == str(workspace / "custom-adr")

    def test_absolute_path_non_slot(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        blog_path = tmp_path / "external" / "blog"
        claude_text = f"**Blog directory:** `{blog_path}/`"
        result = resolve_artifact_dir.resolve("blog", str(workspace), claude_text)
        assert result == str(blog_path)

    def test_unrecognized_type_uses_default(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = resolve_artifact_dir.resolve("snapshots", str(workspace), "")
        assert result == str(workspace / "snapshots")


class TestSlotEscapeDetection:
    """Absolute paths escaping slot boundary fall back to default."""

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_absolute_path_in_slot_detected(self, tmp_path, artifact_type):
        slot_workspace = tmp_path / "slots" / "1" / "work"
        slot_workspace.mkdir(parents=True)
        field_name = resolve_artifact_dir.FIELD_NAMES.get(
            artifact_type, artifact_type.title()
        )
        claude_text = f"**{field_name} directory:** `/external/path/`"
        result = resolve_artifact_dir.resolve(
            artifact_type,
            str(slot_workspace),
            claude_text,
            slot_root=str(tmp_path / "slots" / "1"),
        )
        assert result == str(slot_workspace / artifact_type)

    @pytest.mark.parametrize("artifact_type", ARTIFACT_TYPES)
    def test_relative_path_in_slot_ok(self, tmp_path, artifact_type):
        slot_workspace = tmp_path / "slots" / "1" / "work"
        slot_workspace.mkdir(parents=True)
        field_name = resolve_artifact_dir.FIELD_NAMES.get(
            artifact_type, artifact_type.title()
        )
        claude_text = f"**{field_name} directory:** `{artifact_type}/`"
        result = resolve_artifact_dir.resolve(
            artifact_type,
            str(slot_workspace),
            claude_text,
            slot_root=str(tmp_path / "slots" / "1"),
        )
        assert result == str(slot_workspace / artifact_type)

    def test_escape_returns_warning(self, tmp_path):
        slot_workspace = tmp_path / "slots" / "1" / "work"
        slot_workspace.mkdir(parents=True)
        claude_text = "**Blog directory:** `/external/blog/`"
        result, warning = resolve_artifact_dir.resolve_with_warning(
            "blog",
            str(slot_workspace),
            claude_text,
            slot_root=str(tmp_path / "slots" / "1"),
        )
        assert result == str(slot_workspace / "blog")
        assert "escapes slot boundary" in warning

    def test_no_escape_returns_empty_warning(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        claude_text = "**Blog directory:** `blog/`"
        result, warning = resolve_artifact_dir.resolve_with_warning(
            "blog",
            str(workspace),
            claude_text,
        )
        assert result == str(workspace / "blog")
        assert warning == ""

    def test_absolute_path_inside_slot_is_ok(self, tmp_path):
        slot_root = tmp_path / "slots" / "1"
        slot_workspace = slot_root / "work"
        slot_workspace.mkdir(parents=True)
        blog_inside_slot = slot_workspace / "blog"
        claude_text = f"**Blog directory:** `{blog_inside_slot}/`"
        result = resolve_artifact_dir.resolve(
            "blog",
            str(slot_workspace),
            claude_text,
            slot_root=str(slot_root),
        )
        assert result == str(blog_inside_slot)

    def test_no_slot_root_skips_escape_check(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        external = tmp_path / "external" / "blog"
        claude_text = f"**Blog directory:** `{external}/`"
        result = resolve_artifact_dir.resolve("blog", str(workspace), claude_text)
        assert result == str(external)


class TestEdgeCases:
    def test_trailing_slash_stripped(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        claude_text = "**Blog directory:** `blog/`"
        result = resolve_artifact_dir.resolve("blog", str(workspace), claude_text)
        assert not result.endswith("/")

    def test_tilde_expansion(self, tmp_path):
        slot_workspace = tmp_path / "slots" / "1" / "work"
        slot_workspace.mkdir(parents=True)
        claude_text = "**Blog directory:** `~/claude/public/casehub/blog/`"
        result = resolve_artifact_dir.resolve(
            "blog",
            str(slot_workspace),
            claude_text,
            slot_root=str(tmp_path / "slots" / "1"),
        )
        assert result == str(slot_workspace / "blog")

    def test_multiple_slots_different_escape(self, tmp_path):
        slot1 = tmp_path / "slots" / "1"
        slot2 = tmp_path / "slots" / "2"
        slot1_ws = slot1 / "work"
        slot1_ws.mkdir(parents=True)
        slot2_ws = slot2 / "work"
        slot2_ws.mkdir(parents=True)

        blog_in_slot1 = str(slot1_ws / "blog")
        claude_text = f"**Blog directory:** `{blog_in_slot1}/`"

        r1 = resolve_artifact_dir.resolve(
            "blog", str(slot1_ws), claude_text, slot_root=str(slot1)
        )
        assert r1 == blog_in_slot1

        r2 = resolve_artifact_dir.resolve(
            "blog", str(slot2_ws), claude_text, slot_root=str(slot2)
        )
        assert r2 == str(slot2_ws / "blog")
