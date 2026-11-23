"""Tests for project/areas.py — read-only survey command."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(repo: Path, *args: str):
    subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True, check=True,
    )


def _init_repo(path: Path, branch: str = "main"):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", branch)
    (path / "README.md").write_text("init")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")


def _add_blog_entry(repo: Path, name: str, content: str):
    blog = repo / "docs" / "blog"
    blog.mkdir(parents=True, exist_ok=True)
    (blog / name).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"add {name}")


def build_family(tmp_path: Path) -> Path:
    """Build a realistic family tree with canonical, slot, clone, attic."""
    family = tmp_path / "family"
    family.mkdir()

    proj = family / "myproject"
    _init_repo(proj)

    wsp = family / "wsp-myproject"
    _init_repo(wsp)
    (wsp / ".workspace").touch()
    _git(wsp, "add", "-A")
    _git(wsp, "commit", "-q", "-m", "add workspace marker")

    slot_dir = family / "slots" / "1"
    slot_dir.mkdir(parents=True)
    slot_proj = slot_dir / "myproject"
    _init_repo(slot_proj)
    slot_wsp = slot_dir / "wsp-myproject"
    _init_repo(slot_wsp)
    (slot_wsp / ".workspace").touch()
    _git(slot_wsp, "add", "-A")
    _git(slot_wsp, "commit", "-q", "-m", "add workspace marker")
    (slot_dir / ".slot").write_text(
        "repos: myproject, wsp-myproject\n"
        "primary: myproject\n"
        "branch: issue-42-feature\n"
        "title: Feature\n"
        "state: active\n"
    )

    clone_dir = family / "clone" / "myproject"
    clone_dir.mkdir(parents=True)
    clone_proj = clone_dir / "myproject"
    _init_repo(clone_proj)
    clone_wsp = clone_dir / "wsp-myproject"
    _init_repo(clone_wsp)
    (clone_wsp / ".workspace").touch()
    _git(clone_wsp, "add", "-A")
    _git(clone_wsp, "commit", "-q", "-m", "add workspace marker")
    (clone_dir / ".permanent").touch()

    attic_dir = family / "slots" / "attic" / "2"
    attic_dir.mkdir(parents=True)
    attic_proj = attic_dir / "myproject"
    _init_repo(attic_proj)
    (attic_dir / ".slot").write_text(
        "repos: myproject\nprimary: myproject\n"
        "branch: old\ntitle: Old\nstate: archived\n"
    )

    return family


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------

class TestDiscoverAreas:
    def test_finds_all_kinds(self, tmp_path):
        from project.areas import discover_areas
        family = build_family(tmp_path)
        areas = discover_areas(family)
        kinds = [a.kind for a in areas]
        assert "canonical" in kinds
        assert "slot" in kinds
        assert "clone" in kinds
        assert "attic" in kinds

    def test_ordering(self, tmp_path):
        from project.areas import discover_areas
        family = build_family(tmp_path)
        areas = discover_areas(family)
        kinds = [a.kind for a in areas]
        assert kinds.index("canonical") < kinds.index("slot")
        assert kinds.index("slot") < kinds.index("clone")
        assert kinds.index("clone") < kinds.index("attic")

    def test_workspace_paired_not_separate(self, tmp_path):
        from project.areas import discover_areas
        family = build_family(tmp_path)
        areas = discover_areas(family)
        area_paths = [a.path.name for a in areas]
        assert "wsp-myproject" not in area_paths
        canonical = [a for a in areas if a.kind == "canonical"][0]
        assert canonical.workspace_repo is not None
        assert canonical.workspace_repo.name == "wsp-myproject"

    def test_slot_has_repos(self, tmp_path):
        from project.areas import discover_areas
        family = build_family(tmp_path)
        areas = discover_areas(family)
        slot = [a for a in areas if a.kind == "slot"][0]
        assert slot.project_repo is not None
        assert slot.slot_number == 1

    def test_clone_has_permanent(self, tmp_path):
        from project.areas import discover_areas
        family = build_family(tmp_path)
        areas = discover_areas(family)
        clone = [a for a in areas if a.kind == "clone"][0]
        assert clone.repo_name == "myproject"
        assert clone.project_repo is not None

    def test_empty_family(self, tmp_path):
        from project.areas import discover_areas
        family = tmp_path / "empty"
        family.mkdir()
        areas = discover_areas(family)
        assert areas == []


# ---------------------------------------------------------------------------
# Git helper tests
# ---------------------------------------------------------------------------

def _clone_repo(canon: Path, dest: Path):
    subprocess.run(
        ["git", "clone", "-q", "--shared", str(canon), str(dest)],
        capture_output=True, text=True, check=True,
    )


class TestFollowStateReadonly:
    def test_current(self, tmp_path):
        from project.areas import follow_state_readonly
        canon = tmp_path / "canon"
        _init_repo(canon)
        clone = tmp_path / "clone"
        _clone_repo(canon, clone)
        assert follow_state_readonly(clone, canon, "main") == "current"

    def test_fast_forward(self, tmp_path):
        from project.areas import follow_state_readonly
        canon = tmp_path / "canon"
        _init_repo(canon)
        clone = tmp_path / "clone"
        _clone_repo(canon, clone)
        (canon / "new.txt").write_text("new")
        _git(canon, "add", "-A")
        _git(canon, "commit", "-q", "-m", "advance")
        assert follow_state_readonly(clone, canon, "main") == "fast-forward"

    def test_diverged(self, tmp_path):
        from project.areas import follow_state_readonly
        canon = tmp_path / "canon"
        _init_repo(canon)
        clone = tmp_path / "clone"
        _clone_repo(canon, clone)
        (canon / "a.txt").write_text("a")
        _git(canon, "add", "-A")
        _git(canon, "commit", "-q", "-m", "canon change")
        (clone / "b.txt").write_text("b")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "clone change")
        assert follow_state_readonly(clone, canon, "main") == "diverged"

    def test_unknown_missing_branch(self, tmp_path):
        from project.areas import follow_state_readonly
        canon = tmp_path / "canon"
        _init_repo(canon)
        clone = tmp_path / "clone"
        _init_repo(clone)
        assert follow_state_readonly(clone, canon, "nonexistent") == "unknown"


class TestAheadReadonly:
    def test_zero(self, tmp_path):
        from project.areas import ahead_readonly
        canon = tmp_path / "canon"
        _init_repo(canon)
        clone = tmp_path / "clone"
        _clone_repo(canon, clone)
        assert ahead_readonly(clone, canon, "main", "main") == 0

    def test_with_commits(self, tmp_path):
        from project.areas import ahead_readonly
        canon = tmp_path / "canon"
        _init_repo(canon)
        clone = tmp_path / "clone"
        _clone_repo(canon, clone)
        _git(clone, "checkout", "-b", "feature")
        (clone / "feat.txt").write_text("feat")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "feat 1")
        (clone / "feat2.txt").write_text("feat2")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "feat 2")
        assert ahead_readonly(clone, canon, "main", "feature") == 2


class TestEntriesOnRef:
    def test_finds_entries(self, tmp_path):
        from project.areas import entries_on_ref
        repo = tmp_path / "repo"
        _init_repo(repo)
        _add_blog_entry(repo, "entry1.md", "# Entry 1")
        _add_blog_entry(repo, "entry2.md", "# Entry 2")
        result = entries_on_ref(repo, "main", "docs/blog")
        assert result == {"docs/blog/entry1.md", "docs/blog/entry2.md"}

    def test_empty(self, tmp_path):
        from project.areas import entries_on_ref
        repo = tmp_path / "repo"
        _init_repo(repo)
        result = entries_on_ref(repo, "main", "docs/blog")
        assert result == set()


class TestEntryContentFromRef:
    def test_reads_content(self, tmp_path):
        from project.areas import entry_content_from_ref
        repo = tmp_path / "repo"
        _init_repo(repo)
        _add_blog_entry(repo, "entry.md", "---\ntitle: Test\n---\nBody")
        content = entry_content_from_ref(repo, "main", "docs/blog/entry.md")
        assert "title: Test" in content
        assert "Body" in content


class TestParseFrontmatter:
    def test_valid(self):
        from project.areas import parse_frontmatter_from_text
        text = "---\ntitle: Hello\nprojects: owner/repo\n---\nBody text"
        fm = parse_frontmatter_from_text(text)
        assert fm is not None
        assert fm["title"] == "Hello"
        assert fm["projects"] == "owner/repo"

    def test_no_frontmatter(self):
        from project.areas import parse_frontmatter_from_text
        assert parse_frontmatter_from_text("Just plain text") is None

    def test_bare_project(self):
        from project.areas import parse_frontmatter_from_text
        text = "---\ntitle: Hello\nprojects: engine\n---\nBody"
        fm = parse_frontmatter_from_text(text)
        assert fm is not None
        assert "/" not in fm["projects"]
