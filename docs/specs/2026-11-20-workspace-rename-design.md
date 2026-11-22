# Workspace Rename Script — Design Spec

**Date:** 2026-11-20
**Issue:** Hortora/soredium#TBD
**Status:** Approved

## Purpose

A script that safely renames a workspace repo (the companion repo holding
blog, handoff, specs, plans) across all locations that reference it:
GitHub, local directories, git internals, the worklog database, Claude
Code session history, and documentation files.

Designed from first-hand experience renaming `cc-praxis` → `soredium`
(2026-11-20), which uncovered 12 distinct layers that need updating
and several failure modes that are invisible until git starts printing
errors.

## Scope

**In scope:** workspace repo renames (the `wsp-X` / `work-X` companion
repos). The common case — workspace names change more often than project
names.

**Out of scope (future):** project directory renames. The topology
discovery and path-rewriting layers are designed to be reusable by a
future project-rename script.

## Inputs

```
python3 scripts/rename_workspace.py <family_root> old=<name> new=<name>
python3 scripts/rename_workspace.py <family_root> old=<name> new=<name> plan
python3 scripts/rename_workspace.py <family_root> old=<name> new=<name> --apply
```

- `family_root`: e.g. `~/claude/hortora`
- `old`: current workspace name (e.g. `cc-praxis`)
- `new`: target workspace name (e.g. `soredium`)
- No subcommand: audit (read-only report)
- `plan`: audit + show exact actions
- `--apply`: audit + execute all actions

The script derives all paths from these three values:
- Canonical workspace: `~/claude/public/<old>/` → `~/claude/public/<new>/`
- GitHub repo: `<github_user>/wsp-<old>` → `<github_user>/wsp-<new>`
- Clone/slot workspace dirs: `wsp-<old>` or `work-<old>`

The GitHub username is read from the canonical workspace's `origin`
remote URL.

## Architecture

Two modules:

### `scripts/rename_topo.py` — shared topology layer

Reusable discovery and path operations. A future project-rename script
imports the same functions.

```python
def discover_workspace_dirs(family_root, old_name) -> list[WorkspaceDir]
def find_alternates(dirs, old_path) -> list[AlternatesFinding]
def find_remotes(dirs, old_path) -> list[RemoteFinding]
def find_symlinks(family_root, old_path) -> list[SymlinkFinding]
def find_claude_projects(old_path, new_path) -> list[ClaudeProjectFinding]
def find_worklog_rows(old_path) -> list[WorklogFinding]
def find_file_references(file, patterns) -> list[FileRefFinding]
def find_github_issues(owner_repo, old_name) -> list[IssueFinding]
```

Each function returns typed findings with `location`, `current_value`,
`proposed_value`, and `category` (mechanical / historical / advisory).

`WorkspaceDir` records:
- `path`: absolute path to the workspace directory
- `layout`: `canonical` | `clone` | `slot` | `attic` | `quarantine`
- `active`: whether the slot is active (not archived)
- `rename_dir`: whether the directory itself should be renamed (only
  canonical and clone; slot/attic directories keep their names)

### `scripts/rename_workspace.py` — workspace orchestration

Three phases:

**Phase 1 — Audit** (always, read-only):

Calls every `find_*` function and prints a table:

```
LAYER          LOCATION                                      ACTION
github         mdproctor/wsp-cc-praxis                       rename → wsp-soredium
canonical      ~/claude/public/cc-praxis/                    rename → soredium/
clone          clone/soredium/wsp-cc-praxis/                 rename → wsp-soredium/
alternates     clone/.../alternates (5 files)                rewrite path
remote         clone/.../config (3 remotes)                  rewrite URL
symlink        hortora/soredium/wksp (2 links)               rewrite target
worklog        repos id=46,2631                              update path
claude-proj    ~/.claude/projects/-...-cc-praxis             rename dir
CLAUDE.md      3 files, 7 lines                              rewrite
HANDOFF.md     2 files, line 4                               rewrite
---
historical     docs/retro-issues.md (107 refs)               no change
historical     docs/specs/ (50 refs)                         no change
advisory       clone .workspace ahead of canonical           report only
issues         Hortora/soredium#595 (1 line)                 report only
```

Exit code: 0 if nothing to do, 1 if changes needed.

**Phase 2 — Plan** (`plan` subcommand):

Prints every action numbered, in execution order:

```
 1. gh repo rename wsp-soredium --repo mdproctor/wsp-cc-praxis --yes
 2. mv ~/claude/public/cc-praxis ~/claude/public/soredium
 3. mv clone/soredium/wsp-cc-praxis clone/soredium/wsp-soredium
 4. rewrite alternates: clone/soredium/wsp-soredium/.git/objects/info/alternates
 5. rewrite alternates: slots/9/work-cc-praxis/.git/objects/info/alternates
 ...
```

**Phase 3 — Apply** (`--apply` flag):

Executes each action in order. Each step prints `OK: <what it did>` or
`FAIL: <what went wrong>`. On failure, stops and reports which steps
completed and which remain.

