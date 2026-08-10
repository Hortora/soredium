# Slot Propagation Fix — Design Spec

**Issue:** Hortora/soredium#210
**Branch:** issue-210-slot-propagation-fix
**Date:** 2026-08-10

## Problem

When `work-end` closes a slot, changes fail to propagate back to the original repos. Two independent failure paths produce the same symptom — the original repo falls behind:

1. **Promotion push (Phase A):** `artifact_promote.py to-workspace-main` pushes workspace main from the slot clone to the original workspace repo. This fails because the original has main checked out and git rejects pushes to a checked-out branch in non-bare repos (`denyCurrentBranch`). The error is caught as `PUSHED=failed` — non-fatal. Promoted artifacts exist in the slot but never reach the original.

2. **Land step (Phase C):** `merge_slot()` iterates only project repos via `get_slot_repos()`, which excludes workspace directories (`work-*`) via `is_project_repo()`. Workspace repos get stamped but are never merged to their originals' main, never pushed to GitHub.

**Invariant that must hold:** After work-end closes a slot, every git repo in the slot (project AND workspace) has its complete merged work on the original repo's main AND on GitHub. If this invariant breaks, repos diverge.

## Design

### Remote layout (slot creation)

At slot creation, reconfigure each clone's remotes to mirror the original's fork model:

```
local    → /Users/mdproctor/claude/casehub/pages         (clone source, fetch-only)
origin   → https://github.com/mdproctor/casehub-pages    (fork — push target)
upstream → https://github.com/casehubio/casehub-pages    (blessed — rebase source, optional)
```

**Setup sequence** (after `git clone --shared`):

```python
fork_remote, blessed_remote = detect_topology(original)
fork_url = git_get_url(original, fork_remote)

git -C <clone> remote rename origin local
git -C <clone> remote add origin <fork_url>
git -C <clone> fetch origin
git -C <clone> branch --set-upstream-to=origin/main main

if blessed_remote:
    blessed_url = git_get_url(original, blessed_remote)
    git -C <clone> remote add upstream <blessed_url>
```

For direct-model repos (no fork — e.g., workspace repos), `origin` points to the single GitHub remote. No `upstream` added.

**Also configure `updateInstead` on originals:**

```python
git -C <original> config receive.denyCurrentBranch updateInstead
```

This enables the local push (see below) regardless of which branch the original has checked out.

### Dual push — GitHub + local

The land step pushes each repo to two targets:

1. **GitHub (fork)** — primary, durable. `git push origin main` from the slot clone.
2. **Local original** — secondary, immediate sync. `git push local main` from the slot clone. Uses `updateInstead` when main is checked out; works without it when main is not checked out.

The GitHub push is the critical path. The local push is best-effort — if it fails, work is safely on GitHub and the original syncs at next session start via `sync-main`.

**Push to the blessed repo (upstream/casehubio) never happens automatically.** That's a controlled operation via PR or explicit rebase-push.

### Unified push loop

Replace the current split handling (project repos in push loop + workspace repos in stamp-only loop) with a single loop over all git repos in the slot.

**New function:**

```python
def get_all_slot_repos(slot_dir: Path) -> list[str]:
    """All git repos in the slot — project + workspace."""
    return [
        d.name for d in sorted(slot_dir.iterdir())
        if d.is_dir() and (d / ".git").exists()
        and d.name not in (".m2", "attic")
    ]
```

`get_slot_repos()` is retained unchanged for callers that need project-only lists (plan management, deferred item detection).

### Land step flow (revised `merge_slot`)

```
Phase 1: Rebase all feature branches
Phase 2: Merge, push, verify (per repo)
Phase 3: Stamp all feature branches
Phase 4: Report propagation summary
```

**Phase 1 — Rebase:**

For each repo in `get_all_slot_repos()`:

```python
rebase_remote = "upstream" if has_upstream(slot_repo) else "origin"
git -C <slot_repo> fetch <rebase_remote> main
git -C <slot_repo> rebase <rebase_remote>/main
```

Fetch from `upstream` (blessed) when it exists — the fork might be behind the canonical state. Fall back to `origin` for direct-model repos.

If rebase fails (conflict): abort rebase, HARD STOP, report which repo conflicted.

**Phase 2 — Merge and push:**

For each repo, track status in a `results` dict:

```python
# Checkout main and catch up
git -C <slot_repo> checkout main
git -C <slot_repo> merge --ff-only origin/main   # catch up with fork

# Merge feature branch
rc = git -C <slot_repo> merge --ff-only <branch>
if rc != 0:
    git -C <slot_repo> merge <branch> --no-edit   # workspace repos with promotion commits

slot_sha = git -C <slot_repo> rev-parse main

# Push to GitHub (fork) — primary
rc = git -C <slot_repo> push origin main
if rc != 0:
    results[repo] = ("github_failed", slot_sha)
    continue

# Verify GitHub push
github_sha = git ls-remote origin main  # parse SHA from output
if slot_sha != github_sha:
    results[repo] = ("github_verify_failed", slot_sha)
    continue

# Push to local original — secondary, best-effort
rc = git -C <slot_repo> push local main
if rc != 0:
    results[repo] = ("local_failed", slot_sha)
    # Not fatal — work is on GitHub
    continue

# Verify local push
original = resolve_original_repo(slot_repo)
local_sha = git -C <original> rev-parse main
if local_sha != slot_sha:
    results[repo] = ("local_verify_failed", slot_sha)
    continue

results[repo] = ("ok", slot_sha)
```

**Phase 3 — Stamp:**

