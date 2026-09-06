# Subfolder-Scoped Workspaces for Monorepo App Containers

**Issue:** Hortora/soredium#333
**Date:** 2026-09-05

## Problem

Soredium conflates "project" with "git repo root." Monorepo containers
(like quarkmind) have multiple independent app folders sharing one git
repo. Each app needs its own Claude workspace, CLAUDE.md, and session
scope. Today there is no way to create a workspace scoped to a
subfolder — workspace-init and topology.py assume the project IS the
git root.

## Design Principle

**Normalize at the boundary, run one pipeline.**

There is no "subfolder mode." There is always a project scope and a git
root. Sometimes they are the same directory. The pipeline does not know
or care.

The only place that "knows" about subfolders is workspace-init — during
one-time setup, it detects that CWD is inside a git repo but not the
root. After setup, symlinks encode the decision and the pipeline is
uniform.

## Architecture

### Layer 1: Topology (single source of truth)

`Topology` dataclass gains one field: `git_root`.

```python
@dataclass
class Topology:
    layout: Literal["single", "dual", "slot"]
    project: Path       # the project scope — what you work on
    git_root: Path      # the git repository root — where .git lives
    workspace: Path
    workspace_root: Path
    slot_dir: Path | None
    primary_repo: str | None
    in_worktree: bool
    main_worktree_root: Path | None

    @property
    def is_scoped(self) -> bool:
        return self.project != self.git_root

    @property
    def scope_rel(self) -> str:
        if not self.is_scoped:
            return ""
        return str(self.project.relative_to(self.git_root))
```

Properties are computed, not stored. `is_scoped` and `scope_rel` are
convenience accessors — no pipeline logic branches on them.

### Layer 2: Symlink search priority chain

`resolve()` looks for symlinks in this order:

1. **Walk up from CWD toward git root** — check each directory from
   CWD upward for `wksp/` or `proj/`. Stop at the first match. This
   handles both `apps/foo/` (exact CWD) and `apps/foo/src/main/java/`
   (nested within app folder) — same pattern as git finding `.git`.
2. **Git root** — if not found during walk-up (existing behavior)
3. **Main worktree** — if in a worktree (existing fallback)

This is a search order, not a conditional. It handles every entry point:

| Entry point | Step | project | git_root | workspace |
|---|---|---|---|---|
| App folder (apps/foo/) | 1 | apps/foo/ | quarkmind/ | ~/public/quarkmind-foo/ |
| App workspace | 2 | apps/foo/ | quarkmind/ | ~/public/quarkmind-foo/ |
| Repo root (single-repo) | 1 or 2 | quarkmind/ | quarkmind/ | ~/public/quarkmind/ |
| Root workspace | 2 | quarkmind/ | quarkmind/ | ~/public/quarkmind/ |

`git_root` is always derived: `git rev-parse --show-toplevel` from
within the resolved `project` path.

### Layer 3: ctx.py CLAUDE.md merge

ctx.py always reads two CLAUDE.md files and merges them:

```python
scope_text = read(topo.project / "CLAUDE.md")
root_text  = read(topo.git_root / "CLAUDE.md")

def _merge(field: str) -> str | None:
    scope_val = extract(scope_text, field)
    if scope_val is not None:
        return scope_val
    return extract(root_text, field)

owner_repo = _merge("GitHub repo")
project_type = _merge("Type")
issues_status = _merge("Issue tracking")
```

Uses `is not None` (not `or`) to distinguish "field present but empty"
from "field absent." An app that sets `Blog directory:` (empty) should
NOT inherit the root's blog directory.

For single-repo: both reads hit the same file. The fallback is a
no-op because scope already has every field. Same result as today.

### Layer 4: ctx.py output

New field emitted:

```
GIT_ROOT=/path/to/quarkmind
```

`PROJECT` semantics change to mean scope (= `topo.project`), which for
single-repo is the same as git root. All other fields unchanged.

### Layer 5: Workspace-init subfolder flow

workspace-init detects subfolder mode from CWD:

```
CWD != git_root AND no wksp/ at CWD?
  → "CWD is apps/foo/ inside quarkmind — scope workspace to this folder? (YES/n)"
  → YES: create workspace, proj/ → CWD, CWD/wksp → workspace
  → NO: offer repo-root workspace (existing flow)
```

Workspace naming: `<repo>-<leaf-dir>` → `quarkmind-foo`. Confirmation
if ambiguous.

`wksp/` symlink in the app folder is excluded via `.git/info/exclude`
(one entry per app: `apps/foo/wksp`).

App-level CLAUDE.md is created with project type and build commands.
Root CLAUDE.md provides shared conventions.

## Implementation changes

### topology.py

1. Add `git_root: Path` to `Topology` dataclass
2. Add `is_scoped` and `scope_rel` computed properties
3. Restructure `resolve()` symlink search:
   - Walk up from CWD toward git root, checking each directory for
     `wksp/` or `proj/`. Stop at the first match.
   - When `wksp/` found and its directory != git root: `project = that directory`
   - If no match during walk-up: fall back to git root check (existing)
   - Always: `git_root = git rev-parse --show-toplevel` from project
