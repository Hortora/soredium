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
