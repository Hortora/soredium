"""Cross-estate verification checks.

Pure functions that inspect relationships across multiple slots/repos.
No side effects, no fixes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
from slot_io import parse_slot as _parse_slot

from verification import Finding, read_file_safe


def check_duplicate_slots(slots_dir: Path) -> list[Finding]:
    """Detect multiple active slots using the same branch."""
    findings: list[Finding] = []
    if not slots_dir.exists():
        return findings
    branch_map: dict[str, str] = {}
    for slot_dir in sorted(slots_dir.iterdir()):
        if not slot_dir.is_dir() or not slot_dir.name.isdigit():
            continue
        info = _parse_slot(slot_dir)
        if not info or not info.branch:
            continue
        if info.branch in branch_map:
            findings.append(Finding(
                "ERROR", "duplicate-slot",
                f"slots {branch_map[info.branch]} and {slot_dir.name} both use branch {info.branch}",
            ))
        else:
            branch_map[info.branch] = slot_dir.name
    return findings


def check_duplicate_issues(slots_dir: Path) -> list[Finding]:
    """Detect the same issue being worked on in multiple active slots."""
    findings: list[Finding] = []
    if not slots_dir.exists():
        return findings
    issue_map: dict[str, list[str]] = {}
    for slot_dir in sorted(slots_dir.iterdir()):
        if not slot_dir.is_dir() or not slot_dir.name.isdigit():
            continue
        info = _parse_slot(slot_dir)
        if not info:
            continue
        issue_repo = info.issue_repo
        if info.covers:
            nums = re.findall(r'\d+', info.covers)
            for n in nums:
                key = f"{issue_repo}#{n}" if issue_repo else n
                issue_map.setdefault(key, []).append(f"slot {slot_dir.name}")
    for issue_key, locations in sorted(issue_map.items()):
        if len(locations) > 1:
            findings.append(Finding(
                "ERROR", "duplicate-issue",
                f"issue {issue_key} being worked on in {' AND '.join(locations)}",
            ))
    return findings


def check_split_brain(slots_dir: Path, attic_dir: Path) -> list[Finding]:
    """Detect slots that exist in both active and attic directories."""
    findings: list[Finding] = []
    if not slots_dir.exists() or not attic_dir.exists():
        return findings
    active_nums = {
        d.name for d in slots_dir.iterdir()
        if d.is_dir() and d.name.isdigit()
    }
    attic_nums = {
        d.name for d in attic_dir.iterdir()
        if d.is_dir() and d.name.isdigit()
    }
    for num in sorted(active_nums & attic_nums):
        findings.append(Finding(
            "ERROR", "split-brain",
            f"slot {num} exists in BOTH slots/{num}/ AND slots/attic/{num}/",
        ))
    return findings


def check_zombie_slots(slots_dir: Path) -> list[Finding]:
    """Detect active slots where all project branches are stamped/closed."""
    from verification import git
    findings: list[Finding] = []
    for slot_dir in sorted(slots_dir.iterdir()):
        if not slot_dir.is_dir() or slot_dir.name in ("attic", "quarantine"):
            continue
        slot_file = slot_dir / ".slot"
        if not slot_file.exists():
            continue
        parsed = _parse_slot(slot_file)
        branch = parsed.get("branch", "")
        if not branch:
            continue
        all_stamped = True
        has_repos = False
        for clone in sorted(slot_dir.iterdir()):
            if not clone.is_dir() or not (clone / ".git").exists():
                continue
            if clone.name.startswith("wsp-") or (clone / ".workspace").exists():
                continue
            has_repos = True
            r = git(clone, "log", "-1", "--format=%s", branch)
            if r.returncode == 0 and r.stdout.strip():
                if not r.stdout.strip().startswith("chore: branch closed"):
                    all_stamped = False
                    break
            else:
                r2 = git(clone, "branch", "--show-current")
                if r2.returncode != 0 or r2.stdout.strip() != "main":
                    all_stamped = False
                    break
        if has_repos and all_stamped:
            findings.append(Finding(
                "WARN", "zombie-slot",
                f"slot {slot_dir.name} ({branch}): all branches stamped but slot not archived",
            ))
    return findings


def check_dangling_plans(slots_dir: Path) -> list[Finding]:
    """Detect .plan files with state: active but no corresponding branch."""
    from verification import git
    findings: list[Finding] = []
    for slot_dir in sorted(slots_dir.iterdir()):
        if not slot_dir.is_dir() or slot_dir.name in ("attic", "quarantine"):
            continue
        for plan_path in slot_dir.rglob(".plan"):
            if plan_path.stat().st_size == 0:
                continue
            text = plan_path.read_text()
            if "state: active" not in text:
                continue
            branch_line = ""
            for line in text.splitlines():
                if line.startswith("branch:"):
                    branch_line = line.split(":", 1)[1].strip()
                    break
            if not branch_line or branch_line == "main":
                continue
            plan_parent = plan_path.parent
            if not (plan_parent / ".git").exists():
                continue
            r = git(plan_parent, "branch", "--list", branch_line)
            if r.returncode == 0 and not r.stdout.strip():
                findings.append(Finding(
                    "WARN", "dangling-plan",
                    f"slot {slot_dir.name}: .plan references {branch_line} but branch doesn't exist",
                ))
    return findings


def check_unpublished_slot_blogs(
    slots_dir: Path, published_filenames: set[str],
) -> list[Finding]:
    """Detect blog entries on slot workspace clone mains not at any publication destination.

    Slot workspace clones accumulate blogs on main that never reach publication
    destinations because the ceremony only promotes from canonical workspaces.
    """
    findings: list[Finding] = []
    for slot_dir in sorted(slots_dir.iterdir()):
        if not slot_dir.is_dir() or slot_dir.name in ("attic", "quarantine"):
            continue
        for clone in sorted(slot_dir.iterdir()):
            if not clone.is_dir():
                continue
            is_workspace = clone.name.startswith("wsp-") or (clone / ".workspace").exists()
            if not is_workspace:
                continue
            if not (clone / ".git").exists():
                continue
            blog = clone / "blog"
            if not blog.exists():
                continue
            for f in sorted(blog.glob("*.md")):
                if f.name in ("INDEX.md",):
                    continue
                if f.name not in published_filenames:
                    findings.append(Finding(
                        "WARN", "slot-blog-unpublished",
                        f"slot {slot_dir.name}/{clone.name}: {f.name} not at any publication destination",
                    ))
    return findings


SKIP_FILENAMES = {"INDEX.md", "index.html", ".gitkeep", "decisions.md", "pipeline.state"}

_IMG_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg"}


def check_workspace_promotion_gaps(
    workspace: Path, project: Path,
) -> list[Finding]:
    """Detect blogs/specs/images in workspace not promoted to project docs/.

    Compares workspace main blog/ against project docs/blog/, and
    workspace specs/ against project docs/specs/. Also checks blog
    images (images/, svg/, assets/ subdirs).
    """
    findings: list[Finding] = []

    for art_type, ws_sub, proj_sub in [
        ("blog", "blog", "docs/blog"),
        ("spec", "specs", "docs/specs"),
    ]:
        ws_dir = workspace / ws_sub
        proj_dir = project / proj_sub
        if not ws_dir.exists():
            continue
        proj_names = set()
        if proj_dir.exists():
            proj_names = {f.name for f in proj_dir.glob("*.md")}
        for f in sorted(ws_dir.glob("*.md")):
            if f.name in SKIP_FILENAMES or f.name in proj_names:
                continue
            findings.append(Finding(
                "ERROR", f"unpromoted-{art_type}",
                f"{workspace.name}/{ws_sub}/{f.name} not in {project.name}/{proj_sub}/",
            ))

    ws_blog = workspace / "blog"
    proj_blog = project / "docs" / "blog"
    if ws_blog.exists() and proj_blog.exists():
        for img_sub in ("images", "svg", "assets"):
            ws_imgs = ws_blog / img_sub
            proj_imgs = proj_blog / img_sub
            if not ws_imgs.exists():
                continue
            proj_img_names = set()
            if proj_imgs.exists():
                proj_img_names = {f.name for f in proj_imgs.iterdir()
                                  if f.suffix.lower() in _IMG_SUFFIXES}
            for f in ws_imgs.iterdir():
                if f.suffix.lower() in _IMG_SUFFIXES and f.name not in proj_img_names:
                    findings.append(Finding(
                        "WARN", "unpromoted-image",
                        f"{workspace.name}/blog/{img_sub}/{f.name} not in {project.name}/docs/blog/{img_sub}/",
                    ))

    return findings


def promote_workspace_gaps(
    workspace: Path, project: Path,
) -> list[str]:
    """Auto-fix workspace→project promotion gaps. Returns list of actions taken."""
    import shutil

    actions: list[str] = []

    for art_type, ws_sub, proj_sub in [
        ("blog", "blog", "docs/blog"),
        ("spec", "specs", "docs/specs"),
    ]:
        ws_dir = workspace / ws_sub
        proj_dir = project / proj_sub
        if not ws_dir.exists():
            continue
        proj_dir.mkdir(parents=True, exist_ok=True)
        proj_names = {f.name for f in proj_dir.glob("*.md")}
        for f in sorted(ws_dir.glob("*.md")):
            if f.name in SKIP_FILENAMES or f.name in proj_names:
                continue
            shutil.copy2(str(f), str(proj_dir / f.name))
            actions.append(f"PROMOTED {art_type}: {f.name}")

    ws_blog = workspace / "blog"
    proj_blog = project / "docs" / "blog"
    if ws_blog.exists():
        for img_sub in ("images", "svg", "assets"):
            ws_imgs = ws_blog / img_sub
            proj_imgs = proj_blog / img_sub
            if not ws_imgs.exists():
                continue
            proj_imgs.mkdir(parents=True, exist_ok=True)
            proj_img_names = {f.name for f in proj_imgs.iterdir()
                              if f.suffix.lower() in _IMG_SUFFIXES} if proj_imgs.exists() else set()
            for f in ws_imgs.iterdir():
                if f.suffix.lower() in _IMG_SUFFIXES and f.name not in proj_img_names:
                    shutil.copy2(str(f), str(proj_imgs / f.name))
                    actions.append(f"PROMOTED image: {img_sub}/{f.name}")

    return actions
