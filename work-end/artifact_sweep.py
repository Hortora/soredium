#!/usr/bin/env python3
"""Sweep workspace artifacts to project — find and promote gaps.

Compares workspace artifact directories against project destinations.
Promotes any entries that exist in workspace but not in project.
Covers all categories: specs, ADRs, blog, plans, snapshots.

Usage:
    python3 artifact_sweep.py <workspace> <project> [covers=<csv>] [dry_run=yes]

Output (KEY=value lines):
    GAPS=<count>
    PROMOTED=<count>
    CATEGORY_<name>=<count>
"""
import shutil
import subprocess
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_script_dir))
sys.path.insert(0, str(_script_dir.parent / "project"))

from workspace_artifacts import scan, CATEGORIES
from artifact_promote import _copromote_images, ImageNotPromoted


def verify_images(project: Path) -> list[str]:
    """Check promoted .md files for broken image references."""
    try:
        from verification.repo_checks import extract_image_refs
    except ImportError:
        return []
    broken: list[str] = []
    for dest_dir in ["docs/blog", "docs/specs", "docs/adr"]:
        target = project / dest_dir
        if not target.is_dir():
            continue
        for md in target.rglob("*.md"):
            for raw_ref, resolved in extract_image_refs(md):
                if not resolved.exists():
                    broken.append(f"{md.relative_to(project)}: {raw_ref}")
    return broken


DEST_PREFIX = {
    "specs": "docs/specs",
    "adr": "docs/adr",
    "blog": "docs/blog",
    "plans": "",
    "snapshots": "",
}


GATED_CATEGORIES = ("specs", "adr", "blog")


def _quiet_scan(workspace: Path) -> dict[str, list[str]]:
    """scan() without its per-image warnings on stderr, which drown a ceremony's output."""
    import contextlib
    import io
    with contextlib.redirect_stderr(io.StringIO()):
        return scan(workspace)


def touched_artifacts(workspace: Path) -> set[str]:
    """Workspace paths this work added or changed: what one close is answerable for.

    Everything the checked-out branch holds that the canonical workspace's base
    branch lacks (in a slot that includes commits made directly on the clone's
    main), plus anything not committed yet. Older artifacts that were never
    promoted are a backlog, not this close's doing, and are not in the set.
    """
    import canonical_sync
    names: set[str] = set()
    try:
        canon = canonical_sync.locate(workspace)
        base = canonical_sync._onto(Path(workspace), canon)
    except canonical_sync.SyncError:
        base = ""
    if base:
        diff = subprocess.run(
            ["git", "-C", str(workspace), "diff", "--name-only", "--no-renames",
             "--diff-filter=AM", "-z", base, "HEAD"],
            capture_output=True, text=True)
        names.update(n for n in diff.stdout.split("\0") if n)
    status = subprocess.run(
        ["git", "-C", str(workspace), "status", "--porcelain", "-z", "--untracked-files=all"],
        capture_output=True, text=True)
    for entry in status.stdout.split("\0"):
        if len(entry) > 3 and entry[0] != "D" and entry[1] != "D":
            names.add(entry[3:])
    return names


def branch_gaps(workspace: Path, project: Path) -> list[dict]:
    """Documents this work added to the workspace that the project does not hold yet.

    Markdown only, in the categories that have a place in the project (specs,
    ADRs, blog): images travel with the document that refers to them.
    """
    touched = touched_artifacts(workspace)
    if not touched:
        return []
    return [gap for gap in find_gaps(workspace, project, quiet=True)
            if gap["category"] in GATED_CATEGORIES
            and gap["source_rel"].endswith(".md")
            and gap["source_rel"] in touched]


def find_gaps(workspace: Path, project: Path, quiet: bool = False) -> list[dict]:
    """Compare workspace artifacts against project. Returns list of gap dicts."""
    artifacts = _quiet_scan(workspace) if quiet else scan(workspace)
    gaps: list[dict] = []

    for category, sources in artifacts.items():
        dest_prefix = DEST_PREFIX.get(category, category)

        for source_rel in sources:
            source_path = workspace / source_rel
            if not source_path.exists():
                continue

            filename = Path(source_rel).name
            if dest_prefix:
                dest_rel = f"{dest_prefix}/{filename}"
            else:
                dest_rel = source_rel

            dest_path = project / dest_rel

            if category in ("specs",):
                parent_dir = Path(source_rel).parent.name
                if parent_dir != category and parent_dir != "docs":
                    dest_rel = f"{dest_prefix}/{parent_dir}/{filename}"
                    dest_path = project / dest_rel

            if not dest_path.exists():
                gaps.append({
                    "category": category,
                    "source": str(source_path),
                    "source_rel": source_rel,
                    "dest_rel": dest_rel,
                    "dest": str(dest_path),
                })

    return gaps


