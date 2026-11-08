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
from artifact_promote import _copromote_images


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


def find_gaps(workspace: Path, project: Path) -> list[dict]:
    """Compare workspace artifacts against project. Returns list of gap dicts."""
    artifacts = scan(workspace)
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
                _copromote_images(src, dst, str(project))

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
            subprocess.run(
                ["git", "-C", str(project), "commit", "-m", msg],
                capture_output=True,
            )

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

    if not workspace.is_dir():
        print(f"ERROR=workspace_not_found:{workspace}")
        return 1
    if not project.is_dir():
        print(f"ERROR=project_not_found:{project}")
        return 1

    gaps = find_gaps(workspace, project)
    print(f"GAPS={len(gaps)}")

    if not gaps:
        print("PROMOTED=0")
        return 0

    for gap in gaps:
        print(f"GAP={gap['category']}:{gap['source_rel']}")

    result = promote_gaps(gaps, project, covers=covers, dry_run=dry_run)
    print(f"PROMOTED={result['promoted']}")
    for cat, count in result.get("by_category", {}).items():
        print(f"CATEGORY_{cat}={count}")

    if dry_run:
        print("DRY_RUN=yes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