4. Set `git_root` in every code path (currently implicit as `project`)
5. `_resolve_symlink_target()` — no changes needed (already preserves
   subfolder targets)

### ctx.py

1. Read CLAUDE.md from `topo.project` (scope) — replaces hardcoded
   `topo.project` which was always git root
2. Read root CLAUDE.md from `topo.git_root` — new fallback read
3. Merge with scope-wins, root-fills-gaps pattern
4. Emit `GIT_ROOT` in output dict
5. Symlink checks (`wksp_ok`, `proj_ok`) — check at `topo.project`
   instead of only at CWD
6. Git operations (`branch --show-current`) — use `topo.git_root`

### workspace-init

1. Add CWD vs git-root comparison at the start of setup
2. When CWD is a subfolder: offer subfolder-scoped workspace
3. Create workspace with `proj/` → CWD (not git root)
4. Create `CWD/wksp/` → workspace
5. Add `CWD-relative-path/wksp` to `.git/info/exclude`
6. Create app-level CLAUDE.md with project type, build commands
7. Workspace CLAUDE.md `add-dir` points to app folder

### Consumer audit

Consumers that use `PROJECT` from ctx.py output:

| Consumer | Current use | Change needed |
|---|---|---|
| work-start Step 7 | `git -C $PROJECT checkout -b` | MUST use `$GIT_ROOT` |
| work-start Step 4d | `git -C $PROJECT fetch/rebase` | MUST use `$GIT_ROOT` |
| work-end merge/push | `git -C $PROJECT` | MUST use `$GIT_ROOT` |
| work-end artifact promotion | workspace paths | None — uses `$WORKSPACE` |
| git-commit | `git -C $PROJECT add/commit` | MUST use `$GIT_ROOT` |
| work_state.py | `git -C project branch` | Safe — branch queries don't use relative paths |
| brief | reads `.plan` | None — uses `$WORKSPACE` |
| handover | writes HANDOFF | None — uses `$WORKSPACE` |

**CRITICAL (from adversarial review):** Consumers that run
`git add .`, `git diff -- .`, or `git status .` via `git -C $PROJECT`
will scope-limit results to the app folder. This silently misses
root-level file changes (e.g., parent pom.xml). Migration to
`$GIT_ROOT` for staging/diff/status consumers is a correctness fix,
not cosmetic. Branch/checkout/log (without `-- .`) commands are safe
from subdirectories.

### Tests

Per protocol `externalised-scripts-require-tests`:

1. **topology.py tests:**
   - Single-repo: `project == git_root`, `is_scoped == False`
   - Subfolder via `wksp/` at CWD: `project = CWD`, `git_root = repo root`
   - Subfolder via `proj/` from workspace: `project = app folder`, `git_root = repo root`
   - CWD priority: `wksp/` at CWD takes precedence over `wksp/` at git root
   - Walk-up: CWD nested inside app folder (e.g., `apps/foo/src/`) finds `wksp/` at `apps/foo/`
   - Walk-up stops at git root — does not walk beyond
   - Existing single-repo behavior unchanged (regression)

2. **ctx.py tests:**
   - CLAUDE.md merge: scope field wins over root
   - CLAUDE.md merge: root fills gap when scope field is missing
   - CLAUDE.md merge: empty scope field is NOT overridden by root (is not None vs or)
   - Single-repo: merge is no-op (same file)
   - `GIT_ROOT` emitted in output
   - Regression: single-repo output identical to current

3. **workspace-init tests:**
   - Subfolder detection: CWD inside repo but not root
   - Workspace creation: `proj/` → app folder, `wksp/` → workspace
   - `.git/info/exclude` updated correctly
   - No detection when CWD is the git root (existing flow)

## Invariants

These are testable and enforceable:

1. `git_root` always has `.git` — `(git_root / ".git").exists()`
2. `project` is inside or equal to `git_root` — `project.relative_to(git_root)` succeeds
3. For single-repo: `project == git_root` and `scope_rel == ""`
4. `git -C git_root` is always valid for git operations
5. ctx.py output is identical for single-repo projects (regression test)

## What does NOT change

- Branch naming: standard `issue-NNN-slug`
- `git -C` from any consumer: works from subdirectories
- Workspace model: one independent workspace per scope
- Work lifecycle: branches are repo-wide, workspace artifacts are scope-specific
- Slots: no change (slot detection is independent of scope)
- `_resolve_symlink_target()`: already preserves subfolder paths
- Layout discriminator: `Literal["single", "dual", "slot"]` unchanged

## References

- topology.py — current path resolution, `_resolve_symlink_target` (line 44-73)
- ctx.py — current CLAUDE.md reading (line 98-101), symlink checks (line 134-147)
- issue-220 decisions — D3 flat dataclass pattern, D2 single CLI entry point
- GE-20260529-182916 — ctx.py CWD subdirectory false negatives (failure mode 4)
- GE-20260816-8b9589 — workspace symlink to project subdirectory wrong-repo commits
- GE-20260804-09f3da — cross-repo context contamination from wrong wksp symlink
- GE-20260811-8d569b — git `<rev>:<path>` resolves from repo root even with `-C <subdir>`
- workspace-init/SKILL.md — current workspace creation flow