def promote_gaps(gaps: list[dict], project: Path,
                 covers: str = "", dry_run: bool = False) -> dict:
    """Copy gap artifacts to project and commit."""
    if not gaps:
        return {"promoted": 0, "skipped": 0}

    promoted = 0
    by_category: dict[str, int] = {}

    for gap in gaps:
        src = Path(gap["source"])
        dst = Path(gap["dest"])

        if dry_run:
            promoted += 1
            cat = gap["category"]
            by_category[cat] = by_category.get(cat, 0) + 1
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
            if src.suffix == ".md":
                try:
                    _copromote_images(src, dst, str(project))
                except ImageNotPromoted as error:
                    subprocess.run(["git", "-C", str(project), "reset", "-q"],
                                   capture_output=True)
                    return {"promoted": 0, "by_category": {},
                            "error": f"image not promoted: {error}"}

        subprocess.run(
            ["git", "-C", str(project), "add", gap["dest_rel"]],
            capture_output=True,
        )
        promoted += 1
        cat = gap["category"]
        by_category[cat] = by_category.get(cat, 0) + 1

    if promoted > 0 and not dry_run:
        has_staged = subprocess.run(
            ["git", "-C", str(project), "diff", "--cached", "--quiet"],
            capture_output=True,
        ).returncode != 0

        if has_staged:
            issue_ref = ""
            if covers:
                from queue_io import parse_covers
                nums = parse_covers(covers)
                if nums:
                    issue_ref = f"  Refs #{nums[0]}"

            msg = f"docs: promote {promoted} artifact(s) from workspace{issue_ref}"
            committed = subprocess.run(
                ["git", "-C", str(project), "commit", "-m", msg],
                capture_output=True, text=True,
            )
            if committed.returncode != 0:
                # Copied and staged but not committed is not promoted. Say so.
                return {"promoted": 0, "by_category": {},
                        "error": " ".join((committed.stderr or committed.stdout).split())}

    if promoted > 0 and not dry_run:
        broken = verify_images(project)
        if broken:
            return {"promoted": promoted, "by_category": by_category,
                    "broken_images": broken}

    return {"promoted": promoted, "by_category": by_category}


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: artifact_sweep.py <workspace> <project> [covers=...] [dry_run=yes]")
        return 1

    workspace = Path(sys.argv[1])
    project = Path(sys.argv[2])

    params: dict[str, str] = {}
    for arg in sys.argv[3:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            params[k] = v

    covers = params.get("covers", "")
    dry_run = params.get("dry_run", "no") == "yes"
    branch_only = params.get("scope", "all") == "branch"

    if not workspace.is_dir():
        print(f"ERROR=workspace_not_found:{workspace}")
        return 1
    if not project.is_dir():
        print(f"ERROR=project_not_found:{project}")
        return 1

    gaps = branch_gaps(workspace, project) if branch_only else find_gaps(workspace, project)
    print(f"GAPS={len(gaps)}")

    if not gaps:
        print("PROMOTED=0")
        return 0

    for gap in gaps:
        print(f"GAP={gap['category']}:{gap['source_rel']}")

    result = promote_gaps(gaps, project, covers=covers, dry_run=dry_run)
    if result.get("error"):
        print("ERROR=commit_failed")
        print(f"ERROR_DETAIL={result['error']}")
        print("PROMOTED=0")
        return 1
    print(f"PROMOTED={result['promoted']}")
    for cat, count in result.get("by_category", {}).items():
        print(f"CATEGORY_{cat}={count}")

    if dry_run:
        print("DRY_RUN=yes")

    if branch_only:
        left = branch_gaps(workspace, project)
        print(f"REMAINING={len(left)}")
        return 1 if left and not dry_run else 0

    # Also sweep canonical workspace→project promotion gaps
    # (catches content written to workspace main that was never promoted)
    try:
        from verification.cross_checks import check_workspace_promotion_gaps, promote_workspace_gaps
        canon_gaps = check_workspace_promotion_gaps(workspace, project)
        if canon_gaps:
            print(f"PROMOTION_GAPS={len(canon_gaps)}")
            if not dry_run:
                actions = promote_workspace_gaps(workspace, project)
                if actions:
                    print(f"SWEPT={len(actions)}")
                    for a in actions:
                        print(a)
                    subprocess.run(["git", "-C", str(project), "add", "docs/"],
                                   capture_output=True)
                    has_changes = subprocess.run(
                        ["git", "-C", str(project), "diff", "--cached", "--quiet"],
                        capture_output=True,
                    ).returncode != 0
                    if has_changes:
                        issue_ref = ""
                        if covers:
                            from queue_io import parse_covers
                            nums = parse_covers(covers)
                            if nums:
                                issue_ref = f"  Refs #{nums[0]}"
                        subprocess.run(["git", "-C", str(project), "commit", "-m",
                                        f"docs: sweep-promote {len(actions)} workspace artifacts{issue_ref}"],
                                       capture_output=True)
            else:
                for g in canon_gaps:
                    print(f"WOULD_SWEEP={g.category}: {g.message}")
        else:
            print("PROMOTION_GAPS=0")
    except ImportError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
