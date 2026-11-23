"""Tests for project/areas.py — read-only survey command."""
from __future__ import annotations

import subprocess
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Inspection tests
# ---------------------------------------------------------------------------

class TestInspectRepo:
    def test_basic(self, tmp_path):
        from project.areas import inspect_repo, RepoInfo, RepoState
        repo = tmp_path / "repo"
        _init_repo(repo)
        ri = RepoInfo(name="repo", path=repo, role="project")
        state = inspect_repo(ri, canon_repo=None, base="main")
        assert state.branch == "main"
        assert state.dirty_count == 0
        assert state.ahead_of_canonical == 0
        assert state.in_progress is None

    def test_dirty(self, tmp_path):
        from project.areas import inspect_repo, RepoInfo
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "dirty.txt").write_text("dirty")
        ri = RepoInfo(name="repo", path=repo, role="project")
        state = inspect_repo(ri, canon_repo=None, base="main")
        assert state.dirty_count == 1


class TestInspectMarkers:
    def test_slot(self, tmp_path):
        from project.areas import inspect_markers, discover_areas
        family = build_family(tmp_path)
        slot = [a for a in discover_areas(family) if a.kind == "slot"][0]
        markers = inspect_markers(slot)
        assert ".slot" in markers

    def test_clone(self, tmp_path):
        from project.areas import inspect_markers, discover_areas
        family = build_family(tmp_path)
        clone = [a for a in discover_areas(family) if a.kind == "clone"][0]
        markers = inspect_markers(clone)
        assert ".permanent" in markers


class TestInspectClosures:
    def test_stamped_branch(self, tmp_path):
        from project.areas import inspect_closures, RepoInfo, Area, QueueInfo
        repo = tmp_path / "wsp"
        _init_repo(repo)
        _git(repo, "checkout", "-b", "issue-10-feat")
        (repo / "work.txt").write_text("work")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "work")
        _git(repo, "commit", "--allow-empty", "-m",
             "chore: branch closed — landed as abc123 on main")
        _git(repo, "checkout", "main")
        ri = RepoInfo(name="wsp", path=repo, role="workspace")
        area = Area(kind="canonical", path=repo)
        closures = inspect_closures(ri, area, [])
        stamped = [c for c in closures if c.branch == "issue-10-feat"]
        assert len(stamped) == 1
        assert stamped[0].source == "stamp"
        assert stamped[0].landed_sha == "abc123"

    def test_unstamped_active(self, tmp_path):
        from project.areas import inspect_closures, RepoInfo, Area, QueueInfo
        repo = tmp_path / "wsp"
        _init_repo(repo)
        _git(repo, "checkout", "-b", "issue-20-wip")
        (repo / "wip.txt").write_text("wip")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "wip")
        _git(repo, "checkout", "main")
        ri = RepoInfo(name="wsp", path=repo, role="workspace")
        area = Area(kind="slot", path=tmp_path)
        qi = QueueInfo(path=Path("/fake"), items=2, open_items=1,
                       active_issue="hortora/proj#20", status="active",
                       is_root=False)
        closures = inspect_closures(ri, area, [qi])
        unstamped = [c for c in closures if c.branch == "issue-20-wip"]
        assert len(unstamped) == 1
        assert unstamped[0].classification == "active"

    def test_unstamped_attic_is_orphaned(self, tmp_path):
        from project.areas import inspect_closures, RepoInfo, Area
        repo = tmp_path / "wsp"
        _init_repo(repo)
        _git(repo, "checkout", "-b", "old-branch")
        (repo / "old.txt").write_text("old")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "old work")
        _git(repo, "checkout", "main")
        ri = RepoInfo(name="wsp", path=repo, role="workspace")
        area = Area(kind="attic", path=tmp_path)
        closures = inspect_closures(ri, area, [])
        orphaned = [c for c in closures if c.branch == "old-branch"]
        assert len(orphaned) == 1
        assert orphaned[0].classification == "orphaned"


