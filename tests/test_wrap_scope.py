"""work-end/scope.py: follow-up actions reach exactly what the ceremony covered (#571)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _d in ("work-end", "project", "work-slot"):
    sys.path.insert(0, str(ROOT / _d))

import scope  # noqa: E402


def g(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


def repo_with_remote(tmp_path: Path, name: str) -> tuple[Path, Path]:
    bare = tmp_path / "remotes" / f"{name}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo = tmp_path / name
    repo.mkdir()
    g(repo, "init", "-q", "-b", "main")
    (repo / "seed.txt").write_text(name)
    g(repo, "add", ".")
    g(repo, "commit", "-q", "-m", "init")
    g(repo, "remote", "add", "origin", str(bare))
    g(repo, "push", "-q", "origin", "main")
    return repo, bare


def commit(repo: Path, name: str, text: str = "x") -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    g(repo, "add", name)
    g(repo, "commit", "-q", "-m", f"add {name}")


def remote_main(bare: Path) -> str:
    return g(bare, "rev-parse", "refs/heads/main")


@pytest.fixture
def world(tmp_path):
    """A project and its workspace, each with a remote, plus an unrelated repo that is ahead."""
    project, project_remote = repo_with_remote(tmp_path, "project")
    workspace, workspace_remote = repo_with_remote(tmp_path, "workspace")
    (workspace / "proj").symlink_to(project)
    (project / "wksp").symlink_to(workspace)
    # As workspace-init does: the links are local, never tracked and never "dirty".
    (project / ".git" / "info" / "exclude").write_text("wksp\n")
    (workspace / ".git" / "info" / "exclude").write_text("proj\n")
    other, other_remote = repo_with_remote(tmp_path, "unrelated")
    commit(other, "elsewhere.txt")
    return dict(project=project, project_remote=project_remote, workspace=workspace,
                workspace_remote=workspace_remote, other=other, other_remote=other_remote)


class TestCovered:

    def test_project_and_workspace_and_nothing_else(self, world):
        assert scope.covered(world["workspace"]) == [world["project"].resolve(),
                                                     world["workspace"].resolve()]

    def test_one_repo_serving_as_both_is_listed_once(self, tmp_path):
        repo, _ = repo_with_remote(tmp_path, "solo")
        assert scope.covered(repo) == [repo.resolve()]

    def test_a_slot_covers_its_repos_as_their_canonicals(self, tmp_path):
        canonical, _ = repo_with_remote(tmp_path, "engine")
        ws_canonical, _ = repo_with_remote(tmp_path, "wsp")
        slot = tmp_path / "slots" / "7"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("# Slot 7\n\n## Repos\n- engine (primary)\n")
        for source, name in ((canonical, "engine"), (ws_canonical, "wsp")):
            subprocess.run(["git", "clone", "-q", "--shared", str(source), str(slot / name)],
                           check=True)
            g(slot / name, "remote", "rename", "origin", "local")
        (slot / "wsp" / ".workspace").write_text(f"project: {canonical}\n")
        found = scope.covered(slot / "wsp")
        assert canonical.resolve() in found and ws_canonical.resolve() in found
        assert all(".git" not in str(p) and "slots" not in p.parts for p in found)


class TestPublish:

    def test_publishes_both_covered_repos(self, world):
        commit(world["project"], "code.txt")
        commit(world["workspace"], "notes.md")

        pushed, failed = scope.publish(world["workspace"])

        assert failed == {}
        assert pushed == {str(world["project"].resolve()): 1, str(world["workspace"].resolve()): 1}
        assert remote_main(world["project_remote"]) == g(world["project"], "rev-parse", "main")
        assert remote_main(world["workspace_remote"]) == g(world["workspace"], "rev-parse", "main")

    def test_an_unrelated_repo_that_is_ahead_is_never_touched(self, world):
        commit(world["project"], "code.txt")
        before = remote_main(world["other_remote"])

        scope.publish(world["workspace"])

        assert remote_main(world["other_remote"]) == before
        assert g(world["other"], "rev-list", "--count", "origin/main..main") == "1"

    def test_nothing_ahead_publishes_nothing(self, world):
        assert scope.publish(world["workspace"]) == ({}, {})

    def test_a_repo_with_no_remote_is_skipped_quietly(self, world, tmp_path):
        g(world["workspace"], "remote", "remove", "origin")
        commit(world["project"], "code.txt")
        commit(world["workspace"], "notes.md")
        pushed, failed = scope.publish(world["workspace"])
        assert list(pushed) == [str(world["project"].resolve())] and failed == {}

    def test_one_failure_does_not_stop_the_other(self, world):
        commit(world["project"], "code.txt")
        commit(world["workspace"], "notes.md")
        g(world["project"], "remote", "set-url", "origin", str(world["project"] / "nowhere.git"))

        pushed, failed = scope.publish(world["workspace"])

        assert str(world["workspace"].resolve()) in pushed
        assert str(world["project"].resolve()) in failed

    def test_command_line(self, world, capsys):
        commit(world["project"], "code.txt")
        assert scope.main(["publish", str(world["workspace"])]) == 0
        out = capsys.readouterr().out
        assert f"PUBLISHED={world['project'].resolve()} commits=1" in out
        assert "PUBLISHED_COUNT=1" in out
        assert "unrelated" not in out


class TestPromoteBacklog:

    def test_promotes_what_the_project_lacks(self, world):
        commit(world["workspace"], "blog/2026-01-01-entry.md", "# Entry\n")

        promoted, failed = scope.promote_backlog(world["workspace"])

        assert failed == {}
        assert promoted == {"workspace -> project": 1}
        assert g(world["project"], "show", "main:docs/blog/2026-01-01-entry.md") == "# Entry"
        assert g(world["project"], "status", "--porcelain") == ""

    def test_nothing_missing_does_nothing(self, world):
        tip = g(world["project"], "rev-parse", "main")
        assert scope.promote_backlog(world["workspace"]) == ({}, {})
        assert g(world["project"], "rev-parse", "main") == tip

    def test_another_workspace_with_a_backlog_is_not_touched(self, world, tmp_path):
        other_project, _ = repo_with_remote(tmp_path, "other-project")
        other_ws, _ = repo_with_remote(tmp_path, "other-ws")
        (other_ws / "proj").symlink_to(other_project)
        commit(other_ws, "blog/2026-02-02-theirs.md")
        tip = g(other_project, "rev-parse", "main")

        scope.promote_backlog(world["workspace"])

        assert g(other_project, "rev-parse", "main") == tip

    def test_command_line(self, world, capsys):
        commit(world["workspace"], "blog/2026-01-01-entry.md", "# Entry\n")
        assert scope.main(["promote-backlog", str(world["workspace"])]) == 0
        out = capsys.readouterr().out
        assert "PROMOTED=workspace -> project documents=1" in out
        assert "PROMOTED_COUNT=1" in out


class TestCommandLine:

    def test_usage(self, capsys):
        assert scope.main([]) == 2
        assert scope.main(["publish"]) == 2

    def test_missing_workspace(self, tmp_path, capsys):
        assert scope.main(["covered", str(tmp_path / "absent")]) == 1
        assert "ERROR=workspace_not_found" in capsys.readouterr().out

    def test_covered_prints_one_line_per_repo(self, world, capsys):
        assert scope.main(["covered", str(world["workspace"])]) == 0
        out = capsys.readouterr().out.splitlines()
        assert out == [f"COVERED={world['project'].resolve()}",
                       f"COVERED={world['workspace'].resolve()}"]


def routing_for(tmp_path: Path, site: Path) -> Path:
    import yaml
    path = tmp_path / "routing" / "blog-routing.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "version": 1,
        "destinations": {"site-notes": {"type": "git", "path": str(site), "subdir": "_notes/"}},
        "defaults": {"destinations": ["site-notes"]},
        "rules": [],
    }))
    return path


ENTRY = "---\ntitle: T\nentry_type: note\n---\n\nBody.\n"


class TestPublishBlog:
    """Only landed entries of the covered projects go out, one commit per site."""

    @pytest.fixture
    def blog(self, world, tmp_path):
        site, site_remote = repo_with_remote(tmp_path, "site")
        g(world["project"], "remote", "set-url", "origin", "https://github.com/acme/project.git")
        world.update(site=site, site_remote=site_remote, routing=routing_for(tmp_path, site))
        return world

    def test_a_landed_entry_is_posted_committed_and_published(self, blog):
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY)

        posted, held = scope.publish_blog(blog["workspace"], blog["routing"])

        assert held == {}
        assert posted == {"site-notes": 1}
        assert g(blog["site"], "show", "main:_notes/2026-01-01-a.md").startswith("---")
        assert g(blog["site"], "show", "--name-only", "--format=", "main") == "_notes/2026-01-01-a.md"
        assert remote_main(blog["site_remote"]) == g(blog["site"], "rev-parse", "main")
        assert g(blog["site"], "status", "--porcelain") == ""

    def test_running_again_posts_nothing(self, blog):
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY)
        scope.publish_blog(blog["workspace"], blog["routing"])
        tip = g(blog["site"], "rev-parse", "main")
        assert scope.publish_blog(blog["workspace"], blog["routing"]) == ({}, {})
        assert g(blog["site"], "rev-parse", "main") == tip

    def test_a_revised_entry_replaces_the_published_one(self, blog):
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY)
        scope.publish_blog(blog["workspace"], blog["routing"])
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY + "Revised.\n")

        posted, held = scope.publish_blog(blog["workspace"], blog["routing"])

        assert posted == {"site-notes": 1} and held == {}
        assert "Revised." in g(blog["site"], "show", "main:_notes/2026-01-01-a.md")

    def test_an_entry_only_on_a_working_branch_is_not_published(self, blog):
        g(blog["project"], "checkout", "-q", "-b", "issue-1-x")
        commit(blog["project"], "docs/blog/2026-01-02-unlanded.md", ENTRY)

        posted, held = scope.publish_blog(blog["workspace"], blog["routing"])

        assert posted == {}
        assert not (blog["site"] / "_notes" / "2026-01-02-unlanded.md").exists()
        assert g(blog["project"], "symbolic-ref", "--short", "HEAD") == "issue-1-x"

    def test_landed_entries_are_published_while_another_branch_is_checked_out(self, blog):
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY)
        g(blog["project"], "checkout", "-q", "-b", "issue-1-x")
        commit(blog["project"], "docs/blog/2026-01-02-unlanded.md", ENTRY)

        posted, held = scope.publish_blog(blog["workspace"], blog["routing"])

        assert posted == {"site-notes": 1}
        assert (blog["site"] / "_notes" / "2026-01-01-a.md").exists()
        assert not (blog["site"] / "_notes" / "2026-01-02-unlanded.md").exists()

    def test_uncommitted_blog_changes_on_the_base_branch_hold_the_project_back(self, blog):
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY)
        (blog["project"] / "docs" / "blog" / "2026-01-01-a.md").write_text(ENTRY + "unsaved\n")

        posted, held = scope.publish_blog(blog["workspace"], blog["routing"])

        assert posted == {}
        assert "uncommitted changes under docs/blog" in held["project"]
        assert not (blog["site"] / "_notes").exists()

    def test_a_project_with_no_blog_entries_is_passed_over_quietly(self, blog):
        g(blog["project"], "remote", "remove", "origin")
        assert scope.publish_blog(blog["workspace"], blog["routing"]) == ({}, {})

    def test_problems_are_reported_without_failing_the_command(self, blog, capsys):
        g(blog["project"], "remote", "remove", "origin")
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY)
        assert scope.main(["publish-blog", str(blog["workspace"]),
                           f"routing={blog['routing']}"]) == 0
        assert "BLOG_HELD=project reason=" in capsys.readouterr().out

    def test_a_project_with_no_remote_is_never_routed_on_a_guess(self, blog):
        g(blog["project"], "remote", "remove", "origin")
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY)
        posted, held = scope.publish_blog(blog["workspace"], blog["routing"])
        assert posted == {} and "no remote to identify it" in held["project"]

    def test_other_staged_work_in_the_site_repo_stays_out_of_the_commit(self, blog):
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY)
        (blog["site"] / "draft.md").write_text("someone else's")
        g(blog["site"], "add", "draft.md")

        scope.publish_blog(blog["workspace"], blog["routing"])

        assert g(blog["site"], "show", "--name-only", "--format=", "main") == "_notes/2026-01-01-a.md"
        assert g(blog["site"], "status", "--porcelain") == "A  draft.md"

    def test_a_site_repo_on_another_branch_is_not_committed_to(self, blog):
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY)
        g(blog["site"], "checkout", "-q", "-b", "redesign")
        tip = g(blog["site"], "rev-parse", "main")

        posted, held = scope.publish_blog(blog["workspace"], blog["routing"])

        assert g(blog["site"], "rev-parse", "main") == tip
        assert any("not main" in why for why in held.values())

    def test_another_projects_entries_are_not_published(self, blog, tmp_path):
        other_project, _ = repo_with_remote(tmp_path, "other-project")
        g(other_project, "remote", "set-url", "origin", "https://github.com/acme/other.git")
        commit(other_project, "docs/blog/2026-03-03-theirs.md", ENTRY)

        scope.publish_blog(blog["workspace"], blog["routing"])

        assert not (blog["site"] / "_notes" / "2026-03-03-theirs.md").exists()

    def test_command_line(self, blog, capsys):
        commit(blog["project"], "docs/blog/2026-01-01-a.md", ENTRY)
        assert scope.main(["publish-blog", str(blog["workspace"]), f"routing={blog['routing']}"]) == 0
        out = capsys.readouterr().out
        assert "BLOG_PUBLISHED=site-notes entries=1" in out
        assert "BLOG_PUBLISHED_COUNT=1" in out
