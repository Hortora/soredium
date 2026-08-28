"""Tests for work-slot/slot_maven.py"""

import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_maven


class TestWriteSlotSettings:
    def test_creates_settings_with_host_fallback(self, tmp_path):
        slot_dir = tmp_path / "slots" / "82"
        slot_dir.mkdir(parents=True)
        settings_path = slot_maven._write_slot_settings(slot_dir)
        assert settings_path.exists()
        content = settings_path.read_text()
        assert "host-m2" in content
        assert "file://" in content
        assert ".m2/repository" in content
        assert "slot-host-fallback" in content

    def test_includes_plugin_repositories(self, tmp_path):
        slot_dir = tmp_path / "slots" / "82"
        slot_dir.mkdir(parents=True)
        settings_path = slot_maven._write_slot_settings(slot_dir)
        content = settings_path.read_text()
        assert "host-m2-plugins" in content
        assert "<pluginRepository>" in content

    def test_snapshots_update_policy_always(self, tmp_path):
        slot_dir = tmp_path / "slots" / "82"
        slot_dir.mkdir(parents=True)
        settings_path = slot_maven._write_slot_settings(slot_dir)
        content = settings_path.read_text()
        assert "<updatePolicy>always</updatePolicy>" in content

    def test_idempotent(self, tmp_path):
        slot_dir = tmp_path / "slots" / "82"
        slot_dir.mkdir(parents=True)
        path1 = slot_maven._write_slot_settings(slot_dir)
        content1 = path1.read_text()
        path2 = slot_maven._write_slot_settings(slot_dir)
        content2 = path2.read_text()
        assert content1 == content2

    def test_settings_path_is_in_slot_dir(self, tmp_path):
        slot_dir = tmp_path / "slots" / "82"
        slot_dir.mkdir(parents=True)
        settings_path = slot_maven._write_slot_settings(slot_dir)
        assert settings_path.parent == slot_dir
        assert settings_path.name == "slot-settings.xml"


