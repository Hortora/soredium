#!/usr/bin/env python3
"""
Safely rename a workspace repo across all locations.

Discovers every slot, clone, and attic workspace directory in a family,
then rewrites alternates, remotes, symlinks, worklog rows, Claude Code
project directories, and documentation references.

Usage:
    python3 scripts/rename_workspace.py <family_root> old=<name> new=<name>          # audit
    python3 scripts/rename_workspace.py <family_root> old=<name> new=<name> plan     # plan
    python3 scripts/rename_workspace.py <family_root> old=<name> new=<name> --apply  # apply
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

scripts_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(scripts_dir))

from rename_topo import (
    Finding, WorkspaceDir, discover_workspace_dirs,
    find_alternates, find_remotes, find_symlinks,
    find_worklog_rows, find_claude_projects, find_file_references,
    mangle_path,
)


def _github_user(canonical: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(canonical), "remote", "get-url", "origin"],
        capture_output=True, text=True)
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    for prefix in ("https://github.com/", "git@github.com:"):
        if url.startswith(prefix):
            return url[len(prefix):].split("/")[0]
    return None


def _file_ref_patterns(old_name: str, new_name: str) -> tuple[list[str], list[str]]:
    return (
        [f"~/claude/public/{old_name}", f"wsp-{old_name}"],
        [f"~/claude/public/{new_name}", f"wsp-{new_name}"],
    )


def audit(
    family_root: Path,
    old_name: str,
    new_name: str,
    public_dir: Path | None = None,
    db_path: Path | None = None,
    projects_dir: Path | None = None,
    skip_github: bool = False,
) -> list[Finding]:
    if public_dir is None:
        public_dir = family_root.parent / "public"

    old_canonical = public_dir / old_name
    new_canonical = public_dir / new_name
    old_path = str(old_canonical)
    new_path = str(new_canonical)

    findings: list[Finding] = []
    dirs = discover_workspace_dirs(family_root, old_name, public_dir=public_dir)

    if not skip_github and old_canonical.is_dir():
        user = _github_user(old_canonical)
        if user:
            findings.append(Finding(
                location="github",
                current=f"{user}/wsp-{old_name}",
                proposed=f"{user}/wsp-{new_name}",
                category="mechanical",
            ))

    for d in dirs:
        if d.rename_dir:
            if d.layout == "canonical":
                new_dir = public_dir / new_name
            else:
                new_dir = d.path.parent / d.path.name.replace(old_name, new_name)
            findings.append(Finding(
                location=f"dir:{d.layout}",
                current=str(d.path),
                proposed=str(new_dir),
                category="mechanical",
            ))

    findings.extend(find_alternates(dirs, old_path, new_path))
    findings.extend(find_remotes(dirs, old_path, new_path))
    findings.extend(find_symlinks(family_root, old_path, new_path))

    old_pats, new_pats = _file_ref_patterns(old_name, new_name)
    for d in dirs:
        if not d.path.is_dir():
            continue
        for doc in ("CLAUDE.md", "HANDOFF.md"):
            doc_path = d.path / doc
            if doc_path.exists():
                findings.extend(find_file_references(doc_path, old_pats, new_pats))
    for child in sorted(family_root.iterdir()):
        if child.is_dir() and (child / ".git").exists():
            cm = child / "CLAUDE.md"
            if cm.exists():
                findings.extend(find_file_references(cm, old_pats, new_pats))

    clone_base = family_root / "clone"
    if clone_base.is_dir():
        for project_dir in sorted(clone_base.iterdir()):
            qr = project_dir / ".queue-root"
            if qr.exists() and old_name in qr.read_text():
                findings.extend(find_file_references(
                    qr, [f"wsp-{old_name}"], [f"wsp-{new_name}"]))

    findings.extend(find_worklog_rows(old_path, new_path, db_path=db_path))
    for d in dirs:
        if d.layout in ("clone", "slot") and str(d.path) != old_path:
            findings.extend(find_worklog_rows(
                str(d.path), str(d.path).replace(old_name, new_name),
                db_path=db_path))

    findings.extend(find_claude_projects(old_path, new_path,
                                         projects_dir=projects_dir))

    return findings


def apply(
    family_root: Path,
    old_name: str,
    new_name: str,
    public_dir: Path | None = None,
    db_path: Path | None = None,
    projects_dir: Path | None = None,
    skip_github: bool = False,
) -> int:
    if public_dir is None:
        public_dir = family_root.parent / "public"

    old_canonical = public_dir / old_name
    new_canonical = public_dir / new_name
    old_path = str(old_canonical)
    new_path = str(new_canonical)
    actions = 0

    # 1. GitHub rename
    if not skip_github and old_canonical.is_dir():
        user = _github_user(old_canonical)
        if user:
            result = subprocess.run(
                ["gh", "repo", "rename", f"wsp-{new_name}",
                 "--repo", f"{user}/wsp-{old_name}", "--yes"],
                capture_output=True, text=True)
            if result.returncode == 0:
                print(f"OK: GitHub {user}/wsp-{old_name} → wsp-{new_name}")
                actions += 1
            else:
                print(f"FAIL: GitHub rename: {result.stderr.strip()}")
                return -1

    # 2. Canonical directory rename
    if old_canonical.is_dir():
        old_canonical.rename(new_canonical)
        print(f"OK: {old_canonical} → {new_canonical}")
        actions += 1
    elif not new_canonical.is_dir():
        print(f"SKIP: neither {old_canonical} nor {new_canonical} exists")

    # 3. Clone/slot directory renames
    dirs = discover_workspace_dirs(family_root, old_name, public_dir=public_dir)
    for d in dirs:
        if d.rename_dir and d.path.is_dir():
            new_dir = d.path.parent / d.path.name.replace(old_name, new_name)
            if not new_dir.exists():
                d.path.rename(new_dir)
                print(f"OK: {d.path} → {new_dir}")
                actions += 1

    # Re-discover with both old and new names to catch everything
    all_dirs = discover_workspace_dirs(family_root, new_name, public_dir=public_dir)
    all_dirs.extend(discover_workspace_dirs(family_root, old_name, public_dir=public_dir))
    seen: set[str] = set()
    deduped: list[WorkspaceDir] = []
    for d in all_dirs:
        key = str(d.path)
        if key not in seen:
            seen.add(key)
            deduped.append(d)
    all_dirs = deduped

    # 4. Alternates
    for f in find_alternates(all_dirs, old_path, new_path):
        alt_file = Path(f.location)
        if alt_file.exists():
            content = alt_file.read_text()
            alt_file.write_text(content.replace(old_path, new_path))
            print(f"OK: alternates {alt_file}")
            actions += 1

    # 5. Remotes
    for f in find_remotes(all_dirs, old_path, new_path):
        ws_path, remote_name = f.location.rsplit(":", 1)
        subprocess.run(
            ["git", "-C", ws_path, "remote", "set-url", remote_name, f.proposed],
            capture_output=True, check=True)
        print(f"OK: remote {ws_path}:{remote_name}")
        actions += 1

    # GitHub remote on canonical
    if new_canonical.is_dir() and not skip_github:
        result = subprocess.run(
            ["git", "-C", str(new_canonical), "remote", "get-url", "origin"],
            capture_output=True, text=True)
        if result.returncode == 0 and old_name in result.stdout:
            new_url = result.stdout.strip().replace(
                f"wsp-{old_name}", f"wsp-{new_name}")
            subprocess.run(
                ["git", "-C", str(new_canonical), "remote", "set-url",
                 "origin", new_url],
                capture_output=True, check=True)
            print(f"OK: canonical origin → {new_url}")
            actions += 1

    # 6. Symlinks
    for f in find_symlinks(family_root, old_path, new_path):
        link = Path(f.location)
        if link.is_symlink():
            link.unlink()
            os.symlink(f.proposed, link)
            print(f"OK: symlink {link}")
            actions += 1

    # 7. Worklog
    if db_path is None:
        db_path = Path.home() / ".hortora" / "worklog.db"
    if db_path.exists():
        worklog_findings: list[Finding] = []
        worklog_findings.extend(find_worklog_rows(old_path, new_path, db_path=db_path))
        for d in all_dirs:
            old_d = str(d.path).replace(new_name, old_name)
            if old_d != str(d.path):
                worklog_findings.extend(
                    find_worklog_rows(old_d, str(d.path), db_path=db_path))
        if worklog_findings:
            today = datetime.date.today().strftime("%Y%m%d")
            backup = db_path.parent / f"{db_path.name}.before-rename-{today}"
            if not backup.exists():
                src_conn = sqlite3.connect(str(db_path))
                dst_conn = sqlite3.connect(str(backup))
                src_conn.backup(dst_conn)
                dst_conn.close()
                src_conn.close()
                print(f"OK: worklog backup → {backup}")
            conn = sqlite3.connect(str(db_path))
            for f in worklog_findings:
                _id = int(f.location.split("id=")[1])
                conn.execute("UPDATE repos SET path = ? WHERE id = ?",
                             (f.proposed, _id))
            conn.commit()
            conn.close()
            actions += len(worklog_findings)
            print(f"OK: worklog {len(worklog_findings)} rows updated")

    # 8. File references (CLAUDE.md, HANDOFF.md)
    old_pats, new_pats = _file_ref_patterns(old_name, new_name)
    for d in all_dirs:
        if not d.path.is_dir():
            continue
        for doc in ("CLAUDE.md", "HANDOFF.md"):
            doc_path = d.path / doc
            if not doc_path.exists():
                continue
            refs = find_file_references(doc_path, old_pats, new_pats)
            if refs:
                content = doc_path.read_text()
                for old_p, new_p in zip(old_pats, new_pats):
                    content = content.replace(old_p, new_p)
                doc_path.write_text(content)
                print(f"OK: {doc_path} ({len(refs)} lines)")
                actions += 1

    for child in sorted(family_root.iterdir()):
        if child.is_dir() and (child / ".git").exists():
            cm = child / "CLAUDE.md"
            if not cm.exists():
                continue
            refs = find_file_references(cm, old_pats, new_pats)
            if refs:
                content = cm.read_text()
                for old_p, new_p in zip(old_pats, new_pats):
                    content = content.replace(old_p, new_p)
                cm.write_text(content)
                print(f"OK: {cm} ({len(refs)} lines)")
                actions += 1

    # 9. .queue-root
    clone_base = family_root / "clone"
    if clone_base.is_dir():
        for project_dir in sorted(clone_base.iterdir()):
            qr = project_dir / ".queue-root"
            if qr.exists() and old_name in qr.read_text():
                content = qr.read_text()
                content = content.replace(f"wsp-{old_name}", f"wsp-{new_name}")
                qr.write_text(content)
                print(f"OK: {qr}")
                actions += 1

    # 10. Claude projects
    if projects_dir is None:
        projects_dir = Path.home() / ".claude" / "projects"
    for f in find_claude_projects(old_path, new_path, projects_dir=projects_dir):
        old_dir = Path(f.location)
        new_dir = old_dir.parent / f.proposed
        if old_dir.is_dir() and not new_dir.exists():
            old_dir.rename(new_dir)
            print(f"OK: Claude projects {old_dir.name} → {f.proposed}")
            actions += 1

    return actions


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 3:
        print(__doc__.strip())
        return 1

    family_root = Path(args[0]).expanduser().resolve()
    old_name = new_name = ""
    mode = "audit"
    for arg in args[1:]:
        if arg.startswith("old="):
            old_name = arg[4:]
        elif arg.startswith("new="):
            new_name = arg[4:]
        elif arg == "plan":
            mode = "plan"
        elif arg == "--apply":
            mode = "apply"

    if not old_name or not new_name:
        print("Required: old=<name> new=<name>")
        return 1

    if mode == "apply":
        count = apply(family_root, old_name, new_name)
        if count < 0:
            return 1
        print(f"\n{count} actions applied.")
        return 0

    findings = audit(family_root, old_name, new_name)
    mechanical = [f for f in findings if f.category == "mechanical"]
    historical = [f for f in findings if f.category == "historical"]
    advisory = [f for f in findings if f.category == "advisory"]

    if not findings:
        print("Nothing to do.")
        return 0

    print(f"{'LAYER':<15} {'LOCATION':<60} {'ACTION'}")
    print("-" * 110)
    for f in mechanical:
        loc = f.location if len(f.location) <= 60 else "..." + f.location[-57:]
        cur = f.current[:25] if len(f.current) > 25 else f.current
        prop = f.proposed[:25] if len(f.proposed) > 25 else f.proposed
        print(f"{'mechanical':<15} {loc:<60} {cur} → {prop}")

    if historical:
        print(f"\n{len(historical)} historical references (no change)")
    if advisory:
        print(f"\n{len(advisory)} advisory items")

    if mode == "plan":
        print(f"\nRun with --apply to execute {len(mechanical)} actions.")

    return 1 if mechanical else 0


if __name__ == "__main__":
    sys.exit(main())
