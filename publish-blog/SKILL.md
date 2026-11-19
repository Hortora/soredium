---
name: publish-blog
description: >
  Use when publishing blog entries to external platforms via blog-routing.yaml
  — user says "publish blog", "publish entries", "cross-post this entry", or
  invokes /publish-blog. NOT for writing new entries (use write-content with diary type for that).
---

# Publish Blog

Routes blog entries from the workspace blog directory to external publishing
destinations based on `blog-routing.yaml` routing rules.

This is a **second-level routing** step, independent of the workspace `## Routing`
config. That config controls where the `blog/` directory lives.
This skill controls where individual entries are cross-posted to blog platforms.

---

## Prerequisites

- `blog-routing.yaml` exists at `~/.claude/blog-routing.yaml` (global) and optionally
  at `<workspace>/blog-routing.yaml` (project override)
- Blog entries have `entry_type`, `projects`, and optionally `tags` in frontmatter
- **Field naming:** `entry_type` is the blog entry's content type (article, note). `type` in blog-routing.yaml is the destination transport type (git). Different contexts, same word — do not confuse them.
- Each destination path in the routing config is a valid directory

---

## Workflow

### Step 0 — Resolve blog directory

```bash
python3 ~/.claude/skills/project/ctx.py
```

Read `BLOG_DIR`, `HAS_BLOG_ROUTING`, `IN_SLOT`, and `WORKSPACE` from the output.

ctx.py already validates `BLOG_DIR` against the slot boundary — if the configured
path escapes the slot, `BLOG_DIR` is returned empty.

If `BLOG_DIR` is non-empty, use it directly. Otherwise fall back to `blog/`
relative to `WORKSPACE` (or CWD if `WORKSPACE` is not set).

### Steps 1–4 — Run routing plan

Read `HAS_BLOG_ROUTING` from the ctx.py output (already run in Step 0).

If `HAS_BLOG_ROUTING=no`, stop:
> "No global routing config found at `~/.claude/blog-routing.yaml`."

Run the routing plan script:

```bash
python3 ~/.claude/skills/publish-blog/blog_publish.py plan "$WORKSPACE"
```

The script loads the global routing config (`~/.claude/blog-routing.yaml`),
merges any workspace override (`<workspace>/blog-routing.yaml`), scans blog
entries, resolves destinations per entry, and checks presence at each
destination. It outputs structured lines:

```
ENTRY=<file> DEST=<name> PATH=<destination path> PRESENT=yes|no
...
MISSING=<file:dest pairs with PRESENT=no>
ENTRIES_MISSING=<entries with at least one missing destination>
```

Present the results as a table:

```
Blog publishing plan
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Entry                               Destinations          Present
2026-04-14-mdp01-day-zero.md       personal-blog          yes
2026-04-14-mdp02-closing-gaps.md   personal-blog          no
2026-04-14-quarkus-article.md      quarkus-blog           no
                                   personal-blog          yes

  MISSING: 2 entries need publishing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Publish missing? (y/n) or enter entry numbers to publish selectively:
```

If user enters numbers (e.g. "1 3"), publish only those entries.
If user says `y`, publish all missing entries.
If user says `n`, stop.

### Step 5 — Validate destinations

For each destination referenced in the plan:

```python
dest_config = router.get_destination_config(dest_name)
dest_path = Path(dest_config['path']).expanduser()
subdir = dest_config.get('subdir', '')
target_dir = dest_path / subdir if subdir else dest_path
```

Check the target directory exists:
```bash
ls "<target_dir>" 2>/dev/null || echo "missing"
```

If any target directory is missing, warn before proceeding:
```
⚠️ Destination 'quarkus-blog' → ~/quarkus-community-blog/_posts/ does not exist.
   Create it, or skip this destination? (create / skip / abort)
```

### Step 5b — Verify image references

Before copying entries, verify all image references resolve. For each entry
being published, call `check_broken_images()` from `verification.repo_checks`:

```python
from pathlib import Path
from verification.repo_checks import check_broken_images

findings = check_broken_images(Path(entry_path))
```

If any broken refs found, present them:
```
⚠️ Broken image references found:
  entry.md — image not found: images/missing.png

Proceed anyway? (y/n)
```

If user says `n`, stop. If `y`, continue with broken refs noted.

### Step 6 — Copy entries and images to destinations

For each (entry, destination) pair approved by the user:

1. Copy the entry:
```bash
python3 ~/.claude/skills/publish-blog/blog_publish.py copy-entry \
  "$BLOG_DIR/<filename>" "<target_dir>"
```

Expected output: `COPIED=yes`
Error cases: `ERROR=source_not_found`, `ERROR=copy_failed`

The script copies the images the entry refers to along with it and checks
each one arrived. Read its output:
- `IMAGES_VERIFIED=<n>`: that many images are at the destination, identical.
- `WARN=image_not_found: <ref>`: the entry refers to an image the source
  does not have either (example syntax, or never drawn). Nothing was lost;
  tell the user.
- `ERROR=image_not_copied: <ref>`: an image the source has did not arrive.
  The copy failed. Do not commit this destination; show the error.

Do not copy images yourself.

**Git staging is handled separately in Step 7 — do not manually `git add` here.**

### Step 7 — Commit destinations with a remote

After copying all entries for a destination, if the destination is a `git` type:

First, verify remote exists:
```bash
git -C "<dest_path>" remote get-url origin 2>/dev/null && echo "has-remote"
```

Then commit the copied files and publish the destination's base branch:
```bash
python3 ~/.claude/skills/publish-blog/blog_publish.py commit-destination \
  "<dest_path>" \
  "files=<subdir>/<filename1>,<subdir>/<filename2>" \
  "message=chore: publish blog entries from soredium"
```