class TestSetupSlotRepo:
    def test_creates_new_config_with_repo_local_and_settings(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_maven.setup_slot_repo(repo_wt, m2)
        config = (repo_wt / ".mvn" / "maven.config").read_text()
        assert f"-Dmaven.repo.local={m2}" in config
        assert "--settings=.mvn/slot-settings.xml" in config

    def test_generates_slot_settings_xml(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_maven.setup_slot_repo(repo_wt, m2)
        assert (slot_dir / "slot-settings.xml").exists()

    def test_copies_settings_into_mvn_dir(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_maven.setup_slot_repo(repo_wt, m2)
        local = repo_wt / ".mvn" / "slot-settings.xml"
        assert local.exists()
        assert local.read_text() == (slot_dir / "slot-settings.xml").read_text()

    def test_appends_to_existing_config(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        mvn_dir = repo_wt / ".mvn"
        mvn_dir.mkdir(parents=True)
        (mvn_dir / "maven.config").write_text(
            "-Dquarkus.bootstrap.application-model.serialization.format=jos\n"
        )
        m2 = slot_dir / ".m2"
        slot_maven.setup_slot_repo(repo_wt, m2)
        config = (mvn_dir / "maven.config").read_text()
        assert "serialization.format=jos" in config
        assert f"-Dmaven.repo.local={m2}" in config
        assert "--settings=.mvn/slot-settings.xml" in config

    def test_fixes_legacy_dash_s_format(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        mvn_dir = repo_wt / ".mvn"
        mvn_dir.mkdir(parents=True)
        m2 = slot_dir / ".m2"
        (mvn_dir / "maven.config").write_text(
            f"-Dmaven.repo.local={m2}\n"
            f"-s {slot_dir}/slot-settings.xml\n"
        )
        slot_maven.setup_slot_repo(repo_wt, m2)
        config = (mvn_dir / "maven.config").read_text()
        assert "-s " not in config
        assert "--settings=.mvn/slot-settings.xml" in config

    def test_idempotent(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_maven.setup_slot_repo(repo_wt, m2)
        slot_maven.setup_slot_repo(repo_wt, m2)
        config = (repo_wt / ".mvn" / "maven.config").read_text()
        assert config.count("-Dmaven.repo.local=") == 1
        assert config.count("--settings=") == 1

    def test_multiple_repos_share_same_settings(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        m2 = slot_dir / ".m2"
        repo_a = slot_dir / "engine"
        repo_a.mkdir()
        repo_b = slot_dir / "blocks"
        repo_b.mkdir()
        slot_maven.setup_slot_repo(repo_a, m2)
        slot_maven.setup_slot_repo(repo_b, m2)
        config_a = (repo_a / ".mvn" / "maven.config").read_text()
        config_b = (repo_b / ".mvn" / "maven.config").read_text()
        assert "--settings=.mvn/slot-settings.xml" in config_a
        assert "--settings=.mvn/slot-settings.xml" in config_b
        assert (slot_dir / "slot-settings.xml").exists()
        assert (repo_a / ".mvn" / "slot-settings.xml").exists()
        assert (repo_b / ".mvn" / "slot-settings.xml").exists()

    def test_creates_gitignore_with_all_baseline_patterns(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        changed = slot_maven.setup_slot_repo(repo_wt, m2)
        assert changed is True
        gitignore = (repo_wt / ".gitignore").read_text()
        for pattern in [".mvn/maven.config", ".mvn/slot-settings.xml",
                        ".worktrees", ".worktrees/", ".claude", ".claude/"]:
            assert pattern in gitignore.splitlines()

    def test_appends_missing_baseline_patterns(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        (repo_wt / ".gitignore").write_text("target/\n.mvn/maven.config\n.claude/\n")
        changed = slot_maven.setup_slot_repo(repo_wt, m2)
        assert changed is True
        lines = (repo_wt / ".gitignore").read_text().splitlines()
        assert "target/" in lines
        assert ".mvn/maven.config" in lines
        assert ".mvn/slot-settings.xml" in lines
        assert ".worktrees" in lines
        assert ".worktrees/" in lines
        assert ".claude" in lines
        assert ".claude/" in lines

    def test_all_patterns_present_returns_false(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        (repo_wt / ".gitignore").write_text(
            ".mvn/maven.config\n.mvn/slot-settings.xml\n"
            ".worktrees\n.worktrees/\n.claude\n.claude/\n"
        )
        changed = slot_maven.setup_slot_repo(repo_wt, m2)
        assert changed is False

    def test_gitignore_baseline_idempotent(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_maven.setup_slot_repo(repo_wt, m2)
        content_after_first = (repo_wt / ".gitignore").read_text()
        changed = slot_maven.setup_slot_repo(repo_wt, m2)
        assert changed is False
        assert (repo_wt / ".gitignore").read_text() == content_after_first

    def test_preserves_existing_gitignore_content(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        (repo_wt / ".gitignore").write_text("target/\n*.pyc\n__pycache__\n")
        slot_maven.setup_slot_repo(repo_wt, m2)
        lines = (repo_wt / ".gitignore").read_text().splitlines()
        assert lines[0] == "target/"
        assert lines[1] == "*.pyc"
        assert lines[2] == "__pycache__"

    def test_adds_bare_form_when_slash_form_exists(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        (repo_wt / ".gitignore").write_text(
            ".mvn/maven.config\n.mvn/slot-settings.xml\n"
            ".claude/\n.worktrees/\n"
        )
        changed = slot_maven.setup_slot_repo(repo_wt, m2)
        assert changed is True
        lines = (repo_wt / ".gitignore").read_text().splitlines()
        assert ".claude" in lines
        assert ".claude/" in lines
        assert ".worktrees" in lines
        assert ".worktrees/" in lines
