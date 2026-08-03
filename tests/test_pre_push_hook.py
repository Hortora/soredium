#!/usr/bin/env python3
"""Tests for project/pre_push_hook.py — lifecycle gate enforcement."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
from pre_push_hook import HookResult, hook_check, find_meta


class TestHookCheck:
    @pytest.mark.parametrize(
        "state, push_to_main, should_block",
        [
            ("active", True, True),
            ("scaffolded", True, True),
            ("transitioning", True, True),
            ("paused", True, True),
            ("closing:review", True, True),
            ("closing:verified", True, True),
            ("closing:promoted", True, True),
            ("closing:pushed", True, False),
            ("closing:merged", True, False),
            ("closing:stamped", True, False),
            ("active", False, False),
            ("closing:review", False, False),
            ("closing:pushed", False, False),
            ("scaffolded", False, False),
        ],
    )
    def test_hook_enforcement(self, state, push_to_main, should_block, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text(f"branch: test\nstate: {state}\ndate: 2026-08-03\n")
        result = hook_check(meta, push_to_main=push_to_main)
        assert result.blocked == should_block

    def test_no_meta_allows_push(self, tmp_path):
        meta = tmp_path / ".meta"
        result = hook_check(meta, push_to_main=True)
        assert result.blocked is False

    def test_blocked_message_includes_state(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: test\nstate: active\ndate: 2026-08-03\n")
        result = hook_check(meta, push_to_main=True)
        assert "active" in result.message

    def test_blocked_message_suggests_work_end(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: test\nstate: closing:review\ndate: 2026-08-03\n")
        result = hook_check(meta, push_to_main=True)
        assert "work-end" in result.message


class TestFindMeta:
    def test_finds_via_local_design_dir(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        meta = design / ".meta"
        meta.write_text("branch: x\nstate: active\n")
        found = find_meta(tmp_path)
        assert found is not None
        assert found.exists()

    def test_returns_none_when_no_meta(self, tmp_path):
        assert find_meta(tmp_path) is None

    def test_finds_via_wksp_symlink(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        design = workspace / "design"
        design.mkdir()
        (design / ".meta").write_text("branch: x\nstate: active\n")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "wksp").symlink_to(workspace)
        found = find_meta(repo)
        assert found is not None
