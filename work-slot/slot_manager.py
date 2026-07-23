#!/usr/bin/env python3
"""
slot_manager.py — Worktree slot operations for multi-repo families

Subcommands:
  create-slot <family-root> repos=<csv> branch=<name> issue=<N> issue-repo=<o/r> [covers=<csv>] [context=<text>]
  list-slots <family-root> [--all]
  remove-slot <family-root> slot=<N> [--force-delete]
  scan-ready <family-root>
  merge-slot <family-root> slot=<N>
  archive-slot <family-root> slot=<N>

Note: remove-slot archives to worktrees/attic/ by default. Only --force-delete permanently removes.

All commands output KEY=VALUE pairs on stdout for easy parsing.
"""

import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run_cmd(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout, result.stderr


def allocate_slot_number(worktrees_dir: Path) -> int:
    if not worktrees_dir.exists():
        return 1
    existing = [
        int(d.name) for d in worktrees_dir.iterdir()
        if d.is_dir() and d.name.isdigit()
    ]
    attic_dir = worktrees_dir / "attic"
    if attic_dir.exists():
        existing.extend(
            int(d.name) for d in attic_dir.iterdir()
            if d.is_dir() and d.name.isdigit()
        )
    return max(existing, default=0) + 1


def resolve_workspace_source(repo_path: Path) -> tuple[Path, str] | None:
    wksp = repo_path / "wksp"
    if not wksp.is_symlink():
        return None
    target = wksp.resolve()
    parent = target.parent
    if (parent / ".git").exists() or (parent / ".git").is_file():
        return parent, "work"
    if (target / ".git").exists() or (target / ".git").is_file():
        return target, f"work-{target.name}"
    return None


def setup_maven_config(repo_worktree: Path, m2_path: Path) -> None:
    mvn_dir = repo_worktree / ".mvn"
    mvn_dir.mkdir(parents=True, exist_ok=True)
    config_file = mvn_dir / "maven.config"
    line = f"-Dmaven.repo.local={m2_path}"
    if config_file.exists():
        content = config_file.read_text()
        if line not in content:
            config_file.write_text(content.rstrip() + "\n" + line + "\n")
    else:
        config_file.write_text(line + "\n")


def repoint_wksp(repo_worktree: Path, ws_subdir: Path) -> None:
    wksp = repo_worktree / "wksp"
    if wksp.is_symlink() or wksp.exists():
        wksp.unlink()
    rel = os.path.relpath(ws_subdir, repo_worktree)
    wksp.symlink_to(rel)


def create_proj_symlink(ws_subdir: Path, repo_worktree: Path) -> None:
    proj = ws_subdir / "proj"
    if proj.is_symlink() or proj.exists():
        proj.unlink()
    rel = os.path.relpath(repo_worktree, ws_subdir)
    proj.symlink_to(rel)


def replicate_claude_md(repo_path: Path, ws_subdir: Path, repo_worktree: Path) -> None:
    orig_wksp = repo_path / "wksp"
    if not orig_wksp.is_symlink():
        return
    orig_ws_target = orig_wksp.resolve()
    orig_claude = orig_ws_target / "CLAUDE.md"
    if not orig_claude.exists():
        return

    ws_claude = ws_subdir / "CLAUDE.md"
    proj_claude = repo_worktree / "CLAUDE.md"

    if orig_claude.is_symlink():
        # Workspace symlink → project real file (most repos).
        # Project worktree already has the file (git-tracked).
        if not ws_claude.exists():
            ws_claude.symlink_to("proj/CLAUDE.md")
    else:
        # Workspace real file → project symlink (e.g. pages).
        # Copy to workspace subdir, symlink from project worktree.
        if not ws_claude.exists():
            shutil.copy2(str(orig_claude), str(ws_claude))
        if not proj_claude.exists():
            proj_claude.symlink_to("wksp/CLAUDE.md")


def sync_main(repo_path: str) -> None:
    rc, _, _ = run_cmd(["git", "-C", repo_path, "fetch", "origin"])
    if rc != 0:
        print(f"WARN=fetch_failed repo={repo_path}")
        return
    rc, _, _ = run_cmd(["git", "-C", repo_path, "remote", "get-url", "upstream"])
    if rc == 0:
        run_cmd(["git", "-C", repo_path, "fetch", "upstream"])
        run_cmd(["git", "-C", repo_path, "rebase", "upstream/main"])
        run_cmd(["git", "-C", repo_path, "push", "origin", "main"])
    else:
        run_cmd(["git", "-C", repo_path, "rebase", "origin/main"])


def write_slot_md(slot_dir: Path, slot_number: int, repos: list[str],
                  branch: str, issue: str, issue_repo: str,
                  covers: str, context: str) -> None:
    content = f"""# Slot {slot_number} — {branch}

## Issue
{issue_repo}#{issue}
Covers: {covers}

## What to do
{context}

## Repos
"""
    for i, repo in enumerate(repos):
        primary = " (primary)" if i == 0 else ""
        content += f"- {repo}{primary}\n"
    content += f"\n## Created\n{datetime.date.today().isoformat()}, branch: {branch}\n"
    (slot_dir / "SLOT.md").write_text(content)


def create_slot(family_root: Path, repos: list[str], branch: str,
                issue: str, issue_repo: str, covers: str,
                context: str) -> dict:
    worktrees_dir = family_root / "worktrees"
    worktrees_dir.mkdir(exist_ok=True)
    slot_num = allocate_slot_number(worktrees_dir)
    slot_dir = worktrees_dir / str(slot_num)
    slot_dir.mkdir()
    m2_dir = slot_dir / ".m2"
    m2_dir.mkdir()

    ws_created: dict[str, Path] = {}

    for repo_name in repos:
        repo_path = family_root / repo_name
        if not repo_path.is_dir():
            print(f"ERROR=repo_not_found repo={repo_name}")
            sys.exit(1)

        sync_main(str(repo_path))

        rc, _, stderr = run_cmd([
            "git", "-C", str(repo_path),
            "worktree", "add", str(slot_dir / repo_name), "-b", branch,
        ])
        if rc != 0:
            print(f"ERROR=worktree_add_failed repo={repo_name} stderr={stderr.strip()}")
            sys.exit(1)

        setup_maven_config(slot_dir / repo_name, m2_dir)

        ws_info = resolve_workspace_source(repo_path)
        if ws_info:
            ws_source, ws_name = ws_info
            ws_key = str(ws_source)
            ws_slot_dir = slot_dir / ws_name

            if ws_key not in ws_created:
                sync_main(str(ws_source))
                rc, _, stderr = run_cmd([
                    "git", "-C", str(ws_source),
                    "worktree", "add", str(ws_slot_dir), "-b", branch,
                ])
                if rc != 0:
                    print(f"ERROR=workspace_worktree_failed ws={ws_name} stderr={stderr.strip()}")
                    sys.exit(1)
                ws_created[ws_key] = ws_slot_dir

            wksp_target = repo_path / "wksp"
            if wksp_target.is_symlink():
                orig_target = wksp_target.resolve()
                try:
                    rel_subdir = orig_target.relative_to(ws_source)
                    ws_subdir = ws_slot_dir / rel_subdir
                except ValueError:
                    ws_subdir = ws_slot_dir

                ws_subdir.mkdir(parents=True, exist_ok=True)
                repoint_wksp(slot_dir / repo_name, ws_subdir)
                create_proj_symlink(ws_subdir, slot_dir / repo_name)
                replicate_claude_md(repo_path, ws_subdir, slot_dir / repo_name)

    primary_repo = repos[0]
    primary_wksp = slot_dir / primary_repo / "wksp"
    if primary_wksp.is_symlink():
        ws_path = primary_wksp.resolve()
        scaffold_script = Path.home() / ".claude" / "skills" / "work-start" / "scaffold.py"
        if scaffold_script.exists():
            run_cmd([
                sys.executable, str(scaffold_script), str(ws_path),
                f"branch={branch}",
                f"project-sha=slot-creation",
                f"date={datetime.date.today().isoformat()}",
                f"issue={issue}",
                f"issue-repo={issue_repo}",
                f"covers={covers}",
            ])

    write_slot_md(slot_dir, slot_num, repos, branch, issue,
                  issue_repo, covers, context)

    return {
        "slot_number": slot_num,
        "slot_dir": str(slot_dir),
        "branch": branch,
        "repos": repos,
    }


def is_project_repo(name: str) -> bool:
    return not name.startswith("work") and name != ".m2" and name != "attic"


def get_slot_repos(slot_dir: Path) -> list[str]:
    return [
        d.name for d in sorted(slot_dir.iterdir())
        if d.is_dir() and (d / ".git").exists() and is_project_repo(d.name)
    ]


def parse_slot_md(slot_dir: Path) -> dict:
    slot_md = slot_dir / "SLOT.md"
    if not slot_md.exists():
        return {}
    content = slot_md.read_text()
    result: dict = {"repos": [], "context": "", "issue": "", "issue_repo": "", "covers": ""}

    in_issue = False
    in_what = False
    in_repos = False
    context_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("# Slot") and "—" in line:
            result["branch"] = line.split("—", 1)[1].strip()
        if line.startswith("Covers:"):
            result["covers"] = line.split(":", 1)[1].strip()
        if line.startswith("## Issue"):
            in_issue, in_what, in_repos = True, False, False
            continue
        if line.startswith("## What to do"):
            in_issue, in_what, in_repos = False, True, False
            continue
        if line.startswith("## Repos"):
            in_issue, in_what, in_repos = False, False, True
            continue
        if line.startswith("## "):
            in_issue, in_what, in_repos = False, False, False
            continue
        if in_issue and "#" in line and not line.startswith("Covers:"):
            parts = line.strip().split("#")
            if len(parts) == 2:
                result["issue_repo"] = parts[0]
                result["issue"] = parts[1]
        if in_what:
            context_lines.append(line.strip())
        if in_repos and line.strip().startswith("- "):
            repo_name = line.strip().lstrip("- ").split(" ")[0].strip()
            if repo_name:
                result["repos"].append(repo_name)

    result["context"] = " ".join(l for l in context_lines if l).strip()
    return result


def get_repo_stats(repo_path: Path) -> dict:
    rc, log_out, _ = run_cmd(
        ["git", "-C", str(repo_path), "log", "--oneline", "origin/main..HEAD"]
    )
    commits = len(log_out.strip().splitlines()) if rc == 0 and log_out.strip() else 0
    rc, stat_out, _ = run_cmd(
        ["git", "-C", str(repo_path), "diff", "--shortstat", "origin/main..HEAD"]
    )
    diff = stat_out.strip() if rc == 0 else ""
    return {"commits": commits, "diff": diff}


def scan_ready(family_root: Path) -> list[dict]:
    worktrees_dir = family_root / "worktrees"
    if not worktrees_dir.exists():
        return []
    slots = []
    for d in sorted(worktrees_dir.iterdir()):
        if not d.is_dir() or not d.name.isdigit():
            continue
        if not (d / ".phase-a-complete").exists():
            continue
        if (d / ".landed").exists():
            continue
        timestamp = ""
        for line in (d / ".phase-a-complete").read_text().splitlines():
            if line.startswith("timestamp="):
                timestamp = line.split("=", 1)[1]
        md = parse_slot_md(d)
        repo_names = md.get("repos", [])
        repo_data = []
        for repo_name in repo_names:
            repo_path = d / repo_name
            if repo_path.is_dir() and (repo_path / ".git").exists():
                stats = get_repo_stats(repo_path)
                repo_data.append({"name": repo_name, **stats})
            else:
                repo_data.append({"name": repo_name, "commits": 0, "diff": ""})
        slots.append({
            "number": int(d.name),
            "branch": md.get("branch", ""),
            "repos": repo_data,
            "issue": md.get("issue", ""),
            "issue_repo": md.get("issue_repo", ""),
            "covers": md.get("covers", ""),
            "context": md.get("context", ""),
            "phase_a_timestamp": timestamp,
        })
    return slots


def resolve_original_repo(worktree_path: Path) -> Path:
    rc, common_dir, _ = run_cmd(
        ["git", "-C", str(worktree_path), "rev-parse", "--git-common-dir"]
    )
    if rc != 0:
        return worktree_path
    common = Path(common_dir.strip())
    if not common.is_absolute():
        common = (worktree_path / common).resolve()
    return common.parent


def merge_slot(family_root: Path, slot_num: int) -> int:
    slot_dir = family_root / "worktrees" / str(slot_num)
    if not slot_dir.exists():
        print(f"ERROR=slot_not_found slot={slot_num}")
        return 1
    if not (slot_dir / ".phase-a-complete").exists():
        print(f"ERROR=not_ready slot={slot_num}")
        return 1
    if (slot_dir / ".landed").exists():
        print(f"ERROR=already_landed slot={slot_num}")
        return 1

    branch = ""
    for line in (slot_dir / ".phase-a-complete").read_text().splitlines():
        if line.startswith("branch="):
            branch = line.split("=", 1)[1]
    if not branch:
        print("ERROR=no_branch_in_marker")
        return 1

    repos = get_slot_repos(slot_dir)
    if not repos:
        print("ERROR=no_repos_in_slot")
        return 1

    progress_file = slot_dir / ".merge-progress"
    pushed_repos: set[str] = set()
    if progress_file.exists():
        for line in progress_file.read_text().splitlines():
            if "=pushed:" in line:
                pushed_repos.add(line.split("=")[0])

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        print(f"STAGE=rebase ATTEMPT={attempt}")
        for repo_name in repos:
            slot_repo = slot_dir / repo_name
            run_cmd(["git", "-C", str(slot_repo), "fetch", "origin", "main"])
            rc, _, _ = run_cmd(["git", "-C", str(slot_repo), "rebase", "origin/main"])
            if rc != 0:
                run_cmd(["git", "-C", str(slot_repo), "rebase", "--abort"])
                print("STAGE=rebase STATUS=fail")
                print(f"ERROR=conflict repo={repo_name}")
                return 1
        print("STAGE=rebase STATUS=pass")

        print(f"STAGE=push ATTEMPT={attempt}")
        push_failed = False
        landed_shas: dict[str, str] = {}

        for repo_name in repos:
            if repo_name in pushed_repos:
                for line in progress_file.read_text().splitlines():
                    if line.startswith(f"{repo_name}=pushed:"):
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            landed_shas[repo_name] = parts[1]
                continue

            slot_repo = slot_dir / repo_name
            original = resolve_original_repo(slot_repo)
            rc, _, _ = run_cmd(["git", "-C", str(original), "fetch", "origin", "main"])
            if rc != 0:
                push_failed = True
                print(f"WARN=fetch_failed repo={repo_name} attempt={attempt}")
                break
            rc, _, _ = run_cmd(["git", "-C", str(original), "rebase", "origin/main"])
            if rc != 0:
                push_failed = True
                print(f"WARN=rebase_failed repo={repo_name} attempt={attempt}")
                break
            rc, _, _ = run_cmd(["git", "-C", str(original), "merge", "--ff-only", branch])
            if rc != 0:
                push_failed = True
                print(f"WARN=ff_only_failed repo={repo_name} attempt={attempt}")
                break
            rc, _, _ = run_cmd(["git", "-C", str(original), "push", "origin", "main"])
            if rc != 0:
                push_failed = True
                print(f"WARN=push_failed repo={repo_name} attempt={attempt}")
                break

            rc, sha, _ = run_cmd(["git", "-C", str(original), "rev-parse", "HEAD"])
            sha = sha.strip() if rc == 0 else "unknown"
            landed_shas[repo_name] = sha
            with open(progress_file, "a") as f:
                f.write(f"{repo_name}=pushed:{sha}\n")
            pushed_repos.add(repo_name)

        if push_failed:
            if attempt < max_attempts:
                continue
            print("STAGE=push STATUS=fail")
            print("ERROR=retry_exhausted")
            return 1

        if progress_file.exists():
            progress_file.unlink()
        shas_str = ",".join(f"{r}:{s}" for r, s in landed_shas.items())
        (slot_dir / ".landed").write_text(
            f"branch={branch}\n"
            f"repos={','.join(repos)}\n"
            f"landed_shas={shas_str}\n"
            f"timestamp={datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
        )
        print("STAGE=push STATUS=pass")
        print(f"LANDED_SHAS={shas_str}")
        return 0

    return 1


def relocate_claude_projects(slot_dir: Path, dest_dir: Path) -> int:
    """Move .claude/projects/ directories to match the slot's new attic path."""
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.is_dir():
        return 0

    slot_path_encoded = str(slot_dir).replace("/", "-")
    dest_path_encoded = str(dest_dir).replace("/", "-")
    moved = 0

    for proj_dir in claude_projects.iterdir():
        if not proj_dir.is_dir():
            continue
        if slot_path_encoded in proj_dir.name:
            new_name = proj_dir.name.replace(slot_path_encoded, dest_path_encoded)
            new_path = claude_projects / new_name
            if not new_path.exists():
                shutil.move(str(proj_dir), str(new_path))
                moved += 1
    return moved


def archive_slot(family_root: Path, slot_num: int) -> None:
    slot_dir = family_root / "worktrees" / str(slot_num)
    if not slot_dir.exists():
        print(f"ERROR=slot_not_found slot={slot_num}")
        sys.exit(1)
    for sub in slot_dir.iterdir():
        if sub.is_dir() and (sub / ".git").exists():
            rc, _, stderr = run_cmd(["git", "worktree", "remove", "--force", str(sub)])
            if rc != 0:
                print(f"WARN=worktree_remove_failed dir={sub.name} stderr={stderr.strip()}")
    attic_dir = family_root / "worktrees" / "attic"
    attic_dir.mkdir(exist_ok=True)
    dest = attic_dir / str(slot_num)
    moved = relocate_claude_projects(slot_dir, dest)
    shutil.move(str(slot_dir), str(dest))
    if moved:
        print(f"CLAUDE_PROJECTS_MOVED={moved}")
    print(f"ARCHIVED={slot_num}")


def list_slots(family_root: Path, include_archived: bool = False) -> list[dict]:
    worktrees_dir = family_root / "worktrees"
    if not worktrees_dir.exists():
        return []
    slots = []
    for d in sorted(worktrees_dir.iterdir()):
        if not d.is_dir() or not d.name.isdigit():
            continue
        repos = [
            sub.name for sub in sorted(d.iterdir())
            if sub.is_dir() and (sub / ".git").exists() and is_project_repo(sub.name)
        ]
        branch = ""
        slot_md = d / "SLOT.md"
        if slot_md.exists():
            for line in slot_md.read_text().splitlines():
                if line.startswith("# Slot") and "—" in line:
                    branch = line.split("—", 1)[1].strip()
                    break

        if (d / ".landed").exists():
            state = "landed"
        elif (d / ".phase-a-complete").exists():
            state = "ready to land"
        else:
            state = "active"

        slots.append({
            "number": int(d.name),
            "branch": branch,
            "repos": repos,
            "state": state,
        })

    if include_archived:
        attic_dir = worktrees_dir / "attic"
        if attic_dir.exists():
            for d in sorted(attic_dir.iterdir()):
                if not d.is_dir() or not d.name.isdigit():
                    continue
                md = parse_slot_md(d)
                slots.append({
                    "number": int(d.name),
                    "branch": md.get("branch", ""),
                    "repos": md.get("repos", []),
                    "state": "archived",
                })

    return slots


def remove_slot(family_root: Path, slot_num: int, force_delete: bool = False) -> None:
    slot_dir = family_root / "worktrees" / str(slot_num)
    if not slot_dir.exists():
        print(f"ERROR=slot_not_found slot={slot_num}")
        sys.exit(1)

    for sub in slot_dir.iterdir():
        if sub.is_dir() and (sub / ".git").exists():
            run_cmd(["git", "worktree", "remove", "--force", str(sub)])

    if force_delete:
        shutil.rmtree(slot_dir, ignore_errors=True)
        print(f"DELETED={slot_num}")
    else:
        attic_dir = family_root / "worktrees" / "attic"
        attic_dir.mkdir(exist_ok=True)
        dest = attic_dir / str(slot_num)
        moved = relocate_claude_projects(slot_dir, dest)
        shutil.move(str(slot_dir), str(dest))
        if moved:
            print(f"CLAUDE_PROJECTS_MOVED={moved}")
        print(f"ARCHIVED={slot_num}")


def parse_args() -> dict[str, str]:
    parsed = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            key, val = arg.split("=", 1)
            parsed[key] = val
        else:
            if "subcommand" not in parsed:
                parsed["subcommand"] = arg
            elif "target" not in parsed:
                parsed["target"] = arg
    return parsed


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    args = parse_args()
    subcommand = args.get("subcommand")

    if subcommand == "create-slot":
        family_root = Path(args.get("target", "."))
        repos = [r.strip() for r in args.get("repos", "").split(",") if r.strip()]
        if not repos:
            print("ERROR=missing_repos")
            sys.exit(1)
        branch = args.get("branch", "")
        if not branch:
            print("ERROR=missing_branch")
            sys.exit(1)
        result = create_slot(
            family_root=family_root,
            repos=repos,
            branch=branch,
            issue=args.get("issue", ""),
            issue_repo=args.get("issue-repo", ""),
            covers=args.get("covers", args.get("issue", "")),
            context=args.get("context", ""),
        )
        print(f"SLOT_NUMBER={result['slot_number']}")
        print(f"SLOT_DIR={result['slot_dir']}")
        print(f"BRANCH={result['branch']}")

    elif subcommand == "list-slots":
        family_root = Path(args.get("target", "."))
        include_archived = "--all" in sys.argv
        slots = list_slots(family_root, include_archived=include_archived)
        for s in slots:
            repos_str = ",".join(s["repos"]) if isinstance(s["repos"], list) else s["repos"]
            print(f"SLOT={s['number']} BRANCH={s['branch']} REPOS={repos_str} STATE={s['state']}")
        print(f"COUNT={len(slots)}")

    elif subcommand == "remove-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        force_delete = "--force-delete" in sys.argv
        remove_slot(family_root, slot_num, force_delete=force_delete)

    elif subcommand == "scan-ready":
        family_root = Path(args.get("target", "."))
        slots = scan_ready(family_root)
        print(json.dumps({"slots": slots}, indent=2))

    elif subcommand == "merge-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        sys.exit(merge_slot(family_root, slot_num))

    elif subcommand == "archive-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        archive_slot(family_root, slot_num)

    else:
        print(f"ERROR=unknown_subcommand subcommand={subcommand}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
