"""Read-only survey of every area in a family root."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml

from git_util import git


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RepoInfo:
    name: str
    path: Path
    role: str  # "project" | "workspace"


@dataclass
class Area:
    kind: str  # "canonical" | "slot" | "clone" | "attic"
    path: Path
    slot_number: int | None = None
    repo_name: str | None = None
    repos: list[RepoInfo] = field(default_factory=list)
    project_repo: RepoInfo | None = None
    workspace_repo: RepoInfo | None = None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _is_workspace(path: Path) -> bool:
    return (path / ".workspace").exists() or path.name.startswith("wsp-")


def _pair_workspace(project_name: str, family_root: Path) -> Path | None:
    wsp = family_root / f"wsp-{project_name}"
    if wsp.is_dir() and (wsp / ".git").exists():
        return wsp
    for child in sorted(family_root.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        if _is_workspace(child):
            proj_link = child / "proj"
            if proj_link.is_symlink():
                target = proj_link.resolve()
                if target.name == project_name:
                    return child
    return None


def _discover_repos_in_area(area_dir: Path) -> tuple[list[RepoInfo], RepoInfo | None, RepoInfo | None]:
    repos: list[RepoInfo] = []
    project_repo = None
    workspace_repo = None
    for child in sorted(area_dir.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        if child.name in ("slots", "clone", "attic"):
            continue
        if _is_workspace(child):
            ri = RepoInfo(name=child.name, path=child, role="workspace")
            repos.append(ri)
            workspace_repo = ri
        else:
            ri = RepoInfo(name=child.name, path=child, role="project")
            repos.append(ri)
            if project_repo is None:
                project_repo = ri
    return repos, project_repo, workspace_repo


def discover_areas(family_root: Path) -> list[Area]:
    canonicals: list[Area] = []
    slots: list[Area] = []
    clones: list[Area] = []
    attics: list[Area] = []

    skip_dirs = {"slots", "clone", "attic", ".git"}

    for child in sorted(family_root.iterdir()):
        if not child.is_dir() or child.name in skip_dirs:
            continue
        if not (child / ".git").exists():
            continue
        if _is_workspace(child):
            continue
        wsp_path = _pair_workspace(child.name, family_root)
        project_ri = RepoInfo(name=child.name, path=child, role="project")
        workspace_ri = None
        all_repos = [project_ri]
        if wsp_path:
            workspace_ri = RepoInfo(name=wsp_path.name, path=wsp_path, role="workspace")
            all_repos.append(workspace_ri)
        canonicals.append(Area(
            kind="canonical", path=child,
            repos=all_repos, project_repo=project_ri,
            workspace_repo=workspace_ri,
        ))

    slots_dir = family_root / "slots"
    if slots_dir.is_dir():
        for child in sorted(slots_dir.iterdir(), key=lambda p: (not p.name.isdigit(), p.name)):
            if child.name == "attic":
                continue
            if not child.is_dir() or not (child / ".slot").exists():
                continue
            repos, proj, wsp = _discover_repos_in_area(child)
            num = int(child.name) if child.name.isdigit() else None
            slots.append(Area(
                kind="slot", path=child, slot_number=num,
                repos=repos, project_repo=proj, workspace_repo=wsp,
            ))

    clone_dir = family_root / "clone"
    if clone_dir.is_dir():
        for child in sorted(clone_dir.iterdir()):
            if not child.is_dir() or not (child / ".permanent").exists():
                continue
            repos, proj, wsp = _discover_repos_in_area(child)
            clones.append(Area(
                kind="clone", path=child, repo_name=child.name,
                repos=repos, project_repo=proj, workspace_repo=wsp,
            ))

    attic_dir = slots_dir / "attic" if slots_dir.is_dir() else None
    if attic_dir and attic_dir.is_dir():
        for child in sorted(attic_dir.iterdir(), key=lambda p: (not p.name.isdigit(), p.name)):
            if not child.is_dir() or not (child / ".slot").exists():
                continue
            repos, proj, wsp = _discover_repos_in_area(child)
            num = int(child.name) if child.name.isdigit() else None
            attics.append(Area(
                kind="attic", path=child, slot_number=num,
                repos=repos, project_repo=proj, workspace_repo=wsp,
            ))

    return canonicals + slots + clones + attics


# ---------------------------------------------------------------------------
# Read-only git helpers
# ---------------------------------------------------------------------------

def follow_state_readonly(clone_repo: Path, canon_repo: Path, base: str) -> str:
    clone_result = git(clone_repo, "rev-parse", "--verify", f"refs/heads/{base}")
    canon_result = git(canon_repo, "rev-parse", "--verify", f"refs/heads/{base}")
    if clone_result.returncode != 0 or canon_result.returncode != 0:
        return "unknown"
    clone_sha = clone_result.stdout.strip()
    canon_sha = canon_result.stdout.strip()
    if clone_sha == canon_sha:
        return "current"
    result = git(clone_repo, "merge-base", clone_sha, canon_sha)
    merge_base = result.stdout.strip()
    if not merge_base:
        return "diverged"
    if merge_base == clone_sha:
        return "fast-forward"
    if merge_base == canon_sha:
        return "ahead"
    return "diverged"


def ahead_readonly(repo: Path, canon_repo: Path, base: str, branch: str) -> int:
    result = git(canon_repo, "rev-parse", "--verify", f"refs/heads/{base}")
    if result.returncode != 0:
        return 0
    canon_sha = result.stdout.strip()
    result = git(repo, "rev-list", "--count", f"{canon_sha}..refs/heads/{branch}")
    count = result.stdout.strip()
    return int(count) if count.isdigit() else 0


def entries_on_ref(repo: Path, ref: str, blog_dir: str = "docs/blog") -> set[str]:
    result = git(repo, "ls-tree", "-r", "--name-only", ref, "--", blog_dir)
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.strip().splitlines() if line}


def entry_content_from_ref(repo: Path, ref: str, path: str) -> str:
    result = git(repo, "show", f"{ref}:{path}")
    return result.stdout if result.returncode == 0 else ""


def parse_frontmatter_from_text(text: str) -> dict[str, Any] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None


# ---------------------------------------------------------------------------
# Inspection data types
# ---------------------------------------------------------------------------

from canonical_sync import locate, in_progress, worktrees
from queue_home import candidates as queue_candidates, uses_root
from slot_io import parse_slot, SlotInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verification import Finding

MARKER_FILES = [
    ".slot", ".permanent", ".queue-root", ".clone-enabled",
    ".landed", ".close-state", ".workspace", "blog-routing.yaml",
]

STAMP_PATTERN = re.compile(
    r"chore: branch closed(?:\s*—\s*landed as\s+(\S+)\s+on\s+(\S+))?"
)


@dataclass
class RepoState:
    name: str
    path: Path
    role: str
    branch: str = ""
    dirty_count: int = 0
    remotes: list[str] = field(default_factory=list)
    ahead_of_canonical: int = 0
    follow_state: str | None = None
    in_progress: str | None = None
    worktrees: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class QueueInfo:
    path: Path
    items: int = 0
    open_items: int = 0
    active_issue: str | None = None
    status: str = ""
    is_root: bool = False


@dataclass
class DriftEntry:
    file: str
    source_repo: str
    dest_repo: str
    status: str  # "gap" | "waiting" | "unpublished"
    bare_project: bool = False


@dataclass
class ClosureRecord:
    branch: str
    source: str = "none"  # "ref" | "stamp" | "none"
    classification: str = "active"
    landed_sha: str | None = None
    landed_on: str | None = None
    promoted: list[str] = field(default_factory=list)
    published: list[str] = field(default_factory=list)
    closed_at: str | None = None


@dataclass
class WorkEndPreview:
    would_land: list[str] = field(default_factory=list)
    needs_promotion: list[str] = field(default_factory=list)
    would_publish: list[str] = field(default_factory=list)
    gates_refusing: list[str] = field(default_factory=list)
    would_skip: bool = True


@dataclass
class AreaReport:
    area: Area
    markers: list[str] = field(default_factory=list)
    repos: list[RepoState] = field(default_factory=list)
    queues: list[QueueInfo] = field(default_factory=list)
    closures: list[ClosureRecord] = field(default_factory=list)
    work_end_preview: WorkEndPreview | None = None
    legacy_layout: bool = False
    findings: list[Finding] = field(default_factory=list)
    drift: list[DriftEntry] = field(default_factory=list)
    slot_info: SlotInfo | None = None
    error: str | None = None


@dataclass
class SurveyResult:
    family_root: Path
    areas: list[AreaReport] = field(default_factory=list)
    attention: list[Finding] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Inspection functions
# ---------------------------------------------------------------------------

def inspect_repo(repo_info: RepoInfo, canon_repo: Path | None = None,
                 base: str = "main") -> RepoState:
    repo = repo_info.path
    branch_result = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

    status_result = git(repo, "status", "--porcelain")
    dirty = len([l for l in status_result.stdout.strip().splitlines() if l]) if status_result.returncode == 0 else 0

    remote_result = git(repo, "remote")
    remotes = [l for l in remote_result.stdout.strip().splitlines() if l] if remote_result.returncode == 0 else []

    ahead = 0
    follow = None
    if canon_repo and canon_repo != repo:
        ahead = ahead_readonly(repo, canon_repo, base, branch)
        follow = follow_state_readonly(repo, canon_repo, base)

    ip = in_progress(repo)

    wt_result = worktrees(repo)
    wt = [(str(p), b) for p, b in wt_result]

    return RepoState(
        name=repo_info.name, path=repo, role=repo_info.role,
        branch=branch, dirty_count=dirty, remotes=remotes,
        ahead_of_canonical=ahead, follow_state=follow,
        in_progress=ip, worktrees=wt,
    )


def inspect_queues(area: Area) -> list[QueueInfo]:
    result = []
    try:
        cands = queue_candidates(area.path)
    except Exception:
        return result
    is_root = uses_root(area.path)
    for c in cands:
        result.append(QueueInfo(
            path=c.path, items=c.items, open_items=c.open_items,
            active_issue=c.active or None, status=c.status,
            is_root=is_root,
        ))
    return result


def inspect_markers(area: Area) -> list[str]:
    return [m for m in MARKER_FILES if (area.path / m).exists()]


def inspect_closures(workspace_repo: RepoInfo, area: Area,
                     queues: list[QueueInfo], base: str = "main") -> list[ClosureRecord]:
    repo = workspace_repo.path
    result_cmd = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    if result_cmd.returncode != 0:
        return []
    branches = [b for b in result_cmd.stdout.strip().splitlines()
                if b and b != base]

    has_open_items = any(q.open_items > 0 for q in queues)
    records: list[ClosureRecord] = []

    for branch in branches:
        log_result = git(repo, "log", "-1", "--format=%s", branch)
        msg = log_result.stdout.strip() if log_result.returncode == 0 else ""

        match = STAMP_PATTERN.search(msg)
        if match:
            records.append(ClosureRecord(
                branch=branch, source="stamp",
                classification="stamped",
                landed_sha=match.group(1), landed_on=match.group(2),
            ))
        else:
            if area.kind == "attic":
                classification = "orphaned"
            elif (area.path / ".landed").exists():
                classification = "landed-not-stamped"
            elif area.kind in ("slot", "clone") and has_open_items:
                classification = "active"
            else:
                classification = "stale"
            records.append(ClosureRecord(
                branch=branch, source="none",
                classification=classification,
            ))

    return records


# ---------------------------------------------------------------------------
# Blog drift detection
# ---------------------------------------------------------------------------

def inspect_promotion_drift(project_repo: RepoInfo, workspace_repo: RepoInfo,
                            base: str) -> list[DriftEntry]:
    drift: list[DriftEntry] = []
    wsp = workspace_repo.path
    proj = project_repo.path

    ws_base_entries = entries_on_ref(wsp, base, "docs/blog")
    proj_base_entries = entries_on_ref(proj, base, "docs/blog")

    ws_branch = git(wsp, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    ws_head_entries = entries_on_ref(wsp, "HEAD", "docs/blog") if ws_branch != base else ws_base_entries

    waiting_entries = ws_head_entries - ws_base_entries
    for entry in sorted(waiting_entries):
        drift.append(DriftEntry(
            file=entry, source_repo=workspace_repo.name,
            dest_repo=project_repo.name, status="waiting",
        ))

    for entry in sorted(ws_base_entries):
        content = entry_content_from_ref(wsp, base, entry)
        fm = parse_frontmatter_from_text(content)
        bare = False
        if fm:
            projects_val = fm.get("projects", "")
            if isinstance(projects_val, list):
                bare = any(isinstance(p, str) and p and "/" not in p for p in projects_val)
            elif isinstance(projects_val, str) and projects_val and "/" not in projects_val:
                bare = True

        is_gap = entry not in proj_base_entries
        if is_gap or bare:
            drift.append(DriftEntry(
                file=entry, source_repo=workspace_repo.name,
                dest_repo=project_repo.name,
                status="gap" if is_gap else "bare-ref-only",
                bare_project=bare,
            ))

    return drift


def resolve_dest_repo(dest_path: Path) -> tuple[Path, str] | None:
    current = dest_path.resolve() if dest_path.exists() else dest_path
    while current != current.parent:
        if (current / ".git").exists():
            base_result = git(current, "rev-parse", "--abbrev-ref", "HEAD")
            base = base_result.stdout.strip() if base_result.returncode == 0 else "main"
            return current, base
        current = current.parent
    return None


def inspect_unpublished(workspace_repo: RepoInfo, base: str,
                        routing_yaml_path: Path) -> list[DriftEntry]:
    if not routing_yaml_path.exists():
        return []
    try:
        config = yaml.safe_load(routing_yaml_path.read_text())
    except (yaml.YAMLError, OSError):
        return []
    if not config:
        return []

    destinations = config.get("destinations", {})
    defaults = config.get("defaults", {})
    default_dests = defaults.get("destinations", [])

    dest_cache: dict[str, tuple[Path, str, str]] = {}
    for name, dest_conf in destinations.items():
        dest_path = Path(str(dest_conf.get("path", ""))).expanduser()
        subdir = dest_conf.get("subdir", "")
        full_path = dest_path / subdir if subdir else dest_path
        resolved = resolve_dest_repo(full_path)
        if resolved:
            dest_cache[name] = (resolved[0], resolved[1], subdir)

    if not dest_cache:
        return []

    wsp = workspace_repo.path
    ws_entries = entries_on_ref(wsp, base, "docs/blog")
    drift: list[DriftEntry] = []

    for entry_path in sorted(ws_entries):
        entry_name = Path(entry_path).name
        missing_at: list[str] = []
        for dest_name in default_dests:
            if dest_name not in dest_cache:
                missing_at.append(dest_name)
                continue
            repo_path, dest_base, subdir = dest_cache[dest_name]
            dest_entries = entries_on_ref(repo_path, dest_base, subdir.rstrip("/"))
            found = any(Path(e).name == entry_name for e in dest_entries)
            if not found:
                missing_at.append(dest_name)

        if missing_at:
            drift.append(DriftEntry(
                file=entry_path, source_repo=workspace_repo.name,
                dest_repo=",".join(missing_at), status="unpublished",
            ))

    return drift


# ---------------------------------------------------------------------------
# Work-end preview
# ---------------------------------------------------------------------------

def work_end_preview(area: Area, repos: list[RepoState],
                     queues: list[QueueInfo], closures: list[ClosureRecord],
                     drift: list[DriftEntry],
                     done_branches: list[str] | None = None) -> WorkEndPreview:
    preview = WorkEndPreview()
    if done_branches:
        preview.would_land = list(done_branches)
        preview.would_skip = False

    gaps = [d for d in drift if d.status == "gap"]
    if gaps:
        preview.needs_promotion = [d.file for d in gaps]
        preview.would_skip = False

    unpub = [d for d in drift if d.status == "unpublished"]
    if unpub:
        preview.would_publish = [d.file for d in unpub]
        preview.would_skip = False

    for branch in (done_branches or []):
        for repo in repos:
            ref_result = git(repo.path, "rev-parse", "--verify",
                             f"refs/squash-reviewed/{branch}")
            if ref_result.returncode != 0:
                preview.gates_refusing.append(f"squash_review_needed:{branch}")

    return preview


# ---------------------------------------------------------------------------
# Finding generation
# ---------------------------------------------------------------------------

def generate_findings(report: AreaReport) -> list[Finding]:
    findings: list[Finding] = []

    if report.error:
        findings.append(Finding("ERROR", "inspection-failed", report.error))
        return findings

    for repo in report.repos:
        if repo.follow_state == "diverged":
            findings.append(Finding(
                "ERROR", "drift",
                f"{report.area.kind} {report.area.path.name}: "
                f"{repo.name} diverged from canonical"))

        if repo.in_progress:
            findings.append(Finding(
                "ERROR", "stuck-operation",
                f"{report.area.path.name}/{repo.name}: "
                f"{repo.in_progress} in progress"))

        if repo.dirty_count > 0 and repo.branch in ("main", "master"):
            findings.append(Finding(
                "WARN", "dirty-base",
                f"{report.area.path.name}/{repo.name}: "
                f"{repo.dirty_count} dirty files on {repo.branch}"))

        if repo.ahead_of_canonical > 0:
            findings.append(Finding(
                "INFO", "ahead",
                f"{report.area.path.name}/{repo.name}: "
                f"{repo.ahead_of_canonical} ahead of canonical"))

    if len(report.queues) > 1 and not any(q.is_root for q in report.queues):
        findings.append(Finding(
            "WARN", "queue-ambiguity",
            f"{report.area.path.name}: {len(report.queues)} queues, no .queue-root"))

    if ".close-state" in report.markers:
        findings.append(Finding(
            "WARN", "stale-state",
            f"{report.area.path.name}: stale .close-state file"))

    if report.legacy_layout:
        findings.append(Finding(
            "INFO", "legacy-layout",
            f"{report.area.path.name}: legacy layout detected"))

    if ".landed" in report.markers and report.area.kind == "slot":
        findings.append(Finding(
            "INFO", "landed-not-archived",
            f"slot {report.area.slot_number or report.area.path.name}: "
            f"landed, ready for archive"))

    for c in report.closures:
        if c.classification == "orphaned":
            findings.append(Finding(
                "WARN", "unstamped-orphaned",
                f"{report.area.path.name}: branch {c.branch} has no stamp"))
        elif c.classification == "landed-not-stamped":
            findings.append(Finding(
                "WARN", "unstamped-orphaned",
                f"{report.area.path.name}: branch {c.branch} landed but not stamped"))
        elif c.classification == "stale":
            findings.append(Finding(
                "INFO", "unstamped-stale",
                f"{report.area.path.name}: branch {c.branch} appears stale"))

    for d in report.drift:
        if d.status == "gap":
            findings.append(Finding(
                "WARN", "promotion-gap",
                f"{d.source_repo}: {d.file} not promoted to {d.dest_repo}"))
        elif d.status == "unpublished":
            findings.append(Finding(
                "INFO", "unpublished",
                f"{d.source_repo}: {d.file} unpublished at {d.dest_repo}"))
        if d.bare_project:
            findings.append(Finding(
                "WARN", "bare-project-ref",
                f"{d.source_repo}/{d.file}: projects value is not owner/repo"))

    return findings


# ---------------------------------------------------------------------------
# Survey orchestrator
# ---------------------------------------------------------------------------

def inspect_area(area: Area, family_root: Path) -> AreaReport:
    report = AreaReport(area=area)

    try:
        canon_repo = None
        base = "main"
        if area.kind in ("slot", "clone", "attic") and area.project_repo:
            try:
                canon = locate(area.project_repo.path)
                canon_repo = canon.repo
                base = canon.base
            except Exception:
                pass

        for ri in area.repos:
            cr = canon_repo if ri.role == "project" else None
            report.repos.append(inspect_repo(ri, canon_repo=cr, base=base))

        report.queues = inspect_queues(area)
        report.markers = inspect_markers(area)

        if area.kind in ("slot", "attic"):
            report.slot_info = parse_slot(area.path)

        has_plan = (area.path / ".plan").exists()
        has_queue = (area.path / ".queue").exists()
        report.legacy_layout = has_plan and not has_queue

        if area.workspace_repo:
            report.closures = inspect_closures(
                area.workspace_repo, area, report.queues, base=base)

        if area.project_repo and area.workspace_repo:
            report.drift = inspect_promotion_drift(
                area.project_repo, area.workspace_repo, base)
            routing_yaml = area.workspace_repo.path / "blog-routing.yaml"
            if not routing_yaml.exists() and area.path != area.workspace_repo.path:
                routing_yaml = area.path / "blog-routing.yaml"
            if routing_yaml.exists():
                unpub = inspect_unpublished(area.workspace_repo, base, routing_yaml)
                report.drift.extend(unpub)

        done_branches: list[str] = []
        if area.workspace_repo:
            try:
                from queue_io import read_queue
                q = read_queue(area.workspace_repo.path)
                if q:
                    done_branches = [
                        item.done_branch for item in q.done_items()
                        if item.done_branch
                    ]
            except Exception:
                pass
        report.work_end_preview = work_end_preview(
            area, report.repos, report.queues, report.closures,
            report.drift, done_branches=done_branches)

        report.findings = generate_findings(report)

    except Exception as e:
        report.error = str(e)
        report.findings = [Finding("ERROR", "inspection-failed", str(e))]

    return report


def survey(family_roots: list[Path]) -> list[SurveyResult]:
    results: list[SurveyResult] = []
    for root in family_roots:
        areas = discover_areas(root)
        reports: list[AreaReport] = []
        for area in areas:
            reports.append(inspect_area(area, root))

        attention: list[Finding] = []
        summary: dict[str, int] = {}
        for r in reports:
            kind = r.area.kind
            summary[kind] = summary.get(kind, 0) + 1
            for f in r.findings:
                if f.severity in ("ERROR", "WARN"):
                    attention.append(f)

        results.append(SurveyResult(
            family_root=root, areas=reports,
            attention=attention, summary=summary,
        ))
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def format_kv(results: list[SurveyResult]) -> str:
    lines: list[str] = []
    for sr in results:
        lines.append(f"FAMILY={sr.family_root}")
        lines.append(f"AREA_COUNT={len(sr.areas)}")
        for kind, count in sorted(sr.summary.items()):
            lines.append(f"{kind.upper()}_COUNT={count}")
        lines.append(f"ATTENTION_COUNT={len(sr.attention)}")

        for i, report in enumerate(sr.areas, 1):
            prefix = f"AREA_{i}"
            a = report.area
            lines.append(f"{prefix}_KIND={a.kind}")
            lines.append(f"{prefix}_PATH={a.path}")
            if a.project_repo:
                lines.append(f"{prefix}_PROJECT={a.project_repo.name}")
            if a.workspace_repo:
                lines.append(f"{prefix}_WORKSPACE={a.workspace_repo.name}")

            for j, repo in enumerate(report.repos, 1):
                rp = f"{prefix}_REPO_{j}"
                lines.append(f"{rp}_NAME={repo.name}")
                lines.append(f"{rp}_BRANCH={repo.branch}")
                lines.append(f"{rp}_DIRTY={repo.dirty_count}")
                lines.append(f"{rp}_AHEAD={repo.ahead_of_canonical}")
                if repo.follow_state:
                    lines.append(f"{rp}_FOLLOW={repo.follow_state}")
                if repo.in_progress:
                    lines.append(f"{rp}_IN_PROGRESS={repo.in_progress}")

            lines.append(f"{prefix}_QUEUES={len(report.queues)}")
            for j, q in enumerate(report.queues, 1):
                qp = f"{prefix}_QUEUE_{j}"
                lines.append(f"{qp}_STATUS={q.status}")
                lines.append(f"{qp}_ITEMS={q.items}")
                lines.append(f"{qp}_OPEN={q.open_items}")
                if q.active_issue:
                    lines.append(f"{qp}_ACTIVE={q.active_issue}")

            if report.work_end_preview and not report.work_end_preview.would_skip:
                wep = report.work_end_preview
                if wep.would_land:
                    lines.append(f"{prefix}_WORK_END_WOULD_LAND={','.join(wep.would_land)}")
                if wep.gates_refusing:
                    lines.append(f"{prefix}_WORK_END_GATES={','.join(wep.gates_refusing)}")

            if report.error:
                lines.append(f"{prefix}_ERROR={report.error}")

        for i, f in enumerate(sr.attention, 1):
            lines.append(f"FINDING_{i}={f.severity}:{f.category}:{f.message}")

    return "\n".join(lines)


if __name__ == "__main__":
    roots = [Path(a) for a in sys.argv[1:] if a != "survey"]
    if not roots:
        print("ERROR=no family roots provided")
        sys.exit(1)
    results = survey(roots)
    print(format_kv(results))
