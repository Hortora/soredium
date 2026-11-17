"""git-squash/hooks/pre-push, installed in a real repo and exercised with real pushes.

The hook checks only what is decidable: no merge commits onto a base branch, no
rewriting of a base branch, no deleting it. It replaced two hooks that judged
commit subjects or refused every push outright.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "git-squash" / "hooks" / "pre-push"


def g(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=check)


def commit(repo: Path, name: str, message: str) -> str:
    (repo / name).write_text(name + "\n")
    g(repo, "add", ".")
    g(repo, "commit", "-q", "-m", message)
    return g(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def world(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)],
                   capture_output=True, check=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    g(repo, "init", "-q", "-b", "main")
    g(repo, "config", "user.name", "T")
    g(repo, "config", "user.email", "t@t")
    commit(repo, "a.txt", "init")
    g(repo, "remote", "add", "origin", str(remote))
    g(repo, "push", "-q", "-u", "origin", "main")
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HOOK, hook)
    hook.chmod(0o755)
    return repo, remote


def remote_main(remote: Path) -> str:
    return g(remote, "rev-parse", "main").stdout.strip()


def merge_into_main(repo: Path) -> str:
    g(repo, "checkout", "-q", "-b", "side")
    commit(repo, "side.txt", "feat: side")
    g(repo, "checkout", "-q", "main")
    commit(repo, "main.txt", "feat: main")
    g(repo, "merge", "-q", "--no-ff", "side", "-m", "Merge branch 'side'")
    return g(repo, "rev-parse", "HEAD").stdout.strip()


class TestAllows:
    def test_linear_commits_to_main(self, world):
        repo, remote = world
        tip = commit(repo, "b.txt", "chore: apply spotless")     # a subject the old hook refused

        result = g(repo, "push", "origin", "main", check=False)

        assert result.returncode == 0, result.stderr
        assert remote_main(remote) == tip

    def test_any_number_of_commits_with_any_subjects(self, world):
        repo, remote = world
        for subject in ("fix(test): flaky", 'Revert "feat: x"', "docs: fix stale link", "ci: retrigger"):
            tip = commit(repo, subject.replace(" ", "-").replace('"', "") + ".txt", subject)

        result = g(repo, "push", "origin", "main", check=False)

        assert result.returncode == 0, result.stderr
        assert remote_main(remote) == tip

    def test_merge_commits_on_a_working_branch_are_not_its_business(self, world):
        repo, remote = world
        merge_into_main(repo)
        g(repo, "branch", "-m", "main", "feature")

        result = g(repo, "push", "origin", "feature", check=False)

        assert result.returncode == 0, result.stderr

    def test_merges_the_remote_already_has_do_not_block_later_pushes(self, world):
        repo, remote = world
        merge_into_main(repo)
        g(repo, "push", "--no-verify", "origin", "main")          # history from before the rule
        tip = commit(repo, "later.txt", "feat: later")

        result = g(repo, "push", "origin", "main", check=False)

        assert result.returncode == 0, result.stderr
        assert remote_main(remote) == tip

    def test_first_push_of_main_to_an_empty_remote(self, world, tmp_path):
        repo, remote = world
        empty = tmp_path / "empty.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(empty)],
                       capture_output=True, check=True)
        g(repo, "remote", "add", "other", str(empty))

        result = g(repo, "push", "other", "main", check=False)

        assert result.returncode == 0, result.stderr

    def test_tags_and_other_refs(self, world):
        repo, remote = world
        g(repo, "tag", "v1")
        assert g(repo, "push", "origin", "v1", check=False).returncode == 0


class TestRefuses:
    def test_a_merge_commit_onto_main(self, world):
        repo, remote = world
        before = remote_main(remote)
        merge_into_main(repo)

        result = g(repo, "push", "origin", "main", check=False)

        assert result.returncode != 0
        assert "merge commit" in result.stderr and "Merge branch 'side'" in result.stderr
        assert "work end" in result.stderr
        assert remote_main(remote) == before

    def test_a_forced_push_that_rewrites_main(self, world):
        repo, remote = world
        commit(repo, "b.txt", "feat: b")
        g(repo, "push", "-q", "origin", "main")
        published = remote_main(remote)
        g(repo, "reset", "-q", "--hard", "HEAD~1")
        commit(repo, "c.txt", "feat: c instead")

        result = g(repo, "push", "--force", "origin", "main", check=False)

        assert result.returncode != 0
        assert "rewrite main" in result.stderr
        assert "canonical_sync.py publish" in result.stderr
        assert remote_main(remote) == published

    def test_deleting_main_on_the_remote(self, world):
        repo, remote = world
        before = remote_main(remote)

        result = g(repo, "push", "origin", ":main", check=False)

        assert result.returncode != 0
        assert "refusing to delete main" in result.stderr
        assert remote_main(remote) == before

    def test_pushing_another_branch_onto_main_with_a_merge_in_it(self, world):
        repo, remote = world
        before = remote_main(remote)
        merge_into_main(repo)
        g(repo, "branch", "-m", "main", "feature")

        result = g(repo, "push", "origin", "feature:main", check=False)

        assert result.returncode != 0
        assert remote_main(remote) == before


def test_publish_goes_through_the_hook(world):
    """canonical_sync publishes with a plain push, so the hook must let reviewed, linear
    work through. The hooks it replaced refused every push or judged subjects."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
    import canonical_sync
    repo, remote = world
    tip = commit(repo, "b.txt", "docs: fix stale wording")

    result = canonical_sync.publish_base(repo)

    assert result.published == "origin"
    assert remote_main(remote) == tip
