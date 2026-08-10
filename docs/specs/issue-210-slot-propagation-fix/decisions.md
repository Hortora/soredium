# Decisions — issue-210-slot-propagation-fix

## D1: Push topology — dual push (GitHub + local)

**Choice:** Slot pushes to GitHub (fork) first, then pushes to the local original.
**Alternatives:**
- GitHub-only with lazy sync — local original catches up at next session start. Rejected: creates a sync gap where the original is stale.
- Local-only push (current approach) — push to local original, then original pushes to GitHub. Rejected: fails because local repos are non-bare with main checked out.
- `updateInstead` only (no GitHub push) — push directly to local original. Rejected: misses durability (work not on GitHub until original pushes) and doesn't fix the "push to casehubio" stability concern.
**Rationale:** GitHub push gives durability and team visibility. Local push gives immediate sync. Neither alone is sufficient.
**Trade-offs:** Two pushes per repo instead of one. The local push is best-effort — if it fails, work is safely on GitHub and the original syncs at next session start.
**Exploration:** deep-analysis
**Status:** captured

## D2: Slot remote layout — fork model mirroring

**Choice:** At slot creation, reconfigure remotes: rename `origin` to `local` (clone source), add `origin` pointing to the fork URL (from the original's push target), optionally add `upstream` pointing to the blessed repo. Push to `origin` (fork) only — never push to `upstream` (blessed) automatically.
**Alternatives:**
- `set-url --push origin` (asymmetric remote) — simpler setup but confusing to debug. Rejected for clarity.
- Keep origin as local, add `github` remote — non-standard naming. Rejected: `origin` should mean the primary remote.
**Rationale:** Mirrors the standard fork model. `origin` means what everyone expects. The blessed repo gets updated via PRs, not automatic pushes from work-end.
**Trade-offs:** Three extra commands at slot creation (rename, add, set-upstream). One-time cost.
**Depends on:** D1 (dual push requires knowing where to push)
**Exploration:** deep-analysis
**Status:** captured

## D3: `updateInstead` on originals at slot creation

**Choice:** Set `receive.denyCurrentBranch=updateInstead` on every original repo (project + workspace) when creating a slot.
**Alternatives:**
- Fallback pull when push fails — requires the original to be on main. Rejected: too restrictive.
- No local sync (GitHub-only) — creates a stale gap. Rejected per D1.
**Rationale:** The only git mechanism that updates a checked-out branch from outside. When main is NOT checked out, the push works without it (normal git behavior). When main IS checked out, `updateInstead` atomically updates ref + working tree. Refuses on dirty worktree (safe).
**Trade-offs:** Leaves config on original repos permanently. Harmless — local only, idempotent, can be unset.
**Exploration:** deep-analysis
**Status:** captured

## D4: Unified push loop — all repos in one path

**Choice:** Replace the split handling (project repos in push loop, workspace repos in stamp-only loop) with a single loop over all git repos in the slot. New `get_all_slot_repos()` function includes workspace dirs that `get_slot_repos()` excludes.
**Alternatives:**
- Separate workspace push loop — duplicates logic, more code to maintain. Rejected.
- Extend `get_slot_repos()` — breaks callers that need project-only lists (plan management). Rejected.
**Rationale:** One loop, one code path, one set of retry/verification logic. Eliminates the root cause of workspace repos being silently skipped.
**Trade-offs:** `get_slot_repos()` retained for project-only callers. Two functions with similar names — name must be clear.
**Depends on:** D1 (the push logic is the same for all repos)
**Exploration:** quick
**Status:** captured

## D5: SHA verification after each push

**Choice:** After every push (GitHub + local), verify SHA matches. `git ls-remote origin main` for GitHub, `git -C <original> rev-parse main` for local. Mismatch on GitHub = HARD STOP. Mismatch on local = WARN (work is on GitHub).
**Alternatives:**
- No verification — silent failures look like success. Rejected: unrecoverable data loss.
**Rationale:** A push can silently fail (rejected, timeout, stale ref). Without verification, the `.landed` marker is written and the slot is archived with the work gone.
**Trade-offs:** Extra `ls-remote` call per repo. Negligible cost for critical safety.
**Exploration:** quick
**Status:** captured

## D6: Per-repo propagation summary

**Choice:** Track per-repo status (pushed/failed/skipped) and report a summary at the end instead of hard-stopping on each failure independently.
**Alternatives:**
- Hard-stop on first failure (current behavior) — gives no visibility into which repos succeeded. Rejected.
**Rationale:** Partial propagation (project pushed, workspace failed) is an inconsistent state. The summary gives the user actionable information to recover.
**Trade-offs:** Slightly more complex reporting logic. Worth it for debuggability.
**Depends on:** D4 (unified loop makes tracking straightforward)
**Exploration:** quick
**Status:** captured

## D7: Relaxed preflight — drop "must be on main" requirement

**Choice:** Remove the preflight check that requires original repos to be on main. Only check for dirty worktree (which `updateInstead` refuses on). The push works regardless of which branch the original has checked out.
**Alternatives:**
- Keep strict preflight (current behavior) — blocks work-end when originals are on feature branches. Rejected: too restrictive, and D3 eliminates the need.
**Rationale:** With `updateInstead`, pushing to main works whether main is checked out or not. The dirty-worktree check is the only safety gate needed (and only when main IS checked out).
**Trade-offs:** Slightly less control over original repo state. Acceptable because the push mechanism handles all states.
**Depends on:** D3 (`updateInstead` makes this safe)
**Exploration:** quick
**Status:** captured

## D8: Workspace merge strategy — ff-only with regular merge fallback

**Choice:** When merging the feature branch into slot main before pushing, try ff-only first. If ff-only fails (workspace repos with promotion commits on main), fall back to regular merge. Mirrors the branch-mode behavior in `work_end_execute.py` lines 242-244.
**Alternatives:**
- Always ff-only — fails for workspace repos with promotion commits. Rejected.
- Always regular merge — creates unnecessary merge commits for project repos. Rejected.
- Rebase promotion commits onto feature first — fragile, complex. Rejected.
**Rationale:** Project repos: feature branch rebased onto origin/main, so merge is ff-only. Workspace repos: main has promotion commits from `to-workspace-main`, feature has design journal work. These diverge from the common ancestor, requiring a regular merge. The merge commit is accurate history.
**Trade-offs:** Workspace repos get merge commits. Acceptable — these are methodology artifacts, not production code.
**Depends on:** D4 (the merge happens in the unified push loop)
**Exploration:** quick
**Status:** captured

## D9: Retroactive migration for existing slots

**Choice:** Provide a `migrate-remotes` subcommand in `slot_manager.py` that adds the GitHub remote and `updateInstead` config to all active (non-archived) slot clones. Run once to bring existing slots up to the new topology.
**Alternatives:**
- No migration — existing slots use old push path. Rejected: they'd still fail to propagate.
- Auto-detect at merge time — if GitHub remote missing, add it on the fly. Adds complexity to the merge path. Rejected: one-time migration is cleaner.
**Rationale:** Concrete, testable, one-time operation. Existing slots get the same remote layout as new ones.
**Trade-offs:** Extra subcommand that's used once. Minimal cost.
**Exploration:** quick
**Status:** captured
