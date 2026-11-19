"""`work wrap` and `work end` driven step by step on real repos (#571)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _d in ("project", "work-slot", "work-end"):
    sys.path.insert(0, str(ROOT / _d))

import branch_base  # noqa: E402
import squash_marker  # noqa: E402
import work  # noqa: E402
from queue_io import Queue, QueueItem, QueueState, read_queue, write_queue  # noqa: E402

WORK = str(ROOT / "project" / "work.py")
BRANCH = "issue-1-x"


def g(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


def with_remote(tmp_path: Path, name: str) -> tuple[Path, Path]:
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
    (repo / name).write_text(text)
    g(repo, "add", name)
    g(repo, "commit", "-q", "-m", f"feat: {name} Refs O/r#1")


@pytest.fixture
def world(tmp_path):
    """Project and workspace on a working branch for the one active item, each with a remote."""
    project, project_remote = with_remote(tmp_path, "project")
    workspace, workspace_remote = with_remote(tmp_path, "workspace")
    (workspace / "proj").symlink_to(project)
    (project / ".git" / "info" / "exclude").write_text("wksp\n")
    (workspace / ".git" / "info" / "exclude").write_text("proj\n.work-progress\n")
    for repo, name in ((project, "code.txt"), (workspace, "notes.md")):
        base = g(repo, "rev-parse", "main")
        g(repo, "checkout", "-q", "-b", BRANCH)
        branch_base.record(repo, BRANCH, base)
        commit(repo, name)
        squash_marker.mark(repo, BRANCH)
    write_queue(workspace, Queue(
        items=[QueueItem(ref="o/r#1", title="First", completed=False, active=True),
               QueueItem(ref="o/r#2", title="Second", completed=False, active=False)],
        state=QueueState(branch=BRANCH, issue_repo="O/r", status="active", covers="o/r#1")))
    g(workspace, "add", ".queue")
    g(workspace, "commit", "-q", "-m", "chore: queue Refs O/r#1")
    squash_marker.mark(workspace, BRANCH)
    return dict(project=project, workspace=workspace, project_remote=project_remote,
                workspace_remote=workspace_remote)


def run(world, command: str, *extra: str) -> dict[str, str]:
    ws, proj = world["workspace"], world["project"]
    branch = g(ws, "symbolic-ref", "--short", "HEAD")
    done = subprocess.run(
        ["python3", WORK, command, f"workspace={ws}", f"project={proj}", f"branch={branch}",
         "base_branch=main", f"on_main={'yes' if branch == 'main' else 'no'}",
         "covers=o/r#1", "issue_repo=O/r", f"plan_path={ws / '.queue'}", *extra],
        capture_output=True, text=True, cwd=str(ws))
    out: dict[str, str] = {"_code": str(done.returncode), "_raw": done.stdout + done.stderr}
    for line in done.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key] = value
    return out


def answer(world, command: str, step: str, *extra: str) -> dict[str, str]:
    return run(world, command, f"step_done={step}", "outcome=completed", *extra)


def drive_to_item_finished(world, command: str) -> dict[str, str]:
    assert run(world, command)["ACTION"] == "review"
    assert answer(world, command, "review")["ACTION"] == "diary"
    assert answer(world, command, "diary")["ACTION"] == "file_issues"
    result = answer(world, command, "file_issues")
    assert result["ACTION"] == "item_finished", result["_raw"]
    return result


class TestOrder:

    def test_wrap_has_no_step_that_lands_promotes_or_publishes(self):
        names = [s.name for s in work.WRAP_STEPS]
        assert names == ["review", "diary", "file_issues", "item_finished", "mark_done",
                         "commit_queue", "handoff"]
        assert not {"land", "promote_backlog", "publish", "publish_blog"} & set(names)

    def test_end_is_wrap_with_the_close_between_marking_done_and_the_handoff(self):
        names = [s.name for s in work.END_STEPS]
        assert names == ["review", "diary", "file_issues", "item_finished", "mark_done",
                         "commit_queue", "land", "promote_backlog", "publish", "publish_blog",
                         "handoff"]

    def test_the_finished_question_cannot_be_skipped(self):
        step = next(s for s in work.END_STEPS if s.name == "item_finished")
        assert step.skippable is False

    def test_each_judgment_step_has_an_instruction_file(self):
        for step in work.END_STEPS:
            if step.handler:
                assert (ROOT / "work" / step.handler).is_file(), step.handler


class TestWrap:

    def test_finished_item_is_marked_done_and_nothing_lands(self, world):
        before = g(world["project"], "rev-parse", "main")
        drive_to_item_finished(world, "wrap")

        result = answer(world, "wrap", "item_finished", "finished=yes")
        assert result["ACTION"] == "handoff", result["_raw"]
        result = answer(world, "wrap", "handoff")

        assert result["ACTION"] == "complete", result["_raw"]
        queue = read_queue(world["workspace"])
        first = next(i for i in queue.items if i.ref == "o/r#1")
        assert first.done_branch == BRANCH and not first.completed
        assert g(world["project"], "rev-parse", "main") == before
        assert g(world["project_remote"], "rev-parse", "refs/heads/main") == before
        assert result["ITEM_FINISHED"] == "yes"
        assert "scaffold the next item" in result["THEN"]
        assert g(world["workspace"], "status", "--porcelain") == "", "the queue change is committed"

    def test_unfinished_item_stays_active(self, world):
        drive_to_item_finished(world, "wrap")

        result = answer(world, "wrap", "item_finished", "finished=no")
        assert result["ACTION"] == "handoff", result["_raw"]
        result = answer(world, "wrap", "handoff")

        assert result["ACTION"] == "complete"
        first = next(i for i in read_queue(world["workspace"]).items if i.ref == "o/r#1")
        assert first.active and not first.done_branch
        assert result["ITEM_FINISHED"] == "no"
        assert "continues the current item" in result["THEN"]

    def test_the_answer_is_required(self, world):
        drive_to_item_finished(world, "wrap")
        result = answer(world, "wrap", "item_finished")
        assert result["ACTION"] == "error" and result["ERROR"] == "answer_required"
        assert run(world, "wrap")["ACTION"] == "item_finished"

    def test_a_repeated_first_call_resumes_where_it_stopped(self, world):
        assert run(world, "wrap")["ACTION"] == "review"
        assert answer(world, "wrap", "review")["ACTION"] == "diary"
        assert run(world, "wrap")["ACTION"] == "diary"


class TestEnd:

    def test_finished_item_is_landed_and_published(self, world):
        drive_to_item_finished(world, "end")

        result = answer(world, "end", "item_finished", "finished=yes")
        assert result["ACTION"] == "handoff", result["_raw"]
        result = answer(world, "end", "handoff")

        assert result["ACTION"] == "complete", result["_raw"]
        project = world["project"]
        assert g(project, "show", "main:code.txt") == "x"
        assert g(world["project_remote"], "rev-parse", "refs/heads/main") == \
            g(project, "rev-parse", "main")
        assert g(world["workspace_remote"], "rev-parse", "refs/heads/main") == \
            g(world["workspace"], "rev-parse", "main")
        first = next(i for i in read_queue(world["workspace"]).items if i.ref == "o/r#1")
        assert first.completed
        assert "o/r#1" in result["STEP_LAND"]
        assert result["STEP_PUBLISH"].startswith("PUBLISHED_COUNT=")

    def test_unfinished_item_is_not_landed(self, world):
        before = g(world["project"], "rev-parse", "main")
        drive_to_item_finished(world, "end")

        result = answer(world, "end", "item_finished", "finished=no")
        assert result["ACTION"] == "handoff", result["_raw"]

        assert g(world["project"], "rev-parse", "main") == before
        assert g(world["project"], "symbolic-ref", "--short", "HEAD") == BRANCH
        first = next(i for i in read_queue(world["workspace"]).items if i.ref == "o/r#1")
        assert first.active and not first.completed

    def test_a_failed_landing_stops_before_anything_is_published(self, world):
        project = world["project"]
        commit(project, "second.txt")            # now two commits and no review of the tip
        remote_before = g(world["project_remote"], "rev-parse", "refs/heads/main")
        drive_to_item_finished(world, "end")

        result = answer(world, "end", "item_finished", "finished=yes")

        assert result["ACTION"] == "error", result["_raw"]
        assert result["STEP"] == "land" and result["ERROR"] == "squash_review_needed"
        assert g(world["project_remote"], "rev-parse", "refs/heads/main") == remote_before

        again = run(world, "end")                 # still failing: it does not skip ahead
        assert again["ACTION"] == "error" and again["STEP"] == "land"
        third = run(world, "end")
        fourth = run(world, "end")
        assert fourth["ACTION"] == "error" and fourth["STEP"] == "land", \
            "a failing step must never be marked skipped"
        assert g(world["project_remote"], "rev-parse", "refs/heads/main") == remote_before

        squash_marker.mark(project, BRANCH)
        resumed = run(world, "end")
        assert resumed["ACTION"] == "handoff", resumed["_raw"]
        assert g(world["project_remote"], "rev-parse", "refs/heads/main") == \
            g(project, "rev-parse", "main")


class TestReport:

    def test_a_step_that_could_not_do_something_is_called_out(self, world):
        g(world["project"], "remote", "set-url", "origin", str(world["project"] / "nowhere.git"))
        drive_to_item_finished(world, "end")
        answer(world, "end", "item_finished", "finished=yes")

        result = answer(world, "end", "handoff")

        assert result["ACTION"] == "complete", result["_raw"]
        assert "NOT_PUBLISHED" in result["STEP_PUBLISH"]
        assert result["ATTENTION"].startswith("publish")
        assert g(world["project"], "show", "main:code.txt") == "x", "landing still happened"

    def test_a_clean_run_has_no_attention_line(self, world):
        drive_to_item_finished(world, "end")
        answer(world, "end", "item_finished", "finished=yes")
        result = answer(world, "end", "handoff")
        assert result["ACTION"] == "complete" and "ATTENTION" not in result


class TestNoLostWork:
    """Existing layouts and half-finished states are refused or left intact, never guessed at."""

    def test_end_says_up_front_which_repos_it_is_limited_to(self, world):
        result = run(world, "end")
        assert str(world["project"].resolve()) in result["SCOPE"]
        assert str(world["workspace"].resolve()) in result["SCOPE"]
        assert result["ACTION"] == "review"

    def test_wrap_prints_no_scope_because_it_publishes_nothing(self, world):
        assert "SCOPE" not in run(world, "wrap")

    def test_workspace_left_on_main_is_brought_onto_the_branch_first(self, world):
        """The safe repair from the alignment check: a clean workspace joins the project."""
        g(world["workspace"], "checkout", "-q", "main")

        result = run(world, "end")

        assert result["ALIGNMENT_REPAIRED"] == "workspace_behind"
        assert g(world["workspace"], "symbolic-ref", "--short", "HEAD") == BRANCH
        assert result["ACTION"] == "review"

    def test_both_repos_on_main_while_the_work_is_on_a_branch_stops_and_names_the_branch(
            self, world):
        """The queue rides on the working branch, so from main it is not even visible."""
        for key in ("project", "workspace"):
            g(world[key], "checkout", "-q", "main")
        before = {k: g(world[k], "rev-parse", "HEAD") for k in ("project", "workspace")}

        result = run(world, "end")

        assert result["ACTION"] == "stop", result["_raw"]
        assert result["STOP_REASON"] == "nothing_to_end"
        assert BRANCH in result["DETAIL"]
        assert {k: g(world[k], "rev-parse", "HEAD") for k in ("project", "workspace")} == before
        assert g(world["project"], "rev-parse", BRANCH), "the branch and its work are still there"

    def test_queue_naming_another_branch_than_the_one_checked_out_is_refused(self, world):
        ws = world["workspace"]
        for key in ("project", "workspace"):
            g(world[key], "checkout", "-q", "-b", "issue-9-elsewhere")
            branch_base.record(world[key], "issue-9-elsewhere", g(world[key], "rev-parse", "main"))
        before = g(world["project"], "rev-parse", "HEAD")

        result = run(world, "end")

        assert result["ACTION"] == "decision", result["_raw"]
        assert result["DECISION"] in ("active_branch_not_checked_out", "alignment_queue_mismatch")
        assert g(world["project"], "rev-parse", "HEAD") == before
        assert next(i for i in read_queue(ws).items if i.ref == "o/r#1").active

    def test_finished_on_the_base_branch_never_closes_the_item_outright(self, tmp_path):
        """An item with no working branch cannot be marked done by the sequence."""
        workspace, _ = with_remote(tmp_path, "solo")
        (workspace / ".git" / "info" / "exclude").write_text(".work-progress\n")
        write_queue(workspace, Queue(
            items=[QueueItem(ref="o/r#1", title="First", completed=False, active=True)],
            state=QueueState(branch="", issue_repo="O/r", status="active", covers="o/r#1")))
        g(workspace, "add", ".queue")
        g(workspace, "commit", "-q", "-m", "queue")
        world = dict(project=workspace, workspace=workspace)
        drive_to_item_finished(world, "wrap")

        result = answer(world, "wrap", "item_finished", "finished=yes")

        assert result["ACTION"] == "handoff", result["_raw"]
        first = read_queue(workspace).items[0]
        assert first.active and not first.completed and not first.done_branch

    def test_an_interrupted_run_says_it_is_resuming(self, world):
        run(world, "wrap")
        answer(world, "wrap", "review")
        result = run(world, "wrap")
        assert result["RESUMING"] == "wrap steps_already_done=review"
        assert result["ACTION"] == "diary"

    def test_a_fresh_run_does_not_claim_to_resume(self, world):
        assert "RESUMING" not in run(world, "wrap")

    def test_uncommitted_work_in_the_project_stops_the_landing_and_is_untouched(self, world):
        (world["project"] / "unsaved.txt").write_text("in progress")
        drive_to_item_finished(world, "end")

        result = answer(world, "end", "item_finished", "finished=yes")

        assert result["ACTION"] == "error" and result["STEP"] == "land", result["_raw"]
        assert (world["project"] / "unsaved.txt").read_text() == "in progress"
        assert g(world["project_remote"], "rev-parse", "refs/heads/main") != \
            g(world["project"], "rev-parse", BRANCH)

    def test_old_progress_from_before_runs_were_recorded_is_not_trusted(self, world):
        (world["workspace"] / ".work-progress").write_text(
            "review=done\ndiary=done\nfile_issues=done\nitem_finished=done\n"
            "mark_done=done\nland=done\npublish=done\nhandoff=done\n")
        result = run(world, "end")
        assert result["ACTION"] == "review", "a stale progress file must not skip the sequence"


class TestNothingIsRepairedWhenTheQueueDisagrees:

    def test_project_on_a_hand_made_branch_and_workspace_on_main_changes_nothing(self, world):
        """The alignment repair would move the workspace onto the project's branch.
        It must not, when the queue says the work is on a third branch."""
        g(world["workspace"], "checkout", "-q", "main")
        write_queue(world["workspace"], Queue(
            items=[QueueItem(ref="o/r#1", title="First", completed=False, active=True)],
            state=QueueState(branch="issue-7-somewhere-else", issue_repo="O/r", status="active")))
        g(world["workspace"], "add", ".queue")
        g(world["workspace"], "commit", "-q", "-m", "queue on main")
        g(world["project"], "checkout", "-q", "-b", "wip/hand-made")
        before = {k: (g(world[k], "symbolic-ref", "--short", "HEAD"), g(world[k], "rev-parse", "HEAD"),
                      g(world[k], "for-each-ref", "refs/heads"))
                  for k in ("project", "workspace")}

        result = run(world, "end")

        assert result["ACTION"] == "decision", result["_raw"]
        assert result["DECISION"] == "active_branch_not_checked_out"
        assert "ALIGNMENT_REPAIRED" not in result
        after = {k: (g(world[k], "symbolic-ref", "--short", "HEAD"), g(world[k], "rev-parse", "HEAD"),
                     g(world[k], "for-each-ref", "refs/heads"))
                 for k in ("project", "workspace")}
        assert after == before


class TestEndInANumberedSlot:
    """The whole sequence in a slot with two project repos and a workspace clone,
    the queue at the slot root (#571)."""

    @pytest.fixture
    def slot(self, tmp_path):
        canonical, remotes = {}, {}
        for name in ("agency", "connectors", "wsp", "unrelated"):
            repo, bare = with_remote(tmp_path / "canonical", name)
            canonical[name], remotes[name] = repo, bare
        commit(canonical["unrelated"], "elsewhere.txt")      # ahead of its remote, not ours
        slot_dir = tmp_path / "family" / "slots" / "42"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot 42 — test\n\n## Issue\no/r#1\n\n## Repos\n- agency (primary)\n- connectors\n")
        clones = {}
        for name in ("agency", "connectors", "wsp"):
            clone = slot_dir / name
            subprocess.run(["git", "clone", "-q", str(canonical[name]), str(clone)], check=True)
            g(clone, "remote", "rename", "origin", "local")
            base = g(clone, "rev-parse", "main")
            g(clone, "checkout", "-q", "-b", BRANCH)
            branch_base.record(clone, BRANCH, base)
            commit(clone, f"{name}-work.txt")
            squash_marker.mark(clone, BRANCH)
            clones[name] = clone
        (clones["wsp"] / ".workspace").write_text(f"project: {clones['agency']}\n")
        (clones["wsp"] / ".git" / "info" / "exclude").write_text(".workspace\n.work-progress\n")
        write_queue(slot_dir, Queue(
            items=[QueueItem(ref="o/r#1", title="First", completed=False, active=True)],
            state=QueueState(branch=BRANCH, issue_repo="O/r", status="active", covers="o/r#1")))
        return dict(slot=slot_dir, clones=clones, canonical=canonical, remotes=remotes)

    def _run(self, slot, *extra):
        ws, proj = slot["clones"]["wsp"], slot["clones"]["agency"]
        branch = g(ws, "symbolic-ref", "--short", "HEAD")
        done = subprocess.run(
            ["python3", WORK, "end", f"workspace={ws}", f"project={proj}", f"branch={branch}",
             "base_branch=main", f"on_main={'yes' if branch == 'main' else 'no'}", "in_slot=yes",
             f"slot_path={slot['slot']}", f"plan_path={slot['slot'] / '.queue'}",
             "covers=o/r#1", "issue_repo=O/r", *extra],
            capture_output=True, text=True, cwd=str(ws))
        out = {"_raw": done.stdout + done.stderr}
        for line in done.stdout.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                out[key] = value
        return out

    def _answer(self, slot, step, *extra):
        return self._run(slot, f"step_done={step}", "outcome=completed", *extra)

    def _drive(self, slot, finished="yes"):
        first = self._run(slot)
        assert first["ACTION"] == "review", first["_raw"]
        assert self._answer(slot, "review")["ACTION"] == "diary"
        assert self._answer(slot, "diary")["ACTION"] == "file_issues"
        assert self._answer(slot, "file_issues")["ACTION"] == "item_finished"
        result = self._answer(slot, "item_finished", f"finished={finished}")
        return first, result

    def test_scope_is_the_slots_repos_as_their_canonicals(self, slot):
        first = self._run(slot)
        for name in ("agency", "connectors", "wsp"):
            assert str(slot["canonical"][name].resolve()) in first["SCOPE"]
        assert "unrelated" not in first["SCOPE"]

    def test_every_repo_of_the_slot_lands_and_is_published(self, slot):
        _, result = self._drive(slot)
        assert result["ACTION"] == "handoff", result["_raw"]
        result = self._answer(slot, "handoff")
        assert result["ACTION"] == "complete", result["_raw"]

        for name in ("agency", "connectors"):
            canonical = slot["canonical"][name]
            assert g(canonical, "show", f"main:{name}-work.txt") == "x"
            assert g(slot["remotes"][name], "rev-parse", "refs/heads/main") == \
                g(canonical, "rev-parse", "main")
            assert g(slot["clones"][name], "symbolic-ref", "--short", "HEAD") == "main"
            assert g(canonical, "rev-list", "--merges", "--count", "main") == "0"
        assert g(slot["canonical"]["wsp"], "show", "main:wsp-work.txt") == "x"
        assert read_queue(slot["slot"]).items[0].completed

    def test_a_canonical_repo_outside_the_slot_is_never_published(self, slot):
        before = g(slot["remotes"]["unrelated"], "rev-parse", "refs/heads/main")
        self._drive(slot)
        self._answer(slot, "handoff")
        assert g(slot["remotes"]["unrelated"], "rev-parse", "refs/heads/main") == before

    def test_unfinished_item_in_a_slot_lands_nothing(self, slot):
        before = {n: g(slot["canonical"][n], "rev-parse", "main") for n in ("agency", "connectors")}
        _, result = self._drive(slot, finished="no")
        assert result["ACTION"] == "handoff", result["_raw"]
        assert {n: g(slot["canonical"][n], "rev-parse", "main")
                for n in ("agency", "connectors")} == before
        assert g(slot["clones"]["agency"], "symbolic-ref", "--short", "HEAD") == BRANCH
        assert read_queue(slot["slot"]).items[0].active
        assert not (slot["slot"] / ".landed").exists()

    def test_the_queue_stays_at_the_slot_root(self, slot):
        self._drive(slot)
        assert (slot["slot"] / ".queue").exists()
        assert not (slot["clones"]["wsp"] / ".queue").exists()
