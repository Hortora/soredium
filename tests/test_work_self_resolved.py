"""`work wrap` and `work end` driven by self-resolved context (#588).

Every call omits workspace=, project=, branch=, etc. so fill_from_context()
calls ctx.resolve() — the path a real session takes.  The existing
test_work_wrap_end.py passes every argument explicitly, bypassing ctx entirely.

Three layouts: plain dual workspace, permanent clone with root queue, and
numbered slot.  Each includes a failed-landing-then-retry path that verifies
the retry resumes at the failed step even though ctx re-resolves with the
next item's covers.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _d in ("project", "work-slot", "work-end"):
    sys.path.insert(0, str(ROOT / _d))

import branch_base  # noqa: E402
import squash_marker  # noqa: E402
from queue_io import Queue, QueueItem, QueueState, read_queue, write_queue  # noqa: E402

WORK = str(ROOT / "project" / "work.py")
CTX = str(ROOT / "project" / "ctx.py")
BRANCH = "issue-1-x"


def g(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


def commit(repo: Path, name: str, text: str = "x") -> None:
    (repo / name).write_text(text)
    g(repo, "add", name)
    g(repo, "commit", "-q", "-m", f"feat: {name} Refs O/r#1")


def with_remote(tmp_path: Path, name: str) -> tuple[Path, Path]:
    bare = tmp_path / "remotes" / f"{name}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare),
                     "--template="], check=True)
    repo = tmp_path / name
    repo.mkdir()
    g(repo, "init", "-q", "-b", "main", "--template=")
    (repo / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (repo / "seed.txt").write_text(name)
    g(repo, "add", ".")
    g(repo, "commit", "-q", "-m", "init")
    g(repo, "remote", "add", "origin", str(bare))
    g(repo, "push", "-q", "origin", "main")
    return repo, bare


def ctx_resolve(cwd: Path) -> dict[str, str]:
    done = subprocess.run(["python3", CTX], capture_output=True, text=True,
                          cwd=str(cwd))
    return dict(l.split("=", 1) for l in done.stdout.splitlines() if "=" in l)


# ---------------------------------------------------------------------------
# Self-resolved driver — no workspace=, project=, etc.
# ---------------------------------------------------------------------------

def run_self(cwd: Path, command: str, *extra: str) -> dict[str, str]:
    done = subprocess.run(
        ["python3", WORK, command, *extra],
        capture_output=True, text=True, cwd=str(cwd))
    out: dict[str, str] = {"_code": str(done.returncode), "_raw": done.stdout + done.stderr}
    for line in done.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key] = value
    return out


def answer_self(cwd: Path, command: str, step: str, *extra: str) -> dict[str, str]:
    return run_self(cwd, command, f"step_done={step}", "outcome=completed", *extra)


def drive_to_item_finished(cwd: Path, command: str) -> dict[str, str]:
    result = run_self(cwd, command)
    assert result["ACTION"] == "review", result["_raw"]
    assert answer_self(cwd, command, "review")["ACTION"] == "diary"
    assert answer_self(cwd, command, "diary")["ACTION"] == "file_issues"
    result = answer_self(cwd, command, "file_issues")
    assert result["ACTION"] == "item_finished", result["_raw"]
    return result


def setup_working_branch(repos: list[tuple[Path, str]], queue_target: Path,
                          issue_repo: str = "O/r", covers: str = "o/r#1"):
    """Create BRANCH in every repo and write the queue to queue_target."""
    for repo, filename in repos:
        base = g(repo, "rev-parse", "main")
        g(repo, "checkout", "-q", "-b", BRANCH)
        branch_base.record(repo, BRANCH, base)
        commit(repo, filename)
        squash_marker.mark(repo, BRANCH)
    write_queue(queue_target, Queue(
        items=[QueueItem(ref=f"{covers.split('#')[0]}#1", title="First",
                         completed=False, active=True),
               QueueItem(ref=f"{covers.split('#')[0]}#2", title="Second",
                         completed=False, active=False)],
        state=QueueState(branch=BRANCH, issue_repo=issue_repo, status="active",
                         covers=covers)))


# ====================================================================
# Plain workspace (dual layout: project + workspace with proj/ symlink)
# ====================================================================

@pytest.fixture
def plain(tmp_path):
    project, project_remote = with_remote(tmp_path, "project")
    workspace, workspace_remote = with_remote(tmp_path, "workspace")
    (workspace / "proj").symlink_to(project)
    (project / ".git" / "info" / "exclude").write_text("wksp\n")
    (workspace / ".git" / "info" / "exclude").write_text("proj\n.work-progress\n")
    setup_working_branch(
        [(project, "code.txt"), (workspace, "notes.md")],
        queue_target=workspace)
    g(workspace, "add", ".queue")
    g(workspace, "commit", "-q", "-m", "chore: queue Refs O/r#1")
    squash_marker.mark(workspace, BRANCH)
    return dict(project=project, workspace=workspace,
                project_remote=project_remote, workspace_remote=workspace_remote)


class TestPlainWorkspace:

    def test_ctx_resolves_the_right_project_and_workspace(self, plain):
        found = ctx_resolve(plain["workspace"])
        assert Path(found["PROJECT"]).resolve() == plain["project"].resolve()
        assert Path(found["WORKSPACE"]).resolve() == plain["workspace"].resolve()
        assert found["CURRENT_BRANCH"] == BRANCH
        assert found["COVERS"] == "o/r#1"

    def test_wrap_completes(self, plain):
        ws = plain["workspace"]
        drive_to_item_finished(ws, "wrap")
        result = answer_self(ws, "wrap", "item_finished", "finished=yes")
        assert result["ACTION"] == "handoff", result["_raw"]
        result = answer_self(ws, "wrap", "handoff")
        assert result["ACTION"] == "complete", result["_raw"]
        first = next(i for i in read_queue(ws).items if i.ref == "o/r#1")
        assert first.done_branch == BRANCH and not first.completed

    def test_end_lands_and_publishes(self, plain):
        ws = plain["workspace"]
        drive_to_item_finished(ws, "end")
        result = answer_self(ws, "end", "item_finished", "finished=yes")
        assert result["ACTION"] == "handoff", result["_raw"]
        result = answer_self(ws, "end", "handoff")
        assert result["ACTION"] == "complete", result["_raw"]
        assert g(plain["project"], "show", "main:code.txt") == "x"
        assert g(plain["project_remote"], "rev-parse", "refs/heads/main") == \
            g(plain["project"], "rev-parse", "main")
        first = next(i for i in read_queue(ws).items if i.ref == "o/r#1")
        assert first.completed
        assert "o/r#1" in result["STEP_LAND"]

    def test_retry_after_failed_landing_resumes_at_the_failed_step(self, plain):
        ws = plain["workspace"]
        commit(plain["project"], "second.txt")
        drive_to_item_finished(ws, "end")
        failed = answer_self(ws, "end", "item_finished", "finished=yes")
        assert failed["ACTION"] == "error" and failed["STEP"] == "land", failed["_raw"]

        retry = run_self(ws, "end")
        assert retry["ACTION"] == "error" and retry["STEP"] == "land", retry["_raw"]
        assert "RESUMING" in retry, "retry must resume, not restart from review"

        squash_marker.mark(plain["project"], BRANCH)
        resumed = run_self(ws, "end")
        assert resumed["ACTION"] == "handoff", resumed["_raw"]
        result = answer_self(ws, "end", "handoff")
        assert result["ACTION"] == "complete", result["_raw"]
        assert g(plain["project"], "show", "main:code.txt") == "x"
        assert g(plain["project"], "show", "main:second.txt") == "x"
        assert "o/r#1" in result["STEP_LAND"]


# ====================================================================
# Permanent clone with root queue
# ====================================================================

def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "main", "--template="],
                   capture_output=True, check=True)
    (path / "seed.txt").write_text(path.name)
    g(path, "add", ".")
    g(path, "commit", "-q", "-m", "init")
    return path


@pytest.fixture
def clone(tmp_path):
    family = tmp_path / "family"
    family.mkdir()
    (family / "slots").mkdir()

    canonical_p = _init_repo(family / "P")
    (canonical_p / "src.txt").write_text("source\n")
    g(canonical_p, "add", ".")
    g(canonical_p, "commit", "-q", "-m", "add source")

    canonical_w = _init_repo(family / "W")
    (canonical_w / "proj").symlink_to(os.path.relpath(canonical_p, canonical_w))
    write_queue(canonical_w, Queue(
        items=[QueueItem(ref="O/R#1", title="Task", completed=False, active=True),
               QueueItem(ref="O/R#2", title="Second", completed=False, active=False)],
        state=QueueState(branch="", issue_repo="O/R", status="active")))
    g(canonical_w, "add", ".")
    g(canonical_w, "commit", "-q", "-m", "workspace init with queue")

    (canonical_p / "wksp").symlink_to(os.path.relpath(canonical_w, canonical_p))
    g(canonical_p, "add", ".")
    g(canonical_p, "commit", "-q", "-m", "add wksp symlink")

    from clone_manager import create_clone
    result = create_clone(family, "P")
    assert result["CREATED"] == "yes", f"create_clone failed: {result}"

    clone_target = family / "clone" / "P"
    project_clone = clone_target / "P"
    ws_dirs = [d for d in clone_target.iterdir()
               if d.is_dir() and d.name != "P"
               and (d / ".git").exists()
               and (d / ".workspace").exists()]
    assert ws_dirs, "workspace clone not found"
    ws_clone = ws_dirs[0]

    for repo in (project_clone, ws_clone):
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        dirty = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet"],
                               capture_output=True).returncode != 0
        if dirty:
            g(repo, "commit", "-q", "-m", "chore: clean inherited state")

    for repo, name in ((project_clone, "feature.txt"), (ws_clone, "notes.md")):
        base = g(repo, "rev-parse", "main")
        g(repo, "checkout", "-q", "-b", BRANCH)
        branch_base.record(repo, BRANCH, base)
        commit(repo, name)
        squash_marker.mark(repo, BRANCH)

    write_queue(ws_clone, Queue(
        items=[QueueItem(ref="O/R#1", title="Task", completed=False, active=True),
               QueueItem(ref="O/R#2", title="Second", completed=False, active=False)],
        state=QueueState(branch=BRANCH, issue_repo="O/R", status="active", covers="O/R#1")))

    return dict(family=family, canonical_p=canonical_p, canonical_w=canonical_w,
                clone_target=clone_target, project_clone=project_clone,
                ws_clone=ws_clone)


class TestPermanentClone:

    def test_ctx_resolves_the_clone_layout(self, clone):
        found = ctx_resolve(clone["ws_clone"])
        assert Path(found["PROJECT"]).resolve() == clone["project_clone"].resolve()
        assert found["CURRENT_BRANCH"] == BRANCH
        assert found["COVERS"] == "O/R#1"
        assert found.get("PLAN_PATH", "").endswith(".queue")

    def test_end_lands_through_canonical(self, clone):
        ws = clone["ws_clone"]
        drive_to_item_finished(ws, "end")
        result = answer_self(ws, "end", "item_finished", "finished=yes")
        assert result["ACTION"] == "handoff", result["_raw"]
        result = answer_self(ws, "end", "handoff")
        assert result["ACTION"] == "complete", result["_raw"]
        assert g(clone["canonical_p"], "show", "main:feature.txt") == "x"

    def test_retry_after_failed_landing_resumes(self, clone):
        ws = clone["ws_clone"]
        commit(clone["project_clone"], "extra.txt")
        drive_to_item_finished(ws, "end")
        failed = answer_self(ws, "end", "item_finished", "finished=yes")
        assert failed["ACTION"] == "error" and failed["STEP"] == "land", failed["_raw"]

        retry = run_self(ws, "end")
        assert "RESUMING" in retry, "retry must resume, not restart"
        assert retry["STEP"] == "land"

        squash_marker.mark(clone["project_clone"], BRANCH)
        resumed = run_self(ws, "end")
        assert resumed["ACTION"] == "handoff", resumed["_raw"]
        result = answer_self(ws, "end", "handoff")
        assert result["ACTION"] == "complete", result["_raw"]
        assert g(clone["canonical_p"], "show", "main:feature.txt") == "x"


# ====================================================================
# Numbered slot
# ====================================================================

@pytest.fixture
def slot(tmp_path):
    canonical, remotes = {}, {}
    for name in ("agency", "wsp"):
        repo, bare = with_remote(tmp_path / "canonical", name)
        canonical[name], remotes[name] = repo, bare

    slot_dir = tmp_path / "family" / "slots" / "42"
    slot_dir.mkdir(parents=True)
    (slot_dir / ".slot").write_text(
        "# Slot 42 — test\n\n## Issue\no/r#1\n\n## Repos\n- agency (primary)\n")
    clones: dict[str, Path] = {}
    for name in ("agency", "wsp"):
        clone_path = slot_dir / name
        subprocess.run(["git", "clone", "-q", str(canonical[name]), str(clone_path)],
                       check=True)
        g(clone_path, "remote", "rename", "origin", "local")
        base = g(clone_path, "rev-parse", "main")
        g(clone_path, "checkout", "-q", "-b", BRANCH)
        branch_base.record(clone_path, BRANCH, base)
        commit(clone_path, f"{name}-work.txt")
        squash_marker.mark(clone_path, BRANCH)
        clones[name] = clone_path

    (clones["wsp"] / ".workspace").write_text(f"project: {clones['agency']}\n")
    (clones["wsp"] / ".git" / "info" / "exclude").write_text(
        ".workspace\n.work-progress\nproj\n")
    (clones["wsp"] / "proj").symlink_to(clones["agency"])

    import queue_home
    write_queue(slot_dir, Queue(
        items=[QueueItem(ref="o/r#1", title="First", completed=False, active=True),
               QueueItem(ref="o/r#2", title="Second", completed=False, active=False)],
        state=QueueState(branch=BRANCH, issue_repo="O/r", status="active", covers="o/r#1")))
    queue_home.mark(slot_dir)

    return dict(slot=slot_dir, clones=clones, canonical=canonical, remotes=remotes)


class TestNumberedSlot:

    def test_ctx_resolves_slot_layout(self, slot):
        found = ctx_resolve(slot["clones"]["wsp"])
        assert Path(found["PROJECT"]).resolve() == slot["clones"]["agency"].resolve()
        assert found["IN_SLOT"] == "yes"
        assert found["CURRENT_BRANCH"] == BRANCH
        assert found["COVERS"] == "o/r#1"

    def test_end_lands_every_repo(self, slot):
        ws = slot["clones"]["wsp"]
        drive_to_item_finished(ws, "end")
        result = answer_self(ws, "end", "item_finished", "finished=yes")
        assert result["ACTION"] == "handoff", result["_raw"]
        result = answer_self(ws, "end", "handoff")
        assert result["ACTION"] == "complete", result["_raw"]
        for name in ("agency",):
            assert g(slot["canonical"][name], "show", f"main:{name}-work.txt") == "x"
        assert read_queue(slot["slot"], exact=True).items[0].completed

    def test_retry_after_failed_landing_resumes(self, slot):
        ws = slot["clones"]["wsp"]
        commit(slot["clones"]["agency"], "extra.txt")
        drive_to_item_finished(ws, "end")
        failed = answer_self(ws, "end", "item_finished", "finished=yes")
        assert failed["ACTION"] == "error" and failed["STEP"] == "land", failed["_raw"]

        retry = run_self(ws, "end")
        assert "RESUMING" in retry, "retry must resume, not restart"
        assert retry["STEP"] == "land"

        squash_marker.mark(slot["clones"]["agency"], BRANCH)
        resumed = run_self(ws, "end")
        assert resumed["ACTION"] == "handoff", resumed["_raw"]
        result = answer_self(ws, "end", "handoff")
        assert result["ACTION"] == "complete", result["_raw"]
        assert g(slot["canonical"]["agency"], "show", "main:agency-work.txt") == "x"