For each repo: checkout feature branch, create `chore: branch closed — landed as <sha> on main` empty commit, push stamp to origin (GitHub).

**Phase 4 — Report:**

```
Propagation results:
  ✅ engine        → origin/main (pushed, verified)
  ✅ work-casehub  → origin/main (pushed, verified)
  ⚠️ pages         → origin/main (pushed) local (dirty worktree, will sync at next session)
  ❌ other-repo    → origin/main (rejected — force push required?)

2/3 repos fully propagated, 1 local-sync warning, 0 failures.
```

GitHub failures (`github_failed`, `github_verify_failed`) block `.landed` marker — HARD STOP.
Local failures (`local_failed`, `local_verify_failed`) are warnings — work is on GitHub.

### Relaxed preflight

Remove the check that requires original repos to be on main. The push works regardless:
- Main not checked out → push to main updates the ref (normal git behavior)
- Main checked out → `updateInstead` updates ref + working tree

Retain the dirty-worktree check. `updateInstead` refuses on dirty worktrees when main is checked out. The check is a clear error message rather than a cryptic push failure.

**Revised preflight:**

```python
for repo_name in get_all_slot_repos(slot_dir):
    slot_repo = slot_dir / repo_name
    original = resolve_original_repo(slot_repo)
    
    # Check for dirty worktree (updateInstead refuses on dirty)
    rc, status_out, _ = run_cmd(
        ["git", "-C", str(original), "status", "--porcelain"]
    )
    if rc == 0 and status_out.strip():
        cur_branch = get_current_branch(original)
        if cur_branch == "main":
            # Dirty worktree on main — updateInstead will refuse
            print(f"ERROR=dirty_worktree repo={repo_name} path={original}")
            preflight_ok = False
        else:
            # Dirty worktree on a feature branch — push to main still works
            # (denyCurrentBranch only applies to the checked-out branch)
            pass
```

### Retroactive migration

New subcommand `slot_manager.py migrate-remotes <family_root>`:

1. Find all active (non-archived) slots
2. For each slot, for each repo clone:
   - If `local` remote already exists: skip (already migrated)
   - Read original's push URL via `detect_topology()`
   - `git remote rename origin local`
   - `git remote add origin <fork_url>`
   - `git fetch origin`
   - `git branch --set-upstream-to=origin/main main`
   - If blessed exists: `git remote add upstream <blessed_url>`
3. For each original repo:
   - `git config receive.denyCurrentBranch updateInstead`
4. Report: `Migrated N slots (M repos total). N originals configured.`

### Workspace merge topology

Workspace repos have a split commit topology after Phase A promotion:

```
origin/main:   A ── X ── Y          (external changes)
slot main:     A ── P ── Q          (promotion commits from to-workspace-main)
feature:       A ── X ── Y ── D'    (rebased onto origin/main)
```

The merge in Phase 2 tries ff-only first (handles project repos cleanly), then falls back to a regular merge (handles workspace repos with promotion commits). The merge commit accurately reflects the topology — two streams of work (feature + promotion) combined.

For project repos, the feature branch is rebased onto origin/main, and main has no local commits, so the merge is always ff-only. No merge commits.

## Files changed

| File | Change |
|------|--------|
| `work-slot/slot_manager.py` | `create_slot()`: add remote reconfiguration + `updateInstead`. `merge_slot()`: unified push loop, dual push, SHA verification, propagation summary, relaxed preflight. New `get_all_slot_repos()`. New `migrate-remotes` subcommand. |
| `work-slot/SKILL.md` | Document new remote layout, migration command |

## What this does NOT change

- `artifact_promote.py` — no changes. The promotion push now goes to GitHub (via `origin`) instead of the local original. It works because `origin` now points to GitHub after the remote reconfiguration.
- `work_end_execute.py` — branch-mode landing unchanged. Only slot mode is affected.
- `close_artifacts.py` — no changes. It calls `artifact_promote.py` which benefits from the remote fix automatically.
- `get_slot_repos()` — retained unchanged for project-only callers.
- The blessed repo push — never automatic. PR or explicit operation only.

## Test plan

Tests required per protocol `externalised-scripts-require-tests`:

1. **`get_all_slot_repos()`** — returns project + workspace dirs, excludes `.m2` and `attic`
2. **Remote reconfiguration** — after `create_slot()`, slot clone has `local` (local path), `origin` (fork URL), optional `upstream` (blessed URL)
3. **`updateInstead` configuration** — after `create_slot()`, original has `receive.denyCurrentBranch=updateInstead`
4. **Dual push — GitHub + local** — mock push to verify both targets are attempted, local failure is warning not error
5. **SHA verification** — mismatch after GitHub push is HARD STOP, mismatch after local push is WARN
6. **Propagation summary** — correct status per repo, correct aggregate (failures block, warnings don't)
7. **Relaxed preflight** — dirty worktree on main blocks, dirty worktree on feature branch passes, clean worktree always passes
8. **Workspace merge** — ff-only succeeds for project repos, regular merge succeeds for workspace repos with promotion commits
9. **`migrate-remotes`** — migrates active slots, skips archived, idempotent (second run is no-op)
10. **Fork model detection** — fork repos get origin=fork + upstream=blessed, direct repos get origin=github only

## Garden context

- **GE-0137** — `git push` to non-bare repo rejected when target branch checked out (root cause documentation)
- **GE-20260730-37faf4** — `git clone --shared` for zero-cost independent clones (slot mechanism)
- **GE-20260802-a3c094** — `source-dir` filesystem copy for cross-repo promotion (prior fix)
- **GE-20260802-f3b24b** — three silent-skip bugs in slot promotion (related prior fixes)
