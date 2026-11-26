"""Structured closure refs in workspace git refs (#618)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

import closure_refs


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "T")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "t@t")


def g(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def init(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    g(ws, "init", "-q", "-b", "main")
    (ws / "README.md").write_text("init\n")
    g(ws, "add", "-A")
    g(ws, "commit", "-q", "-m", "init")
    g(ws, "checkout", "-q", "-b", "feat")
    (ws / "notes.md").write_text("work\n")
    g(ws, "add", "-A")
    g(ws, "commit", "-q", "-m", "feat: notes")
    return ws


class TestRecord:
    def test_writes_closed_ref_pointing_at_landed_sha(self, tmp_path):
        ws = init(tmp_path)
        main_tip = g(ws, "rev-parse", "main")

        closure_refs.record(ws, "feat", landed_sha=main_tip, base_branch="main")

        assert closure_refs.closed_sha(ws, "feat") == main_tip

    def test_writes_meta_blob_with_structured_fields(self, tmp_path):
        ws = init(tmp_path)
        main_tip = g(ws, "rev-parse", "main")

        closure_refs.record(ws, "feat", landed_sha=main_tip, base_branch="main",
                            issue="o/r#42", promoted=["docs/spec.md"],
                            published=["hortora.github.io"])

        meta = closure_refs.read(ws, "feat")
        assert meta is not None
        assert meta["landed_sha"] == main_tip
        assert meta["landed_on"] == "main"
        assert meta["issue"] == "o/r#42"
        assert "docs/spec.md" in meta["promoted"]
        assert "hortora.github.io" in meta["published"]
        assert "closed" in meta

    def test_empty_promoted_and_published(self, tmp_path):
        ws = init(tmp_path)
        main_tip = g(ws, "rev-parse", "main")

        closure_refs.record(ws, "feat", landed_sha=main_tip, base_branch="main")

        meta = closure_refs.read(ws, "feat")
        assert meta["promoted"] == ""
        assert meta["published"] == ""

    def test_meta_blob_sha_is_returned(self, tmp_path):
        ws = init(tmp_path)
        main_tip = g(ws, "rev-parse", "main")

        blob_sha = closure_refs.record(ws, "feat", landed_sha=main_tip,
                                       base_branch="main")

        assert blob_sha
        content = g(ws, "cat-file", "blob", blob_sha)
        assert f"landed_sha: {main_tip}" in content


class TestRead:
    def test_returns_none_for_unclosed_branch(self, tmp_path):
        ws = init(tmp_path)
        assert closure_refs.read(ws, "feat") is None

    def test_closed_sha_returns_empty_for_unclosed(self, tmp_path):
        ws = init(tmp_path)
        assert closure_refs.closed_sha(ws, "feat") == ""


class TestListClosed:
    def test_lists_closed_branches(self, tmp_path):
        ws = init(tmp_path)
        main_tip = g(ws, "rev-parse", "main")
        closure_refs.record(ws, "feat", landed_sha=main_tip, base_branch="main")
        g(ws, "checkout", "-q", "-b", "fix")
        (ws / "fix.md").write_text("fix\n")
        g(ws, "add", "-A")
        g(ws, "commit", "-q", "-m", "fix")
        closure_refs.record(ws, "fix", landed_sha=main_tip, base_branch="main")

        closed = closure_refs.list_closed(ws)
        assert sorted(closed) == ["feat", "fix"]

    def test_empty_when_nothing_closed(self, tmp_path):
        ws = init(tmp_path)
        assert closure_refs.list_closed(ws) == []


class TestClear:
    def test_removes_both_refs(self, tmp_path):
        ws = init(tmp_path)
        main_tip = g(ws, "rev-parse", "main")
        closure_refs.record(ws, "feat", landed_sha=main_tip, base_branch="main")
        assert closure_refs.read(ws, "feat") is not None

        closure_refs.clear(ws, "feat")

        assert closure_refs.read(ws, "feat") is None
        assert closure_refs.closed_sha(ws, "feat") == ""
        assert closure_refs.list_closed(ws) == []