Execution order:
1. GitHub rename (external, non-reversible — done first so redirects work)
2. Canonical directory rename
3. Clone/active-slot workspace directory renames (clone and permanent
   clones only; numbered slot dirs keep their names)
4. All alternates rewrites
5. All remote URL rewrites
6. All symlink rewrites
7. Worklog backup (`worklog.db.before-rename-YYYYMMDD`) then row updates
8. CLAUDE.md reference rewrites
9. HANDOFF.md reference rewrites (line matching `**Where to work:**` only)
10. `.queue-root` adopted-from path rewrites
11. `.claude/projects/` directory renames

## Rules

### What gets rewritten

| Pattern | Replacement | Where |
|---------|-------------|-------|
| `~/claude/public/<old>` | `~/claude/public/<new>` | CLAUDE.md, HANDOFF.md, alternates, remotes, symlinks |
| `wsp-<old>` | `wsp-<new>` | CLAUDE.md (GitHub repo name), directory names (clone only) |
| `work-<old>` | *not rewritten* | Slot directory names are preserved |
| `/public/cc-praxis/` (absolute) | `/public/soredium/` | alternates, remotes, symlinks, worklog |

### What is never touched

- **Slot/attic workspace directory names**: `work-cc-praxis` stays as-is.
  Only alternates and remotes inside are fixed.
- **Historical content**: blog entries, specs, retro-issues, ADRs.
  Identified by path (`docs/blog/`, `docs/specs/`, `docs/retro-issues.md`,
  `docs/adr/`).
- **HANDOFF.md historical lines**: only the `**Where to work:**` line
  is rewritten. Session summaries referencing the old name are past-tense
  narrative.
- **Clone `.workspace` commits**: reported as advisory. The clone's
  `.workspace` legitimately differs from canonical (points at clone
  project path). ctx.py auto-corrects it on next run.
- **GitHub issue bodies**: reported with issue numbers but not modified
  (requires manual review — issue body content varies).

### CLAUDE.md rewrite rules

Lines are candidates if they contain `~/claude/public/<old>` or the
GitHub repo pattern `wsp-<old>`. Each candidate line is checked:

- Skip if inside a fenced code block that is clearly historical context
- Skip if the line is in a section whose heading contains "History",
  "Migration", "Retro", or "Legacy"
- Otherwise rewrite

The script reports each rewritten line with before/after for review.

### Worklog safety

- Always back up with sqlite3 backup API before writing
- Backup name: `worklog.db.before-rename-YYYYMMDD`
- Only update `repos` table `path` column
- Never touch `events` or `metadata` tables (historical)

### Failure handling

If any step fails:
1. Print which step failed and the error
2. Print which steps completed (these are not rolled back — each is
   independently correct)
3. Print which steps remain
4. Exit 1

There is no automatic rollback. Each step is independently safe and
the partial state is valid (e.g., GitHub renamed but local not yet →
old URLs redirect, local still works). The user can re-run `--apply`
and completed steps are detected as no-ops.

### Idempotency

Each action checks current state before acting:
- Directory already has new name → skip
- Alternates already points to new path → skip
- Remote already points to new path → skip
- Worklog row already has new path → skip
- GitHub repo already has new name → skip

This means `--apply` can be run multiple times safely, including after
a partial failure.

## Testing

`tests/test_rename_workspace.py` on a scratch git layout:

### Fixtures

```python
def workspace_family(tmp_path):
    """Create a family root with:
    - ~/claude/public/<old>/ — canonical workspace with .git, CLAUDE.md, HANDOFF.md
    - <family>/clone/<project>/wsp-<old>/ — clone workspace with alternates + remote
    - <family>/slots/attic/3/work-<old>/ — attic slot with alternates
    - <family>/<project>/wksp → canonical workspace (symlink)
    - ~/.claude/projects/-...-<old> — fake Claude project dir
    - worklog.db with 2 rows
    """
```

### Test cases

1. **Audit finds all layers** — every finding type appears in output
2. **Plan lists actions in order** — numbered, matches execution order
3. **Apply renames directories** — canonical + clone dirs renamed
4. **Apply fixes alternates** — all alternates point to new path
5. **Apply fixes remotes** — all remote URLs updated
6. **Apply fixes symlinks** — wksp/proj resolve correctly
7. **Apply rewrites CLAUDE.md** — active references changed, historical left
8. **Apply rewrites HANDOFF.md** — only "where to work" line
9. **Apply updates worklog** — backup created, rows updated
10. **Apply renames Claude projects** — directory renamed
11. **Idempotent re-run** — second `--apply` is all no-ops, exit 0
12. **Partial failure recovery** — fail at step N, re-run completes
13. **Slot dirs not renamed** — `work-<old>` directory name preserved
14. **Historical content preserved** — blog/specs refs unchanged

GitHub rename is mocked in tests (no network).

## References

- Hands-on rename session 2026-11-20 (this conversation)
- `scripts/fix_absolute_symlinks.py` — dry-run/apply pattern
- `scripts/reconcile_slots.py` — 3-phase audit/strategy/execute pattern
- `work-slot/slot_claude.py` — Claude project directory path mangling
- `scripts/migrate_slot_workspace.py` — slot migration pattern
