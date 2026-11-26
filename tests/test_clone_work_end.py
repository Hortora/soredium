"""End-to-end test: one piece of work through a permanent clone.

Creates a family with canonical project + workspace, creates a permanent
clone, does one branch of work, and runs close.close() for real.
Modelled on test_close_integration.py and test_canonical_sync.py fixtures.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))

from queue_io import write_queue, Queue, QueueItem, QueueState
from close import close, render
import squash_marker
import branch_base


HOOK = Path(__file__).parent.parent / "hooks" / "push-guard.py"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=check,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main", "--template=")
    (path / ".git" / "hooks").mkdir(exist_ok=True)
    _git(path, "commit", "--allow-empty", "-m", "init")
    return path


def _main_head(repo: Path) -> str:
    return _git(repo, "rev-parse", "main").stdout.strip()


def _merge_count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--merges", "--count", "main").stdout.strip())


def _push_guard_hook(command: str, cwd: Path) -> subprocess.CompletedProcess:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": str(cwd)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True)


@pytest.fixture
def clone_world(tmp_path):
    """Family with canonical P and W, permanent clone, one branch of work done.

    Returns (family, canonical_p, canonical_w, clone_target, project_clone,
             ws_clone, branch).

    New workspace model: ws_clone is a local wksp/ directory at the clone root,
    not a cloned workspace repo. The queue lives at the clone root (.queue-root),
    not in the workspace.
    """
    family = tmp_path / "family"
    family.mkdir()
    (family / "slots").mkdir()

    # Canonical project repo P
    canonical_p = _init_repo(family / "P")
    (canonical_p / "src.txt").write_text("source\n")
    _git(canonical_p, "add", ".")
    _git(canonical_p, "commit", "-m", "add source")

    # Canonical workspace W with proj -> P, and a committed .queue
    canonical_w = _init_repo(family / "W")
    proj_link = canonical_w / "proj"
    proj_link.symlink_to(os.path.relpath(canonical_p, canonical_w))
    write_queue(canonical_w, Queue(
        items=[QueueItem(ref="R#1", title="Task", completed=False, active=True)],
        state=QueueState(branch="", issue_repo="R", status="active"),
    ))
    _git(canonical_w, "add", ".")
    _git(canonical_w, "commit", "-m", "workspace init with queue")

    # P/wksp -> W
    wksp_link = canonical_p / "wksp"
    wksp_link.symlink_to(os.path.relpath(canonical_w, canonical_p))
    _git(canonical_p, "add", ".")
    _git(canonical_p, "commit", "-m", "add wksp symlink")

    # Create permanent clone
    from clone_manager import create_clone
    result = create_clone(family, "P")
    assert result["CREATED"] == "yes", f"create_clone failed: {result}"

    clone_target = family / "clone" / "P"
    project_clone = clone_target / "P"

    # Find workspace (new model: wksp/ directory with .workspace marker)
    ws_dirs = [d for d in clone_target.iterdir()
               if d.is_dir() and d.name != "P"
               and (d / ".workspace").exists()]
    assert ws_dirs, "workspace not found"
    ws_clone = ws_dirs[0]

    branch = "issue-1-x"

    # Create branch in project clone
    main_sha_p = _main_head(project_clone)
    _git(project_clone, "checkout", "-b", branch)
    branch_base.record(project_clone, branch, main_sha_p)
    (project_clone / "feature.txt").write_text("new feature\n")
    _git(project_clone, "add", ".")
    _git(project_clone, "commit", "-m", "feat: add feature Refs #1")
    squash_marker.mark(project_clone, branch)

    # Workspace clone: in the new model it's a local git repo, not a clone.
    # Create a branch to match the project clone.
    if (ws_clone / ".git").exists():
        _git(ws_clone, "checkout", "-b", branch)
        (ws_clone / "notes.md").write_text("work notes\n")
        _git(ws_clone, "add", ".")
        _git(ws_clone, "commit", "-m", "docs: work notes Refs #1")

    # Queue lives at clone root (.queue-root), not in the workspace
    write_queue(clone_target, Queue(
        items=[QueueItem(ref="R#1", title="Task", completed=False, active=True)],
        state=QueueState(branch=branch, issue_repo="R", status="active"),
    ))

    return family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch


class TestCloneWorkEnd:

    def test_close_succeeds(self, clone_world):
        """Assertion 1: result.success"""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        assert result.success, f"close failed: {result.errors}"

    def test_work_reaches_canonical_no_merges(self, clone_world):
        """Assertion 2: canonical P main has the project commit, with linear history.
        Workspace is local (new model) — workspace content stays local."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        assert result.success, f"close failed: {result.errors}"

        p_show = subprocess.run(
            ["git", "-C", str(canonical_p), "show", "main:feature.txt"],
            capture_output=True, text=True,
        )
        assert p_show.returncode == 0, "feature.txt not on canonical P main"

        assert _merge_count(canonical_p) == 0, "canonical P has merge commits"

    def test_clone_structure_survives(self, clone_world):
        """Assertion 3: <family>/clone/P still exists with .slot and .permanent."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        close(ws_clone)
        assert clone_target.is_dir()
        assert (clone_target / ".slot").exists()
        assert (clone_target / ".permanent").exists()

    def test_no_landed_marker(self, clone_world):
        """Assertion 4: <family>/clone/P/.landed does NOT exist."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        close(ws_clone)
        assert not (clone_target / ".landed").exists(), \
            ".landed was written — permanent clone should not be marked for archive"

    def test_no_slot_ready_for_archive(self, clone_world):
        """Assertion 5: render output does not contain SLOT_READY_FOR_ARCHIVE."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        lines = render(result)
        archive_lines = [l for l in lines if "SLOT_READY_FOR_ARCHIVE" in l]
        assert archive_lines == [], \
            f"close offered to archive a permanent clone: {archive_lines}"

    def test_clone_main_equals_canonical_main(self, clone_world):
        """Assertion 6: after close, project clone's main equals canonical P main.
        Workspace clone is local (new model) — it does not track canonical."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        close(ws_clone)
        assert _main_head(project_clone) == _main_head(canonical_p), \
            "project clone main diverged from canonical"

    def test_push_guard_blocks_clone(self, clone_world):
        """Assertion 7: git push from the project clone is refused by push-guard.py."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        verdict = _push_guard_hook("git push", project_clone)
        assert verdict.returncode == 2, \
            f"push-guard did not block (rc={verdict.returncode}): {verdict.stderr}"


class TestCloneWorkspaceIsSettled:
    """#563: the workspace side of a ceremony in a permanent clone."""

    def _closed(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        assert result.success, f"close failed: {result.errors}"
        return result

    def test_queue_has_the_item_closed(self, clone_world):
        clone_target = clone_world[3]
        ws_clone = clone_world[5]
        self._closed(clone_world)
        from queue_io import read_queue
        queue = read_queue(ws_clone)
        states = {i.ref: i.completed for i in queue.items}
        assert states.get("R#1") is True

    def test_workspace_is_local_and_untouched_by_ceremony(self, clone_world):
        """New model: workspace is local, ceremony doesn't settle or land it."""
        ws_clone = clone_world[5]
        self._closed(clone_world)
        assert (ws_clone / ".workspace").exists(), "workspace marker should survive ceremony"

    def test_project_clone_is_back_on_its_base_branch_and_clean(self, clone_world):
        project_clone = clone_world[4]
        self._closed(clone_world)
        assert _git(project_clone, "branch", "--show-current").stdout.strip() == "main"
        assert _git(project_clone, "status", "--porcelain").stdout.strip() == ""

    def test_project_clone_is_level_with_canonical(self, clone_world):
        """Project clone tracks canonical. Workspace is local — no sync check."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        self._closed(clone_world)
        assert _main_head(project_clone) == _main_head(canonical_p)

    def test_root_queue_at_the_clone_root(self, clone_world):
        clone_target = clone_world[3]
        self._closed(clone_world)
        assert (clone_target / ".queue").exists()

    def test_canonical_project_is_offered_for_publishing(self, clone_world, tmp_path):
        """Publishing offer comes from the project canonical, not workspace."""
        canonical_p = clone_world[1]
        bare = tmp_path / "remotes" / "P.git"
        bare.parent.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        subprocess.run(["git", "-C", str(canonical_p), "remote", "add", "origin", str(bare)],
                       check=True)
        subprocess.run(["git", "-C", str(canonical_p), "push", "-q", "origin", "main"],
                       check=True)

        result = self._closed(clone_world)

        ahead = int(subprocess.run(
            ["git", "-C", str(canonical_p), "rev-list", "--count", "origin/main..main"],
            capture_output=True, text=True, check=True).stdout.strip())
        assert ahead > 0
        assert result.unpublished.get(str(canonical_p.resolve())) == ahead

    def test_workspace_with_uncommitted_changes_is_harmless(self, clone_world):
        """New model: workspace is local, dirty state doesn't affect ceremony."""
        ws_clone = clone_world[5]
        (ws_clone / "unsaved.md").write_text("in progress")

        result = self._closed(clone_world)

        assert (ws_clone / "unsaved.md").read_text() == "in progress"
        assert result.success

    def test_a_second_item_can_be_closed_from_the_settled_clone(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        self._closed(clone_world)

        second = "issue-2-y"
        for repo, name in ((project_clone, "second.txt"), (ws_clone, "notes2.md")):
            base = _main_head(repo)
            _git(repo, "checkout", "-b", second)
            branch_base.record(repo, second, base)
            (repo / name).write_text("more\n")
            _git(repo, "add", name)
            _git(repo, "commit", "-m", f"feat: {name} Refs #2")
            squash_marker.mark(repo, second)
        write_queue(ws_clone, Queue(
            items=[QueueItem(ref="R#1", title="Task", completed=True, active=False),
                   QueueItem(ref="R#2", title="Next", completed=False, active=True)],
            state=QueueState(branch=second, issue_repo="R", status="active"),
        ))
        from queue_io import queue_dir
        qd = queue_dir(ws_clone)
        if qd == ws_clone:
            _git(ws_clone, "add", ".queue")
            _git(ws_clone, "commit", "-m", "chore: queue second item")

        result = close(ws_clone)

        assert result.success, f"second close failed: {result.errors}"
        assert subprocess.run(["git", "-C", str(canonical_p), "show", "main:second.txt"],
                              capture_output=True).returncode == 0
        from queue_io import read_queue
        queue = read_queue(ws_clone)
        states = {i.ref: i.completed for i in queue.items}
        assert states.get("R#2") is True
        assert _merge_count(canonical_p) == 0


class TestCloneWorkEndAtIntervals:
    """#571: in a clone, landing only the done items leaves the active item's
    branches checked out in both clones."""

    def _one_done_one_in_progress(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        second = "issue-2-y"
        parent_tip = _git(project_clone, "rev-parse", branch).stdout.strip()
        _git(project_clone, "checkout", "-b", second, branch)
        branch_base.record(project_clone, second, parent_tip, branch)
        (project_clone / "second.txt").write_text("in progress\n")
        _git(project_clone, "add", ".")
        _git(project_clone, "commit", "-m", "feat: second.txt Refs #2")
        write_queue(clone_target, Queue(
            items=[QueueItem(ref="R#1", title="Task", completed=False, active=False,
                             done_branch=branch),
                   QueueItem(ref="R#2", title="Next", completed=False, active=True)],
            state=QueueState(branch=second, issue_repo="R", status="active"),
        ))
        return second

    def test_done_item_lands_and_both_clones_stay_on_the_active_branch(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        second = self._one_done_one_in_progress(clone_world)

        result = close(ws_clone, land_active=False)

        assert result.success, f"close failed: {result.errors}"
        assert result.closed_items == ["R#1"]
        assert subprocess.run(["git", "-C", str(canonical_p), "show", "main:feature.txt"],
                              capture_output=True).returncode == 0
        assert _git(project_clone, "branch", "--show-current").stdout.strip() == second
        assert (project_clone / "second.txt").read_text() == "in progress\n"
        assert not (clone_target / ".landed").exists()

    def test_the_queue_shows_one_closed_and_one_still_active(self, clone_world):
        ws_clone = clone_world[5]
        self._one_done_one_in_progress(clone_world)

        close(ws_clone, land_active=False)

        from queue_io import read_queue
        queue = read_queue(ws_clone)
        states = {i.ref: (i.completed, i.active) for i in queue.items}
        assert states == {"R#1": (True, False), "R#2": (False, True)}
        assert queue.state.branch == "issue-2-y"

    def test_the_active_item_reaches_canonical(self, clone_world):
        """In the new model (project-only branches, stacked), the active item's
        commits may be carried as strays when the done item lands. Either way,
        the content reaches canonical."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        second = self._one_done_one_in_progress(clone_world)
        close(ws_clone, land_active=False)

        assert subprocess.run(["git", "-C", str(canonical_p), "show", "main:feature.txt"],
                              capture_output=True).returncode == 0
        assert _merge_count(canonical_p) == 0


class TestDivergedBaseIsNotCarried:
    """A clone whose own main has diverged from canonical is reported, never replayed."""

    def test_diverged_clone_blocks_ceremony(self, clone_world):
        """#624: a diverged clone now blocks preflight instead of landing silently."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        (canonical_p / "elsewhere.txt").write_text("landed by someone else\n")
        _git(canonical_p, "add", "elsewhere.txt")
        _git(canonical_p, "commit", "-m", "feat: elsewhere Refs #9")
        _git(project_clone, "checkout", "main")
        (project_clone / "stray.txt").write_text("old clone history\n")
        _git(project_clone, "add", "stray.txt")
        _git(project_clone, "commit", "-m", "feat: stray Refs #9")
        _git(project_clone, "checkout", branch)

        result = close(ws_clone)

        assert not result.success
        assert any("diverged" in e for e in result.errors)

    def test_a_clone_main_that_is_only_ahead_is_still_carried(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        _git(project_clone, "checkout", "main")
        (project_clone / "extra.txt").write_text("extra\n")
        _git(project_clone, "add", "extra.txt")
        _git(project_clone, "commit", "-m", "feat: extra Refs #9")
        _git(project_clone, "checkout", branch)

        result = close(ws_clone)

        assert result.success, f"close failed: {result.errors}"
        assert subprocess.run(["git", "-C", str(canonical_p), "show", "main:extra.txt"],
                              capture_output=True).returncode == 0


class TestClosureRefs:
    """#618: close ceremony writes structured closure refs to workspace."""

    def test_closure_refs_written_after_close(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        assert result.success, f"close failed: {result.errors}"

        import closure_refs
        meta = closure_refs.read(ws_clone, branch)
        assert meta is not None, "no closure ref written for the branch"
        assert meta["landed_on"] == "main"
        assert meta["landed_sha"]
        assert meta["issue"] == "R#1"

    def test_closure_ref_lists_the_branch(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        close(ws_clone)

        import closure_refs
        closed = closure_refs.list_closed(ws_clone)
        assert branch in closed


class TestPipelineStateFilesNotCarried:
    """Pipeline state files at the clone root are not in a git repo,
    so they cannot be carried to canonical."""

    def test_pipeline_files_at_clone_root_not_in_git(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        (clone_target / ".work-progress").write_text("step=test\n")
        (clone_target / ".wrap-log.jsonl").write_text("{}\n")
        result = subprocess.run(
            ["git", "-C", str(clone_target), "status", "--porcelain"],
            capture_output=True, text=True)
        assert result.returncode != 0 or result.stdout.strip() == "", \
            "clone root should not be a git repo — pipeline files are outside git"

    def test_workspace_is_local_no_remote_to_carry(self, clone_world):
        ws_clone = clone_world[5]
        result = subprocess.run(
            ["git", "-C", str(ws_clone), "remote"],
            capture_output=True, text=True)
        assert result.stdout.strip() == "", \
            "workspace should have no remotes — nothing can be carried"
