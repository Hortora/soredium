"""Tests for project/migrate_meta.py — .meta to .plan migration."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

import migrate_meta


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True, check=True)
    return path


META_CONTENT = """\
branch: issue-49-pluggable-workbench-layout
state: scaffolded
project-sha: abc123
date: 2026-08-13
issue: 49
issue-repo: Hortora/trellis
covers: 49
flyway-next-v: none
design-repo: workspace
design-section-hashes:
"""


class TestMigrateMeta:
    def test_migrates_meta_to_plan(self, tmp_path, capsys):
        repo = init_repo(tmp_path / "ws")
        design = repo / "design"
        design.mkdir()
        meta = design / ".meta"
        meta.write_text(META_CONTENT)
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add meta"], capture_output=True)

        rc = migrate_meta.migrate(repo)

        assert rc == 0
        out = capsys.readouterr().out
        assert "ACTION=migrated" in out
        plan = design / ".plan"
        assert plan.exists()
        content = plan.read_text()
        assert "## State" in content
        assert "branch: issue-49-pluggable-workbench-layout" in content
        assert "## Queue" in content
        assert "#49" in content
        assert not meta.exists()

    def test_deletes_vestigial_meta_when_plan_exists(self, tmp_path, capsys):
        repo = init_repo(tmp_path / "ws")
        design = repo / "design"
        design.mkdir()
        meta = design / ".meta"
        meta.write_text(META_CONTENT)
        plan = design / ".plan"
        plan.write_text("# Work Plan\n\n## State\nbranch: test\nstate: active\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add both"], capture_output=True)

        rc = migrate_meta.migrate(repo)

        assert rc == 0
        out = capsys.readouterr().out
        assert "ACTION=deleted" in out
        assert not meta.exists()
        assert plan.exists()

    def test_deletes_vestigial_meta_when_plan_at_root(self, tmp_path, capsys):
        repo = init_repo(tmp_path / "ws")
        design = repo / "design"
        design.mkdir()
        meta = design / ".meta"
        meta.write_text(META_CONTENT)
        plan = repo / ".plan"
        plan.write_text("# Work Plan\n\n## State\nbranch: test\nstate: active\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add both"], capture_output=True)

        rc = migrate_meta.migrate(design)

        assert rc == 0
        out = capsys.readouterr().out
        assert "ACTION=deleted" in out

    def test_returns_error_when_no_meta(self, tmp_path, capsys):
        repo = init_repo(tmp_path / "ws")

        rc = migrate_meta.migrate(repo)

        assert rc == 1
        out = capsys.readouterr().out
        assert "ERROR=no_meta_found" in out

    def test_skips_empty_meta(self, tmp_path, capsys):
        repo = init_repo(tmp_path / "ws")
        meta = repo / ".meta"
        meta.write_text("")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add empty"], capture_output=True)

        rc = migrate_meta.migrate(repo)

        assert rc == 0
        out = capsys.readouterr().out
        assert "ACTION=skipped" in out

    def test_handles_meta_at_root_not_design(self, tmp_path, capsys):
        repo = init_repo(tmp_path / "ws")
        meta = repo / ".meta"
        meta.write_text("branch: test-branch\nstate: active\nissue: 42\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add meta"], capture_output=True)

        rc = migrate_meta.migrate(repo)

        assert rc == 0
        plan = repo / ".plan"
        assert plan.exists()
        content = plan.read_text()
        assert "branch: test-branch" in content
        assert "#42" in content
