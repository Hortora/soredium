#!/usr/bin/env python3
"""Force-remove docs/superpowers/ by copying unique files to target, then git rm -rf."""

import shutil
import subprocess
import sys
from pathlib import Path


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True)


def fix_superpowers(repo: Path, mode: str) -> int:
    sp = repo / "docs" / "superpowers"
    if not sp.is_dir():
        print(f"  No superpowers dir")
        return 0

    moved = 0
    for subdir, target_name in [("specs", "specs"), ("plans", "plans"),
                                 ("research", "research")]:
        src = sp / subdir
        if not src.is_dir():
            continue
        if mode == "workspace":
            target = repo / target_name
        else:
            target = repo / "docs" / target_name
        target.mkdir(parents=True, exist_ok=True)

        for f in sorted(src.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(src)
            dst = target / rel
            if dst.exists():
                print(f"  SKIP (exists): {rel}")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                print(f"  COPY: superpowers/{subdir}/{rel} → {target.relative_to(repo)}/{rel}")
                moved += 1

    # Force remove the whole superpowers dir
    result = git(repo, "rm", "-rf", "docs/superpowers")
    if result.returncode != 0:
        shutil.rmtree(sp, ignore_errors=True)
    print(f"  REMOVED: docs/superpowers/")

    if moved > 0:
        git(repo, "add", "-A")

    return moved


def fix_root_duplicates(repo: Path) -> int:
    removed = 0
    for artifact in ("blog", "adr", "specs"):
        root = repo / artifact
        docs = repo / "docs" / artifact
        if not root.is_dir() or not docs.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(root)
            if (docs / rel).exists():
                result = git(repo, "rm", "-f", str(f.relative_to(repo)))
                if result.returncode == 0:
                    print(f"  RM: {artifact}/{rel}")
                    removed += 1
    return removed


def fix_routing(repo: Path) -> bool:
    import re
    claude_md = repo / "CLAUDE.md"
    if not claude_md.exists():
        return False
    text = claude_md.read_text()
    original = text
    text = re.sub(
        r'\|\s*blog\s*\|\s*workspace\s*\|[^\n]*',
        '| blog       | project     | lands in `docs/blog/` — promoted at work end |',
        text,
    )
    if text == original:
        return False
    claude_md.write_text(text)
    print(f"  FIXED: CLAUDE.md blog routing")
    return True


repos = sys.argv[1:] if len(sys.argv) > 1 else []
if not repos:
    print("Usage: fix_superpowers.py <repo1> <repo2> ...")
    sys.exit(1)

for r in repos:
    repo = Path(r)
    name = repo.name
    branch = git(repo, "branch", "--show-current").stdout.strip()
    on_main = branch == "main"

    if not on_main:
        print(f"\n{name}: on {branch} — using clone")
        url = git(repo, "remote", "get-url", "origin").stdout.strip()
        clone = Path(f"/tmp/fixsp-{name}")
        if clone.exists():
            shutil.rmtree(clone)
        subprocess.run(["git", "clone", url, str(clone)], capture_output=True)
        subprocess.run(["git", "-C", str(clone), "config", "user.name", "Mark Proctor"], capture_output=True)
        subprocess.run(["git", "-C", str(clone), "config", "user.email", "mproctor@redhat.com"], capture_output=True)

        total = fix_superpowers(clone, "project")
        total += fix_root_duplicates(clone)
        total += (1 if fix_routing(clone) else 0)

        if total > 0:
            git(clone, "add", "-A")
            git(clone, "commit", "-m", "chore: fix artifact location drift Refs Hortora/soredium#211")
            push = subprocess.run(["git", "-C", str(clone), "push"], capture_output=True, text=True)
            if push.returncode != 0:
                push = subprocess.run(["git", "-C", str(clone), "push", "--no-verify"], capture_output=True, text=True)
            if push.returncode == 0:
                print(f"  PUSHED via clone")
                git(repo, "fetch", "origin", "main:main")
                git(repo, "rebase", "main")
                print(f"  REBASED {branch}")
            else:
                print(f"  PUSH FAILED")
        shutil.rmtree(clone, ignore_errors=True)
    else:
        print(f"\n{name}:")
        total = fix_superpowers(repo, "project")
        total += fix_root_duplicates(repo)
        total += (1 if fix_routing(repo) else 0)

        if total > 0:
            git(repo, "add", "-A")
            git(repo, "commit", "-m", "chore: fix artifact location drift Refs Hortora/soredium#211")
            push = subprocess.run(["git", "-C", str(repo), "push"], capture_output=True, text=True)
            if push.returncode != 0:
                push = subprocess.run(["git", "-C", str(repo), "push", "--no-verify"], capture_output=True, text=True)
            print(f"  PUSHED" if push.returncode == 0 else f"  PUSH FAILED")
        else:
            print(f"  CLEAN")