# ---------------------------------------------------------------------------
# Promotion drift tests
# ---------------------------------------------------------------------------

class TestPromotionDrift:
    def test_gap_detected(self, tmp_path):
        from project.areas import inspect_promotion_drift, RepoInfo, DriftEntry
        proj = tmp_path / "proj"
        _init_repo(proj)
        wsp = tmp_path / "wsp"
        _init_repo(wsp)
        _add_blog_entry(wsp, "entry.md",
                        "---\ntitle: Test\nprojects: owner/repo\n---\nBody")
        drift = inspect_promotion_drift(
            RepoInfo("proj", proj, "project"),
            RepoInfo("wsp", wsp, "workspace"), "main")
        gaps = [d for d in drift if d.status == "gap"]
        assert len(gaps) == 1

    def test_no_gap_when_promoted(self, tmp_path):
        from project.areas import inspect_promotion_drift, RepoInfo
        proj = tmp_path / "proj"
        _init_repo(proj)
        wsp = tmp_path / "wsp"
        _init_repo(wsp)
        _add_blog_entry(wsp, "entry.md",
                        "---\ntitle: Test\nprojects: owner/repo\n---\nBody")
        _add_blog_entry(proj, "entry.md",
                        "---\ntitle: Test\nprojects: owner/repo\n---\nBody")
        drift = inspect_promotion_drift(
            RepoInfo("proj", proj, "project"),
            RepoInfo("wsp", wsp, "workspace"), "main")
        gaps = [d for d in drift if d.status == "gap"]
        assert len(gaps) == 0

    def test_waiting_for_landing(self, tmp_path):
        from project.areas import inspect_promotion_drift, RepoInfo
        proj = tmp_path / "proj"
        _init_repo(proj)
        wsp = tmp_path / "wsp"
        _init_repo(wsp)
        _git(wsp, "checkout", "-b", "feature")
        _add_blog_entry(wsp, "entry.md",
                        "---\ntitle: Test\nprojects: owner/repo\n---\nBody")
        drift = inspect_promotion_drift(
            RepoInfo("proj", proj, "project"),
            RepoInfo("wsp", wsp, "workspace"), "main")
        waiting = [d for d in drift if d.status == "waiting"]
        assert len(waiting) == 1

    def test_no_false_gap_on_feature_branch(self, tmp_path):
        from project.areas import inspect_promotion_drift, RepoInfo
        proj = tmp_path / "proj"
        _init_repo(proj)
        wsp = tmp_path / "wsp"
        _init_repo(wsp)
        _add_blog_entry(wsp, "entry.md",
                        "---\ntitle: Test\nprojects: owner/repo\n---\nBody")
        _add_blog_entry(proj, "entry.md",
                        "---\ntitle: Test\nprojects: owner/repo\n---\nBody")
        _git(proj, "checkout", "-b", "feature-old", "HEAD~1")
        drift = inspect_promotion_drift(
            RepoInfo("proj", proj, "project"),
            RepoInfo("wsp", wsp, "workspace"), "main")
        gaps = [d for d in drift if d.status == "gap"]
        assert len(gaps) == 0

    def test_bare_project_ref_string(self, tmp_path):
        from project.areas import inspect_promotion_drift, RepoInfo
        proj = tmp_path / "proj"
        _init_repo(proj)
        wsp = tmp_path / "wsp"
        _init_repo(wsp)
        _add_blog_entry(wsp, "entry.md",
                        "---\ntitle: Test\nprojects: engine\n---\nBody")
        drift = inspect_promotion_drift(
            RepoInfo("proj", proj, "project"),
            RepoInfo("wsp", wsp, "workspace"), "main")
        bare = [d for d in drift if d.bare_project]
        assert len(bare) >= 1

    def test_bare_project_ref_list(self, tmp_path):
        from project.areas import inspect_promotion_drift, RepoInfo
        proj = tmp_path / "proj"
        _init_repo(proj)
        wsp = tmp_path / "wsp"
        _init_repo(wsp)
        _add_blog_entry(wsp, "entry.md",
                        "---\ntitle: Test\nprojects:\n  - engine\n---\nBody")
        drift = inspect_promotion_drift(
            RepoInfo("proj", proj, "project"),
            RepoInfo("wsp", wsp, "workspace"), "main")
        bare = [d for d in drift if d.bare_project]
        assert len(bare) >= 1

    def test_no_false_gap_for_promoted_bare_ref(self, tmp_path):
        """H1: a promoted entry with bare projects: should not create a gap finding."""
        from project.areas import inspect_promotion_drift, RepoInfo
        proj = tmp_path / "proj"
        _init_repo(proj)
        wsp = tmp_path / "wsp"
        _init_repo(wsp)
        _add_blog_entry(wsp, "entry.md",
                        "---\ntitle: Test\nprojects: engine\n---\nBody")
        _add_blog_entry(proj, "entry.md",
                        "---\ntitle: Test\nprojects: engine\n---\nBody")
        drift = inspect_promotion_drift(
            RepoInfo("proj", proj, "project"),
            RepoInfo("wsp", wsp, "workspace"), "main")
        gaps = [d for d in drift if d.status == "gap"]
        assert len(gaps) == 0
        bare = [d for d in drift if d.bare_project]
        assert len(bare) == 1
        assert bare[0].status == "bare-ref-only"


