"""Tests for classify_repos directory-enumeration fallback."""
import subprocess
import sys
from pathlib import Path

import pytest

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from repo_state import classify_repos, RepoType


def _make_git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)],
                   capture_output=True, check=True)
    (path / "file.txt").write_text("content")
    subprocess.run(["git", "-C", str(path), "add", "."],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"],
                   capture_output=True, check=True)


def test_fallback_when_slot_file_missing(tmp_path):
    """When .slot file is missing, discover repos from directory."""
    slot_dir = tmp_path / "slot-1"
    slot_dir.mkdir()

    _make_git_repo(slot_dir / "engine")
    _make_git_repo(slot_dir / "iot")

    repos = classify_repos(
        project=slot_dir / "engine",
        workspace=slot_dir / "wsp-engine",
        branch="main", base_branch="main",
        slot_path=slot_dir,
    )
    assert len(repos) >= 2
    assert all(r.repo_type == RepoType.CLONE for r in repos)


def test_fallback_excludes_workspace_dirs(tmp_path):
    """Workspace directories (with .workspace marker) are excluded."""
    slot_dir = tmp_path / "slot-1"
    slot_dir.mkdir()

    _make_git_repo(slot_dir / "engine")
    ws_dir = slot_dir / "wsp-engine"
    _make_git_repo(ws_dir)
    (ws_dir / ".workspace").touch()

    repos = classify_repos(
        project=slot_dir / "engine",
        workspace=ws_dir,
        branch="main", base_branch="main",
        slot_path=slot_dir,
    )
    repo_names = {r.name for r in repos}
    assert "engine" in repo_names
    assert "wsp-engine" not in repo_names


def test_fallback_empty_slot_dir(tmp_path):
    """Empty slot directory with no .slot file returns empty list."""
    slot_dir = tmp_path / "slot-1"
    slot_dir.mkdir()

    repos = classify_repos(
        project=tmp_path / "engine",
        workspace=tmp_path / "ws",
        branch="main", base_branch="main",
        slot_path=slot_dir,
    )
    assert repos == []


def test_normal_slot_file_still_works(tmp_path):
    """When .slot file exists, normal path is used (not fallback)."""
    slot_dir = tmp_path / "slot-1"
    slot_dir.mkdir()

    _make_git_repo(slot_dir / "engine")
    _make_git_repo(slot_dir / "iot")
    (slot_dir / ".slot").write_text("## Repos\n- engine (primary)\n- iot\n")

    repos = classify_repos(
        project=slot_dir / "engine",
        workspace=tmp_path / "ws",
        branch="main", base_branch="main",
        slot_path=slot_dir,
    )
    assert len(repos) == 2
    repo_names = {r.name for r in repos}
    assert "engine" in repo_names
    assert "iot" in repo_names
