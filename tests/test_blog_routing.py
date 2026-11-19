"""Tests for publish-blog/blog_routing.py — routing resolution with small fixtures."""

import textwrap
from pathlib import Path

import pytest
import yaml

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "publish-blog"))

from blog_routing import (
    RoutingConfig,
    load_routing,
    parse_frontmatter,
    plan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_routing(path: Path, config: dict) -> Path:
    path.write_text(yaml.dump(config))
    return path


def _write_entry(blog_dir: Path, name: str, frontmatter: dict) -> Path:
    p = blog_dir / name
    fm_text = yaml.dump(frontmatter, default_flow_style=False)
    p.write_text(f"---\n{fm_text}---\n\n# Content\n")
    return p


# ---------------------------------------------------------------------------
# RoutingConfig.resolve_destinations
# ---------------------------------------------------------------------------

class TestResolveDestinations:
    def test_default_destinations_when_no_rule_matches(self):
        config = RoutingConfig(
            destinations={"d1": {"path": "/tmp", "subdir": "_posts"}},
            rules=[{"match": {"entry_type": "article"}, "destinations": ["d1"]}],
            defaults=["d1"],
        )
        fm = {"entry_type": "note"}
        assert config.resolve_destinations(fm) == {"d1"}

    def test_entry_type_match(self):
        config = RoutingConfig(
            destinations={
                "notes": {"path": "/tmp/n"},
                "articles": {"path": "/tmp/a"},
            },
            rules=[
                {"match": {"entry_type": "note"}, "destinations": ["notes"]},
                {"match": {"entry_type": "article"}, "destinations": ["articles"]},
            ],
            defaults=["notes"],
        )
        assert config.resolve_destinations({"entry_type": "article"}) == {"articles"}
        assert config.resolve_destinations({"entry_type": "note"}) == {"notes"}

    def test_project_match_bare(self):
        config = RoutingConfig(
            destinations={"d1": {"path": "/tmp"}},
            rules=[{"match": {"project": "soredium"}, "destinations": ["d1"]}],
            defaults=[],
        )
        assert config.resolve_destinations(
            {"entry_type": "note", "projects": ["soredium"]}
        ) == {"d1"}

    def test_project_match_org_qualified(self):
        config = RoutingConfig(
            destinations={"d1": {"path": "/tmp"}},
            rules=[{"match": {"project": "casehubio/engine"}, "destinations": ["d1"]}],
            defaults=[],
        )
        # org/repo format matches directly
        assert config.resolve_destinations(
            {"entry_type": "note", "projects": ["casehubio/engine"]}
        ) == {"d1"}
        # legacy org-repo format matches
        assert config.resolve_destinations(
            {"entry_type": "note", "projects": ["casehub-engine"]}
        ) == {"d1"}
        # bare repo name matches
        assert config.resolve_destinations(
            {"entry_type": "note", "projects": ["engine"]}
        ) == {"d1"}

    def test_a_project_rule_is_not_widened_by_a_fallback_rule(self):
        """Was test_multiple_rules_union_destinations, which pinned the fault
        behind #569: the entry-type fallback was unioned onto the project rule."""
        config = RoutingConfig(
            destinations={
                "d1": {"path": "/tmp/d1"},
                "d2": {"path": "/tmp/d2"},
            },
            rules=[
                {"match": {"entry_type": "note"}, "destinations": ["d1"]},
                {"match": {"project": "soredium"}, "destinations": ["d2"]},
            ],
            defaults=[],
        )
        result = config.resolve_destinations(
            {"entry_type": "note", "projects": ["soredium"]}
        )
        assert result == {"d2"}

    def test_equally_specific_rules_are_unioned(self):
        config = RoutingConfig(
            destinations={"d1": {"path": "/tmp/d1"}, "d2": {"path": "/tmp/d2"}},
            rules=[
                {"match": {"project": "soredium"}, "destinations": ["d1"]},
                {"match": {"project": "grove"}, "destinations": ["d2"]},
            ],
            defaults=[],
        )
        assert config.resolve_destinations(
            {"entry_type": "note", "projects": ["soredium", "grove"]}) == {"d1", "d2"}

    def test_and_logic_within_rule(self):
        config = RoutingConfig(
            destinations={"d1": {"path": "/tmp"}},
            rules=[{
                "match": {"entry_type": "article", "project": "soredium"},
                "destinations": ["d1"],
            }],
            defaults=["fallback"],
        )
        # Only entry_type matches — not both
        assert config.resolve_destinations(
            {"entry_type": "article", "projects": ["other"]}
        ) == {"fallback"}
        # Both match
        assert config.resolve_destinations(
            {"entry_type": "article", "projects": ["soredium"]}
        ) == {"d1"}

    def test_tags_match(self):
        config = RoutingConfig(
            destinations={"d1": {"path": "/tmp"}},
            rules=[{"match": {"tags": ["quarkus", "java"]}, "destinations": ["d1"]}],
            defaults=["fallback"],
        )
        assert config.resolve_destinations(
            {"entry_type": "note", "tags": ["quarkus"]}
        ) == {"d1"}
        assert config.resolve_destinations(
            {"entry_type": "note", "tags": ["python"]}
        ) == {"fallback"}

    def test_subtype_match(self):
        config = RoutingConfig(
            destinations={"d1": {"path": "/tmp"}},
            rules=[{
                "match": {"entry_type": "note", "subtype": "diary"},
                "destinations": ["d1"],
            }],
            defaults=["fallback"],
        )
        assert config.resolve_destinations(
            {"entry_type": "note", "subtype": "diary"}
        ) == {"d1"}
        assert config.resolve_destinations(
            {"entry_type": "note", "subtype": "log"}
        ) == {"fallback"}


# ---------------------------------------------------------------------------
# load_routing
# ---------------------------------------------------------------------------

class TestLoadRouting:
    def test_global_only(self, tmp_path):
        global_cfg = {
            "version": 1,
            "destinations": {"d1": {"type": "git", "path": "/tmp", "subdir": "_posts"}},
            "defaults": {"destinations": ["d1"]},
            "rules": [{"match": {"entry_type": "note"}, "destinations": ["d1"]}],
        }
        gpath = _write_routing(tmp_path / "global.yaml", global_cfg)
        config = load_routing(global_path=gpath)
        assert config.defaults == ["d1"]
        assert len(config.rules) == 1

    def test_workspace_extends_global(self, tmp_path):
        global_cfg = {
            "version": 1,
            "destinations": {"d1": {"type": "git", "path": "/tmp/d1"}},
            "defaults": {"destinations": ["d1"]},
            "rules": [{"match": {"entry_type": "note"}, "destinations": ["d1"]}],
        }
        ws_cfg = {
            "extends": "~/.claude/blog-routing.yaml",
            "destinations": {"d2": {"type": "git", "path": "/tmp/d2"}},
            "rules": [{"match": {"entry_type": "article"}, "destinations": ["d2"]}],
        }
        gpath = _write_routing(tmp_path / "global.yaml", global_cfg)
        wpath = _write_routing(tmp_path / "ws.yaml", ws_cfg)
        config = load_routing(global_path=gpath, workspace_path=wpath)

        assert "d1" in config.destinations
        assert "d2" in config.destinations
        assert len(config.rules) == 2
        # Defaults stay as global (workspace has no defaults section)
        assert config.defaults == ["d1"]

    def test_workspace_replaces_defaults(self, tmp_path):
        global_cfg = {
            "version": 1,
            "destinations": {"d1": {"path": "/tmp/d1"}, "d2": {"path": "/tmp/d2"}},
            "defaults": {"destinations": ["d1"]},
            "rules": [],
        }
        ws_cfg = {
            "extends": "~/.claude/blog-routing.yaml",
            "defaults": {"destinations": ["d2"]},
        }
        gpath = _write_routing(tmp_path / "global.yaml", global_cfg)
        wpath = _write_routing(tmp_path / "ws.yaml", ws_cfg)
        config = load_routing(global_path=gpath, workspace_path=wpath)
        assert config.defaults == ["d2"]

    def test_missing_global(self, tmp_path):
        config = load_routing(global_path=tmp_path / "nope.yaml")
        assert config.destinations == {}
        assert config.rules == []
        assert config.defaults == []


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_valid_frontmatter(self, tmp_path):
        p = tmp_path / "entry.md"
        p.write_text("---\ntitle: Test\nentry_type: note\n---\n\n# Body\n")
        fm = parse_frontmatter(p)
        assert fm["title"] == "Test"
        assert fm["entry_type"] == "note"

    def test_no_frontmatter(self, tmp_path):
        p = tmp_path / "entry.md"
        p.write_text("# Just a heading\n\nSome text.\n")
        assert parse_frontmatter(p) is None

    def test_empty_frontmatter(self, tmp_path):
        p = tmp_path / "entry.md"
        p.write_text("---\n---\n\n# Body\n")
        assert parse_frontmatter(p) == {}


# ---------------------------------------------------------------------------
# plan()
# ---------------------------------------------------------------------------

class TestPlan:
    def _setup_workspace(self, tmp_path, global_cfg, ws_cfg=None, entries=None):
        """Create a workspace with routing config and blog entries."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        blog_dir = ws / "blog"
        blog_dir.mkdir()

        gpath = _write_routing(tmp_path / "global.yaml", global_cfg)
        if ws_cfg:
            _write_routing(ws / "blog-routing.yaml", ws_cfg)

        for name, fm in (entries or {}).items():
            _write_entry(blog_dir, name, fm)

        return ws, gpath

    def test_entry_present_and_absent(self, tmp_path):
        dest_dir = tmp_path / "dest" / "_posts"
        dest_dir.mkdir(parents=True)
        # Pre-place one entry at destination
        (dest_dir / "present.md").write_text("already here")

        global_cfg = {
            "destinations": {"blog": {"path": str(tmp_path / "dest"), "subdir": "_posts"}},
            "defaults": {"destinations": ["blog"]},
            "rules": [],
        }
        ws, gpath = self._setup_workspace(tmp_path, global_cfg, entries={
            "present.md": {"entry_type": "note"},
            "absent.md": {"entry_type": "note"},
        })

        # "Present" means the destination holds this entry as it now is.
        (dest_dir / "present.md").write_bytes((ws / "blog" / "present.md").read_bytes())

        entries, missing, entries_missing = plan(ws, gpath)
        assert len(entries) == 2
        present_rec = [e for e in entries if e["file"] == "present.md"][0]
        absent_rec = [e for e in entries if e["file"] == "absent.md"][0]
        assert present_rec["present"] == "yes"
        assert absent_rec["present"] == "no"

        assert len(missing) == 1
        assert missing[0]["file"] == "absent.md"
        assert len(entries_missing) == 1

    def test_an_older_version_at_the_destination_is_stale_and_counts_as_missing(self, tmp_path):
        dest_dir = tmp_path / "dest" / "_posts"
        dest_dir.mkdir(parents=True)
        (dest_dir / "revised.md").write_text("the version published before the entry was revised")
        global_cfg = {
            "destinations": {"blog": {"path": str(tmp_path / "dest"), "subdir": "_posts"}},
            "defaults": {"destinations": ["blog"]},
            "rules": [],
        }
        ws, gpath = self._setup_workspace(tmp_path, global_cfg, entries={
            "revised.md": {"entry_type": "note"},
        })

        entries, missing, entries_missing = plan(ws, gpath)

        assert [e["present"] for e in entries] == ["stale"]
        assert [m["file"] for m in missing] == ["revised.md"]
        assert entries[0]["source"] == str(ws.resolve() / "blog" / "revised.md")
        assert [e["file"] for e in entries_missing] == ["revised.md"]

    def test_entry_with_no_frontmatter_is_routed_as_a_note(self, tmp_path):
        """Was test_entry_with_no_frontmatter_skipped; since #572 it is a note."""
        global_cfg = {
            "destinations": {"blog": {"path": str(tmp_path / "dest")}},
            "defaults": {"destinations": ["blog"]},
            "rules": [],
        }
        ws, gpath = self._setup_workspace(tmp_path, global_cfg)
        blog_dir = ws / "blog"
        (blog_dir / "nofm.md").write_text("# No frontmatter\n\nJust text.\n")
        _write_entry(blog_dir, "hasfm.md", {"entry_type": "note"})

        entries, _, _ = plan(ws, gpath)
        files = [e["file"] for e in entries]
        assert "nofm.md" in files
        assert "hasfm.md" in files

    def test_destination_dir_does_not_exist(self, tmp_path):
        """Missing destination directory is reported, not a crash."""
        global_cfg = {
            "destinations": {"blog": {"path": str(tmp_path / "nonexistent"), "subdir": "_posts"}},
            "defaults": {"destinations": ["blog"]},
            "rules": [],
        }
        ws, gpath = self._setup_workspace(tmp_path, global_cfg, entries={
            "entry.md": {"entry_type": "note"},
        })

        entries, missing, entries_missing = plan(ws, gpath)
        assert len(entries) == 1
        assert entries[0]["present"] == "no"
        assert len(missing) == 1

    def test_entry_present_at_one_dest_absent_at_another(self, tmp_path):
        dest1 = tmp_path / "dest1" / "_posts"
        dest1.mkdir(parents=True)
        dest2 = tmp_path / "dest2" / "_notes"
        dest2.mkdir(parents=True)
        (dest1 / "entry.md").write_text("present here")

        global_cfg = {
            "destinations": {
                "blog1": {"path": str(tmp_path / "dest1"), "subdir": "_posts"},
                "blog2": {"path": str(tmp_path / "dest2"), "subdir": "_notes"},
            },
            "defaults": {"destinations": ["blog1", "blog2"]},
            "rules": [],
        }
        ws, gpath = self._setup_workspace(tmp_path, global_cfg, entries={
            "entry.md": {"entry_type": "note"},
        })

        (dest1 / "entry.md").write_bytes((ws / "blog" / "entry.md").read_bytes())

        entries, missing, entries_missing = plan(ws, gpath)
        assert len(entries) == 2
        present = [e for e in entries if e["present"] == "yes"]
        absent = [e for e in entries if e["present"] == "no"]
        assert len(present) == 1
        assert present[0]["dest"] == "blog1"
        assert len(absent) == 1
        assert absent[0]["dest"] == "blog2"
        assert len(entries_missing) == 1

    def test_workspace_override_with_extends(self, tmp_path):
        dest1 = tmp_path / "dest1"
        dest1.mkdir()
        dest2 = tmp_path / "dest2"
        dest2.mkdir()

        global_cfg = {
            "destinations": {"d1": {"path": str(dest1)}},
            "defaults": {"destinations": ["d1"]},
            "rules": [],
        }
        ws_cfg = {
            "extends": "~/.claude/blog-routing.yaml",
            "destinations": {"d2": {"path": str(dest2)}},
            "defaults": {"destinations": ["d2"]},
        }
        ws, gpath = self._setup_workspace(tmp_path, global_cfg, ws_cfg=ws_cfg, entries={
            "entry.md": {"entry_type": "note"},
        })

        entries, _, _ = plan(ws, gpath)
        # Workspace defaults replace global — entry goes to d2, not d1
        assert len(entries) == 1
        assert entries[0]["dest"] == "d2"

    def test_projects_bare_and_org_qualified(self, tmp_path):
        dest = tmp_path / "dest"
        dest.mkdir()

        global_cfg = {
            "destinations": {"d1": {"path": str(dest)}},
            "defaults": {"destinations": []},
            "rules": [
                {"match": {"project": "casehubio/engine"}, "destinations": ["d1"]},
            ],
        }
        ws, gpath = self._setup_workspace(tmp_path, global_cfg, entries={
            "org.md": {"entry_type": "note", "projects": ["casehubio/engine"]},
            "legacy.md": {"entry_type": "note", "projects": ["casehub-engine"]},
            "bare.md": {"entry_type": "note", "projects": ["engine"]},
            "other.md": {"entry_type": "note", "projects": ["other"]},
        })

        entries, _, _ = plan(ws, gpath)
        matched = {e["file"] for e in entries if e["dest"] == "d1"}
        assert matched == {"org.md", "legacy.md", "bare.md"}

    def test_index_md_skipped(self, tmp_path):
        global_cfg = {
            "destinations": {"d1": {"path": str(tmp_path / "dest")}},
            "defaults": {"destinations": ["d1"]},
            "rules": [],
        }
        ws, gpath = self._setup_workspace(tmp_path, global_cfg, entries={
            "entry.md": {"entry_type": "note"},
        })
        (ws / "blog" / "INDEX.md").write_text("---\ntitle: Index\n---\n")

        entries, _, _ = plan(ws, gpath)
        files = [e["file"] for e in entries]
        assert "INDEX.md" not in files


# The routing file in use on 2026-11-19, reduced to its rules. Pinned here so the
# resolution of real entries cannot change without a test changing with it.
REAL_GLOBAL = {
    "version": 1,
    "destinations": {
        "personal-notes": {"type": "git", "path": "/x/personal", "subdir": "_notes/"},
        "personal-articles": {"type": "git", "path": "/x/personal", "subdir": "_articles/"},
        "casehub-notes": {"type": "git", "path": "/x/casehub", "subdir": "_notes/"},
        "casehub-articles": {"type": "git", "path": "/x/casehub", "subdir": "_articles/"},
    },
    "defaults": {"destinations": ["personal-notes", "casehub-notes"]},
    "rules": [
        {"match": {"project": "casehubio/engine"},
         "destinations": ["personal-notes", "casehub-notes"]},
        {"match": {"project": "casehubio/engine", "entry_type": "article"},
         "destinations": ["personal-articles", "casehub-articles"]},
        {"match": {"project": "soredium"}, "destinations": ["personal-notes"]},
        {"match": {"project": "soredium", "entry_type": "article"},
         "destinations": ["personal-articles"]},
        {"match": {"project": "quarkus-langchain4j"}, "destinations": []},
        {"match": {"entry_type": "article"},
         "destinations": ["personal-articles", "casehub-articles"]},
        {"match": {"entry_type": "note"},
         "destinations": ["personal-notes", "casehub-notes"]},
    ],
}
CC_PRAXIS_OVERRIDE = {
    "version": 1,
    "extends": "~/.claude/blog-routing.yaml",
    "destinations": {"hortora-diary": {"type": "git", "path": "/x/hortora", "subdir": "_posts/"}},
    "defaults": {"destinations": ["hortora-diary"]},
    "rules": [{"match": {"entry_type": "note", "subtype": "diary"},
               "destinations": ["hortora-diary"]}],
}


class TestProjectRulesAreNotOverriddenByFallbacks:
    """#569: 87 hortora entries reached an organisation's site because every
    matching rule was unioned."""

    @pytest.fixture
    def routing(self, tmp_path):
        g = _write_routing(tmp_path / "global.yaml", REAL_GLOBAL)
        return load_routing(global_path=g)

    @pytest.fixture
    def cc_praxis(self, tmp_path):
        g = _write_routing(tmp_path / "global.yaml", REAL_GLOBAL)
        w = _write_routing(tmp_path / "ws.yaml", CC_PRAXIS_OVERRIDE)
        return load_routing(global_path=g, workspace_path=w)

    @pytest.mark.parametrize("projects", [["soredium"], ["Hortora/soredium"]])
    def test_a_soredium_note_never_reaches_a_casehub_destination(self, routing, projects):
        got = routing.resolve_destinations({"entry_type": "note", "projects": projects})
        assert got == {"personal-notes"}

    def test_a_soredium_article_goes_only_where_its_most_specific_rule_says(self, routing):
        got = routing.resolve_destinations({"entry_type": "article", "projects": ["soredium"]})
        assert got == {"personal-articles"}

    @pytest.mark.parametrize("entry_type", ["note", "article"])
    def test_an_empty_destination_list_means_nowhere(self, routing, entry_type):
        got = routing.resolve_destinations(
            {"entry_type": entry_type, "projects": ["quarkus-langchain4j"]})
        assert got == set()

    def test_casehub_engine_note_and_article(self, routing):
        note = routing.resolve_destinations(
            {"entry_type": "note", "projects": ["casehubio/engine"]})
        article = routing.resolve_destinations(
            {"entry_type": "article", "projects": ["casehubio/engine"]})
        assert note == {"personal-notes", "casehub-notes"}
        assert article == {"personal-articles", "casehub-articles"}

    def test_fallback_applies_when_no_project_rule_matches(self, routing):
        got = routing.resolve_destinations({"entry_type": "note", "projects": ["casehubio/ops"]})
        assert got == {"personal-notes", "casehub-notes"}

    def test_defaults_apply_only_when_nothing_matches(self, routing):
        got = routing.resolve_destinations({"entry_type": "brief", "projects": ["casehubio/ops"]})
        assert got == {"personal-notes", "casehub-notes"}

    def test_workspace_rule_adds_to_the_project_rule(self, cc_praxis):
        got = cc_praxis.resolve_destinations(
            {"entry_type": "note", "subtype": "diary", "projects": ["soredium"]})
        assert got == {"personal-notes", "hortora-diary"}

    def test_workspace_rule_does_not_bring_the_global_fallback_back(self, cc_praxis):
        got = cc_praxis.resolve_destinations(
            {"entry_type": "note", "subtype": "diary", "projects": ["Hortora/soredium"]})
        assert "casehub-notes" not in got and "casehub-articles" not in got

    def test_no_destination_of_another_organisation_for_any_soredium_entry(self, cc_praxis):
        for entry_type in ("note", "article"):
            for subtype in ("diary", "explanation", ""):
                fm = {"entry_type": entry_type, "projects": ["soredium"]}
                if subtype:
                    fm["subtype"] = subtype
                got = cc_praxis.resolve_destinations(fm)
                assert not any(d.startswith("casehub") for d in got), (fm, got)


# The routing file as proposed after #569: nothing reaches an organisation's
# site without a rule naming one of its projects.
PROPOSED_GLOBAL = {
    "version": 1,
    "destinations": REAL_GLOBAL["destinations"],
    "defaults": {"destinations": ["personal-notes"]},
    "rules": [
        {"match": {"project": "casehubio/*"},
         "destinations": ["personal-notes", "casehub-notes"]},
        {"match": {"project": "casehubio/*", "entry_type": "article"},
         "destinations": ["personal-articles", "casehub-articles"]},
        {"match": {"project": "quarkusio/quarkus-langchain4j"}, "destinations": []},
        {"match": {"entry_type": "article"}, "destinations": ["personal-articles"]},
        {"match": {"entry_type": "note"}, "destinations": ["personal-notes"]},
    ],
}


def _project_repo(tmp_path: Path, name: str, slug: str | None) -> Path:
    import subprocess as sp
    repo = tmp_path / "projects" / name
    repo.mkdir(parents=True)
    sp.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    if slug:
        sp.run(["git", "-C", str(repo), "remote", "add", "origin",
                f"https://github.com/{slug}.git"], check=True)
    return repo


def _workspace_for(tmp_path: Path, project: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "blog").mkdir(parents=True)
    (ws / "proj").symlink_to(project)
    return ws


class TestEntriesAreIdentifiedByTheirRepo:
    """#569: what an entry's frontmatter says cannot send it to another organisation."""

    @pytest.fixture
    def gpath(self, tmp_path):
        return _write_routing(tmp_path / "blog-routing.yaml", PROPOSED_GLOBAL)

    def _dests(self, ws, gpath):
        entries, _, _ = plan(ws, gpath, check_present_fn=lambda *_: False)
        return {e["dest"] for e in entries}

    def test_source_is_read_from_the_projects_remote(self, tmp_path):
        from blog_routing import source_identity
        project = _project_repo(tmp_path, "engine", "Hortora/engine")
        ws = _workspace_for(tmp_path, project)
        assert source_identity(ws) == "Hortora/engine"
        assert source_identity(project) == "Hortora/engine"

    def test_upstream_is_preferred_over_origin(self, tmp_path):
        import subprocess as sp
        from blog_routing import source_identity
        project = _project_repo(tmp_path, "ops", "someone/fork-of-ops")
        sp.run(["git", "-C", str(project), "remote", "add", "upstream",
                "git@github.com:casehubio/ops.git"], check=True)
        assert source_identity(project) == "casehubio/ops"

    def test_a_clone_answers_as_its_canonical_repo(self, tmp_path):
        import subprocess as sp
        from blog_routing import source_identity
        canonical = _project_repo(tmp_path, "soredium", "Hortora/soredium")
        clone = tmp_path / "clone" / "soredium"
        clone.mkdir(parents=True)
        sp.run(["git", "-C", str(clone), "init", "-q", "-b", "main"], check=True)
        sp.run(["git", "-C", str(clone), "remote", "add", "local", str(canonical)], check=True)
        assert source_identity(clone) == "Hortora/soredium"

    @pytest.mark.parametrize("projects", [["engine"], ["casehub-engine"], ["hortora-engine"],
                                          None])
    def test_a_hortora_entry_never_reaches_casehub_whatever_it_is_tagged(
            self, tmp_path, gpath, projects):
        project = _project_repo(tmp_path, "engine", "Hortora/engine")
        ws = _workspace_for(tmp_path, project)
        fm = {"entry_type": "note"}
        if projects is not None:
            fm["projects"] = projects
        _write_entry(ws / "blog", "2026-01-01-a.md", fm)
        assert self._dests(ws, gpath) == {"personal-notes"}

    @pytest.mark.parametrize("projects", [None, ["engine"], ["casehub-engine"]])
    def test_a_casehub_entry_reaches_casehub_even_untagged(self, tmp_path, gpath, projects):
        project = _project_repo(tmp_path, "engine", "casehubio/engine")
        ws = _workspace_for(tmp_path, project)
        fm = {"entry_type": "note"}
        if projects is not None:
            fm["projects"] = projects
        _write_entry(ws / "blog", "2026-01-01-a.md", fm)
        assert self._dests(ws, gpath) == {"personal-notes", "casehub-notes"}

    def test_a_casehub_article_goes_to_the_article_destinations(self, tmp_path, gpath):
        project = _project_repo(tmp_path, "ops", "casehubio/ops")
        ws = _workspace_for(tmp_path, project)
        _write_entry(ws / "blog", "2026-01-01-a.md", {"entry_type": "article"})
        assert self._dests(ws, gpath) == {"personal-articles", "casehub-articles"}

    def test_a_qualified_frontmatter_project_adds_a_second_project(self, tmp_path, gpath):
        project = _project_repo(tmp_path, "soredium", "Hortora/soredium")
        ws = _workspace_for(tmp_path, project)
        _write_entry(ws / "blog", "2026-01-01-a.md",
                     {"entry_type": "note", "projects": ["casehubio/engine"]})
        assert self._dests(ws, gpath) == {"personal-notes", "casehub-notes"}

    def test_a_rule_for_one_repo_publishes_nowhere(self, tmp_path, gpath):
        project = _project_repo(tmp_path, "lc4j", "someone/quarkus-langchain4j")
        import subprocess as sp
        sp.run(["git", "-C", str(project), "remote", "add", "upstream",
                "https://github.com/quarkusio/quarkus-langchain4j.git"], check=True)
        ws = _workspace_for(tmp_path, project)
        _write_entry(ws / "blog", "2026-01-01-a.md", {"entry_type": "note"})
        assert self._dests(ws, gpath) == set()

    def test_unknown_source_falls_back_to_frontmatter_and_says_so(self, tmp_path, gpath, capsys):
        project = _project_repo(tmp_path, "nameless", None)
        ws = _workspace_for(tmp_path, project)
        _write_entry(ws / "blog", "2026-01-01-a.md", {"entry_type": "note"})
        assert self._dests(ws, gpath) == {"personal-notes"}
        assert "WARN=source_unknown" in capsys.readouterr().err

    @pytest.mark.parametrize("rule, identity, expected", [
        ("casehubio/*", "casehubio/engine", True),
        ("casehubio/*", "CaseHubIO/Ops", True),
        ("casehubio/*", "Hortora/engine", False),
        ("casehubio/*", "casehubio-fork/engine", False),
        ("casehubio/engine", "casehubio/engine", True),
        ("casehubio/engine", "Hortora/engine", False),
        ("soredium", "Hortora/soredium", True),
        ("engine", "Hortora/engine", True),
    ])
    def test_identity_matching(self, rule, identity, expected):
        from blog_routing import _identity_matches
        assert _identity_matches(rule, identity) is expected


class TestUntypedEntriesAreNotes:
    """#572: an entry that does not say what it is is a note, routed by its repo."""

    def _ws(self, tmp_path, slug="casehubio/engine"):
        project = _project_repo(tmp_path, "p", slug)
        ws = _workspace_for(tmp_path, project)
        _write_entry(ws / "blog", "2026-01-01-good.md", {"entry_type": "article"})
        _write_entry(ws / "blog", "2026-01-02-untyped.md", {"title": "no type"})
        (ws / "blog" / "2026-01-03-bare.md").write_text("# No frontmatter at all\n")
        _write_entry(ws / "blog", "2026-01-04-diary.md", {"entry_type": "diary"})
        (ws / "blog" / "INDEX.md").write_text("# index\n")
        return ws

    def _routes(self, ws, tmp_path):
        gpath = _write_routing(tmp_path / "blog-routing.yaml", PROPOSED_GLOBAL)
        entries, _, _ = plan(ws, gpath, check_present_fn=lambda *_: False)
        out: dict[str, set[str]] = {}
        for e in entries:
            out.setdefault(e["file"], set()).add(e["dest"])
        return out

    def test_in_a_casehub_repo_they_go_to_both_notes_sites(self, tmp_path):
        routes = self._routes(self._ws(tmp_path), tmp_path)
        for name in ("2026-01-02-untyped.md", "2026-01-03-bare.md", "2026-01-04-diary.md"):
            assert routes[name] == {"personal-notes", "casehub-notes"}, name
        assert routes["2026-01-01-good.md"] == {"personal-articles", "casehub-articles"}

    def test_in_a_hortora_repo_they_go_to_personal_notes_only(self, tmp_path):
        routes = self._routes(self._ws(tmp_path, "Hortora/engine"), tmp_path)
        for name in ("2026-01-02-untyped.md", "2026-01-03-bare.md", "2026-01-04-diary.md"):
            assert routes[name] == {"personal-notes"}, name

    def test_each_is_named_with_its_reason(self, tmp_path):
        from blog_routing import defaulted
        assert defaulted(self._ws(tmp_path)) == [
            {"file": "2026-01-02-untyped.md", "reason": "no_entry_type"},
            {"file": "2026-01-03-bare.md", "reason": "no_frontmatter"},
            {"file": "2026-01-04-diary.md", "reason": "unknown_entry_type:diary"},
        ]

    def test_the_command_line_prints_them_and_a_count(self, tmp_path, capsys):
        from blog_routing import plan_cli
        ws = self._ws(tmp_path)
        gpath = _write_routing(tmp_path / "blog-routing.yaml", PROPOSED_GLOBAL)
        plan_cli(str(ws), str(gpath))
        out = capsys.readouterr().out
        assert "DEFAULTED=2026-01-03-bare.md AS=note REASON=no_frontmatter" in out
        assert "DEFAULTED_COUNT=3" in out
        assert "UNROUTABLE" not in out

    def test_a_fully_typed_workspace_reports_zero(self, tmp_path, capsys):
        from blog_routing import plan_cli
        project = _project_repo(tmp_path, "p", "casehubio/ops")
        ws = _workspace_for(tmp_path, project)
        _write_entry(ws / "blog", "2026-01-01-good.md", {"entry_type": "note"})
        gpath = _write_routing(tmp_path / "blog-routing.yaml", PROPOSED_GLOBAL)
        plan_cli(str(ws), str(gpath))
        assert "DEFAULTED_COUNT=0" in capsys.readouterr().out