# ---------------------------------------------------------------------------
# Survey orchestrator tests
# ---------------------------------------------------------------------------

class TestSurvey:
    def test_complete(self, tmp_path):
        from project.areas import survey, SurveyResult
        family = build_family(tmp_path)
        results = survey([family])
        assert len(results) == 1
        r = results[0]
        assert r.family_root == family
        assert len(r.areas) >= 4
        assert isinstance(r.summary, dict)

    def test_read_only(self, tmp_path):
        from project.areas import survey

        def tree(directory: Path) -> dict[str, bytes]:
            result = {}
            for p in sorted(directory.rglob("*")):
                if p.is_file() and ".git" not in p.relative_to(directory).parts:
                    result[str(p.relative_to(directory))] = p.read_bytes()
            return result

        family = build_family(tmp_path)
        before = tree(family)
        survey([family])
        after = tree(family)
        assert before == after

    def test_idempotent(self, tmp_path):
        from project.areas import survey
        family = build_family(tmp_path)
        r1 = survey([family])
        r2 = survey([family])
        assert len(r1) == len(r2)
        assert len(r1[0].areas) == len(r2[0].areas)
        assert r1[0].summary == r2[0].summary

    def test_findings_for_diverged_clone(self, tmp_path):
        from project.areas import survey
        family = build_family(tmp_path)
        # Make clone diverge from canonical by adding a commit to canonical
        canon_proj = family / "myproject"
        clone_proj = family / "clone" / "myproject" / "myproject"
        # Clone needs shared ancestry for meaningful divergence
        _git(clone_proj, "remote", "add", "local", str(canon_proj))
        _git(clone_proj, "fetch", "local")
        _git(clone_proj, "reset", "--hard", "local/main")
        # Now diverge
        (canon_proj / "canon.txt").write_text("canon")
        _git(canon_proj, "add", "-A")
        _git(canon_proj, "commit", "-q", "-m", "canon diverge")
        (clone_proj / "clone.txt").write_text("clone")
        _git(clone_proj, "add", "-A")
        _git(clone_proj, "commit", "-q", "-m", "clone diverge")
        results = survey([family])
        attention = results[0].attention
        drift_errors = [f for f in attention if f.category == "drift"]
        assert len(drift_errors) >= 1


# ---------------------------------------------------------------------------
# Output tests
# ---------------------------------------------------------------------------

class TestFormatKV:
    def test_basic(self, tmp_path):
        from project.areas import survey, format_kv
        family = build_family(tmp_path)
        results = survey([family])
        output = format_kv(results)
        assert "FAMILY=" in output
        assert "AREA_COUNT=" in output
        assert "AREA_1_KIND=" in output