Expected output: `COMMITTED=yes` then `PUBLISHED=<remote>` (`PUBLISHED=none`
when the destination has no remote).

- `ERROR=dest_not_on_main`: the destination repo is on another branch. It was
  not switched. Tell the user; do not check out its base branch yourself.
- `PUBLISHED=no` with `ERROR=publish_failed: <detail>`: the commit is kept in
  the destination and nothing reached the remote. Report it; publishing can be
  retried with
  `python3 ~/.claude/skills/project/canonical_sync.py publish <dest_path>`.
  Never `git push`.

### Step 8 — Source entries are retained

Source entries are **not** deleted after publishing. The project `docs/blog/`
is the canonical record of what the project produced. The published copies
in destination repos are for readers — the source stays permanently.

Workspace copies (if publishing from a workspace `blog/` dir) are handled
by work-end artifact promotion, not by this skill.

If the user explicitly asks for published entries to be removed from a source
repo, the only way is:
```bash
python3 ~/.claude/skills/publish-blog/blog_publish.py remove-source \
  "<source_repo>" "files=<path1>,<path2>" "verified-in=<dest_dir1>,<dest_dir2>"
```
It removes nothing unless every destination named holds every entry, committed
and byte-identical, with the images it refers to. `ERROR=not_verified` lists
each shortfall as `NOT_VERIFIED=<reason>` and nothing is removed. Never delete
entries with `git rm` or `rm`.

### Step 9 — Summary

```
Publishing complete
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ personal-blog   — 2 entries copied, committed, published
✅ quarkus-blog    — 1 entry published, committed (no remote)
❌ project-blog    — publish failed (commit kept; retry: canonical_sync.py publish ~/project)

Source entries: retained
```

---

## blog-routing.yaml Format

### Global (`~/.claude/blog-routing.yaml`)

```yaml
version: 1

destinations:
  personal-blog:
    type: git
    path: ~/blog/
    subdir: _posts/
  quarkus-blog:
    type: git
    path: ~/quarkus-community-blog/
    subdir: _posts/

defaults:
  destinations: [personal-blog]

rules:
  - match:
      tags: [quarkus]
    destinations: [quarkus-blog, personal-blog]
```

### Project override (`<workspace>/blog-routing.yaml`)

```yaml
extends: ~/.claude/blog-routing.yaml

destinations:
  project-blog:
    type: git
    path: ~/soredium-blog/
    subdir: _posts/

rules:
  - match:
      entry_type: article
      projects: [soredium]
    destinations: [personal-blog, project-blog]
```

### Rule semantics

| Field in `match:` | Match logic |
|-------------------|-------------|
| `entry_type: article` | Exact string match |
| `tags: [quarkus]` | Entry must have at least one of these tags |
| `project: casehubio/engine` | Org-qualified match — see backward compat rule below |
| `projects: [soredium]` | Entry must belong to at least one of these projects |
| Multiple fields | AND logic — all must match |
| What an entry's project is | The repo it lives in, as `owner/repo`, read from the project's git remote (`SOURCE=` in the plan). Fully qualified names in the frontmatter `projects:` line add further projects; bare or legacy names there are ignored when the source is known |
| `project: org/repo`, `org/*`, or bare `repo` | That repo; every repo of the organisation; that repo name under any organisation |
| Rule that names a project | Decides for that project. When several match, the most specific (most fields) wins; equally specific ones are unioned. An empty list means publish nowhere |
| Rule without a project (a fallback by entry type, subtype or tags) | Applies only when no project rule matched |
| Workspace override rules | Always add to the result |
| Nothing matched | The defaults |
| No matching rules | Entry goes to `defaults.destinations` |

**Org-qualified project matching (backward compat):** When a routing rule
uses `org/repo` format (e.g. `casehubio/engine`), match against the entry's
`projects:` list using both the qualified name AND the legacy `<org-prefix>-<repo>`
format. Concretely, `casehubio/engine` matches entries with `projects:` containing
any of: `casehubio/engine`, `casehub-engine`, or `engine`. This handles entries
written before the convention change without requiring bulk frontmatter updates.

---

## Edge Cases

| Situation | Behaviour |
|-----------|-----------|
| Entry missing `entry_type` | Skip with warning |
| Entry with no matching rules | Routes to `defaults.destinations` |
| `defaults.destinations` not configured | Entry gets no destinations (warn user) |
| Destination path missing | Prompt: create / skip / abort |
| Git push fails | Continue with remaining destinations, report at end |
| Entry already exists at destination | Overwrite silently (idempotent) |

---

## Success Criteria

- [ ] Global `blog-routing.yaml` loaded; project override merged if present
- [ ] All entries scanned, `entry_type` parsed
- [ ] Routing plan shown and user confirmed before any file operations
- [ ] All destination directories validated before copying
- [ ] All image references resolve to existing files (no broken `![](images/...)` links)
- [ ] No inline `<svg>` tags in any entry (must be separate `.svg` files)
- [ ] Referenced `.svg` files copied alongside entries to each destination
- [ ] Entries copied to each resolved destination
- [ ] Git destinations committed; destinations with a remote published through `canonical_sync` (or failure reported)
- [ ] Source entries retained in project `docs/blog/` (not deleted)
- [ ] Summary shows per-destination outcome (✅ / ❌)

---

## Skill Chaining

**Invoked by:** User directly — "publish blog", "cross-post entries", `/publish-blog`

**Reads output of:** [`write-content`] — the blog entries in the resolved `$BLOG_DIR`

**No external scripts required** — routing logic is applied inline from the config YAML.

**Related:** workspace `## Routing` config — Level 1 routing (where the `blog/` directory lives).
This skill is Level 2 routing (per-entry cross-posting to platforms). The two are
independent.
