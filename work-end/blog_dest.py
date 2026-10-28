#!/usr/bin/env python3
"""
Resolve blog destinations from ~/.claude/blog-routing.yaml and publish
unpublished entries from the workspace blog directory to ALL destinations.

Usage: python3 ~/.claude/skills/work-end/blog_dest.py <workspace_blog_dir> <branch_name>

Outputs:
  BLOG_DEST=<path>            (first destination, for backward compat)
  BLOG_REPO=<path>            (first destination repo)
  BLOG_SUBDIR=<subdir>        (first destination subdir)
  DEST_COUNT=<N>              (total destinations)
  DEST_N_PATH=<path>          (per-destination path)
  DEST_N_UNPUBLISHED=<csv>    (per-destination unpublished entries)
  UNPUBLISHED=<csv>           (union of all unpublished, for backward compat)

Copies unpublished entries to each destination directory.
Caller is responsible for git add / commit / push per destination repo.
"""
import sys
import os
import shutil
from pathlib import Path

from workspace_artifacts import extract_image_refs

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed — run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

if len(sys.argv) < 3:
    print("Usage: blog_dest.py <workspace_blog_dir> <branch_name>", file=sys.stderr)
    sys.exit(1)

workspace_blog = Path(sys.argv[1])
branch_name = sys.argv[2]

routing_path = Path.home() / ".claude" / "blog-routing.yaml"
if not routing_path.exists():
    print(f"ERROR: {routing_path} not found", file=sys.stderr)
    sys.exit(1)

cfg = yaml.safe_load(routing_path.read_text())
dest_keys = cfg.get("defaults", {}).get("destinations", [])
if not dest_keys:
    print("ERROR: no default destinations in blog-routing.yaml", file=sys.stderr)
    sys.exit(1)

ws_entries = sorted(p.name for p in workspace_blog.glob("*.md") if p.name != "INDEX.md") if workspace_blog.exists() else []
all_unpublished: set[str] = set()

for i, dest_key in enumerate(dest_keys):
    if dest_key not in cfg.get("destinations", {}):
        print(f"DEST_{i}_ERROR=destination '{dest_key}' not found in blog-routing.yaml")
        continue

    dest_cfg = cfg["destinations"][dest_key]
    dest_path = Path(os.path.expanduser(dest_cfg["path"] + dest_cfg.get("subdir", ""))).resolve()
    blog_repo = dest_path.parent
    blog_subdir = dest_path.name

    if i == 0:
        print(f"BLOG_DEST={dest_path}")
        print(f"BLOG_REPO={blog_repo}")
        print(f"BLOG_SUBDIR={blog_subdir}")

    print(f"DEST_{i}_PATH={dest_path}")
    print(f"DEST_{i}_REPO={blog_repo}")

    dest_entries = set(p.name for p in dest_path.glob("*")) if dest_path.exists() else set()
    unpublished = [e for e in ws_entries if e not in dest_entries]

    if unpublished:
        dest_path.mkdir(parents=True, exist_ok=True)
        for entry in unpublished:
            shutil.copy2(workspace_blog / entry, dest_path / entry)
            for img_ref in extract_image_refs(workspace_blog / entry, workspace_blog):
                img_src = workspace_blog / img_ref
                img_dst = dest_path / img_ref
                img_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(img_src), str(img_dst))
        print(f"DEST_{i}_UNPUBLISHED={','.join(unpublished)}")
        all_unpublished.update(unpublished)
    else:
        print(f"DEST_{i}_UNPUBLISHED=")

print(f"DEST_COUNT={len(dest_keys)}")
print(f"UNPUBLISHED={','.join(sorted(all_unpublished))}")
