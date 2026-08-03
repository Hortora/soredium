#!/usr/bin/env python3
"""Recover orphaned specs from closed workspace branches to main."""

import subprocess
import sys
from pathlib import Path


def run(*cmd, cwd=None):
    r = subprocess.run(list(cmd), capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def git(*cmd, cwd):
    return run("git", "-C", str(cwd), *cmd)


def list_branches(ws):
    rc, out, _ = git("branch", "--format=%(refname:short)", cwd=ws)
    if rc != 0:
        return []
    return [b.strip() for b in out.splitlines() if b.strip() and b.strip() != "main"]


def specs_on_branch(ws, branch):
    """List spec files on a branch via git ls-tree."""
    rc, out, _ = git("ls-tree", "-r", "--name-only", branch, "--", "specs/", cwd=ws)
    if rc != 0:
        return []
    return [f for f in out.splitlines() if f.endswith(".md") and "INDEX.md" not in f]


def specs_on_main(ws):
    rc, out, _ = git("ls-tree", "-r", "--name-only", "main", "--", "specs/", cwd=ws)
    if rc != 0:
        return []
    return set(out.splitlines())


def is_closed(ws, branch):
    """Check if branch has EPIC-CLOSED.md or closure stamp."""
    rc, _, _ = git("cat-file", "-e", f"{branch}:design/EPIC-CLOSED.md", cwd=ws)
    if rc == 0:
        return True
    rc2, out, _ = git("log", "-1", "--format=%s", branch, cwd=ws)
    if rc2 == 0 and out.startswith("chore: branch closed"):
        return True
    return False


def recover_specs(ws, branch, specs, dry_run=False):
    """Copy specs from branch to main."""
    recovered = []
    for spec in specs:
        rc, content, _ = git("show", f"{branch}:{spec}", cwd=ws)
        if rc != 0:
            print(f"  SKIP {spec}: git show failed", file=sys.stderr)
            continue
        dst = Path(ws) / spec
        if dry_run:
            recovered.append(spec)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content)
        recovered.append(spec)
    return recovered


def main():
    dry_run = "--dry-run" in sys.argv

    workspaces = []
    base = Path.home() / "claude"

    for parent_dir in [base / "public", base / "private"]:
        if not parent_dir.is_dir():
            continue
        for d in sorted(parent_dir.iterdir()):
            if d.is_dir() and (d / ".git").exists():
                workspaces.append(d)
            if d.is_dir() and not (d / ".git").exists():
                for dd in sorted(d.iterdir()):
                    if dd.is_dir() and (dd / ".git").exists():
                        workspaces.append(dd)

    casehub_work = base / "casehub" / "work"
    if casehub_work.is_dir() and (casehub_work / ".git").exists():
        workspaces.append(casehub_work)

    total_recovered = 0
    total_workspaces = 0

    for ws in workspaces:
        branches = list_branches(ws)
        if not branches:
            continue

        main_specs = specs_on_main(ws)
        orphans = {}

        for branch in branches:
            branch_specs = specs_on_branch(ws, branch)
            if not branch_specs:
                continue
            if not is_closed(ws, branch):
                continue
            new_specs = [s for s in branch_specs if s not in main_specs]
            if new_specs:
                orphans[branch] = new_specs

        if not orphans:
            continue

        total_workspaces += 1
        all_orphan_specs = {}
        for branch, specs in orphans.items():
            for spec in specs:
                if spec not in all_orphan_specs:
                    all_orphan_specs[spec] = branch

        ws_name = ws.relative_to(Path.home() / "claude")
        print(f"\n{'='*60}")
        print(f"Workspace: {ws_name}")
        print(f"  {len(all_orphan_specs)} unique orphaned specs from {len(orphans)} closed branches")

        if dry_run:
            for spec, branch in sorted(all_orphan_specs.items()):
                print(f"  WOULD RECOVER: {spec} (from {branch})")
            total_recovered += len(all_orphan_specs)
            continue

        rc, current, _ = git("branch", "--show-current", cwd=ws)
        if current != "main":
            git("stash", cwd=ws)
            rc, _, err = git("checkout", "main", cwd=ws)
            if rc != 0:
                print(f"  ERROR: cannot checkout main: {err}")
                continue

        git("pull", "--rebase", "origin", "main", cwd=ws)

        recovered = []
        for spec, branch in sorted(all_orphan_specs.items()):
            result = recover_specs(ws, branch, [spec])
            recovered.extend(result)

        if recovered:
            for spec in recovered:
                git("add", spec, cwd=ws)

            branch_list = ", ".join(sorted(orphans.keys())[:5])
            if len(orphans) > 5:
                branch_list += f" +{len(orphans)-5} more"

            msg = (f"docs: recover {len(recovered)} orphaned specs from closed branches\n\n"
                   f"Specs stranded on: {branch_list}")
            git("commit", "-m", msg, cwd=ws)

            rc, _, err = git("push", cwd=ws)
            if rc == 0:
                print(f"  RECOVERED {len(recovered)} specs — pushed")
            else:
                print(f"  RECOVERED {len(recovered)} specs — push failed: {err}")

            total_recovered += len(recovered)

        if current != "main":
            git("checkout", current, cwd=ws)
            git("stash", "pop", cwd=ws)

    print(f"\n{'='*60}")
    action = "Would recover" if dry_run else "Recovered"
    print(f"{action} {total_recovered} specs across {total_workspaces} workspaces")


if __name__ == "__main__":
    main()
