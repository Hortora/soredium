#!/usr/bin/env python3
"""What one ceremony covers, and the follow-up actions limited to exactly that (#571).

    scope.py covered <workspace>            the canonical repos this ceremony covers
    scope.py commit-queue <workspace> [covers=<ref>]
                                            commit the queue file alone, if it changed
    scope.py land <workspace>               land every item marked done; never the active item
    scope.py publish <workspace>            publish each of those that is ahead of its remote
    scope.py promote-backlog <workspace> [covers=<ref>]
                                            promote documents on a covered workspace's base
                                            branch that its project lacks
    scope.py publish-blog <workspace>       post the covered projects' landed blog entries to
                                            the destinations the routing names

"Publish all" and "promote all" mean all of what `covered` prints: the project
and workspace the ceremony ran in, or every repo of the slot or clone it ran in.
Nothing here ever looks for other repos that happen to be ahead. That boundary
is the point of this module: left to wording, "all" has been read as every
repo on the machine.

Nothing is pushed except through canonical_sync.publish_base, which never forces.

`land` fails loudly, because everything after it depends on it. The follow-up
actions (publish, promote-backlog, publish-blog) do what they can and name what
they could not (NOT_PUBLISHED=, NOT_PROMOTED=, BLOG_HELD=) with exit 0: one repo
with expired credentials should not stop the handoff being written, and the
sequence's final report repeats every such line under ATTENTION.
"""
from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _entry in (str(_here), str(_here.parent / "project"), str(_here.parent / "work-slot")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import canonical_sync  # noqa: E402
from canonical_sync import SyncError  # noqa: E402
import close as ceremony  # noqa: E402
import worktrace  # noqa: E402


def covered(workspace: Path) -> list[Path]:
    """Canonical repos the ceremony run from `workspace` covers, each once, in order.

    The same repos the ceremony itself resolves (its topology), plus the
    workspace and, in a slot or clone, every repo in it. A clone answers as its
    canonical repo, because that is what gets published.
    """
    workspace = Path(workspace)
    repos: list[Path] = [entry[0] for entry in ceremony.discover_repo_topology(workspace)]
    if (workspace / ".git").exists():
        repos.append(workspace)
    slot_dir = ceremony._slot_dir_of(workspace)
    if slot_dir is not None:
        from slot_core import get_all_slot_repos
        repos += [slot_dir / name for name in get_all_slot_repos(slot_dir)]
    seen: list[Path] = []
    for repo in repos:
        try:
            canonical = canonical_sync.locate(repo).repo.resolve()
        except SyncError:
            continue
        if canonical not in seen:
            seen.append(canonical)
    return seen


def publish(workspace: Path) -> tuple[dict[str, int], dict[str, str]]:
    """Publish every covered repo that is ahead of its remote.

    Returns ({repo: commits pushed}, {repo: why it was not published}). One
    repo failing does not stop the others. A repo with no remote, or with
    nothing to publish, appears in neither.
    """
    pushed: dict[str, int] = {}
    failed: dict[str, str] = {}
    for repo in covered(workspace):
        try:
            canon = canonical_sync.locate(repo)
            if not canon.blessed or not canonical_sync.unpublished(canon):
                continue
            result = canonical_sync.publish_base(repo)
            pushed[str(repo)] = result.pushed
        except SyncError as error:
            failed[str(repo)] = f"{error.code}: {error.detail}"
    return pushed, failed


def promote_backlog(workspace: Path, covers: str = "") -> tuple[dict[str, int], dict[str, str]]:
    """Promote documents on each covered workspace's base branch that its project lacks.

    Returns ({"workspace -> project": documents promoted}, {pair: why not}).
    Only the ceremony's own workspace/project pairs are considered.
    """
    import contextlib
    import io
    import artifact_promote

    promoted: dict[str, int] = {}
    failed: dict[str, str] = {}
    backlog, _ = ceremony.promotion_backlog(Path(workspace), covers)
    for ws_repo, project in ceremony.promotion_pairs(Path(workspace)):
        pair = f"{ws_repo.name} -> {project.name}"
        if pair not in backlog:
            continue
        params = {"covers": covers} if covers else {}
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = artifact_promote.sweep_promotion_gaps(str(project), str(ws_repo), params)
        lines = captured.getvalue().splitlines()
        swept = next((l.split("=", 1)[1] for l in lines if l.startswith("SWEPT=")), "0")
        problems = [l for l in lines if l.startswith(("ERROR", "CONFLICT", "LAND_ERROR"))]
        if code != 0 or problems:
            failed[pair] = "; ".join(problems) or f"exit {code}"
        if swept.isdigit() and int(swept):
            promoted[pair] = int(swept)
    return promoted, failed


def commit_queue(workspace: Path, covers: str = "") -> tuple[int, list[str]]:
    """Commit the workspace's queue file, that path only, when it has changed.

    Marking an item done rewrites the queue. Left uncommitted it stops the
    ceremony, which will not land from a workspace with changes outside the
    lifecycle files, and it is lost if the branch is switched.
    """
    import subprocess
    workspace = Path(workspace)
    changed = subprocess.run(["git", "-C", str(workspace), "status", "--porcelain", "--", ".queue"],
                             capture_output=True, text=True).stdout.strip()
    if not changed:
        return 0, ["QUEUE_COMMITTED=unchanged"]
    subprocess.run(["git", "-C", str(workspace), "add", "--", ".queue"],
                   capture_output=True, text=True)
    done = subprocess.run(
        ["git", "-C", str(workspace), "commit", "-q",
         "-m", "chore: queue records the item marked done",
         "-m", ceremony._issue_trailer(covers, workspace), "--", ".queue"],
        capture_output=True, text=True)
    if done.returncode != 0:
        return 1, ["ERROR=queue_commit_failed",
                   "DETAIL=" + " ".join((done.stderr or done.stdout).split())[:300]]
    return 0, ["QUEUE_COMMITTED=yes"]


def land(workspace: Path) -> tuple[int, list[str]]:
    """Land every item marked done, for the work end pipeline. Returns (exit code, lines).

    The active item is never landed here: by the time the pipeline lands, a
    finished item has been marked done, and an unfinished one must stay as it
    is. Having nothing to land is not a failure. A stop that needs a person
    (documents to promote, a squash review) is one ERROR line with everything
    needed to act on it, so the pipeline halts instead of carrying on.
    """
    result = ceremony.close(Path(workspace), land_active=False)
    if result.success:
        lines = [l for l in ceremony.render(result) if not l.startswith(("ACTION=", "OFFER="))]
        closed = ",".join(result.closed_items)
        return 0, lines + [f"LANDED={closed or 'nothing'}"]
    if result.unpromoted:
        return 2, ["ERROR=promotion_needed",
                   "UNPROMOTED=" + " ;; ".join(result.unpromoted),
                   "PROMOTE_COMMANDS=" + " ;; ".join(result.promote_commands)]
    if result.squash_review:
        return 2, ["ERROR=squash_review_needed",
                   "SQUASH_REVIEW=" + " ;; ".join(result.squash_review)]
    if result.errors and result.errors[0].startswith("nothing to land"):
        return 0, ["LANDED=nothing"]
    return 1, ["ERROR=land_failed", "DETAIL=" + " ;; ".join(result.errors)]


def _blog_modules():
    publish_dir = str(_here.parent / "publish-blog")
    if publish_dir not in sys.path:
        sys.path.insert(0, publish_dir)
    import blog_publish
    import blog_routing
    return blog_routing, blog_publish


def publish_blog(workspace: Path, routing_path: Path | None = None
                 ) -> tuple[dict[str, int], dict[str, str]]:
    """Post this ceremony's blog entries to the destinations the routing names.

    Only what has landed is published: entries are read from each covered
    project's base branch, never from a working branch, and a project whose
    base-branch checkout has uncommitted changes under docs/blog waits. An
    entry goes out when its destination lacks it or holds an older version.

    Returns ({destination name: entries posted}, {what was held back: why}).
    Each destination repo gets one commit holding only the files written, and
    is then published through canonical_sync. A destination that is not on its
    base branch is left alone.
    """
    import contextlib
    import io
    import subprocess
    blog_routing, blog_publish = _blog_modules()

    posted: dict[str, int] = {}
    held: dict[str, str] = {}
    written: dict[Path, list[Path]] = {}      # destination repo -> files written
    names: dict[Path, set[str]] = {}

    for ws_repo, project in ceremony.promotion_pairs(Path(workspace)):
        label = project.name
        try:
            base = canonical_sync.locate(project).base
            canonical_project = canonical_sync.locate(project).repo
        except SyncError as error:
            held[label] = error.detail
            continue
        has_entries = subprocess.run(
            ["git", "-C", str(canonical_project), "ls-tree", "--name-only", base, "docs/blog/"],
            capture_output=True, text=True).stdout.strip()
        if not has_entries:
            continue        # nothing has landed there to publish
        if not blog_routing.source_identity(canonical_project):
            held[label] = "project has no remote to identify it by; nothing is routed on a guess"
            continue
        override = ws_repo / "blog-routing.yaml"
        try:
            with canonical_sync.checked_out(canonical_project, base) as tree:
                tree = Path(tree)
                dirty = subprocess.run(
                    ["git", "-C", str(tree), "status", "--porcelain", "--", "docs/blog"],
                    capture_output=True, text=True).stdout.strip()
                if dirty:
                    held[label] = f"uncommitted changes under docs/blog on {base}"
                    continue
                entries, missing, _ = blog_routing.plan(
                    tree, routing_path,
                    workspace_routing=override if override.is_file() else None)
                for record in missing:
                    dest_dir = Path(record["path"])
                    captured = io.StringIO()
                    try:
                        with contextlib.redirect_stdout(captured):
                            blog_publish.copy_entry(record["source"], str(dest_dir))
                    except SystemExit:
                        problem = [l for l in captured.getvalue().splitlines()
                                   if l.startswith("ERROR")]
                        held[f"{label}:{record['file']} -> {record['dest']}"] = \
                            "; ".join(problem) or "copy failed"
                        continue
                    top = subprocess.run(
                        ["git", "-C", str(dest_dir), "rev-parse", "--show-toplevel"],
                        capture_output=True, text=True).stdout.strip()
                    if not top:
                        held[f"{label}:{record['file']} -> {record['dest']}"] = \
                            f"{dest_dir} is not in a git repository"
                        continue
                    repo = Path(top)
                    written.setdefault(repo, []).append(dest_dir / record["file"])
                    for raw_ref, resolved in blog_publish.extract_image_refs(Path(record["source"])):
                        if resolved.is_file():
                            written[repo].append(blog_publish._image_dest(dest_dir, raw_ref))
                    names.setdefault(repo, set()).add(record["dest"])
                    posted[record["dest"]] = posted.get(record["dest"], 0) + 1
        except SyncError as error:
            held[label] = error.detail

    for repo, files in written.items():
        label = ", ".join(sorted(names[repo]))
        try:
            canon = canonical_sync.locate(repo)
        except SyncError as error:
            held[label] = error.detail
            continue
        current = subprocess.run(["git", "-C", str(repo), "symbolic-ref", "-q", "--short", "HEAD"],
                                 capture_output=True, text=True).stdout.strip()
        rel = sorted({str(f.resolve().relative_to(repo.resolve())) for f in files})
        if current != canon.base:
            held[label] = (f"{repo.name} is on {current or 'no branch'}, not {canon.base}; "
                           f"the files were written but not committed")
            continue
        subprocess.run(["git", "-C", str(repo), "add", "--", *rel], capture_output=True, text=True)
        done = subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m",
             f"chore: publish {len([r for r in rel if r.endswith('.md')])} blog entries\n\n"
             f"no-issue: published by work end", "--", *rel],
            capture_output=True, text=True)
        if done.returncode != 0 and "nothing to commit" not in (done.stdout + done.stderr):
            held[label] = "commit refused: " + " ".join((done.stderr or done.stdout).split())[:200]
            continue
        try:
            canonical_sync.publish_base(repo)
        except SyncError as error:
            held[label] = f"committed, not pushed: {canonical_sync.redact(error.detail)}"
            continue
        worktrace.record("blog-publish", repo=repo, files=rel, published_from=str(workspace))
    for label, reason in held.items():
        worktrace.record("blog-held", repo=workspace, entries=label, reason=reason[:300])
    return posted, held


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] not in ("covered", "commit-queue", "land", "publish",
                                        "promote-backlog", "publish-blog"):
        print("usage: scope.py <covered|land|publish|promote-backlog|publish-blog> <workspace> "
              "[covers=<ref>] [routing=<path>]", file=sys.stderr)
        return 2
    command, workspace = args[0], Path(args[1])
    if not workspace.is_dir():
        print(f"ERROR=workspace_not_found:{workspace}")
        return 1
    options = dict(a.split("=", 1) for a in args[2:] if "=" in a)
    if command == "commit-queue":
        code, lines = commit_queue(workspace, options.get("covers", ""))
        for line in lines:
            print(line)
        return code
    if command == "land":
        code, lines = land(workspace)
        for line in lines:
            print(line)
        return code
    if command == "covered":
        for repo in covered(workspace):
            print(f"COVERED={repo}")
        return 0
    if command == "publish":
        pushed, failed = publish(workspace)
        for repo, count in pushed.items():
            print(f"PUBLISHED={repo} commits={count}")
        for repo, why in failed.items():
            print(f"NOT_PUBLISHED={repo} reason={canonical_sync.redact(why)}")
        print(f"PUBLISHED_COUNT={len(pushed)}")
        return 0
    if command == "publish-blog":
        routing = Path(options["routing"]).expanduser() if options.get("routing") else None
        posted, held = publish_blog(workspace, routing)
        for destination, count in posted.items():
            print(f"BLOG_PUBLISHED={destination} entries={count}")
        for what, why in held.items():
            print(f"BLOG_HELD={what} reason={why}")
        print(f"BLOG_PUBLISHED_COUNT={sum(posted.values())}")
        return 0
    promoted, failed = promote_backlog(workspace, options.get("covers", ""))
    for pair, count in promoted.items():
        print(f"PROMOTED={pair} documents={count}")
    for pair, why in failed.items():
        print(f"NOT_PROMOTED={pair} reason={why}")
    print(f"PROMOTED_COUNT={sum(promoted.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
