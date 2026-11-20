# Three Lifecycle Gaps — Design Spec

**Issue:** #459
**Branch:** issue-459-lifecycle-gaps
**Scale:** S | **Complexity:** Med

---

## Gap 1 — Publish Parity

### Problem

`blog_publish.py` copies entries to destinations sequentially with no cross-destination reconciliation. When a copy or push fails for one destination, the entry reaches some destinations but not others. Issue #452 reports 1,186 entries at `personal-notes` but missing from `casehub-notes`.

### Fix

Two new subcommands in `blog_publish.py`:

**`verify-parity <routing-yaml> <destination-configs>`**

After all copies and commits, scan the routing config. For every entry that exists in ANY destination of a route, verify it exists in ALL destinations the route specifies. Report discrepancies as KEY=VALUE output:

```
PARITY=no
MISSING_COUNT=3
MISSING_1=2026-09-15-mdp01-foo.md dest=casehub-notes
MISSING_2=...
```

The `publish-blog` SKILL.md gets a new Step 8 (after commit-destination) that calls `verify-parity`. If discrepancies found, re-copy missing entries and re-commit.

**`check-present <entry-path> <dest-dir>`**

Pre-copy check: returns `PRESENT=yes|no`. The SKILL.md Step 6 calls this before `copy-entry` — skip if already present. Prevents redundant copies during backfill.

### Files changed

| File | Change |
|------|--------|
| `publish-blog/blog_publish.py` | Add `verify-parity` and `check-present` subcommands |
| `publish-blog/SKILL.md` | Add verification step after commits; add pre-copy check in Step 6 |
| `tests/test_blog_publish.py` | Tests for both subcommands |

---

## Gap 2 — Zombie Slots

### Problem

`archive_slot` step has `skip_fn=_skip_multi_repo_partial_close` which checks if any workspace in the slot has a `.plan` file. In queue-cycling scenarios, `.plan` still exists when archival is evaluated (archival runs before cleanup), so archival is skipped. When the last issue lands, the same ordering artifact repeats.

### Fix

**A) Relax the skip condition**

In `_skip_multi_repo_partial_close`, exclude the *current* workspace's `.plan` from the "has remaining work" check. The current workspace's plan is about to be cleaned up — its presence is an ordering artifact. Other repos' plans in the slot still block correctly (they represent genuinely incomplete work in sibling repos).

Implementation: the function already receives `ctx` which has `ctx.workspace`. When iterating workspace paths to check for `.plan`, skip the one that matches `ctx.workspace`.

**B) Zombie detection in corruption.py**

New corruption check **S16_ZOMBIE_SLOT**: when `IN_SLOT=yes` and `state: active`, check if all repos in the `.slot` have their branches stamped (stamp commit exists) and landed on main. If yes, flag as warning with action `archive_slot`.

Can query worklog.db for slot state per GE-20260821-e9c59e as a supplementary signal, but the primary check is git-based (stamp commits are authoritative).

### Files changed

| File | Change |
|------|--------|
| `work-end/work_end_orchestrator.py` | `_skip_multi_repo_partial_close`: exclude current workspace's .plan |
| `project/corruption.py` | Add S16_ZOMBIE_SLOT check |
| `tests/test_work_end_orchestrator.py` | Test relaxed skip condition |
| `tests/test_corruption.py` | Test S16 detection |

---

## Gap 3 — Dangling Plans

### Problem

`plan_manager.py advance()` marks the next issue active but doesn't clear the `branch:` field. The plan still references the old stamped branch. At next session start, S5 (branch mismatch) fires but offers wrong actions — it wants to switch to the old branch rather than create a new one for the newly-active issue.

### Fix

**A) Clear branch in advance()**

In `plan_manager.py advance()`, after marking the next issue active, call `set_state(plan_path, "branch", "")`. This clears the stale reference. At next session start, ctx.py sees `state: active` + empty branch + on main → routes to `work start` which creates the correct branch.

**B) S15 corruption check**

New check **S15_PLAN_BRANCH_STALE**: when `.plan` has `state: active` AND a non-empty `branch:` field AND the branch's issue number doesn't match the active queue issue number, flag as warning. Actions: `clear_branch` (set branch to empty, let work-start handle it) or `create_branch` (run work-start inline).

The `clear_branch` action is simpler and delegates to the existing work-start flow. `create_branch` would duplicate work-start logic.

### Files changed

| File | Change |
|------|--------|
| `work-slot/plan_manager.py` | `advance()`: clear branch field after advancing |
| `project/corruption.py` | Add S15_PLAN_BRANCH_STALE check |
| `tests/test_plan_manager.py` | Test branch clearing on advance |
| `tests/test_corruption.py` | Test S15 detection |

---

## Testing Strategy

Each gap gets unit tests for both the prevention fix and the detection fix. No integration tests needed — the prevention fixes are one-liners and the detection fixes follow the existing corruption check pattern.

Protocol: `externalised-scripts-require-tests.md` — all new script logic has tests.

---

## References

- `work-end/work_end_orchestrator.py:260` — `_skip_multi_repo_partial_close`
- `work-end/work_end_orchestrator.py:1328` — `archive_slot` step definition
- `work-slot/plan_manager.py:529` — `advance()` function
- `project/corruption.py:141` — S6_BRANCH_NOT_EXIST
- `project/corruption.py:95` — S5_BRANCH_MISMATCH
- `publish-blog/blog_publish.py:13` — `copy_entry()`
- GE-20260813-556494 — "Authoritative reads with best-effort writes guarantees stale state"
- GE-20260821-e9c59e — "Query worklog.db to audit slot lifecycle state"
- Issue #452 — multi-destination verification
- Issue #402 — S14_MISSING_PLAN
