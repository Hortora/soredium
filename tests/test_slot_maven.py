"""Tests for work-slot/slot_maven.py — CLRM wrapper and repo setup."""

import os
import stat
import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_maven


class TestGenerateMvnWrapper:
    def test_creates_wrapper(self, tmp_path):
        wrapper = slot_maven.generate_mvn_wrapper(tmp_path)
        assert wrapper.exists()
        assert wrapper.name == "mvn"

    def test_wrapper_is_executable(self, tmp_path):
        wrapper = slot_maven.generate_mvn_wrapper(tmp_path)
        assert wrapper.stat().st_mode & stat.S_IEXEC

    def test_wrapper_contains_clrm_flags(self, tmp_path):
        wrapper = slot_maven.generate_mvn_wrapper(tmp_path)
        content = wrapper.read_text()
        assert "maven.repo.local=" in content
        assert "maven.repo.local.tail=" in content

    def test_wrapper_references_slot_m2(self, tmp_path):
        wrapper = slot_maven.generate_mvn_wrapper(tmp_path)
        content = wrapper.read_text()
        assert ".m2/repository" in content

    def test_wrapper_references_host_m2(self, tmp_path):
        wrapper = slot_maven.generate_mvn_wrapper(tmp_path)
        content = wrapper.read_text()
        host_m2 = str(Path.home() / ".m2" / "repository")
        assert host_m2 in content

    def test_creates_m2_directory(self, tmp_path):
        slot_maven.generate_mvn_wrapper(tmp_path)
        assert (tmp_path / ".m2" / "repository").is_dir()

    def test_wrapper_uses_slot_dir_variable(self, tmp_path):
        wrapper = slot_maven.generate_mvn_wrapper(tmp_path)
        content = wrapper.read_text()
        assert "${SLOT_DIR}" in content


class TestSetupSlotRepo:
    def test_creates_gitignore_with_baseline_patterns(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        changed = slot_maven.setup_slot_repo(repo, tmp_path / ".m2" / "repository")
        assert changed is True
        gitignore = (repo / ".gitignore").read_text()
        assert ".mvn/maven.config" in gitignore
        assert ".claude/" in gitignore

    def test_appends_missing_patterns(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".gitignore").write_text("target/\n")
        changed = slot_maven.setup_slot_repo(repo, tmp_path / ".m2" / "repository")
        assert changed is True
        content = (repo / ".gitignore").read_text()
        assert "target/" in content
        assert ".mvn/maven.config" in content

    def test_idempotent(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        slot_maven.setup_slot_repo(repo, tmp_path / ".m2" / "repository")
        changed = slot_maven.setup_slot_repo(repo, tmp_path / ".m2" / "repository")
        assert changed is False

    def test_all_patterns_present_returns_false(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".gitignore").write_text(
            ".mvn/maven.config\n.mvn/slot-settings.xml\n"
            ".worktrees\n.worktrees/\n.claude\n.claude/\n"
        )
        changed = slot_maven.setup_slot_repo(repo, tmp_path / ".m2" / "repository")
        assert changed is False
