"""work-end/artifact_promote.py: promotions are commits that land on disk; nothing pushes or pulls."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"


def g(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=check).stdout.strip()


def init(path: Path) -> Path:
    path.mkdir(parents=True)
    g(path, "init", "-q", "-b", "main")
    g(path, "config", "user.name", "T")
    g(path, "config", "user.email", "t@t")
    (path / "README.md").write_text("init\n")
    g(path, "add", ".")
    g(path, "commit", "-q", "-m", "init")
    return path


def with_remote(repo: Path, bare: Path) -> Path:
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)],
                   capture_output=True, check=True)
    g(repo, "remote", "add", "origin", str(bare))
    g(repo, "push", "-q", "-u", "origin", "main")
    return bare


def slot_clone(canon: Path, slot: Path) -> Path:
    slot.mkdir(parents=True, exist_ok=True)
    (slot / ".slot").write_text("# Slot\n")
    clone = slot / canon.name
    subprocess.run(["git", "clone", "-q", str(canon), str(clone)], capture_output=True, check=True)
    g(clone, "config", "user.name", "T")
    g(clone, "config", "user.email", "t@t")
    g(clone, "remote", "rename", "origin", "local")
    return clone


def run(*args: str) -> tuple[int, dict[str, str], str]:
    result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    out = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key] = value
    return result.returncode, out, result.stdout + result.stderr


def refs(repo: Path) -> list[str]:
    return g(repo, "for-each-ref", "--format=%(refname)").split()


class TestToWorkspaceMain:
    def _on_branch(self, tmp_path):
        ws = init(tmp_path / "workspace")
        bare = with_remote(ws, tmp_path / "ws.git")
        g(ws, "checkout", "-q", "-b", "issue-1")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("an entry\n")
        g(ws, "add", ".")
        g(ws, "commit", "-q", "-m", "docs: entry")
        return ws, bare

    def test_artifact_reaches_main_and_nothing_is_pushed(self, tmp_path):
        ws, bare = self._on_branch(tmp_path)
        remote_before = g(bare, "rev-parse", "main")

        rc, out, text = run("to-workspace-main", str(ws), "branch=issue-1", "artifacts=blog/entry.md")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        assert out["LANDED"] == "yes"
        assert g(ws, "show", "main:blog/entry.md") == "an entry"
        assert g(bare, "rev-parse", "main") == remote_before
        assert refs(bare) == ["refs/heads/main"]
        assert "PUSHED" not in out

    def test_the_workspace_checkout_and_its_uncommitted_work_are_untouched(self, tmp_path):
        ws, _ = self._on_branch(tmp_path)
        (ws / "draft.md").write_text("uncommitted\n")
        (ws / "README.md").write_text("edited, uncommitted\n")

        rc, out, text = run("to-workspace-main", str(ws), "branch=issue-1", "artifacts=blog/entry.md")

        assert rc == 0, text
        assert g(ws, "branch", "--show-current") == "issue-1"
        assert (ws / "draft.md").read_text() == "uncommitted\n"
        assert (ws / "README.md").read_text() == "edited, uncommitted\n"
        assert g(ws, "stash", "list") == ""
        assert len(g(ws, "worktree", "list").splitlines()) == 1
        assert not (ws / ".promote-tmp").exists()

    def test_works_when_the_workspace_is_already_on_main(self, tmp_path):
        """It used to fail here: main cannot be added as a second worktree while checked out."""
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("an entry\n")

        rc, out, text = run("to-workspace-main", str(ws), "branch=main", "artifacts=blog/entry.md")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        assert g(ws, "show", "main:blog/entry.md") == "an entry"

    def test_unreachable_remote_makes_no_difference(self, tmp_path):
        ws, bare = self._on_branch(tmp_path)
        g(ws, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

        rc, out, text = run("to-workspace-main", str(ws), "branch=issue-1", "artifacts=blog/entry.md")

        assert rc == 0, text
        assert out["LANDED"] == "yes"

    def test_in_a_slot_the_artifact_reaches_the_canonical_workspace(self, tmp_path):
        canon = init(tmp_path / "workspace")
        clone = slot_clone(canon, tmp_path / "slots" / "5")
        g(canon, "checkout", "-q", "-b", "someone-elses-work")
        (canon / "wip.md").write_text("uncommitted\n")
        g(clone, "checkout", "-q", "-b", "issue-1", "main")
        (clone / "blog").mkdir()
        (clone / "blog" / "entry.md").write_text("an entry\n")
        g(clone, "add", ".")
        g(clone, "commit", "-q", "-m", "docs: entry")

        rc, out, text = run("to-workspace-main", str(clone), "branch=issue-1", "artifacts=blog/entry.md")

        assert rc == 0, text
        assert out["LANDED"] == "yes"
        assert g(canon, "show", "main:blog/entry.md") == "an entry"
        assert g(canon, "branch", "--show-current") == "someone-elses-work"
        assert (canon / "wip.md").read_text() == "uncommitted\n"
        assert g(canon, "rev-list", "--merges", "--count", "main") == "0"

    def test_missing_artifact_is_reported_not_counted(self, tmp_path):
        ws, _ = self._on_branch(tmp_path)

        rc, out, text = run("to-workspace-main", str(ws), "branch=issue-1",
                            "artifacts=blog/entry.md,blog/nope.md")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        assert out["SKIPPED_PATHS"] == "blog/nope.md"


def test_markdown_promotion_commits_and_exits_cleanly(tmp_path):
    """Every markdown promotion used to die with ModuleNotFoundError after staging the file
    and before committing it, and still exit 0: the artifact was left staged, uncommitted."""
    proj = init(tmp_path / "project")
    ws = init(tmp_path / "workspace")
    (ws / "blog").mkdir()
    (ws / "blog" / "entry.md").write_text("an entry\n")

    rc, out, text = run("to-project", str(proj), str(ws), "artifacts=blog/entry.md", "dest-prefix=docs/")

    assert rc == 0, text
    assert "Traceback" not in text
    assert out["PROMOTED"] == "1"
    assert g(proj, "show", "main:docs/blog/entry.md") == "an entry"
    assert g(proj, "status", "--porcelain") == ""


class TestToProject:
    def _pair(self, tmp_path):
        proj = init(tmp_path / "project")
        bare = with_remote(proj, tmp_path / "proj.git")
        ws = init(tmp_path / "workspace")
        (ws / "specs").mkdir()
        (ws / "specs" / "design.md").write_text("the design\n")
        return proj, ws, bare

    def test_commit_on_the_base_branch_is_landed_and_not_pushed(self, tmp_path):
        proj, ws, bare = self._pair(tmp_path)
        remote_before = g(bare, "rev-parse", "main")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=specs/design.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["PROMOTED"] == "1"
        assert out["LANDED"] == "yes"
        assert g(proj, "show", "main:docs/specs/design.md") == "the design"
        assert g(bare, "rev-parse", "main") == remote_before

    def test_commit_on_a_working_branch_rides_with_the_branch(self, tmp_path):
        proj, ws, bare = self._pair(tmp_path)
        g(proj, "checkout", "-q", "-b", "issue-1")

        rc, out, text = run("to-project", str(proj), str(ws),
                            "artifacts=specs/design.md", "dest-prefix=docs/", "scope=branch")

        assert rc == 0, text
        assert out["LANDED"] == "branch"
        assert g(proj, "show", "issue-1:docs/specs/design.md") == "the design"
        assert refs(bare) == ["refs/heads/main"]          # the branch was not pushed

    def test_in_a_slot_on_the_base_branch_it_reaches_canonical(self, tmp_path):
        canon, ws, _ = self._pair(tmp_path)
        clone = slot_clone(canon, tmp_path / "slots" / "5")

        rc, out, text = run("to-project", str(clone), str(ws),
                            "artifacts=specs/design.md", "dest-prefix=docs/")

        assert rc == 0, text
        assert out["LANDED"] == "yes"
        assert g(canon, "show", "main:docs/specs/design.md") == "the design"

    def test_a_promotion_that_cannot_land_says_so(self, tmp_path):
        canon, ws, _ = self._pair(tmp_path)
        clone = slot_clone(canon, tmp_path / "slots" / "5")
        (canon / "docs" / "specs").mkdir(parents=True)
        (canon / "docs" / "specs" / "design.md").write_text("a different design already here\n")
        g(canon, "add", ".")
        g(canon, "commit", "-q", "-m", "docs: conflicting design")
        canon_before = g(canon, "rev-parse", "main")

        rc, out, text = run("to-project", str(clone), str(ws),
                            "artifacts=specs/design.md", "dest-prefix=docs/")

        assert out["LANDED"] == "no"
        assert "design.md" in out["LAND_ERROR"]
        assert g(canon, "rev-parse", "main") == canon_before


class TestArchivePlans:
    def test_plans_are_archived_on_main_without_a_push(self, tmp_path):
        ws = init(tmp_path / "workspace")
        bare = with_remote(ws, tmp_path / "ws.git")
        g(ws, "checkout", "-q", "-b", "issue-1")
        (ws / "plans").mkdir()
        (ws / "plans" / "plan-a.md").write_text("plan a\n")
        g(ws, "add", ".")
        g(ws, "commit", "-q", "-m", "docs: plan")
        remote_before = g(bare, "rev-parse", "main")

        rc, out, text = run("archive-plans", str(ws), "branch=issue-1")

        assert rc == 0, text
        assert out["ARCHIVED"] == "1"
        assert g(ws, "show", "main:plans/attic/issue-1/plan-a.md") == "plan a"
        assert g(bare, "rev-parse", "main") == remote_before
        assert g(ws, "branch", "--show-current") == "issue-1"
        assert (ws / "plans" / "plan-a.md").exists()       # the branch's own copy is not removed

    def test_on_main_the_plan_moves_into_the_attic(self, tmp_path):
        ws = init(tmp_path / "workspace")
        (ws / "plans").mkdir()
        (ws / "plans" / "plan-a.md").write_text("plan a\n")
        g(ws, "add", ".")
        g(ws, "commit", "-q", "-m", "docs: plan")

        rc, out, text = run("archive-plans", str(ws), "branch=issue-1")

        assert rc == 0, text
        assert out["ARCHIVED"] == "1"
        assert g(ws, "show", "main:plans/attic/issue-1/plan-a.md") == "plan a"
        assert not (ws / "plans" / "plan-a.md").exists()
